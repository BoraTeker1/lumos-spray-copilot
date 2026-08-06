"""Immutable risk-input snapshot: the leakage boundary.

A disease-risk assessment is only meaningful if it can be shown to have used ONLY
what was knowable at the moment of prediction. This module is that guarantee, and it
enforces it structurally rather than by discipline:

* It is framework-free (stdlib only) — no FastAPI, no SQLAlchemy, no session. It
  cannot reach a disposition, an outcome, a harvest result, or an application status,
  because it has no way to query for one.
* Its signature admits only observations and a block. There is deliberately no
  parameter through which post-decision information could be passed, so a future
  caller cannot "just add" outcome data without changing this contract in a way that
  is obvious in review.
* Admissibility is checked on BOTH timestamps. This is the subtle one, and it is the
  reason `recorded_at` exists on every observation model: a reading *about* Tuesday
  that was *entered* on Friday is still hindsight. Filtering on `observed_at` alone
  looks correct and silently leaks — the model would be scored on information the PCA
  could not have had.

The snapshot is content-addressed: the digest is a sha256 over the canonical JSON of
the admitted inputs (same idiom as `ai_brief.input_digest`). Re-snapshotting the same
`as_of` after more data has arrived must produce the identical digest — that is the
property `tests/test_leakage.py` pins, and it is what makes an assessment reproducible
from the audit record years later.

Nothing here decides anything. It gathers, filters, and hashes; `app/disease_risk.py`
reads the result.

As of the platform work, the two-timestamp rule itself lives in `app/pit.py` — every
feature, forecast, and score needs the same guarantee, and there must be exactly one
implementation of it. This module keeps its own names as re-exports so the pilot's
contract (and `tests/test_leakage.py`) is unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app import pit
from app.pit import (  # noqa: F401  (re-exported: the pilot's vocabulary is unchanged)
    EXCLUDED_DEMO_OR_MOCK,
    EXCLUDED_FUTURE_OBSERVATION,
    EXCLUDED_QUALITY_FLAG,
    EXCLUDED_RECORDED_LATE,
    EXCLUDED_SUPERSEDED,
    admissible,
)

SNAPSHOT_VERSION = "risk-snapshot-v1"

# ------------------------------------------------------------------ snapshot basis
# Two ways to decide what a snapshot may contain. They are NOT interchangeable and the
# difference is the whole reason this module exists.
#
#   point_in_time            — observed_at <= as_of AND recorded_at <= as_of.
#                              The live pilot's basis. Proof-grade.
#   retrospective_reconstruction
#                            — observed_at <= as_of only.
#
# Why the second exists: a concierge import of last season's records stamps
# `recorded_at` at ingest time (DATA_PLATFORM.md — never back-dated, because knowing
# something later is not knowing it then). Replaying a past decision date under the
# point-in-time basis therefore admits NOTHING, and a historical scan honestly finds no
# data at all.
#
# The fix is to name the weaker basis, not to weaken the strong one. A retrospective
# snapshot CANNOT support a claim about what a rule "would have said at the time",
# because the record set it reads was assembled with hindsight about which observations
# were worth keeping. It can support one thing only: sizing how often conditions of a
# given kind occurred. `app/backtest.py` is the sole caller, and its output says so.
BASIS_POINT_IN_TIME = "point_in_time"
BASIS_RETROSPECTIVE = "retrospective_reconstruction"
SNAPSHOT_BASES = (BASIS_POINT_IN_TIME, BASIS_RETROSPECTIVE)

_is_demo = pit.is_demo
_superseded_ids = pit.superseded_ids


def _retrospectively_admissible(row, as_of: datetime, superseded: set) -> str | None:
    """`pit.admissible` minus the recorded-late test, and NOTHING else minus.

    Deliberately written as a delegation rather than a copy: superseded rows, quality
    flags and demo inputs must be excluded identically in both bases, and a second
    hand-written filter would drift from `app/pit.py` the first time a reason was added
    there. Only the one rule that a backfill structurally cannot satisfy is relaxed.
    """
    reason = pit.admissible(row, as_of, superseded)
    if reason == pit.EXCLUDED_RECORDED_LATE:
        return None
    return reason


def _weather_payload(row) -> dict:
    return {
        "observed_at": row.observed_at.isoformat(),
        "station_id": row.station_id,
        "station_distance_km": row.station_distance_km,
        "temperature_c": row.temperature_c,
        "relative_humidity_pct": row.relative_humidity_pct,
        "rainfall_mm": row.rainfall_mm,
        "leaf_wetness_minutes": row.leaf_wetness_minutes,
        # Measured vs derived travels into the snapshot: the assessment grades them
        # differently and must not have to guess which it was given.
        "wetness_is_measured": row.wetness_is_measured,
        "source_type": row.source_type,
    }


def _sample_payload(row) -> dict:
    return {
        "observed_at": row.observed_at.isoformat(),
        "method": row.method,
        "target": row.target,
        "units_inspected": row.units_inspected,
        "units_affected": row.units_affected,
        "incidence_pct": row.incidence_pct,
        "severity_index": row.severity_index,
        "severity_scale": row.severity_scale,
        "source_type": row.source_type,
    }


def _block_payload(block) -> dict:
    return {
        "block_id": getattr(block, "id", None),
        "crop": getattr(block, "crop", None),
        "cultivar": getattr(block, "cultivar", None),
        "area": getattr(block, "area", None),
        "area_unit": getattr(block, "area_unit", None),
        # Phenology as recorded, with its observation date — so a stale stage is
        # visible as stale rather than presented as current.
        "phenology_stage": getattr(block, "phenology_stage", None),
        "phenology_observed_on": (
            block.phenology_observed_on.isoformat()
            if getattr(block, "phenology_observed_on", None) else None
        ),
    }


@dataclass
class SnapshotDraft:
    """The admitted inputs plus the record of what was left out and why."""
    as_of: datetime
    horizon_hours: int
    target: str
    payload: dict = field(default_factory=dict)
    excluded: list = field(default_factory=list)
    basis: str = BASIS_POINT_IN_TIME

    @property
    def input_digest(self) -> str:
        return digest_of(self.payload, basis=self.basis)

    def as_payload(self) -> dict:
        return dict(self.payload)


def digest_of(payload: dict, basis: str = BASIS_POINT_IN_TIME) -> str:
    """sha256 over canonical JSON — stable across dict ordering and re-serialization.

    Namespaced by SNAPSHOT_VERSION for the point-in-time basis, so digests computed
    before and after the move to `app/pit.py` — and before and after the retrospective
    basis was added — are byte-identical.

    A retrospective snapshot gets its OWN namespace. Two snapshots of the same block and
    the same `as_of` that admitted different rows must never collide, and a digest is
    the identity a stored assessment is looked up by; sharing a namespace would let a
    retrospective reconstruction masquerade as the prospective record of that moment.
    """
    if basis == BASIS_POINT_IN_TIME:
        return pit.digest_of(payload, SNAPSHOT_VERSION)
    return pit.digest_of(payload, f"{SNAPSHOT_VERSION}|{basis}")


def build_snapshot(
    as_of: datetime,
    horizon_hours: int,
    target: str,
    block,
    weather_observations,
    scouting_samples,
    lookback_hours: int = 168,
    basis: str = BASIS_POINT_IN_TIME,
) -> SnapshotDraft:
    """Gather everything knowable at `as_of` about `block`, and nothing else.

    Parameters are deliberately limited to observations and the block. There is NO
    parameter for a disposition, an outcome, an application, or a harvest result —
    adding one would be a visible change to this signature, which is the point.

    `lookback_hours` bounds how far back weather is gathered (default 7 days): the
    window is part of the snapshot, so two assessments of the same hour see the same
    history.

    `basis` defaults to point-in-time and must be passed explicitly to weaken it. There
    is deliberately no environment variable, no config key and no per-farm setting that
    can flip it: a basis chosen anywhere other than the call site would let a live
    prospective assessment silently become a retrospective one.
    """
    if basis not in SNAPSHOT_BASES:
        raise ValueError(f"unknown snapshot basis {basis!r}; expected one of {SNAPSHOT_BASES}")

    admit = admissible if basis == BASIS_POINT_IN_TIME else _retrospectively_admissible

    weather = list(weather_observations or [])
    samples = list(scouting_samples or [])
    superseded = _superseded_ids(weather) | _superseded_ids(samples)
    window_start = as_of - timedelta(hours=lookback_hours)

    excluded: list = []
    admitted_weather = []
    for row in weather:
        reason = admit(row, as_of, superseded)
        if reason is not None:
            excluded.append({"kind": "weather", "id": row.id, "reason": reason})
            continue
        if row.observed_at < window_start:
            continue  # outside the declared history window, not an anomaly
        admitted_weather.append(row)

    admitted_samples = []
    for row in samples:
        reason = admit(row, as_of, superseded)
        if reason is not None:
            excluded.append({"kind": "scouting_sample", "id": row.id, "reason": reason})
            continue
        admitted_samples.append(row)

    admitted_weather.sort(key=lambda r: (r.observed_at, r.station_id))
    admitted_samples.sort(key=lambda r: (r.observed_at, r.target))

    payload = {
        "snapshot_version": SNAPSHOT_VERSION,
        "as_of": as_of.isoformat(),
        "horizon_hours": horizon_hours,
        "lookback_hours": lookback_hours,
        "target": target,
        "block": _block_payload(block),
        "weather": [_weather_payload(r) for r in admitted_weather],
        "scouting_samples": [_sample_payload(r) for r in admitted_samples],
    }
    # The point-in-time payload is left EXACTLY as it was before this key existed.
    # Adding "basis": "point_in_time" would change every stored digest in the database
    # and orphan every assessment already anchored to one. A retrospective payload is
    # new, so it can afford to carry its own mark — and must, so that a payload read
    # back years later states its own basis rather than relying on a column beside it.
    if basis != BASIS_POINT_IN_TIME:
        payload["basis"] = basis

    return SnapshotDraft(
        as_of=as_of, horizon_hours=horizon_hours, target=target,
        payload=payload, excluded=excluded, basis=basis,
    )
