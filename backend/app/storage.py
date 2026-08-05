"""Object storage for documents, imports, imagery, and generated evidence.

Why this exists. Every document this system has ever processed was read into memory,
extracted from, and thrown away — `extraction.py` and `label_extraction.py` both take
bytes, call a model, and return rows. That was correct while the only documents were
one-shot imports. It stops being correct the moment a label transcription, an insurance
policy, a warehouse receipt, a lien filing, or a soil-test report has to be re-read years
later to defend a decision that cited it. A citation to a document nobody kept is not a
citation.

Design rules:

* **Content-addressed.** The key contains the sha256 of the bytes, so storing the same
  document twice is idempotent and a stored object can always be verified against the
  hash recorded next to the decision that used it. Retrieval checks the hash and raises
  rather than returning bytes that have drifted from what was cited.
* **No vendor in core.** `ObjectStore` is the interface; the local filesystem backend is
  the default and is what tests and development use. The S3 backend lazily imports
  `boto3` exactly like `vision.py` lazily imports `anthropic`, so the dependency is
  optional and nothing breaks without it.
* **No delete in the interface.** Stored objects are evidence. `LocalFileStore` gets a
  `_purge_for_tests` escape hatch that is deliberately named so nobody calls it from
  application code.

Framework-free apart from stdlib: no FastAPI, no SQLAlchemy. The `Document` row that
points at a stored object is an ORM concern and lives in `app/models.py`.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass

# Document kinds. A stored object always knows what sort of thing it is, because
# retention, retrieval, and who may read it all differ by kind.
KIND_LABEL_DOCUMENT = "label_document"
KIND_SOIL_TEST = "soil_test"
KIND_IMPORT_UPLOAD = "import_upload"
KIND_INSURANCE_POLICY = "insurance_policy"
KIND_SALES_CONTRACT = "sales_contract"
KIND_WAREHOUSE_RECEIPT = "warehouse_receipt"
KIND_OWNERSHIP_EVIDENCE = "ownership_evidence"
KIND_FIELD_PHOTO = "field_photo"
KIND_GENERATED_EVIDENCE = "generated_evidence"
KIND_RAW_INGESTION = "raw_ingestion"

DOCUMENT_KINDS = (
    KIND_LABEL_DOCUMENT, KIND_SOIL_TEST, KIND_IMPORT_UPLOAD, KIND_INSURANCE_POLICY,
    KIND_SALES_CONTRACT, KIND_WAREHOUSE_RECEIPT, KIND_OWNERSHIP_EVIDENCE,
    KIND_FIELD_PHOTO, KIND_GENERATED_EVIDENCE, KIND_RAW_INGESTION,
)

_SAFE_SEGMENT = re.compile(r"[^a-z0-9._-]+")


class StorageError(RuntimeError):
    """Raised when an object cannot be stored or verified."""


@dataclass(frozen=True)
class StoredObject:
    """The receipt for a stored object: enough to find it and to prove it is intact."""
    key: str
    sha256: str
    size_bytes: int
    content_type: str | None
    kind: str


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def content_key(kind: str, data: bytes, filename: str | None = None) -> str:
    """A content-addressed key: `kind/aa/bb/<sha256>[-<safe filename>]`.

    The two-level prefix keeps any single directory small on the filesystem backend and
    is the conventional shape for object stores. The original filename is appended when
    supplied because a human retrieving evidence needs to recognise it, but it is
    sanitised and never load-bearing — the hash is the identity.
    """
    if kind not in DOCUMENT_KINDS:
        raise StorageError(f"unknown document kind {kind!r}")
    digest = sha256_of(data)
    suffix = ""
    if filename:
        safe = _SAFE_SEGMENT.sub("-", str(filename).strip().lower())
        # Collapse dot runs so no key segment ever reads as `..`, and trim separators.
        safe = re.sub(r"\.{2,}", ".", safe).strip("-.")
        if safe:
            suffix = f"-{safe[:80]}"
    return f"{kind}/{digest[:2]}/{digest[2:4]}/{digest}{suffix}"


class ObjectStore(ABC):
    """Where bytes live. Implementations must be safe to call concurrently."""

    @abstractmethod
    def put(self, key: str, data: bytes, content_type: str | None = None) -> StoredObject:
        """Store bytes under `key`. Idempotent for identical content."""

    @abstractmethod
    def get(self, key: str) -> bytes:
        """Retrieve bytes, verifying them against the hash embedded in the key."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        ...


def _verify(key: str, data: bytes) -> None:
    """Check retrieved bytes against the digest in the key.

    A silent mismatch is the failure mode that matters: it would mean a decision cites a
    document whose content has since changed, which is exactly the thing content
    addressing exists to make impossible.
    """
    parts = key.split("/")
    if len(parts) < 4:
        return  # not a content-addressed key; nothing to verify against
    digest = parts[3].split("-")[0]
    if len(digest) == 64 and sha256_of(data) != digest:
        raise StorageError(
            f"stored object {key!r} does not match its content hash — the bytes on disk "
            f"are not the bytes that were cited"
        )


class LocalFileStore(ObjectStore):
    """Filesystem-backed store. The default, and what tests and development use."""

    def __init__(self, root: str):
        self.root = os.path.abspath(root)

    def _path(self, key: str) -> str:
        if key.startswith("/") or ".." in key.split("/"):
            raise StorageError(f"unsafe object key {key!r}")
        return os.path.join(self.root, *key.split("/"))

    def put(self, key: str, data: bytes, content_type: str | None = None) -> StoredObject:
        path = self._path(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            # Write to a temp name and rename, so a crash mid-write can never leave a
            # truncated object under a key that claims a content hash.
            tmp = f"{path}.partial"
            with open(tmp, "wb") as handle:
                handle.write(data)
            os.replace(tmp, path)
        return StoredObject(
            key=key,
            sha256=sha256_of(data),
            size_bytes=len(data),
            content_type=content_type,
            kind=key.split("/")[0],
        )

    def get(self, key: str) -> bytes:
        path = self._path(key)
        if not os.path.exists(path):
            raise StorageError(f"object {key!r} not found")
        with open(path, "rb") as handle:
            data = handle.read()
        _verify(key, data)
        return data

    def exists(self, key: str) -> bool:
        return os.path.exists(self._path(key))

    def _purge_for_tests(self) -> None:
        """Delete everything. Named to be un-callable with a straight face in app code."""
        if os.path.isdir(self.root):
            shutil.rmtree(self.root)


class S3ObjectStore(ObjectStore):
    """S3-compatible store (AWS, MinIO, R2). `boto3` is imported lazily and optional."""

    def __init__(self, bucket: str, prefix: str = "", endpoint_url: str | None = None):
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.endpoint_url = endpoint_url
        self._client = None

    @property
    def client(self):
        if self._client is None:
            try:
                import boto3  # noqa: PLC0415  (optional dependency, imported on use)
            except ImportError as exc:  # pragma: no cover - depends on environment
                raise StorageError(
                    "S3 storage requested but boto3 is not installed; install it or set "
                    "LUMOS_STORAGE_BACKEND=local"
                ) from exc
            self._client = boto3.client("s3", endpoint_url=self.endpoint_url)
        return self._client

    def _full(self, key: str) -> str:
        return f"{self.prefix}/{key}" if self.prefix else key

    def put(self, key: str, data: bytes, content_type: str | None = None) -> StoredObject:
        extra = {"ContentType": content_type} if content_type else {}
        self.client.put_object(Bucket=self.bucket, Key=self._full(key), Body=data, **extra)
        return StoredObject(
            key=key, sha256=sha256_of(data), size_bytes=len(data),
            content_type=content_type, kind=key.split("/")[0],
        )

    def get(self, key: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=self._full(key))
        data = response["Body"].read()
        _verify(key, data)
        return data

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=self._full(key))
            return True
        except Exception:  # noqa: BLE001 - any head failure means "not usable"
            return False


def default_root() -> str:
    return os.environ.get(
        "LUMOS_STORAGE_PATH",
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "storage"),
    )


def build_object_store() -> ObjectStore:
    """The configured store: S3 when explicitly selected, local filesystem otherwise.

    Same gating idiom as `vision.default_vision_service` and `llm.default_llm_service`:
    real backend iff the environment asks for it and the dependency is present, else the
    offline default. Nothing silently degrades to a remote service.
    """
    backend = os.environ.get("LUMOS_STORAGE_BACKEND", "local").strip().lower()
    if backend == "s3":
        bucket = os.environ.get("LUMOS_STORAGE_BUCKET")
        if not bucket:
            raise StorageError("LUMOS_STORAGE_BACKEND=s3 requires LUMOS_STORAGE_BUCKET")
        return S3ObjectStore(
            bucket=bucket,
            prefix=os.environ.get("LUMOS_STORAGE_PREFIX", ""),
            endpoint_url=os.environ.get("LUMOS_STORAGE_ENDPOINT"),
        )
    return LocalFileStore(default_root())


_default_store: ObjectStore | None = None


def default_object_store() -> ObjectStore:
    """Process-wide store, built on first use."""
    global _default_store
    if _default_store is None:
        _default_store = build_object_store()
    return _default_store


def store_document(
    kind: str, data: bytes, filename: str | None = None,
    content_type: str | None = None, store: ObjectStore | None = None,
) -> StoredObject:
    """Put bytes in the store under a content-addressed key. The common entry point."""
    target = store or default_object_store()
    return target.put(content_key(kind, data, filename), data, content_type)
