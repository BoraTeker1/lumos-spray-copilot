"""Point-in-time correctness: what was knowable at a moment, and nothing else.

This module is the platform-wide promotion of the rule that `app/risk_snapshot.py`
established for the Botrytis pilot. That rule was written for one disease model; it is
in fact the precondition for every claim the platform will ever make about its own
accuracy — a yield forecast, a credit score, an underwriting decision, a collateral
valuation. All of them are only evidence if they can be shown to have used no
information from after the moment they were made.

The rule, stated once:

    An observation is admissible at `as_of` only when it was BOTH observed at or before
    `as_of` AND recorded at or before `as_of`.

The second half is the load-bearing one and the reason `recorded_at` exists on every
observation table in this system. A reading *about* Tuesday that was *entered* on Friday
is still hindsight. Filtering on `observed_at` alone looks correct in review, passes
every test someone would think to write, and silently leaks the future into a backtest —
the model gets scored on information the human could not have had, and the resulting
accuracy number is fiction.

Also enforced here, for the same reason the pilot enforced it: a superseded row is gone
(a correction is a new row, not an edit), a quality-flagged row is excluded rather than
averaged over, and a demo/simulated row can never reach a real computation. That last one
is belt-and-braces against `crud.ensure_demo_real_separation`, because a fabricated input
entering calibration would poison every number downstream of it.

Framework-free (stdlib only). It cannot query for an outcome because it has no session,
and callers pass plain objects. Keep it that way — the guarantee is structural, not
a matter of discipline.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime

# Reasons an input was excluded. Recorded per row so the exclusion is auditable —
# "we did not use this, and here is why" is part of the evidence, not a detail.
EXCLUDED_FUTURE_OBSERVATION = "observed_after_as_of"
EXCLUDED_RECORDED_LATE = "recorded_after_as_of"
EXCLUDED_SUPERSEDED = "superseded_by_correction"
EXCLUDED_QUALITY_FLAG = "quality_flagged"
EXCLUDED_DEMO_OR_MOCK = "demo_or_simulated_source"


def is_demo(row) -> bool:
    """Mirrors decision_status.is_demo_record without importing it (framework-free)."""
    return (
        getattr(row, "data_source", None) == "demo"
        or getattr(row, "data_confidence", None) == "simulated"
    )


def superseded_ids(rows) -> set:
    """Ids that some later row in `rows` supersedes.

    Note the direction: a correction row points BACK at what it replaces, so the set of
    dead ids is the set of `supersedes_id` values present, not the ids of the correction
    rows themselves.
    """
    return {
        r.supersedes_id for r in rows if getattr(r, "supersedes_id", None) is not None
    }


def admissible(row, as_of: datetime, superseded: set) -> str | None:
    """Why this observation may NOT be used at `as_of`, or None when it may.

    The two-timestamp rule lives here and nowhere else in the platform. Every feature,
    every backtest, and every snapshot builder must reach this function rather than
    writing its own date filter.
    """
    if getattr(row, "id", None) in superseded:
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
    if is_demo(row):
        return EXCLUDED_DEMO_OR_MOCK
    return None


def partition(rows, as_of: datetime, kind: str = "observation"):
    """Split rows into (admitted, excluded-with-reasons) at `as_of`.

    The convenience wrapper most callers want: it computes the supersede set over the
    whole input, which is the step that is easy to forget and impossible to notice
    missing — a forgotten supersede set silently admits corrected-away readings.
    """
    rows = list(rows or [])
    dead = superseded_ids(rows)
    admitted, excluded = [], []
    for row in rows:
        reason = admissible(row, as_of, dead)
        if reason is None:
            admitted.append(row)
        else:
            excluded.append({"kind": kind, "id": getattr(row, "id", None), "reason": reason})
    return admitted, excluded


def digest_of(payload: dict, namespace: str) -> str:
    """sha256 over canonical JSON, namespaced by the caller's version string.

    Stable across dict ordering and re-serialization, so re-computing the same inputs
    after more data has arrived must produce the identical digest. That property is what
    makes a stored prediction reproducible from its audit record years later, and it is
    what every calibration join keys on.

    `namespace` is the caller's own version marker (e.g. "risk-snapshot-v1",
    "feature:gdd_accumulated:v2"). Bumping it deliberately invalidates old digests,
    which is the correct behaviour when the meaning of the inputs changes.
    """
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(f"{namespace}|{body}".encode()).hexdigest()
