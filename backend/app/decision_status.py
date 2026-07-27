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

# --- Recorded real-world outcomes: the single source of truth ------------------
# This vocabulary used to be restated in crud.py, pilot_evidence.py and schemas.py,
# so a new outcome value had to be added in four places to be consistent. Everything
# derives from here now; `schemas.PlannedSprayOutcome` still spells the Literal out
# (a Literal cannot be built from a runtime tuple without losing readability) and
# `test_invariants.py` asserts the two never drift.
OUTCOME_PLANNED = "planned"
# Outcomes that mean a spray was actually applied — these create the linked SprayEvent.
APPLIED_OUTCOMES = ("sprayed_as_planned", "changed_product")
# Outcomes that document a non-application honestly.
NON_APPLIED_OUTCOMES = ("delayed", "avoided", "inspected_first")
# Every outcome a human can record. `planned` is the not-yet-recorded default and is
# deliberately excluded — it is a starting state, not a decision.
PLANNED_SPRAY_OUTCOMES = APPLIED_OUTCOMES + NON_APPLIED_OUTCOMES

# --- PCA disposition: the professional judgement, orthogonal to everything else ---
# What the licensed PCA decided to do about a scheduled Botrytis application. This is
# NOT the deterministic verdict (decision_outcome), NOT the review (review_status), and
# NOT what actually happened (outcome) — those are three different facts about three
# different moments, and collapsing any of them would destroy the pilot's evidence.
#
# There is deliberately no value for rejecting or overriding a Lumos suggestion: while
# the pilot is blinded the PCA never sees an assessment, so an override against an
# unseen number would be meaningless data. Reject-style values are added only when a
# protocol records `unblinded_at`.
DISPOSITION_FOLLOW_BASELINE = "follow_baseline"
DISPOSITION_DEFER = "defer"
DISPOSITION_RESCOUT = "rescout"
DISPOSITION_INSUFFICIENT_EVIDENCE = "insufficient_evidence"
PCA_DISPOSITIONS = (
    DISPOSITION_FOLLOW_BASELINE,
    DISPOSITION_DEFER,
    DISPOSITION_RESCOUT,
    DISPOSITION_INSUFFICIENT_EVIDENCE,
)

# --- Pilot protocol vocabulary ---------------------------------------------------
# Only randomized/matched can support a comparison; observational must yield
# descriptive counts carrying an explicit "not a controlled comparison" note.
ASSIGNMENT_RANDOMIZED = "randomized"
ASSIGNMENT_MATCHED = "matched"
ASSIGNMENT_OBSERVATIONAL = "observational"
ASSIGNMENT_METHODS = (
    ASSIGNMENT_RANDOMIZED, ASSIGNMENT_MATCHED, ASSIGNMENT_OBSERVATIONAL,
)
COMPARABLE_ASSIGNMENT_METHODS = (ASSIGNMENT_RANDOMIZED, ASSIGNMENT_MATCHED)

ARM_CONTROL = "control"
ARM_INTERVENTION = "intervention"
TRIAL_ARMS = (ARM_CONTROL, ARM_INTERVENTION)

# Block-level measured outcomes. Economic ones (yield, packout, cull, cost) are what
# make or break the business case; the agronomic ones are what make it safe.
BLOCK_OUTCOME_TYPES = (
    "disease_incidence",
    "rescue_treatment",
    "yield",
    "marketable_packout",
    "cull",
    "cost",
    "adverse_event",
)


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


# Recorded outcomes that close the door on purchasing inputs for the decision.
PROCUREMENT_BLOCKED_OUTCOMES = ("avoided",)


def procurement_eligible(planned) -> bool:
    """May this decision back a purchasable input-plan item?

    Exactly the gate that allows recording an APPLIED outcome (review approved/
    edited, or review not required) — a rejected or still-pending review keeps
    inputs unpurchasable just as it keeps the sprayer parked — and never after a
    recorded avoidance. A blocked decision becomes eligible only through the
    existing PCA approve/edit path: the PCA review IS the resolution.
    """
    return applied_outcome_allowed(planned) and (
        getattr(planned, "outcome", "planned") not in PROCUREMENT_BLOCKED_OUTCOMES
    )


def is_demo_record(record) -> bool:
    """Demo/simulated provenance — excluded from every real pilot metric."""
    return (
        getattr(record, "data_source", None) == "demo"
        or getattr(record, "data_confidence", None) == "simulated"
    )


# --------------------------------------------------------------------------- #
# Composed states. The verdict (decision_outcome) is the immutable historical  #
# decision; these answer the two questions the UI kept conflating with it:     #
# "is anyone still on the hook for this?" (workflow) and "is the documentation #
# story finished?" (evidence). One derivation, consumed by every surface.      #
# --------------------------------------------------------------------------- #

WORKFLOW_NEEDS_ACTION = "needs_action"
WORKFLOW_AWAITING_PCA = "awaiting_pca"
WORKFLOW_RESOLVED = "resolved"


def workflow_state(planned) -> str:
    """Where this decision sits in the human workflow.

    needs_action — open, and the next move is the grower/operator's (inspect,
    record the outcome, act on guidance). awaiting_pca — open and a required
    review is still outstanding. resolved — a real-world outcome is recorded.
    Resolved is about the DECISION only: follow-up evidence may still be due
    (that lives in evidence_state, never here).
    """
    if is_open(planned):
        return WORKFLOW_AWAITING_PCA if needs_review(planned) else WORKFLOW_NEEDS_ACTION
    return WORKFLOW_RESOLVED


EVIDENCE_MISSING_DOCUMENTATION = "missing_documentation"
EVIDENCE_COMPLETE = "complete"
EVIDENCE_FOLLOW_UP_REQUIRED = "follow_up_required"
EVIDENCE_FOLLOW_UP_IN_PROGRESS = "follow_up_in_progress"
EVIDENCE_VERIFIED = "verified"

# Every evidence state, for exhaustive checks in tests/consumers.
EVIDENCE_STATES = (
    EVIDENCE_MISSING_DOCUMENTATION,
    EVIDENCE_COMPLETE,
    EVIDENCE_FOLLOW_UP_REQUIRED,
    EVIDENCE_FOLLOW_UP_IN_PROGRESS,
    EVIDENCE_VERIFIED,
)


def _outcome_confirmed_by_events(planned, events) -> bool:
    """Do the recorded follow-up events support the recorded outcome?

    Mirrors pilot_evidence.derive_follow_up_summary's confirmed_* semantics
    (kept here because this module must stay import-free): "confirmed" means
    supported by recorded follow-up evidence — correlation, never causation.
    """
    outcome = getattr(planned, "outcome", "planned")
    applications = [e for e in events if e.event_type == "actual_application"]
    rescues = [e for e in events if e.event_type == "rescue_application"]
    ultimately_applied = bool(applications) or bool(rescues)
    if outcome == "avoided":
        return bool(events) and not ultimately_applied
    if outcome == "changed_product":
        return bool(applications) or getattr(planned, "spray_event_id", None) is not None
    if outcome == "delayed":
        # A delayed spray is confirmed once the (later or rescue) application
        # is on record — including the honest failure case where a rescue was needed.
        return ultimately_applied
    if outcome == "inspected_first":
        return any(e.event_type == "scouting_observation" for e in events)
    if outcome == "sprayed_as_planned":
        # Follow-up is only required here for approved-despite-warning; any
        # recorded evidence documents what actually happened.
        return bool(events)
    return False


def evidence_state(planned, follow_up_events) -> str:
    """The documentation story of one decision, independent of its verdict.

    missing_documentation — no real-world outcome recorded yet.
    complete — outcome recorded, no follow-up story required.
    follow_up_required — outcome recorded, follow-up required, nothing recorded.
    follow_up_in_progress — follow-up events exist but don't yet confirm the outcome.
    verified — recorded follow-up events support the recorded outcome
    (evidence-backed, not proof of causation).
    """
    events = list(follow_up_events or [])
    if is_open(planned):
        return EVIDENCE_MISSING_DOCUMENTATION
    if not follow_up_required(planned):
        return EVIDENCE_COMPLETE
    if not events:
        return EVIDENCE_FOLLOW_UP_REQUIRED
    if _outcome_confirmed_by_events(planned, events):
        return EVIDENCE_VERIFIED
    return EVIDENCE_FOLLOW_UP_IN_PROGRESS


# Machine keys for the CURRENT next step. `required_next_action` stays untouched
# as the engine's check-time instruction (historical record); this is what the
# user should do NOW given review/outcome/follow-up progress.
NEXT_AWAIT_PCA_REVIEW = "await_pca_review"
NEXT_RESOLVE_CONFLICT = "resolve_conflict"
NEXT_INSPECT = "inspect"
NEXT_RECORD_OUTCOME = "record_outcome"
NEXT_RECORD_FOLLOW_UP = "record_follow_up"
NEXT_NONE = "none"


def current_next_action(planned, follow_up_events) -> str:
    """The one concrete step that moves this decision forward right now.

    An outstanding required review comes first even for a blocked decision —
    the PCA review IS how a conflict gets resolved (matches workflow_state).
    """
    if is_open(planned):
        if needs_review(planned):
            return NEXT_AWAIT_PCA_REVIEW
        if open_conflict(planned):
            return NEXT_RESOLVE_CONFLICT
        if getattr(planned, "decision_outcome", None) == "inspect_first":
            return NEXT_INSPECT
        return NEXT_RECORD_OUTCOME
    if evidence_state(planned, follow_up_events) in (
        EVIDENCE_FOLLOW_UP_REQUIRED,
        EVIDENCE_FOLLOW_UP_IN_PROGRESS,
    ):
        return NEXT_RECORD_FOLLOW_UP
    return NEXT_NONE


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


def label_record_checked_against(planned) -> int | None:
    """The label record id this stored decision was evaluated against, if any."""
    payload = getattr(planned, "decision_payload", None) or {}
    return (payload.get("inputs_used") or {}).get("label_record_id")


def label_reference_stale(planned, superseded_by_record_id) -> bool:
    """True when the label record this decision cites has since been revised.

    The same honesty rule as the harvest date: a stored decision is never silently
    recomputed, so when the label moves on the record has to SAY it is out of date.
    This matters most exactly where it cannot be fixed automatically — a reviewed or
    applied decision, which `crud.apply_label_values` refuses to rewrite because a PCA
    already signed it.
    """
    if label_record_checked_against(planned) is None:
        return False
    return superseded_by_record_id is not None
