"""The adapter contract and the vocabulary every ingestion run is described in.

Framework-free (stdlib only). An adapter is two pure-ish halves — `fetch` gets bytes
from the outside world, `parse` turns bytes into canonical rows — and a `describe` that
states, without doing any work, whether the adapter can run at all. That last one is
what makes a credential-less deployment inert BY CONSTRUCTION: the pipeline asks
`describe()` first and never calls `fetch` unless the answer is `implemented`.

Two rules worth stating because they are easy to erode:

1. **An issue is recorded, never raised.** A bad row must not abort a 720-row backfill,
   and "we dropped this row and here is why" is part of the evidence, not a detail. The
   only exceptions that escape a pipeline run are programming errors.

2. **A dropped row carries no number.** When a unit conversion refuses, the refusal
   reason is recorded and the row is discarded whole. There is deliberately no path that
   keeps a partially-converted reading, because a temperature that silently stayed in
   Fahrenheit is worse than no temperature at all.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# The eight stages. Named here so an issue can say where it happened and a run
# can be read as a pipeline rather than as a blob of counts.
# ---------------------------------------------------------------------------
STAGE_FETCH = "fetch"
STAGE_PARSE = "parse"
STAGE_VALIDATE = "validate"
STAGE_NORMALIZE = "normalize"
STAGE_ALIGN = "align"
STAGE_RESOLVE = "resolve"
STAGE_DEDUPE = "dedupe"
STAGE_PERSIST = "persist"

STAGES: tuple[str, ...] = (
    STAGE_FETCH,
    STAGE_PARSE,
    STAGE_VALIDATE,
    STAGE_NORMALIZE,
    STAGE_ALIGN,
    STAGE_RESOLVE,
    STAGE_DEDUPE,
    STAGE_PERSIST,
)

# ---------------------------------------------------------------------------
# Run status. `skipped_no_credential` is a first-class outcome, not a failure:
# a deployment without a key is a correctly-configured deployment that cannot
# fetch, and recording it as `failed` would make a healthy system look broken
# and train the operator to ignore the one column that matters.
# ---------------------------------------------------------------------------
RUN_PENDING = "pending"
RUN_RUNNING = "running"
RUN_SUCCEEDED = "succeeded"
RUN_FAILED = "failed"
RUN_SKIPPED_NO_CREDENTIAL = "skipped_no_credential"
RUN_DEAD = "dead"

RUN_STATUSES: tuple[str, ...] = (
    RUN_PENDING,
    RUN_RUNNING,
    RUN_SUCCEEDED,
    RUN_FAILED,
    RUN_SKIPPED_NO_CREDENTIAL,
    RUN_DEAD,
)

# ---------------------------------------------------------------------------
# Adapter availability. The distinction between `requires_credential` and
# `not_implemented` is the whole point of the source registry: one is a
# deployment task, the other is a build task, and an operator staring at the
# sources table needs to know which of the two is in front of them.
# ---------------------------------------------------------------------------
SOURCE_IMPLEMENTED = "implemented"
SOURCE_REQUIRES_CREDENTIAL = "requires_credential"
SOURCE_NOT_IMPLEMENTED = "not_implemented"
SOURCE_DEFERRED_TO_FINANCE_PHASE = "deferred_to_finance_phase"
# A fourth kind of gap, and the one the finance and market domains are in as of
# 2026-08-07: the numbers do not arrive over a wire at all. They arrive when a human
# reads a primary document — a lender's scorecard, an exchange's settlements — and
# transcribes it with a citation into the domain's EMPTY source module. An operator
# looking at this status should not go looking for an API key or a missing library;
# they should go find the document. See `app/transcription.py`.
SOURCE_AWAITING_TRANSCRIPTION = "awaiting_transcription"

SOURCE_STATUSES: tuple[str, ...] = (
    SOURCE_IMPLEMENTED,
    SOURCE_REQUIRES_CREDENTIAL,
    SOURCE_NOT_IMPLEMENTED,
    SOURCE_DEFERRED_TO_FINANCE_PHASE,
    SOURCE_AWAITING_TRANSCRIPTION,
)

# Severities for an issue. `error` drops the row; `warning` keeps it and says why.
SEVERITY_WARNING = "warning"
SEVERITY_ERROR = "error"

# ---------------------------------------------------------------------------
# Issue codes. Enumerated so a test can assert on them and an operator can
# grep for one, rather than everyone inventing prose at the call site.
# ---------------------------------------------------------------------------
ISSUE_NO_FIELD_GEOLOCATION = "no_field_geolocation"
ISSUE_UNIT_REFUSAL = "unit_refusal"
ISSUE_ROW_INVALID = "row_invalid"
ISSUE_UNREQUESTED_STATION = "unrequested_station"
ISSUE_DUPLICATE_ROW = "duplicate_row"
ISSUE_PARSE_FAILED = "parse_failed"
ISSUE_MISSING_OBSERVED_AT = "missing_observed_at"
ISSUE_NO_CREDENTIAL = "no_credential"


@dataclass(frozen=True)
class SourceDescriptor:
    """What a source is, and whether it can run right now.

    `blocker` is required whenever the status is not `implemented` — an operator
    reading "requires_credential" with no next action has been told nothing they
    could not already see.
    """

    source_key: str
    domain: str
    title: str
    provider: str
    status: str
    adapter_version: str = "0"
    blocker: str | None = None
    notes: str | None = None

    def __post_init__(self):
        if self.status not in SOURCE_STATUSES:
            raise ValueError(
                f"{self.source_key}: unknown status {self.status!r}; "
                f"expected one of {SOURCE_STATUSES}"
            )
        if self.status != SOURCE_IMPLEMENTED and not self.blocker:
            raise ValueError(
                f"{self.source_key}: status {self.status!r} must state a `blocker` "
                f"saying what would unblock it"
            )

    @property
    def can_fetch(self) -> bool:
        """The single question the pipeline asks before touching the network."""
        return self.status == SOURCE_IMPLEMENTED

    def as_payload(self) -> dict:
        return {
            "source_key": self.source_key,
            "domain": self.domain,
            "title": self.title,
            "provider": self.provider,
            "status": self.status,
            "adapter_version": self.adapter_version,
            "blocker": self.blocker,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class IngestContext:
    """Everything the operator named, and nothing the adapter may infer.

    Resolution is deterministic *because* this exists: the farm, the field and the
    station are stated up front, so a reading from a station nobody asked for is an
    issue rather than a silent join onto whatever looked closest.
    """

    farm_id: int
    field_id: int | None
    station_id: str
    window_start: datetime
    window_end: datetime
    station_lat: float | None = None
    station_lon: float | None = None
    field_lat: float | None = None
    field_lon: float | None = None
    is_demo: bool = False

    def as_request_payload(self) -> dict:
        """The digestible description of what was asked for.

        Deliberately excludes credentials — this feeds `request_digest`, which is
        stored, and a key that reaches a digest has reached durable storage.
        """
        return {
            "farm_id": self.farm_id,
            "field_id": self.field_id,
            "station_id": self.station_id,
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
        }


@dataclass(frozen=True)
class Issue:
    """Something that went wrong with one row, or with the run as a whole.

    `row_index` is None for run-level issues. `detail` must never contain a credential
    or a raw response body; it is for the small structured facts that make the issue
    actionable (the unit that refused, the station that was not asked for).
    """

    stage: str
    severity: str
    code: str
    message: str
    row_index: int | None = None
    natural_key: str | None = None
    detail: dict | None = None

    def __post_init__(self):
        if self.stage not in STAGES:
            raise ValueError(f"unknown stage {self.stage!r}; expected one of {STAGES}")
        if self.severity not in (SEVERITY_WARNING, SEVERITY_ERROR):
            raise ValueError(f"unknown severity {self.severity!r}")


@dataclass
class FetchResult:
    """Raw bytes plus the redacted description of how they were obtained.

    `request_description` is stored alongside the run so a result can be explained
    years later. It is the adapter's job to have already removed the credential — see
    `cimis._redact`.
    """

    raw: bytes
    content_type: str | None = None
    filename: str | None = None
    request_description: dict = field(default_factory=dict)


@runtime_checkable
class SourceAdapter(Protocol):
    """Two halves and a self-description.

    `parse` returns rows keyed by CANONICAL field names — the same names
    `csv_import.WEATHER_OBSERVATION_FIELDS` declares — because the next stage hands
    them straight to `csv_import.validate_rows`. That reuse is what holds an ingested
    reading to the identical contract as a concierge-entered one, and it only works if
    adapters do not invent their own column names.
    """

    def describe(self) -> SourceDescriptor:
        ...

    def fetch(self, ctx: IngestContext) -> FetchResult:
        ...

    def parse(self, raw: bytes, ctx: IngestContext) -> tuple[list[dict], list[Issue]]:
        ...
