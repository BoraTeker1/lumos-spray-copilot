"""Database access layer. Routes call these helpers; they never touch the session directly.

Keeping DB access here makes the route handlers thin and makes it straightforward to add
an auth/tenant filter later in one place.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock, decision_status, models, schemas
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


def create_planned_spray(
    db: Session, farm: models.Farm, data: schemas.PlannedSprayCreate
) -> models.PlannedSpray:
    """Run the pre-spray decision check against current records and persist the snapshot."""
    sprays = list_spray_events(db, farm.id)
    observations = list_scout_observations(db, farm.id)
    decision = evaluate_planned_spray(
        farm, data, sprays, observations,
        pca_policies=list_pca_policies(db, farm.id),
        today=clock.current_date(),
    )

    planned = models.PlannedSpray(
        farm_id=farm.id,
        **data.model_dump(),
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
    _log_event(
        db, "check_completed", farm_id=farm.id, planned_spray_id=planned.id,
        entry_source=planned.data_source,
        meta={"outcome": decision.outcome, "authority": decision.authority_level},
    )
    db.commit()
    db.refresh(planned)
    return planned


def review_planned_spray(
    db: Session, planned: models.PlannedSpray, data: schemas.PlannedSprayReviewUpdate
) -> models.PlannedSpray:
    """Record the PCA/agronomist's review of a pre-spray decision."""
    planned.review_status = data.action
    planned.review_comment = data.review_comment
    planned.reviewed_by = data.reviewed_by
    planned.reviewed_at = clock.current_datetime()
    planned.pca_next_action = data.pca_next_action if data.action == "edited" else None
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
