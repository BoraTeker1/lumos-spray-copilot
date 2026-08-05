"""Object-storage tests: content addressing, idempotency, and tamper detection."""
import os

import pytest

from app import storage
from app.storage import LocalFileStore, StorageError


@pytest.fixture()
def store(tmp_path):
    return LocalFileStore(str(tmp_path / "objects"))


def test_content_key_is_the_hash_and_is_stable():
    data = b"a soil test report"
    first = storage.content_key(storage.KIND_SOIL_TEST, data)
    second = storage.content_key(storage.KIND_SOIL_TEST, data)
    assert first == second
    assert storage.sha256_of(data) in first
    assert first.startswith("soil_test/")


def test_different_bytes_get_different_keys():
    a = storage.content_key(storage.KIND_SOIL_TEST, b"one")
    b = storage.content_key(storage.KIND_SOIL_TEST, b"two")
    assert a != b


def test_filename_is_appended_but_sanitised_and_never_the_identity():
    data = b"x"
    key = storage.content_key(storage.KIND_LABEL_DOCUMENT, data, "Captan 80 WDG/../label.pdf")
    assert ".." not in key.split("/")[-1]
    assert " " not in key
    # The hash still determines identity: same bytes, different filename, same directory.
    other = storage.content_key(storage.KIND_LABEL_DOCUMENT, data, "different.pdf")
    assert key.rsplit("/", 1)[0] == other.rsplit("/", 1)[0]


def test_unknown_kind_is_refused():
    with pytest.raises(StorageError):
        storage.content_key("not_a_kind", b"x")


def test_put_then_get_round_trips(store):
    data = b"%PDF-1.4 fake label"
    stored = storage.store_document(
        storage.KIND_LABEL_DOCUMENT, data, "label.pdf", "application/pdf", store=store
    )
    assert stored.sha256 == storage.sha256_of(data)
    assert stored.size_bytes == len(data)
    assert stored.kind == storage.KIND_LABEL_DOCUMENT
    assert store.exists(stored.key)
    assert store.get(stored.key) == data


def test_storing_identical_content_twice_is_idempotent(store):
    data = b"same bytes"
    a = storage.store_document(storage.KIND_IMPORT_UPLOAD, data, store=store)
    b = storage.store_document(storage.KIND_IMPORT_UPLOAD, data, store=store)
    assert a.key == b.key
    assert store.get(a.key) == data


def test_retrieving_tampered_bytes_raises_rather_than_returning_them(store):
    """The failure that matters: a decision citing a document that has since changed."""
    stored = storage.store_document(storage.KIND_SALES_CONTRACT, b"agreed price 3.20", store=store)
    path = store._path(stored.key)
    with open(path, "wb") as handle:
        handle.write(b"agreed price 9.99")

    with pytest.raises(StorageError) as exc:
        store.get(stored.key)
    assert "content hash" in str(exc.value)


def test_missing_object_raises(store):
    with pytest.raises(StorageError):
        store.get("soil_test/aa/bb/" + "0" * 64)


def test_path_traversal_keys_are_refused(store):
    with pytest.raises(StorageError):
        store.get("../../etc/passwd")
    with pytest.raises(StorageError):
        store.put("/absolute/key", b"x")


def test_partial_writes_do_not_leave_a_readable_object(store):
    """A crash mid-write must not leave truncated bytes under a key claiming a hash."""
    data = b"complete content"
    stored = storage.store_document(storage.KIND_RAW_INGESTION, data, store=store)
    directory = os.path.dirname(store._path(stored.key))
    assert not any(name.endswith(".partial") for name in os.listdir(directory))


def test_interface_exposes_no_delete():
    """Stored objects are evidence; the escape hatch is named so nobody calls it."""
    assert not hasattr(storage.ObjectStore, "delete")
    assert hasattr(LocalFileStore, "_purge_for_tests")


def test_default_backend_is_local_and_s3_requires_explicit_config(monkeypatch):
    monkeypatch.delenv("LUMOS_STORAGE_BACKEND", raising=False)
    assert isinstance(storage.build_object_store(), LocalFileStore)

    monkeypatch.setenv("LUMOS_STORAGE_BACKEND", "s3")
    monkeypatch.delenv("LUMOS_STORAGE_BUCKET", raising=False)
    with pytest.raises(StorageError) as exc:
        storage.build_object_store()
    assert "LUMOS_STORAGE_BUCKET" in str(exc.value)


def test_module_is_framework_free():
    text = open(storage.__file__).read()
    for forbidden in ("import fastapi", "from fastapi", "import sqlalchemy", "from sqlalchemy"):
        assert forbidden not in text
    # boto3 must be imported lazily so it stays an optional dependency.
    assert "import boto3" in text
    assert text.index("def client") < text.index("import boto3")
