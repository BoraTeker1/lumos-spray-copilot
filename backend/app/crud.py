"""Database access layer. Routes call these helpers; they never touch the session directly.

Keeping DB access here makes the route handlers thin and makes it straightforward to add
an auth/tenant filter later in one place.
"""
from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock, csv_import, decision_status, models, procurement_status, schemas, target_aliases
from app.decision_engine import evaluate_planned_spray
from app.recommendation_engine import generate_recommendation

# Maps decision severity onto the legacy low/moderate/elevated risk vocabulary that the
# weekly-report / audit surfaces still speak.
_SEVERITY_TO_RISK = {"none": "low", "caution": "moderate", "critical": "elevated"}

# Real-world outcomes that mean a spray was actually applied (they create the SprayEvent).
APPLIED_OUTCOMES = ("sprayed_as_planned", "changed_product")


class ReviewRequiredError(Exception):
    """Raised when an applied outcome is recorded before a required PCA review."""


class OutcomeChronologyError(Exception):
    """Raised when a recorded outcome would create an impossible timeline
    (outcome before its check, or an application before its planned date)."""


class FollowUpError(Exception):
    """Raised when a follow-up event is invalid (no recorded outcome yet, or an
    impossible timeline)."""


# Compliance/decision-critical fields carried as DecisionInputValue rows (field-level
# provenance). The application rate is ONE row (amount + unit on the same row).
CRITICAL_INPUT_FIELDS = (
    "product_name", "epa_reg_no", "crop", "target_pest_or_disease", "rate_amount",
    "pre_harvest_interval_days", "re_entry_interval_hours", "intended_date",
    "expected_harvest_date", "active_ingredient", "moa_group",
)

# Legacy record-level values_source -> field-level provenance source_type.
_VALUES_SOURCE_TO_INPUT_SOURCE = {
    "pca_entered": "pca_verified",
    "grower_entered": "user_entered",
    "imported_unverified": "imported_unverified",
}


# ----------------------------------------------------------------------------- Farms
def list_farms(db: Session) -> list[models.Farm]:
    return list(db.scalars(select(models.Farm).order_by(models.Farm.id)))


def get_farm(db: Session, farm_id: int) -> models.Farm | None:
    return db.get(models.Farm, farm_id)


def create_farm(db: Session, data: schemas.FarmCreate) -> models.Farm:
    farm = models.Farm(**data.model_dump())
    db.add(farm)
    db.commit()
    db.refresh(farm)
    return farm


def update_farm(db: Session, farm: models.Farm, data: schemas.FarmUpdate) -> models.Farm:
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(farm, key, value)
    db.commit()
    db.refresh(farm)
    return farm


def delete_farm(db: Session, farm: models.Farm) -> None:
    db.delete(farm)
    db.commit()


# ----------------------------------------------------------------------- SprayEvents
def list_spray_events(db: Session, farm_id: int) -> list[models.SprayEvent]:
    return list(
        db.scalars(
            select(models.SprayEvent)
            .where(models.SprayEvent.farm_id == farm_id)
            .order_by(models.SprayEvent.application_date.desc())
        )
    )


def create_spray_event(
    db: Session, farm_id: int, data: schemas.SprayEventCreate
) -> models.SprayEvent:
    event = models.SprayEvent(farm_id=farm_id, **data.model_dump())
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def get_spray_event(db: Session, event_id: int) -> models.SprayEvent | None:
    return db.get(models.SprayEvent, event_id)


def delete_spray_event(db: Session, event: models.SprayEvent) -> None:
    db.delete(event)
    db.commit()


# ------------------------------------------------------------------ ScoutObservations
def list_scout_observations(db: Session, farm_id: int) -> list[models.ScoutObservation]:
    return list(
        db.scalars(
            select(models.ScoutObservation)
            .where(models.ScoutObservation.farm_id == farm_id)
            .order_by(models.ScoutObservation.observation_date.desc())
        )
    )


def create_scout_observation(
    db: Session, farm_id: int, data: schemas.ScoutObservationCreate
) -> models.ScoutObservation:
    obs = models.ScoutObservation(farm_id=farm_id, **data.model_dump())
    db.add(obs)
    db.commit()
    db.refresh(obs)
    return obs


def get_scout_observation(db: Session, obs_id: int) -> models.ScoutObservation | None:
    return db.get(models.ScoutObservation, obs_id)


def delete_scout_observation(db: Session, obs: models.ScoutObservation) -> None:
    db.delete(obs)
    db.commit()


# ----------------------------------------------------------------- Recommendations
def list_recommendations(db: Session, farm_id: int) -> list[models.Recommendation]:
    return list(
        db.scalars(
            select(models.Recommendation)
            .where(models.Recommendation.farm_id == farm_id)
            .order_by(models.Recommendation.created_at.desc())
        )
    )


def get_recommendation(db: Session, rec_id: int) -> models.Recommendation | None:
    return db.get(models.Recommendation, rec_id)


def generate_and_store_recommendation(
    db: Session, farm: models.Farm
) -> models.Recommendation:
    """Run the rule engine over a farm's records and persist the result."""
    sprays = list_spray_events(db, farm.id)
    observations = list_scout_observations(db, farm.id)

    result = generate_recommendation(farm, sprays, observations, today=clock.current_date())

    rec = models.Recommendation(
        farm_id=farm.id,
        risk_level=result.risk_level,
        next_action=result.next_action,
        recommendation_text=result.recommendation_text,
        agronomist_status="pending",
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


def update_recommendation(
    db: Session, rec: models.Recommendation, data: schemas.RecommendationUpdate
) -> models.Recommendation:
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(rec, key, value)
    db.commit()
    db.refresh(rec)
    return rec


# ----------------------------------------------------------------- PlannedSprays
def list_planned_sprays(db: Session, farm_id: int) -> list[models.PlannedSpray]:
    return list(
        db.scalars(
            select(models.PlannedSpray)
            .where(models.PlannedSpray.farm_id == farm_id)
            .order_by(models.PlannedSpray.intended_date.desc(), models.PlannedSpray.id.desc())
        )
    )


def get_planned_spray(db: Session, planned_id: int) -> models.PlannedSpray | None:
    return db.get(models.PlannedSpray, planned_id)


def _normalized_input(field_name: str, value) -> str | None:
    """Deterministic normalization for a DecisionInputValue row."""
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    if field_name in ("target_pest_or_disease",):
        return target_aliases.normalize(str(value)) or None
    if field_name in ("product_name", "crop", "active_ingredient", "moa_group"):
        return str(value).strip().lower() or None
    if field_name == "epa_reg_no":
        return str(value).strip().lower().replace(" ", "") or None
    return str(value).strip() or None


def _planned_input_rows(planned_like, harvest_date) -> list[tuple[str, object, str | None]]:
    """(field_name, raw value, unit) for every critical input that has a value."""
    rate_unit = getattr(planned_like, "rate_unit", None)
    values = {
        "product_name": getattr(planned_like, "product_name", None),
        "epa_reg_no": getattr(planned_like, "epa_reg_no", None),
        "crop": getattr(planned_like, "crop", None),
        "target_pest_or_disease": getattr(planned_like, "target_pest_or_disease", None),
        "rate_amount": getattr(planned_like, "rate_amount", None),
        "pre_harvest_interval_days": getattr(planned_like, "pre_harvest_interval_days", None),
        "re_entry_interval_hours": getattr(planned_like, "re_entry_interval_hours", None),
        "intended_date": getattr(planned_like, "intended_date", None),
        "expected_harvest_date": harvest_date,
        "active_ingredient": getattr(planned_like, "active_ingredient", None),
        "moa_group": getattr(planned_like, "moa_group", None),
    }
    units = {
        "rate_amount": rate_unit,
        "pre_harvest_interval_days": "days",
        "re_entry_interval_hours": "hours",
    }
    return [
        (name, value, units.get(name))
        for name, value in values.items()
        if value is not None and str(value).strip() != ""
    ]


def active_input_values(planned: models.PlannedSpray) -> dict[str, models.DecisionInputValue]:
    """Latest non-superseded DecisionInputValue per field (the values that drive the
    engine). The chain itself is append-only; this is a read-only resolution."""
    rows = sorted(planned.input_values or [], key=lambda r: (r.created_at, r.id))
    superseded = {r.supersedes_input_value_id for r in rows if r.supersedes_input_value_id}
    current: dict[str, models.DecisionInputValue] = {}
    for row in rows:
        if row.id in superseded:
            continue
        current[row.field_name] = row  # later rows (sorted ascending) win
    return current


def resolve_input_sources(planned: models.PlannedSpray) -> dict:
    """Field-level provenance map for the decision engine."""
    return {
        name: {
            "source_type": row.source_type,
            "entered_by": row.verified_by or None,
        }
        for name, row in active_input_values(planned).items()
    }


def _add_audit_event(
    db: Session, planned: models.PlannedSpray, event_type: str, *,
    actor=None, rationale=None, system_recommendation=None, before=None, after=None,
) -> None:
    """Append (not commit) one immutable audit event. Nothing ever updates these."""
    db.add(models.DecisionAuditEvent(
        planned_spray_id=planned.id,
        event_type=event_type,
        actor=actor,
        rationale=rationale,
        system_recommendation=system_recommendation,
        before=before,
        after=after,
    ))


def _decision_snapshot(planned: models.PlannedSpray) -> dict:
    """Compact decision/current-state snapshot for audit-event before/after blocks."""
    return {
        "decision_outcome": planned.decision_outcome,
        "decision_severity": planned.decision_severity,
        "decision_authority": planned.decision_authority,
        "review_status": planned.review_status,
        "review_comment": planned.review_comment,
        "reviewed_by": planned.reviewed_by,
        "pca_next_action": planned.pca_next_action,
        "outcome": planned.outcome,
        "product_name": planned.product_name,
        "active_ingredient": planned.active_ingredient,
        "rate_amount": planned.rate_amount,
        "rate_unit": planned.rate_unit,
        "intended_date": planned.intended_date.isoformat() if planned.intended_date else None,
        "pre_harvest_interval_days": planned.pre_harvest_interval_days,
        "re_entry_interval_hours": planned.re_entry_interval_hours,
    }


def _eval_farm(farm: models.Farm, planned: models.PlannedSpray | None = None):
    """Farm stand-in for the engine honoring a per-decision harvest input value."""
    harvest = farm.expected_harvest_date
    if planned is not None:
        row = active_input_values(planned).get("expected_harvest_date")
        if row is not None and row.normalized_value:
            harvest = date.fromisoformat(row.normalized_value)
    return SimpleNamespace(expected_harvest_date=harvest)


def create_planned_spray(
    db: Session,
    farm: models.Farm,
    data: schemas.PlannedSprayCreate,
    *,
    input_source_type: str | None = None,
    source_reference: str | None = None,
    expected_harvest_date: date | None = None,
    pilot_import_batch_id: int | None = None,
    commit: bool = True,
) -> models.PlannedSpray:
    """Run the pre-spray decision check against current records and persist the snapshot.

    Also writes the field-level provenance rows (DecisionInputValue) for every critical
    input and the immutable "created" audit event. `input_source_type` overrides the
    provenance derived from `values_source` (the CSV import passes
    "imported_unverified"); imported values can never back a definitive result.
    """
    sprays = list_spray_events(db, farm.id)
    observations = list_scout_observations(db, farm.id)

    source_type = input_source_type or _VALUES_SOURCE_TO_INPUT_SOURCE.get(
        data.values_source, "user_entered"
    )
    harvest = expected_harvest_date or farm.expected_harvest_date
    # Only a per-record harvest date (imported row) gets its own provenance row; a
    # manual check reads the farm-level date, so the farm field stays authoritative
    # (and later edits to it correctly mark the stored decision as stale).
    input_rows = _planned_input_rows(data, expected_harvest_date)
    input_sources = {
        name: {"source_type": source_type, "entered_by": data.values_entered_by}
        for name, _value, _unit in input_rows
    }

    decision = evaluate_planned_spray(
        SimpleNamespace(expected_harvest_date=harvest), data, sprays, observations,
        pca_policies=list_pca_policies(db, farm.id),
        today=clock.current_date(),
        input_sources=input_sources,
    )

    planned = models.PlannedSpray(
        farm_id=farm.id,
        **data.model_dump(),
        pilot_import_batch_id=pilot_import_batch_id,
        decision_outcome=decision.outcome,
        decision_severity=decision.severity,
        decision_confidence=decision.confidence,
        decision_authority=decision.authority_level,
        required_next_action=decision.required_next_action,
        review_required=decision.review_required,
        decision_payload=decision.as_payload(),
        check_risk_level=_SEVERITY_TO_RISK.get(decision.severity, "low"),
        check_text=decision.narrative,
    )
    db.add(planned)
    db.flush()

    now = clock.current_datetime()
    for name, value, unit in input_rows:
        db.add(models.DecisionInputValue(
            planned_spray_id=planned.id,
            field_name=name,
            raw_value=str(value),
            normalized_value=_normalized_input(name, value),
            unit=unit,
            source_type=source_type,
            source_reference=source_reference or data.data_source,
            confidence=data.data_confidence,
            verified_by=data.values_entered_by if source_type == "pca_verified" else None,
            verified_at=now if source_type == "pca_verified" else None,
        ))
    _add_audit_event(
        db, planned, "created",
        actor=data.values_entered_by,
        system_recommendation=decision.outcome,
        after={**_decision_snapshot(planned), "input_source_type": source_type},
    )
    _log_event(
        db, "check_completed", farm_id=farm.id, planned_spray_id=planned.id,
        entry_source=planned.data_source,
        meta={"outcome": decision.outcome, "authority": decision.authority_level},
    )
    if commit:
        db.commit()
        db.refresh(planned)
    else:
        db.flush()
    return planned


def _rerun_decision(db: Session, planned: models.PlannedSpray) -> None:
    """Re-evaluate a planned spray against its CURRENT resolved input values.

    Called after a PCA supersedes values. The prior snapshot is preserved in the audit
    event appended by the caller — this only refreshes the current-state columns.
    """
    farm = get_farm(db, planned.farm_id)
    decision = evaluate_planned_spray(
        _eval_farm(farm, planned), planned,
        list_spray_events(db, planned.farm_id),
        list_scout_observations(db, planned.farm_id),
        pca_policies=list_pca_policies(db, planned.farm_id),
        today=clock.current_date(),
        input_sources=resolve_input_sources(planned),
    )
    planned.decision_outcome = decision.outcome
    planned.decision_severity = decision.severity
    planned.decision_confidence = decision.confidence
    planned.decision_authority = decision.authority_level
    planned.required_next_action = decision.required_next_action
    planned.review_required = decision.review_required
    planned.decision_payload = decision.as_payload()
    planned.check_risk_level = _SEVERITY_TO_RISK.get(decision.severity, "low")
    planned.check_text = decision.narrative


def review_planned_spray(
    db: Session, planned: models.PlannedSpray, data: schemas.PlannedSprayReviewUpdate
) -> models.PlannedSpray:
    """Record the PCA/agronomist's review of a pre-spray decision.

    History is never overwritten: the prior state goes into an immutable audit event,
    and every structured `proposed_*` edit appends a superseding pca_verified
    DecisionInputValue (the old value row stays). When values changed, the decision is
    re-evaluated against the updated values; the pre-review snapshot survives in the
    audit event's `before`.
    """
    before = _decision_snapshot(planned)
    before["decision_payload"] = planned.decision_payload

    planned.review_status = data.action
    planned.review_comment = data.review_comment
    planned.reviewed_by = data.reviewed_by
    planned.reviewed_at = clock.current_datetime()
    planned.pca_next_action = data.pca_next_action if data.action == "edited" else None

    edits = data.proposed_field_edits()
    # The application rate is ONE provenance row (amount + unit together): a
    # unit-only edit re-verifies the current amount with the new unit.
    rate_unit_edit = edits.pop("rate_unit", None)
    if rate_unit_edit is not None:
        if "rate_amount" not in edits and planned.rate_amount is not None:
            edits["rate_amount"] = planned.rate_amount
        planned.rate_unit = rate_unit_edit
    superseded_fields: dict[str, dict] = {}
    if edits:
        current = active_input_values(planned)
        now = clock.current_datetime()
        for field_name, new_value in edits.items():
            prior = current.get(field_name)
            unit = None
            if field_name == "rate_amount":
                unit = rate_unit_edit or planned.rate_unit
            elif field_name == "pre_harvest_interval_days":
                unit = "days"
            elif field_name == "re_entry_interval_hours":
                unit = "hours"
            row = models.DecisionInputValue(
                planned_spray_id=planned.id,
                field_name=field_name,
                raw_value=str(new_value),
                normalized_value=_normalized_input(field_name, new_value),
                unit=unit,
                source_type="pca_verified",
                source_reference="pca_review",
                confidence="pca_reviewed",
                verified_by=data.reviewed_by,
                verified_at=now,
                supersedes_input_value_id=prior.id if prior else None,
            )
            db.add(row)
            superseded_fields[field_name] = {
                "from": getattr(planned, field_name, None)
                if not isinstance(getattr(planned, field_name, None), date)
                else getattr(planned, field_name).isoformat(),
                "to": new_value if not isinstance(new_value, date) else new_value.isoformat(),
            }
            # Denormalized display copy follows the latest verified value.
            setattr(planned, field_name, new_value)
            _add_audit_event(
                db, planned, "input_value_superseded",
                actor=data.reviewed_by,
                rationale=data.review_comment,
                after={"field": field_name, **superseded_fields[field_name]},
            )
        db.flush()  # assign input-value ids before re-resolving
        _rerun_decision(db, planned)

    _add_audit_event(
        db, planned, "reviewed",
        actor=data.reviewed_by,
        rationale=data.review_comment,
        system_recommendation=before["decision_outcome"],
        before=before,
        after={
            **_decision_snapshot(planned),
            "review_action": data.action,
            "changed_fields": superseded_fields,
            "relied_on_evidence": data.relied_on_evidence,
        },
    )

    seconds_to_review = (planned.reviewed_at - planned.created_at).total_seconds()
    _log_event(
        db, "review_recorded", farm_id=planned.farm_id, planned_spray_id=planned.id,
        meta={"action": data.action, "seconds_from_check": round(seconds_to_review, 1)},
    )
    db.commit()
    db.refresh(planned)
    return planned


def record_planned_spray_outcome(
    db: Session, planned: models.PlannedSpray, data: schemas.PlannedSprayOutcomeUpdate
) -> models.PlannedSpray:
    """Record the real-world outcome; applied outcomes create the linked SprayEvent.

    The human gate: when the decision required review, an applied outcome cannot be
    recorded until a PCA has approved or edited the decision (rejected/not_reviewed
    raise `ReviewRequiredError`). Non-applied outcomes are always recordable.
    """
    if data.outcome in APPLIED_OUTCOMES and not decision_status.applied_outcome_allowed(
        planned
    ):
        raise ReviewRequiredError(
            "This decision requires a PCA / agronomist review (approve or edit) before an "
            "applied outcome can be recorded."
        )
    before = _decision_snapshot(planned)

    # Chronology invariants: an outcome can never predate its check, and an applied
    # outcome (or its application date) can never predate the planned date.
    outcome_date = data.outcome_date or clock.current_date()
    checked_on = planned.created_at.date()
    if outcome_date < checked_on:
        raise OutcomeChronologyError(
            f"Outcome date {outcome_date.isoformat()} is before the check was run "
            f"({checked_on.isoformat()}) — an outcome cannot predate its decision check."
        )
    if data.outcome in APPLIED_OUTCOMES:
        application_date = data.application_date or planned.intended_date
        if outcome_date < planned.intended_date:
            raise OutcomeChronologyError(
                f"Outcome date {outcome_date.isoformat()} is before the planned "
                f"application date ({planned.intended_date.isoformat()}) — an applied "
                f"outcome cannot predate the plan it records."
            )
        if application_date < planned.intended_date:
            raise OutcomeChronologyError(
                f"Application date {application_date.isoformat()} is before the planned "
                f"application date ({planned.intended_date.isoformat()})."
            )

    planned.outcome = data.outcome
    planned.outcome_reason = data.outcome_reason
    planned.outcome_date = outcome_date
    planned.outcome_product_name = data.outcome_product_name
    planned.outcome_active_ingredient = data.outcome_active_ingredient

    if data.outcome in APPLIED_OUTCOMES and planned.spray_event_id is None:
        changed = data.outcome == "changed_product"
        event = models.SprayEvent(
            farm_id=planned.farm_id,
            product_name=data.outcome_product_name if changed else planned.product_name,
            active_ingredient=(
                data.outcome_active_ingredient if changed else planned.active_ingredient
            ),
            target_pest_or_disease=planned.target_pest_or_disease,
            field_block=planned.field_block,
            application_date=data.application_date or planned.intended_date,
            cost=None if changed else planned.estimated_cost,
            # PHI/REI were entered for the planned product; they do not carry over to a
            # different product — the changed product's values must be re-entered.
            pre_harvest_interval_days=None if changed else planned.pre_harvest_interval_days,
            re_entry_interval_hours=None if changed else planned.re_entry_interval_hours,
            notes=(
                f"Logged from planned spray #{planned.id} "
                + (
                    f"(product changed from '{planned.product_name}' after the pre-spray "
                    f"check; enter the new product's PHI/REI from its label)."
                    if changed
                    else "(pre-spray decision recorded)."
                )
            ),
            data_source=planned.data_source,
            data_confidence=planned.data_confidence,
        )
        db.add(event)
        db.flush()  # assign event.id for the link
        planned.spray_event_id = event.id

    _add_audit_event(
        db, planned, "outcome_recorded",
        actor=None,
        rationale=data.outcome_reason,
        system_recommendation=planned.decision_outcome,
        before=before,
        after={
            **_decision_snapshot(planned),
            "outcome_date": outcome_date.isoformat(),
            "outcome_product_name": planned.outcome_product_name,
            "follow_up_required": decision_status.follow_up_required(planned),
        },
    )
    _log_event(
        db, "outcome_recorded", farm_id=planned.farm_id, planned_spray_id=planned.id,
        meta={
            "outcome": data.outcome,
            "decision_outcome": planned.decision_outcome,
            # "changed" = the human did something other than spray as planned.
            "decision_changed": data.outcome != "sprayed_as_planned",
        },
    )
    db.commit()
    db.refresh(planned)
    return planned


# -------------------------------------------------------- Decision audit trail
def list_audit_events(db: Session, planned_id: int) -> list[models.DecisionAuditEvent]:
    """Oldest-first immutable audit history for one decision (read-only)."""
    return list(
        db.scalars(
            select(models.DecisionAuditEvent)
            .where(models.DecisionAuditEvent.planned_spray_id == planned_id)
            .order_by(models.DecisionAuditEvent.created_at, models.DecisionAuditEvent.id)
        )
    )


def list_input_values(db: Session, planned_id: int) -> list[models.DecisionInputValue]:
    """Oldest-first field-level provenance rows (the full supersede chain)."""
    return list(
        db.scalars(
            select(models.DecisionInputValue)
            .where(models.DecisionInputValue.planned_spray_id == planned_id)
            .order_by(models.DecisionInputValue.created_at, models.DecisionInputValue.id)
        )
    )


# ------------------------------------------------------- Follow-up timeline
def list_follow_up_events(
    db: Session, planned_id: int
) -> list[models.DecisionFollowUpEvent]:
    return list(
        db.scalars(
            select(models.DecisionFollowUpEvent)
            .where(models.DecisionFollowUpEvent.planned_spray_id == planned_id)
            .order_by(
                models.DecisionFollowUpEvent.observed_at,
                models.DecisionFollowUpEvent.id,
            )
        )
    )


def add_follow_up_event(
    db: Session, planned: models.PlannedSpray, data: schemas.FollowUpEventCreate
) -> models.DecisionFollowUpEvent:
    """Append one follow-up event to a decision's timeline (append-only, no edits).

    Follow-up describes what happened AFTER a recorded outcome, so an outcome must
    exist and the event cannot predate the decision check.
    """
    if decision_status.is_open(planned):
        raise FollowUpError(
            "Record the real-world outcome first — follow-up events describe what "
            "happened after the recorded outcome."
        )
    if data.observed_at < planned.created_at.date():
        raise FollowUpError(
            f"Follow-up observed_at {data.observed_at.isoformat()} is before the "
            f"decision check ({planned.created_at.date().isoformat()})."
        )
    event = models.DecisionFollowUpEvent(
        planned_spray_id=planned.id, **data.model_dump()
    )
    db.add(event)
    db.flush()
    _add_audit_event(
        db, planned, "follow_up_added",
        actor=data.entered_by,
        rationale=data.evidence_notes,
        after={
            "follow_up_event_id": event.id,
            "event_type": data.event_type,
            "observed_at": data.observed_at.isoformat(),
            "severity": data.severity,
            "rescue_required": data.rescue_required,
            "cost": data.cost,
        },
    )
    db.commit()
    db.refresh(event)
    return event


def list_all_follow_up_events(db: Session) -> dict[int, list[models.DecisionFollowUpEvent]]:
    """Follow-up events across ALL farms keyed by planned_spray_id (calibration join)."""
    out: dict[int, list[models.DecisionFollowUpEvent]] = {}
    rows = db.scalars(
        select(models.DecisionFollowUpEvent).order_by(
            models.DecisionFollowUpEvent.observed_at, models.DecisionFollowUpEvent.id
        )
    )
    for row in rows:
        out.setdefault(row.planned_spray_id, []).append(row)
    return out


def list_farm_follow_up_events(
    db: Session, farm_id: int
) -> dict[int, list[models.DecisionFollowUpEvent]]:
    """Follow-up events for every planned spray of a farm, keyed by planned_spray_id."""
    rows = db.scalars(
        select(models.DecisionFollowUpEvent)
        .join(
            models.PlannedSpray,
            models.PlannedSpray.id == models.DecisionFollowUpEvent.planned_spray_id,
        )
        .where(models.PlannedSpray.farm_id == farm_id)
        .order_by(
            models.DecisionFollowUpEvent.observed_at, models.DecisionFollowUpEvent.id
        )
    )
    out: dict[int, list[models.DecisionFollowUpEvent]] = {}
    for row in rows:
        out.setdefault(row.planned_spray_id, []).append(row)
    return out


def list_farm_audit_events(
    db: Session, farm_id: int
) -> dict[int, list[models.DecisionAuditEvent]]:
    """Audit events for every planned spray of a farm, keyed by planned_spray_id."""
    rows = db.scalars(
        select(models.DecisionAuditEvent)
        .join(
            models.PlannedSpray,
            models.PlannedSpray.id == models.DecisionAuditEvent.planned_spray_id,
        )
        .where(models.PlannedSpray.farm_id == farm_id)
        .order_by(models.DecisionAuditEvent.created_at, models.DecisionAuditEvent.id)
    )
    out: dict[int, list[models.DecisionAuditEvent]] = {}
    for row in rows:
        out.setdefault(row.planned_spray_id, []).append(row)
    return out


def list_farm_input_values(
    db: Session, farm_id: int
) -> dict[int, list[models.DecisionInputValue]]:
    """Input-value chains for every planned spray of a farm, keyed by planned_spray_id."""
    rows = db.scalars(
        select(models.DecisionInputValue)
        .join(
            models.PlannedSpray,
            models.PlannedSpray.id == models.DecisionInputValue.planned_spray_id,
        )
        .where(models.PlannedSpray.farm_id == farm_id)
        .order_by(models.DecisionInputValue.created_at, models.DecisionInputValue.id)
    )
    out: dict[int, list[models.DecisionInputValue]] = {}
    for row in rows:
        out.setdefault(row.planned_spray_id, []).append(row)
    return out


# --------------------------------------------------------------- CSV pilot import
def _existing_duplicate_keys(db: Session, farm_id: int, record_type: str) -> dict:
    """Duplicate keys of records already in the DB -> human-readable labels."""
    keys: dict = {}
    if record_type == csv_import.RECORD_TYPE_PLANNED:
        for p in list_planned_sprays(db, farm_id):
            label = f"planned spray #{p.id} ({p.product_name} on {p.intended_date})"
            if p.external_record_id:
                keys[csv_import.duplicate_key_for_planned(
                    p.external_record_id, None, None
                )] = label
            keys[csv_import.duplicate_key_for_planned(
                None, p.product_name, p.intended_date, p.field_block
            )] = label
    else:
        for o in list_scout_observations(db, farm_id):
            label = f"scouting observation #{o.id} ({o.visible_issue} on {o.observation_date})"
            if o.external_record_id:
                keys[csv_import.duplicate_key_for_scouting(
                    o.external_record_id, None, None
                )] = label
            keys[csv_import.duplicate_key_for_scouting(
                None, o.visible_issue, o.observation_date, o.field_block
            )] = label
    return keys


def commit_import(
    db: Session,
    farm: models.Farm,
    record_type: str,
    report: csv_import.DryRunReport,
    *,
    data_source: str,
    data_confidence: str = "user_provided",
    source_label: str | None = None,
    source_filename: str | None = None,
    source_system: str | None = None,
    imported_by: str | None = None,
    notes: str | None = None,
    ai_judgment_id: int | None = None,
    entry_source: str = "csv",
) -> dict:
    """Commit a validated DryRunReport's importable rows (shared by CSV + AI extraction).

    Committed rows carry full provenance: a PilotImportBatch, per-row `data_source`
    ("spreadsheet" or "ai_extracted"), source filename/system, and (for planned
    sprays) field-level DecisionInputValue rows tagged imported_unverified — imported
    regulatory values never silently become verified and never auto-approve.
    """
    payload = report.as_payload()
    batch = models.PilotImportBatch(
        farm_id=farm.id,
        source_label=source_label or source_filename or f"import ({record_type})",
        imported_by=imported_by,
        notes=notes,
        data_source=data_source,
        data_confidence=data_confidence,
        record_type=record_type,
        source_filename=source_filename,
        ai_judgment_id=ai_judgment_id,
    )
    db.add(batch)
    db.flush()

    created_ids: list[int] = []
    if record_type == csv_import.RECORD_TYPE_PLANNED:
        for row in report.importable_rows:
            values = row.values
            data = schemas.PlannedSprayCreate(
                intended_date=values["intended_date"],
                product_name=values["product_name"],
                active_ingredient=values.get("active_ingredient"),
                target_pest_or_disease=values.get("target_pest_or_disease"),
                pre_harvest_interval_days=values.get("pre_harvest_interval_days"),
                re_entry_interval_hours=values.get("re_entry_interval_hours"),
                estimated_cost=values.get("estimated_cost"),
                external_record_id=values.get("external_record_id"),
                field_block=values.get("field_block"),
                crop=values.get("crop"),
                treated_acres=values.get("treated_acres"),
                epa_reg_no=values.get("epa_reg_no"),
                moa_group=values.get("moa_group"),
                rate_amount=values.get("rate_amount"),
                rate_unit=values.get("rate_unit"),
                recommendation_author=values.get("recommendation_author"),
                source_system=source_system,
                source_filename=source_filename,
                notes=values.get("notes"),
                values_source="grower_entered",  # display only; provenance is field-level
                values_entered_by=imported_by,
                data_source=data_source,
                data_confidence=data_confidence,
            )
            planned = create_planned_spray(
                db, farm, data,
                input_source_type="imported_unverified",
                source_reference=(
                    f"{source_filename or entry_source} row {row.row_number}"
                ),
                expected_harvest_date=values.get("expected_harvest_date"),
                pilot_import_batch_id=batch.id,
                commit=False,
            )
            # The import path records the row's origin, not a human values-enterer.
            planned.values_source = "imported_unverified"
            created_ids.append(planned.id)
        batch.planned_spray_count = len(created_ids)
    else:
        for row in report.importable_rows:
            values = row.values
            severity = values.get("severity")
            row_notes = values.get("notes")
            if severity is not None and severity not in (1, 2, 3, 4, 5):
                # A non-1-5 severity is only importable with its scale stated; keep the
                # raw reading visible instead of silently dropping it.
                scale_note = (
                    f"[imported severity {severity} on scale "
                    f"{values.get('severity_scale')}]"
                )
                row_notes = f"{row_notes} {scale_note}".strip() if row_notes else scale_note
            obs = models.ScoutObservation(
                farm_id=farm.id,
                observation_date=values["observation_date"],
                crop_stage=values.get("crop_stage"),
                visible_issue=values["visible_issue"],
                severity_1_to_5=(
                    severity if severity in (1, 2, 3, 4, 5) else None
                ),
                notes=row_notes,
                external_record_id=values.get("external_record_id"),
                field_block=values.get("field_block"),
                severity_scale=values.get("severity_scale"),
                count_value=values.get("count_value"),
                observer=values.get("observer"),
                source_system=source_system,
                source_filename=source_filename,
                data_source=data_source,
                data_confidence=data_confidence,
                pilot_import_batch_id=batch.id,
            )
            db.add(obs)
            db.flush()
            created_ids.append(obs.id)
        batch.scouting_observation_count = len(created_ids)

    _log_event(
        db, "import_used", farm_id=farm.id, entry_source=entry_source,
        meta={
            "record_type": record_type,
            "imported": len(created_ids),
            "duplicates_skipped": payload["duplicate_count"],
            "rows_with_errors": payload["error_count"],
        },
    )
    db.commit()
    db.refresh(batch)
    return {
        "dry_run": False,
        "committed": True,
        "report": payload,
        "batch": {
            "id": batch.id,
            "record_type": batch.record_type,
            "source_filename": batch.source_filename,
            "imported_by": batch.imported_by,
            "ai_judgment_id": batch.ai_judgment_id,
            "planned_spray_count": batch.planned_spray_count,
            "scouting_observation_count": batch.scouting_observation_count,
            "imported_at": batch.created_at.isoformat(),
        },
        "created_record_ids": created_ids,
    }


# Public name for callers outside this module (routes reuse the same dedupe keys).
def existing_duplicate_keys(db: Session, farm_id: int, record_type: str) -> dict:
    return _existing_duplicate_keys(db, farm_id, record_type)


def import_csv(db: Session, farm: models.Farm, req: schemas.CsvImportRequest) -> dict:
    """CSV pilot import: dry-run validation report, or commit the importable rows."""
    report = csv_import.parse_csv(
        req.record_type,
        req.csv_text,
        mapping_overrides=req.mapping,
        existing_keys=_existing_duplicate_keys(db, farm.id, req.record_type),
    )
    if req.dry_run:
        return {
            "dry_run": True, "committed": False, "report": report.as_payload(),
            "batch": None,
        }
    return commit_import(
        db, farm, req.record_type, report,
        data_source="spreadsheet",
        source_label=req.source_filename or f"CSV import ({req.record_type})",
        source_filename=req.source_filename,
        source_system=req.source_system,
        imported_by=req.imported_by,
        notes=req.notes,
        entry_source="csv",
    )


def import_rows(db: Session, farm: models.Farm, req: schemas.RowImportRequest) -> dict:
    """Commit path for human-reviewed structured rows (AI extraction preview → import).

    The rows are RE-validated server-side through the exact same path as the CSV
    import (types, required fields, regulatory warnings, duplicates) — a corrected
    preview can never bypass validation. Rows land as `ai_extracted` provenance with
    field-level imported_unverified values, so they can never auto-approve.
    """
    report = csv_import.validate_rows(
        req.record_type,
        req.rows,
        existing_keys=_existing_duplicate_keys(db, farm.id, req.record_type),
    )
    if req.dry_run:
        return {
            "dry_run": True, "committed": False, "report": report.as_payload(),
            "batch": None,
        }
    return commit_import(
        db, farm, req.record_type, report,
        data_source="ai_extracted",
        source_label=req.source_label or "AI-extracted import",
        source_filename=req.source_filename,
        imported_by=req.imported_by,
        notes=req.notes,
        ai_judgment_id=req.ai_judgment_id,
        entry_source="ai_document",
    )


def comparable_decisions(db: Session, planned: models.PlannedSpray) -> list[dict]:
    """Deterministic retrieval of comparable REAL decisions for the AI review brief.

    Same farm, non-demo, excluding the decision itself; comparable = same target via
    the explicit alias dictionary (never fuzzy), or same active ingredient, or same
    MoA group. Each comparable carries its follow-up summary so the brief is grounded
    in recorded outcomes, not model knowledge. No embeddings, no scoring — plain
    predicates a PCA can verify by eye.
    """
    from app.pilot_evidence import derive_follow_up_summary

    follow_ups = list_farm_follow_up_events(db, planned.farm_id)
    target = planned.target_pest_or_disease
    ai = (planned.active_ingredient or "").strip().lower()
    moa = (planned.moa_group or "").strip().lower()

    out: list[dict] = []
    for p in list_planned_sprays(db, planned.farm_id):
        if p.id == planned.id or decision_status.is_demo_record(p):
            continue
        basis = []
        if target and target_aliases.match_targets(
            target, p.target_pest_or_disease
        ) == target_aliases.MATCH:
            basis.append("same_target")
        if ai and (p.active_ingredient or "").strip().lower() == ai:
            basis.append("same_active_ingredient")
        if moa and (p.moa_group or "").strip().lower() == moa:
            basis.append("same_moa_group")
        if not basis:
            continue
        summary = derive_follow_up_summary(p, follow_ups.get(p.id, []))
        out.append({
            "id": p.id,
            "match_basis": basis,
            "product_name": p.product_name,
            "active_ingredient": p.active_ingredient,
            "moa_group": p.moa_group,
            "target_pest_or_disease": p.target_pest_or_disease,
            "intended_date": p.intended_date.isoformat() if p.intended_date else None,
            "decision_outcome": p.decision_outcome,
            "recorded_outcome": p.outcome,
            "follow_up": {
                "has_follow_up": summary["has_follow_up"],
                "rescue_required": summary["rescue_required"],
                "confirmed_avoided": summary["confirmed_avoided"],
                "spray_ultimately_applied": summary["spray_ultimately_applied"],
                "severity_before": summary["severity_before"],
                "severity_after": summary["severity_after"],
                "yield_impact": summary["yield_impact"],
            },
        })
    return out


# ---------------------------------------------------------------- AI judgment log
def log_ai_judgment(
    db: Session, *, kind: str, model_id: str, prompt_version: str, input_digest: str,
    output: dict | None, confidence: str, abstained: bool, abstain_reason: str | None,
    is_mock: bool, farm_id: int | None = None, planned_spray_id: int | None = None,
) -> models.AiJudgment:
    """Append one immutable AI-judgment record (there is no update or delete)."""
    judgment = models.AiJudgment(
        kind=kind, farm_id=farm_id, planned_spray_id=planned_spray_id,
        model_id=model_id, prompt_version=prompt_version, input_digest=input_digest,
        output=output, confidence=confidence, abstained=abstained,
        abstain_reason=abstain_reason, is_mock=is_mock,
    )
    db.add(judgment)
    db.commit()
    db.refresh(judgment)
    return judgment


def list_ai_judgments(
    db: Session, *, farm_id: int | None = None, planned_spray_id: int | None = None,
    kind: str | None = None,
) -> list[models.AiJudgment]:
    stmt = select(models.AiJudgment).order_by(
        models.AiJudgment.created_at, models.AiJudgment.id
    )
    if farm_id is not None:
        stmt = stmt.where(models.AiJudgment.farm_id == farm_id)
    if planned_spray_id is not None:
        stmt = stmt.where(models.AiJudgment.planned_spray_id == planned_spray_id)
    if kind is not None:
        stmt = stmt.where(models.AiJudgment.kind == kind)
    return list(db.scalars(stmt))


def delete_planned_spray(db: Session, planned: models.PlannedSpray) -> None:
    db.delete(planned)
    db.commit()


# ------------------------------------------------------------------ Pilot events
def _log_event(
    db: Session, event_type: str, *, farm_id=None, planned_spray_id=None,
    entry_source=None, meta=None,
) -> None:
    """Add (not commit) one server-side instrumentation event to the current transaction."""
    db.add(models.PilotEvent(
        event_type=event_type, farm_id=farm_id, planned_spray_id=planned_spray_id,
        entry_source=entry_source, meta=meta,
    ))


def create_pilot_event(db: Session, data: schemas.PilotEventCreate) -> models.PilotEvent:
    """Client-reported workflow event (check_started / check_abandoned / import_used)."""
    event = models.PilotEvent(**data.model_dump())
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def list_pilot_events(db: Session) -> list[models.PilotEvent]:
    return list(
        db.scalars(
            select(models.PilotEvent).order_by(models.PilotEvent.created_at.desc(),
                                               models.PilotEvent.id.desc())
        )
    )


def list_all_planned_sprays(db: Session) -> list[models.PlannedSpray]:
    """Every planned spray across farms (for the instrumentation summary)."""
    return list(db.scalars(select(models.PlannedSpray).order_by(models.PlannedSpray.id)))


# --------------------------------------------------------------- Pilot intake
def create_pilot_farm(db: Session, data: schemas.PilotFarmIntake) -> models.Farm:
    """Create a farm plus its provided sprays and an optional scouting concern."""
    farm = models.Farm(
        name=data.name,
        location=data.location,
        country=data.country,
        crop_type=data.crop_type,
        greenhouse_area=data.greenhouse_area,
        expected_harvest_date=data.expected_harvest_date,
        advisor_involved=data.advisor_involved,
    )
    db.add(farm)
    db.flush()  # assign farm.id

    for sp in data.spray_events:
        if not sp.product_name:
            continue
        db.add(models.SprayEvent(
            farm_id=farm.id,
            product_name=sp.product_name,
            active_ingredient=sp.active_ingredient,
            application_date=sp.application_date or clock.current_date(),
            cost=sp.cost,
            pre_harvest_interval_days=sp.pre_harvest_interval_days,
            re_entry_interval_hours=sp.re_entry_interval_hours,
        ))

    if data.scouting_concern:
        db.add(models.ScoutObservation(
            farm_id=farm.id,
            observation_date=clock.current_date(),
            visible_issue=data.scouting_concern,
            severity_1_to_5=data.scouting_severity_1_to_5,
        ))

    db.commit()
    db.refresh(farm)
    return farm


# --------------------------------------------------- Concierge pilot import
def import_pilot_data(
    db: Session, farm: models.Farm, data: schemas.PilotImport
) -> models.PilotImportBatch:
    """Create a PilotImportBatch plus its spray + scouting records from a concierge import.

    Every created record is tagged with the import's `data_source`/`data_confidence` and linked
    to the batch via `pilot_import_batch_id`, so the audit trail is complete. Returns the batch
    (with its counts populated).
    """
    batch = models.PilotImportBatch(
        farm_id=farm.id,
        source_label=data.source_label,
        imported_by=data.imported_by,
        notes=data.notes,
        data_source=data.data_source,
        data_confidence=data.data_confidence,
    )
    db.add(batch)
    db.flush()  # assign batch.id so records can reference it

    spray_count = 0
    for sp in data.spray_events:
        if not sp.product_name:
            continue
        db.add(models.SprayEvent(
            farm_id=farm.id,
            product_name=sp.product_name,
            active_ingredient=sp.active_ingredient,
            target_pest_or_disease=sp.target_pest_or_disease,
            application_date=sp.application_date or clock.current_date(),
            cost=sp.cost,
            pre_harvest_interval_days=sp.pre_harvest_interval_days,
            re_entry_interval_hours=sp.re_entry_interval_hours,
            notes=sp.notes,
            data_source=data.data_source,
            data_confidence=data.data_confidence,
            pilot_import_batch_id=batch.id,
        ))
        spray_count += 1

    scouting_count = 0
    for ob in data.scouting_observations:
        db.add(models.ScoutObservation(
            farm_id=farm.id,
            observation_date=ob.observation_date or clock.current_date(),
            crop_stage=ob.crop_stage,
            visible_issue=ob.visible_issue,
            severity_1_to_5=ob.severity_1_to_5,
            notes=ob.notes,
            data_source=data.data_source,
            data_confidence=data.data_confidence,
            pilot_import_batch_id=batch.id,
        ))
        scouting_count += 1

    batch.spray_event_count = spray_count
    batch.scouting_observation_count = scouting_count
    db.commit()
    db.refresh(batch)
    return batch


def list_pilot_import_batches(db: Session, farm_id: int) -> list[models.PilotImportBatch]:
    """Newest-first import batches for a farm (for the case study + audit packet)."""
    return list(
        db.scalars(
            select(models.PilotImportBatch)
            .where(models.PilotImportBatch.farm_id == farm_id)
            .order_by(models.PilotImportBatch.created_at.desc(), models.PilotImportBatch.id.desc())
        )
    )


# ----------------------------------------------------------------- PCA policies
def list_pca_policies(db: Session, farm_id: int) -> list[models.PcaPolicy]:
    """The farm's current policies: latest row per normalized target wins
    (history is kept, mirroring SprayBaseline)."""
    rows = db.scalars(
        select(models.PcaPolicy)
        .where(models.PcaPolicy.farm_id == farm_id)
        .order_by(models.PcaPolicy.created_at.desc(), models.PcaPolicy.id.desc())
    )
    current: dict[str, models.PcaPolicy] = {}
    for policy in rows:
        key = (policy.target_pest_or_disease or "").strip().lower()
        if key and key not in current:
            current[key] = policy
    return list(current.values())


def set_pca_policy(
    db: Session, farm_id: int, data: schemas.PcaPolicyCreate
) -> models.PcaPolicy:
    """Record a new policy for the farm+target (the latest one is what the engine uses)."""
    policy = models.PcaPolicy(farm_id=farm_id, **data.model_dump())
    db.add(policy)
    db.commit()
    db.refresh(policy)
    return policy


# --------------------------------------------------------------- Spray baseline
def get_spray_baseline(db: Session, farm_id: int) -> models.SprayBaseline | None:
    """The farm's current baseline (newest wins — we keep history but use the latest)."""
    return db.scalars(
        select(models.SprayBaseline)
        .where(models.SprayBaseline.farm_id == farm_id)
        .order_by(models.SprayBaseline.created_at.desc(), models.SprayBaseline.id.desc())
    ).first()


def set_spray_baseline(
    db: Session, farm_id: int, data: schemas.SprayBaselineCreate
) -> models.SprayBaseline:
    """Record a new baseline for the farm (latest one is the one reduction uses)."""
    baseline = models.SprayBaseline(farm_id=farm_id, **data.model_dump())
    db.add(baseline)
    db.commit()
    db.refresh(baseline)
    return baseline


# ------------------------------------------------------------------ Demo reset
def has_non_demo_data(db: Session) -> bool:
    """True if anything in the DB might be real pilot data (conservative).

    Guards the internal demo-reset endpoint: seeding drops EVERY table, so a reset is
    only allowed when every provenance-carrying row is demo/simulated, no
    provenance-less rows (recommendations, feedback) exist, and every farm actually
    has records proving it is a demo farm.
    """
    provenance_models = (
        models.SprayEvent, models.ScoutObservation, models.PlannedSpray,
        models.SprayBaseline, models.PcaPolicy, models.PilotImportBatch,
        models.InputPlan, models.InputPlanItem, models.SupplierQuote,
        models.FinancingOffer, models.PurchaseOrder, models.OrderEvent,
    )
    for model in provenance_models:
        for row in db.scalars(select(model)):
            if not decision_status.is_demo_record(row):
                return True
    # These carry no provenance fields — any row could be real, so be conservative.
    if db.scalars(select(models.Recommendation)).first() is not None:
        return True
    if db.scalars(select(models.PilotFeedback)).first() is not None:
        return True
    # A farm with zero records can't be proven demo.
    for farm in db.scalars(select(models.Farm)):
        if not (farm.spray_events or farm.scout_observations or farm.planned_sprays):
            return True
    return False


# ------------------------------------------------------------- Pilot feedback
def list_pilot_feedback(db: Session) -> list[models.PilotFeedback]:
    return list(
        db.scalars(
            select(models.PilotFeedback).order_by(models.PilotFeedback.created_at.desc())
        )
    )


def create_pilot_feedback(
    db: Session, data: schemas.PilotFeedbackCreate
) -> models.PilotFeedback:
    fb = models.PilotFeedback(**data.model_dump())
    db.add(fb)
    db.commit()
    db.refresh(fb)
    return fb

# ---------------------------------------------------------- Inputs & finance
# Phase 1 procurement (RFQ model, concierge-operated). No auth exists in v1 —
# attribution is by free-text actor strings, exactly like reviews; the concierge
# entry points are namespaced /internal in main.py. All lifecycle gates live in
# app/procurement_status.py; these helpers enforce them and never move money.


class ProcurementStateError(Exception):
    """Raised on an invalid procurement lifecycle transition (mapped to 409)."""


class ProcurementEligibilityError(Exception):
    """Raised when an ineligible decision is used to back a purchasable input
    (mapped to 409). Eligibility is decision_status.procurement_eligible."""


class ProcurementValidationError(Exception):
    """Raised when a reference is inconsistent (a quote line for a foreign item,
    a cross-farm application link, ...) — mapped to 422."""


def get_input_plan(db: Session, plan_id: int) -> models.InputPlan | None:
    return db.get(models.InputPlan, plan_id)


def list_input_plans(db: Session, farm_id: int) -> list[models.InputPlan]:
    return list(
        db.scalars(
            select(models.InputPlan)
            .where(models.InputPlan.farm_id == farm_id)
            .order_by(models.InputPlan.created_at.desc(), models.InputPlan.id.desc())
        )
    )


def get_input_plan_item(db: Session, item_id: int) -> models.InputPlanItem | None:
    return db.get(models.InputPlanItem, item_id)


def _validate_plan_item(
    db: Session,
    farm: models.Farm,
    plan_is_demo: bool,
    item: schemas.InputPlanItemCreate,
) -> None:
    """Eligibility + scope + demo/real-separation checks for one item."""
    if decision_status.is_demo_record(item) != plan_is_demo:
        raise ProcurementStateError(
            "simulated and real records can never mix within one input plan"
        )
    if item.planned_spray_id is None:
        return
    planned = get_planned_spray(db, item.planned_spray_id)
    if planned is None or planned.farm_id != farm.id:
        raise ProcurementValidationError(
            f"planned spray {item.planned_spray_id} not found on this farm"
        )
    if not decision_status.procurement_eligible(planned):
        raise ProcurementEligibilityError(
            f"decision {planned.id} is not eligible for procurement "
            f"(review_state={decision_status.review_state(planned)}, "
            f"outcome={planned.outcome}); a PCA-approved or PCA-edited review is "
            "required and an avoided decision can never back a purchase"
        )
    if decision_status.is_demo_record(planned) != plan_is_demo:
        raise ProcurementStateError(
            "a simulated demo decision can only back a simulated demo input plan "
            "(and a real decision a real plan)"
        )


def create_input_plan(
    db: Session, farm: models.Farm, data: schemas.InputPlanCreate
) -> models.InputPlan:
    plan = models.InputPlan(
        farm_id=farm.id, **data.model_dump(exclude={"items"})
    )
    for item in data.items:
        _validate_plan_item(db, farm, decision_status.is_demo_record(plan), item)
    db.add(plan)
    db.flush()
    for item in data.items:
        db.add(models.InputPlanItem(input_plan_id=plan.id, **item.model_dump()))
    db.commit()
    db.refresh(plan)
    return plan


def add_input_plan_item(
    db: Session, plan: models.InputPlan, data: schemas.InputPlanItemCreate
) -> models.InputPlanItem:
    if not procurement_status.plan_is_mutable(plan):
        raise ProcurementStateError(
            f"items can only be added while the plan is a draft (status is "
            f"'{plan.status}')"
        )
    _validate_plan_item(db, plan.farm, decision_status.is_demo_record(plan), data)
    item = models.InputPlanItem(input_plan_id=plan.id, **data.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def delete_input_plan_item(db: Session, item: models.InputPlanItem) -> None:
    if not procurement_status.plan_is_mutable(item.input_plan):
        raise ProcurementStateError(
            "items can only be removed while the plan is a draft"
        )
    db.delete(item)
    db.commit()


def submit_input_plan(
    db: Session, plan: models.InputPlan, data: schemas.InputPlanSubmit
) -> models.InputPlan:
    if not procurement_status.plan_transition_allowed(
        plan.status, procurement_status.PLAN_SUBMITTED
    ):
        raise ProcurementStateError(
            f"only a draft plan can be submitted for quotes (status is '{plan.status}')"
        )
    if not plan.items:
        raise ProcurementStateError("a plan needs at least one item to request quotes")
    # Re-check every linked decision: its review/outcome may have changed since
    # the item was added (e.g. a PCA rejected the decision after the fact).
    ineligible = []
    for item in plan.items:
        if item.planned_spray is not None and not decision_status.procurement_eligible(
            item.planned_spray
        ):
            ineligible.append(item.planned_spray_id)
    if ineligible:
        raise ProcurementEligibilityError(
            "linked decisions are no longer eligible for procurement: "
            + ", ".join(str(i) for i in sorted(set(ineligible)))
        )
    plan.status = procurement_status.PLAN_SUBMITTED
    plan.submitted_at = clock.current_datetime()
    plan.submitted_by = data.submitted_by
    db.commit()
    db.refresh(plan)
    return plan


def cancel_input_plan(
    db: Session, plan: models.InputPlan, data: schemas.InputPlanCancel
) -> models.InputPlan:
    if not procurement_status.plan_transition_allowed(
        plan.status, procurement_status.PLAN_CANCELLED
    ):
        raise ProcurementStateError(
            f"a plan with status '{plan.status}' cannot be cancelled"
            + (" — cancel the order instead" if plan.status == "ordered" else "")
        )
    plan.status = procurement_status.PLAN_CANCELLED
    plan.cancelled_at = clock.current_datetime()
    plan.cancelled_reason = data.reason
    db.commit()
    db.refresh(plan)
    return plan


def get_supplier_quote(db: Session, quote_id: int) -> models.SupplierQuote | None:
    return db.get(models.SupplierQuote, quote_id)


def list_supplier_quotes(db: Session, plan_id: int) -> list[models.SupplierQuote]:
    """Quotes in ENTRY ORDER — there is deliberately no ranking anywhere.

    Comparison happens on transparent totals in the UI; Lumos takes no commission
    and never orders quotes by anything but when they arrived.
    """
    return list(
        db.scalars(
            select(models.SupplierQuote)
            .where(models.SupplierQuote.input_plan_id == plan_id)
            .order_by(models.SupplierQuote.id)
        )
    )


def create_supplier_quote(
    db: Session, plan: models.InputPlan, data: schemas.SupplierQuoteCreate
) -> models.SupplierQuote:
    if plan.status not in procurement_status.PLAN_QUOTABLE_STATUSES:
        raise ProcurementStateError(
            f"quotes can only be entered on a submitted plan (status is '{plan.status}')"
        )
    if decision_status.is_demo_record(data) != decision_status.is_demo_record(plan):
        raise ProcurementStateError(
            "simulated and real records can never mix within one input plan"
        )
    plan_item_ids = {item.id for item in plan.items}
    for line in data.items:
        if line.input_plan_item_id not in plan_item_ids:
            raise ProcurementValidationError(
                f"quote line references item {line.input_plan_item_id}, which is "
                "not on this plan"
            )
    quote = models.SupplierQuote(
        input_plan_id=plan.id, **data.model_dump(exclude={"items"})
    )
    db.add(quote)
    db.flush()
    for line in data.items:
        db.add(models.SupplierQuoteItem(supplier_quote_id=quote.id, **line.model_dump()))
    if plan.status == procurement_status.PLAN_SUBMITTED:
        plan.status = procurement_status.PLAN_QUOTED
    db.commit()
    db.refresh(quote)
    return quote


def withdraw_supplier_quote(
    db: Session, quote: models.SupplierQuote
) -> models.SupplierQuote:
    """The ONLY correction path — quotes are never edited, so what the grower saw
    is preserved without a parallel audit system."""
    if quote.status != procurement_status.QUOTE_SUBMITTED:
        raise ProcurementStateError(
            f"only a submitted quote can be withdrawn (status is '{quote.status}')"
        )
    if quote.input_plan.status == procurement_status.PLAN_ORDERED:
        raise ProcurementStateError("quotes cannot be withdrawn after the order exists")
    quote.status = procurement_status.QUOTE_WITHDRAWN
    db.commit()
    db.refresh(quote)
    return quote


def select_quote(
    db: Session, plan: models.InputPlan, data: schemas.SelectQuoteRequest
) -> models.InputPlan:
    if not procurement_status.plan_transition_allowed(
        plan.status, procurement_status.PLAN_QUOTE_SELECTED
    ):
        raise ProcurementStateError(
            f"a quote can only be selected on a quoted plan (status is "
            f"'{plan.status}')"
        )
    quote = get_supplier_quote(db, data.supplier_quote_id)
    if quote is None or quote.input_plan_id != plan.id:
        raise ProcurementValidationError(
            f"quote {data.supplier_quote_id} is not on this plan"
        )
    if not procurement_status.quote_selectable(quote, clock.current_date()):
        raise ProcurementStateError(
            "this quote can no longer be selected (it is "
            f"{procurement_status.quote_state(quote, plan, clock.current_date())})"
        )
    quote.status = procurement_status.QUOTE_SELECTED
    plan.selected_quote_id = quote.id
    plan.selected_by = data.selected_by
    plan.status = procurement_status.PLAN_QUOTE_SELECTED
    db.commit()
    db.refresh(plan)
    return plan


def get_financing_offer(db: Session, offer_id: int) -> models.FinancingOffer | None:
    return db.get(models.FinancingOffer, offer_id)


def create_financing_offer(
    db: Session, quote: models.SupplierQuote, data: schemas.FinancingOfferCreate
) -> models.FinancingOffer:
    plan = quote.input_plan
    if not plan.financing_requested:
        raise ProcurementStateError(
            "the grower has not requested financing on this plan — indicative "
            "offers can only be entered against a request"
        )
    if plan.status in (
        procurement_status.PLAN_ORDERED, procurement_status.PLAN_CANCELLED
    ):
        raise ProcurementStateError(
            f"offers cannot be entered once the plan is {plan.status}"
        )
    if quote.status == procurement_status.QUOTE_WITHDRAWN:
        raise ProcurementStateError("offers cannot be entered on a withdrawn quote")
    if decision_status.is_demo_record(data) != decision_status.is_demo_record(plan):
        raise ProcurementStateError(
            "simulated and real records can never mix within one input plan"
        )
    offer = models.FinancingOffer(supplier_quote_id=quote.id, **data.model_dump())
    db.add(offer)
    db.commit()
    db.refresh(offer)
    return offer


def decide_financing_offer(
    db: Session, offer: models.FinancingOffer, data: schemas.FinancingOfferDecision
) -> models.FinancingOffer:
    """The grower's one-shot accept/decline of INDICATIVE terms — never a loan."""
    today = clock.current_date()
    if not procurement_status.offer_decidable(offer, today):
        raise ProcurementStateError(
            "this offer can no longer be decided (it is "
            f"{procurement_status.offer_state(offer, today)})"
        )
    plan = offer.supplier_quote.input_plan
    if plan.status in (
        procurement_status.PLAN_ORDERED, procurement_status.PLAN_CANCELLED
    ):
        raise ProcurementStateError(
            f"offers cannot be decided once the plan is {plan.status}"
        )
    if data.action == "accepted":
        for sibling_quote in plan.quotes:
            for sibling in sibling_quote.financing_offers:
                if sibling.status == procurement_status.OFFER_ACCEPTED:
                    raise ProcurementStateError(
                        "another financing offer on this plan is already accepted"
                    )
    offer.status = data.action
    offer.decided_by = data.actor
    offer.decided_at = clock.current_datetime()
    offer.decision_notes = data.notes
    db.commit()
    db.refresh(offer)
    return offer


def _add_order_event(
    db: Session,
    order: models.PurchaseOrder,
    event_type: str,
    *,
    occurred_on: date,
    actor: str | None = None,
    notes: str | None = None,
    payload: dict | None = None,
) -> models.OrderEvent:
    """The single writer for order events (add, not commit) — append-only."""
    event = models.OrderEvent(
        purchase_order_id=order.id,
        event_type=event_type,
        occurred_on=occurred_on,
        actor=actor,
        notes=notes,
        payload=payload,
        data_source=order.data_source,
        data_confidence=order.data_confidence,
    )
    db.add(event)
    return event


def create_purchase_order(
    db: Session, plan: models.InputPlan, data: schemas.PurchaseOrderCreate
) -> models.PurchaseOrder:
    if not procurement_status.plan_transition_allowed(
        plan.status, procurement_status.PLAN_ORDERED
    ):
        raise ProcurementStateError(
            f"an order requires a selected quote (plan status is '{plan.status}')"
        )
    quote = get_supplier_quote(db, plan.selected_quote_id)
    accepted_offer = next(
        (
            o for o in quote.financing_offers
            if o.status == procurement_status.OFFER_ACCEPTED
        ),
        None,
    )
    order = models.PurchaseOrder(
        farm_id=plan.farm_id,
        input_plan_id=plan.id,
        selected_quote_id=quote.id,
        accepted_financing_offer_id=accepted_offer.id if accepted_offer else None,
        placed_by=data.placed_by,
        notes=data.notes,
        data_source=plan.data_source,
        data_confidence=plan.data_confidence,
    )
    db.add(order)
    db.flush()
    today = clock.current_date()
    _add_order_event(
        db, order, procurement_status.EVENT_CREATED,
        occurred_on=today, actor=data.placed_by,
        payload={"input_plan_id": plan.id},
    )
    _add_order_event(
        db, order, procurement_status.EVENT_QUOTE_SELECTED,
        occurred_on=today, actor=plan.selected_by,
        payload={
            "supplier_quote_id": quote.id,
            "supplier_name": quote.supplier_name,
            "total_cost": quote.total_cost,
        },
    )
    if accepted_offer is not None:
        _add_order_event(
            db, order, procurement_status.EVENT_FINANCING_SELECTED,
            occurred_on=today, actor=accepted_offer.decided_by,
            payload={
                "financing_offer_id": accepted_offer.id,
                "provider_name": accepted_offer.provider_name,
                "financed_amount": accepted_offer.financed_amount,
            },
        )
    plan.status = procurement_status.PLAN_ORDERED
    db.commit()
    db.refresh(order)
    return order


def get_purchase_order(db: Session, order_id: int) -> models.PurchaseOrder | None:
    return db.get(models.PurchaseOrder, order_id)


def list_purchase_orders(db: Session, farm_id: int) -> list[models.PurchaseOrder]:
    return list(
        db.scalars(
            select(models.PurchaseOrder)
            .where(models.PurchaseOrder.farm_id == farm_id)
            .order_by(
                models.PurchaseOrder.created_at.desc(), models.PurchaseOrder.id.desc()
            )
        )
    )


def list_order_events(db: Session, order_id: int) -> list[models.OrderEvent]:
    return list(
        db.scalars(
            select(models.OrderEvent)
            .where(models.OrderEvent.purchase_order_id == order_id)
            .order_by(models.OrderEvent.created_at, models.OrderEvent.id)
        )
    )


def add_order_event(
    db: Session, order: models.PurchaseOrder, data: schemas.OrderEventCreate
) -> models.OrderEvent:
    """Concierge-posted lifecycle event; the transition map is the idempotency
    guard (a duplicate 'delivered' is an invalid transition, not a no-op)."""
    if not procurement_status.order_event_allowed(order, data.event_type):
        raise ProcurementStateError(
            f"event '{data.event_type}' is not valid while the order is "
            f"'{order.status}'"
        )
    if data.occurred_on < order.created_at.date():
        raise ProcurementStateError("an order event cannot predate the order")
    event = _add_order_event(
        db, order, data.event_type,
        occurred_on=data.occurred_on, actor=data.actor, notes=data.notes,
    )
    new_status = procurement_status.ORDER_EVENT_NEW_STATUS.get(data.event_type)
    if new_status is not None:
        order.status = new_status
    db.commit()
    db.refresh(event)
    return event


def record_input_applied(
    db: Session, order: models.PurchaseOrder, data: schemas.InputAppliedRequest
) -> models.OrderEvent:
    """The explicit delivery→application link. Delivery alone NEVER marks an
    input as applied — this endpoint requires the actual application record."""
    if not procurement_status.order_event_allowed(
        order, procurement_status.EVENT_INPUT_APPLIED
    ):
        raise ProcurementStateError(
            "an input can only be recorded as applied once the order is "
            f"delivered (status is '{order.status}')"
        )
    if order.spray_event_id is not None or order.applied_planned_spray_id is not None:
        raise ProcurementStateError(
            "an application is already linked to this order"
        )
    payload: dict = {}
    if data.spray_event_id is not None:
        spray = db.get(models.SprayEvent, data.spray_event_id)
        if spray is None or spray.farm_id != order.farm_id:
            raise ProcurementValidationError(
                f"spray event {data.spray_event_id} not found on this farm"
            )
        order.spray_event_id = spray.id
        payload["spray_event_id"] = spray.id
    else:
        planned = get_planned_spray(db, data.planned_spray_id)
        if planned is None or planned.farm_id != order.farm_id:
            raise ProcurementValidationError(
                f"planned spray {data.planned_spray_id} not found on this farm"
            )
        if planned.outcome not in APPLIED_OUTCOMES:
            raise ProcurementValidationError(
                f"decision {planned.id} has no applied outcome recorded "
                f"(outcome is '{planned.outcome}')"
            )
        order.applied_planned_spray_id = planned.id
        payload["planned_spray_id"] = planned.id
        if planned.spray_event_id is not None:
            order.spray_event_id = planned.spray_event_id
            payload["spray_event_id"] = planned.spray_event_id
    occurred_on = data.occurred_on or clock.current_date()
    if occurred_on < order.created_at.date():
        raise ProcurementStateError("an order event cannot predate the order")
    event = _add_order_event(
        db, order, procurement_status.EVENT_INPUT_APPLIED,
        occurred_on=occurred_on, actor=data.actor, notes=data.notes,
        payload=payload,
    )
    db.commit()
    db.refresh(event)
    return event
