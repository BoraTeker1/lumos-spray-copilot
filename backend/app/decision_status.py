"""Canonical status derivation for pre-spray decisions (the single source of truth).

Every "does this planned spray still need review / is it open / is it a conflict"
question anywhere in the app (routes, crud gates, evidence aggregation, API schema
fields the frontend renders) MUST come from these helpers. The predicates were
previously re-implemented in five places with subtly different semantics; if a new
notion of "resolved" is ever needed, add it HERE with its own name.

Two deliberately different review questions coexist:

* ``needs_review`` — is a required review still outstanding? A *rejected* review
  resolves it (the PCA did review; they said no).
* ``applied_outcome_allowed`` — may an applied outcome (sprayed_as_planned /
  changed_product) be recorded? A rejection does NOT unlock application — only an
  approval or an edit does.

Framework-free: duck-typed plain objects only, no FastAPI/SQLAlchemy imports.
"""
from __future__ import annotations

# Review states (derived; the stored column is `review_status`).
REVIEW_NOT_REQUIRED = "not_required"
REVIEW_PENDING = "pending"
REVIEW_APPROVED = "approved"
REVIEW_EDITED = "edited"
REVIEW_REJECTED = "rejected"

# A recorded PCA decision of any kind (resolves "needs review", counts as reviewed).
RESOLVED_REVIEW_STATUSES = ("approved", "edited", "rejected")
# Review statuses that unlock recording an APPLIED outcome (rejected does not).
APPLIED_OUTCOME_UNLOCK_STATUSES = ("approved", "edited")


def review_state(planned) -> str:
    """One derived vocabulary for the review situation of a planned spray.

    not_required / pending / approved / edited / rejected — a decision that was
    reviewed reports the recorded action even if the engine never required review.
    """
    status = getattr(planned, "review_status", None)
    if status in RESOLVED_REVIEW_STATUSES:
        return status
    if getattr(planned, "review_required", False):
        return REVIEW_PENDING
    return REVIEW_NOT_REQUIRED


def needs_review(planned) -> bool:
    """A required PCA review is still outstanding (any recorded review resolves it)."""
    return review_state(planned) == REVIEW_PENDING


def applied_outcome_allowed(planned) -> bool:
    """May an applied outcome be recorded? Rejected reviews keep the gate closed."""
    if not getattr(planned, "review_required", False):
        return True
    return getattr(planned, "review_status", None) in APPLIED_OUTCOME_UNLOCK_STATUSES


def is_open(planned) -> bool:
    """No real-world outcome recorded yet."""
    return getattr(planned, "outcome", "planned") == "planned"


def open_conflict(planned) -> bool:
    """A critical (timing-conflict) decision whose outcome is still unresolved."""
    return is_open(planned) and getattr(planned, "decision_severity", None) == "critical"


def conflict_caught(planned) -> bool:
    """A critical conflict the check surfaced, resolved or not (evidence semantics)."""
    return getattr(planned, "decision_severity", None) == "critical"


# Recorded outcomes that always require a follow-up story before any confirmed claim.
FOLLOW_UP_OUTCOMES = ("avoided", "delayed", "inspected_first", "changed_product")


def follow_up_required(planned) -> bool:
    """Does this decision need follow-up evidence before its result can be confirmed?

    True for every non-as-planned recorded outcome, and for "approved despite a
    warning" (sprayed as planned although the check had triggered findings). A planned
    avoidance is NOT a confirmed reduction until follow-up events exist.
    """
    outcome = getattr(planned, "outcome", "planned")
    if outcome in FOLLOW_UP_OUTCOMES:
        return True
    if outcome == "sprayed_as_planned" and getattr(
        planned, "decision_severity", "none"
    ) in ("caution", "critical"):
        return True
    return False


def is_demo_record(record) -> bool:
    """Demo/simulated provenance — excluded from every real pilot metric."""
    return (
        getattr(record, "data_source", None) == "demo"
        or getattr(record, "data_confidence", None) == "simulated"
    )


def status_counts(planned_sprays) -> dict:
    """The per-farm decision counts every surface (dashboard, farm page) must share."""
    planned = list(planned_sprays or [])
    open_planned = [p for p in planned if is_open(p)]
    return {
        "needs_review_count": sum(1 for p in open_planned if needs_review(p)),
        "awaiting_outcome_count": len(open_planned),
        "open_conflict_count": sum(1 for p in open_planned if open_conflict(p)),
    }


def harvest_date_changed_since_check(planned, current_harvest_date) -> bool:
    """True when the farm's harvest date no longer matches the one this check used.

    The decision snapshot deliberately keeps the harvest date it was computed against;
    when the farm's date is later edited the stored decision is stale and the UI must
    say so (we never silently recompute a stored decision).
    """
    payload = getattr(planned, "decision_payload", None) or {}
    inputs = payload.get("inputs_used") or {}
    if "expected_harvest_date" not in inputs:
        return False  # legacy rows without a snapshot: nothing to compare
    # A decision that carries its OWN harvest date (a per-record imported/verified
    # input value) is grounded in that value, not the farm-level field — editing the
    # farm's date does not stale it.
    if "expected_harvest_date" in (inputs.get("field_sources") or {}):
        return False
    checked = inputs.get("expected_harvest_date")
    current = current_harvest_date.isoformat() if current_harvest_date else None
    return checked != current
