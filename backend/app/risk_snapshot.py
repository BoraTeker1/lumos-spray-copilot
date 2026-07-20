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
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta

SNAPSHOT_VERSION = "risk-snapshot-v1"

# Reasons an input was excluded. Recorded per row so the exclusion is auditable —
# "we did not use this, and here is why" is part of the evidence, not a detail.
EXCLUDED_FUTURE_OBSERVATION = "observed_after_as_of"
EXCLUDED_RECORDED_LATE = "recorded_after_as_of"
EXCLUDED_SUPERSEDED = "superseded_by_correction"
EXCLUDED_QUALITY_FLAG = "quality_flagged"
EXCLUDED_DEMO_OR_MOCK = "demo_or_simulated_source"


def _is_demo(row) -> bool:
    """Mirrors decision_status.is_demo_record without importing it (framework-free)."""
    return (
        getattr(row, "data_source", None) == "demo"
        or getattr(row, "data_confidence", None) == "simulated"
    )


def admissible(row, as_of: datetime, superseded_ids: set) -> str | None:
    """Why this observation may NOT be used, or None when it may.

    The two-timestamp rule lives here and nowhere else.
    """
    if getattr(row, "id", None) in superseded_ids:
        return EXCLUDED_SUPERSEDED
    observed_at = getattr(row, "observed_at", None)
    if observed_at is None or observed_at > as_of:
        return EXCLUDED_FUTURE_OBSERVATION
    # The hindsight guard: knowing it later is not knowing it then.
    recorded_at = getattr(row, "recorded_at", None)
    if recorded_at is not None and recorded_at > as_of:
        return EXCLUDED_RECORDED_LATE
    if getattr(row, "quality_flag", None):
        return EXCLUDED_QUALITY_FLAG
    # A demo/simulated reading must never reach a real assessment. The farm-level
    # mixing guard already prevents this; belt and braces, because a fabricated input
    # silently entering calibration would poison every number downstream.
    if _is_demo(row):
        return EXCLUDED_DEMO_OR_MOCK
    return None


def _superseded_ids(rows) -> set:
    return {
        r.supersedes_id for r in rows if getattr(r, "supersedes_id", None) is not None
    }


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

    @property
    def input_digest(self) -> str:
        return digest_of(self.payload)

    def as_payload(self) -> dict:
        return dict(self.payload)


def digest_of(payload: dict) -> str:
    """sha256 over canonical JSON — stable across dict ordering and re-serialization."""
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(f"{SNAPSHOT_VERSION}|{body}".encode()).hexdigest()


def build_snapshot(
    as_of: datetime,
    horizon_hours: int,
    target: str,
    block,
    weather_observations,
    scouting_samples,
    lookback_hours: int = 168,
) -> SnapshotDraft:
    """Gather everything knowable at `as_of` about `block`, and nothing else.

    Parameters are deliberately limited to observations and the block. There is NO
    parameter for a disposition, an outcome, an application, or a harvest result —
    adding one would be a visible change to this signature, which is the point.

    `lookback_hours` bounds how far back weather is gathered (default 7 days): the
    window is part of the snapshot, so two assessments of the same hour see the same
    history.
    """
    weather = list(weather_observations or [])
    samples = list(scouting_samples or [])
    superseded = _superseded_ids(weather) | _superseded_ids(samples)
    window_start = as_of - timedelta(hours=lookback_hours)

    excluded: list = []
    admitted_weather = []
    for row in weather:
        reason = admissible(row, as_of, superseded)
        if reason is not None:
            excluded.append({"kind": "weather", "id": row.id, "reason": reason})
            continue
        if row.observed_at < window_start:
            continue  # outside the declared history window, not an anomaly
        admitted_weather.append(row)

    admitted_samples = []
    for row in samples:
        reason = admissible(row, as_of, superseded)
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
    return SnapshotDraft(
        as_of=as_of, horizon_hours=horizon_hours, target=target,
        payload=payload, excluded=excluded,
    )
