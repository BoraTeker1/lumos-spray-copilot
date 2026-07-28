"""Database access layer. Routes call these helpers; they never touch the session directly.

Keeping DB access here makes the route handlers thin and makes it straightforward to add
an auth/tenant filter later in one place.
"""
from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import (
    clock, crop_aliases, csv_import, decision_status, disease_risk, label_data,
    label_table, models, pca_authority, procurement_status, risk_snapshot, schemas,
    target_aliases,
)
from app.decision_engine import LabelContext, evaluate_planned_spray
from app.recommendation_engine import generate_recommendation

# Maps decision severity onto the legacy low/moderate/elevated risk vocabulary that the
# weekly-report / audit surfaces still speak.
_SEVERITY_TO_RISK = {"none": "low", "caution": "moderate", "critical": "elevated"}

# Real-world outcomes that mean a spray was actually applied (they create the SprayEvent).
APPLIED_OUTCOMES = decision_status.APPLIED_OUTCOMES


class ReviewRequiredError(Exception):
    """Raised when an applied outcome is recorded before a required PCA review."""


class DemoMixingError(Exception):
    """Raised when a real record would be created on a farm whose records are
    simulated demo data (or a demo record on a farm with real records). One farm's
    story is either all simulated or all real — mixed farms would silently blend
    demo rows into analytics/compliance/reduction surfaces that read every row."""


class OutcomeChronologyError(Exception):
    """Raised when a recorded outcome would create an impossible timeline
    (outcome before its check, or an application before its planned date)."""


class FollowUpError(Exception):
    """Raised when a follow-up event is invalid (no recorded outcome yet, or an
    impossible timeline)."""


class PcaAuthorityError(Exception):
    """Raised when PCA authority is claimed without an authorized credential.

    Carries the machine-readable denial reason so the route can report *why* — an
    authorized PCA being refused needs to know whether their token is unknown,
    expired, revoked, or simply not granted this farm."""

    def __init__(self, reason: str, message: str | None = None):
        self.reason = reason
        super().__init__(message or pca_authority.denial_message(reason))


class CrossFarmReferenceError(Exception):
    """Raised when a record would reference a row belonging to a different farm.

    With no tenant model, `farm_id` IS the isolation boundary — so every FK that
    crosses between farm-scoped rows must be checked explicitly. Silently accepting
    a foreign block would attach one farm's outcomes to another farm's decisions."""


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


def reference_farm_ids(db: Session) -> set[int]:
    """Ids of operator reference farms — real provenance, but nobody's grower.

    Returned as a plain set so the pure evidence module can filter on it without
    importing SQLAlchemy.
    """
    return set(
        db.scalars(
            select(models.Farm.id).where(models.Farm.is_reference.is_(True))
        )
    )


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


# ------------------------------------------------------------------ PCA credentials
def create_pca_credential(
    db: Session, data: schemas.PcaCredentialCreate
) -> tuple[models.PcaCredential, str]:
    """Issue a credential; returns (row, plaintext token). The token is shown once."""
    token = pca_authority.generate_token()
    credential = models.PcaCredential(
        **data.model_dump(),
        token_hash=pca_authority.hash_token(token),
        token_prefix=pca_authority.token_prefix(token),
    )
    db.add(credential)
    db.commit()
    db.refresh(credential)
    return credential, token


def list_pca_credentials(db: Session) -> list[models.PcaCredential]:
    return list(db.scalars(select(models.PcaCredential).order_by(models.PcaCredential.id)))


def get_pca_credential(db: Session, credential_id: int) -> models.PcaCredential | None:
    return db.get(models.PcaCredential, credential_id)


def revoke_pca_credential(
    db: Session, credential: models.PcaCredential
) -> models.PcaCredential:
    """Revocation is a timestamp, never a delete — the dispositions it signed remain
    attributable after the credential stops being usable."""
    if credential.revoked_at is None:
        credential.revoked_at = clock.current_datetime()
        db.commit()
        db.refresh(credential)
    return credential


def resolve_pca_token(db: Session, token: str | None) -> models.PcaCredential | None:
    """Look a credential up by token digest. The plaintext is never stored or logged."""
    if not token:
        return None
    return db.scalar(
        select(models.PcaCredential).where(
            models.PcaCredential.token_hash == pca_authority.hash_token(token)
        )
    )


def authorize_pca_for_farm(
    db: Session, credential: models.PcaCredential, data: schemas.PcaFarmAuthorizationCreate
) -> models.PcaFarmAuthorization:
    auth = models.PcaFarmAuthorization(
        pca_credential_id=credential.id, **data.model_dump()
    )
    db.add(auth)
    db.commit()
    db.refresh(auth)
    return auth


def revoke_farm_authorization(
    db: Session, auth: models.PcaFarmAuthorization
) -> models.PcaFarmAuthorization:
    if auth.revoked_at is None:
        auth.revoked_at = clock.current_datetime()
        db.commit()
        db.refresh(auth)
    return auth


def list_farm_authorizations(db: Session, farm_id: int) -> list[models.PcaFarmAuthorization]:
    return list(
        db.scalars(
            select(models.PcaFarmAuthorization)
            .where(models.PcaFarmAuthorization.farm_id == farm_id)
            .order_by(models.PcaFarmAuthorization.id)
        )
    )


def require_pca_for_farm(
    db: Session, token: str | None, farm_id: int
) -> models.PcaCredential:
    """Resolve a token to a credential authorized for `farm_id`, or raise.

    The single authorization entry point — every route that records a professional
    decision goes through here so a new route cannot invent a weaker check.
    """
    if not token:
        raise PcaAuthorityError(pca_authority.DENY_NO_TOKEN)
    credential = resolve_pca_token(db, token)
    reason = pca_authority.authorize(
        credential,
        credential.authorizations if credential is not None else [],
        farm_id,
        today=clock.current_date(),
    )
    if reason is not None:
        raise PcaAuthorityError(reason)
    return credential


def farm_requires_pca_credential(db: Session, farm_id: int) -> bool:
    """True once this farm has any live PCA authorization on record.

    The escalation rule for claimed PCA authority: on a farm that has been set up
    with credentialed PCAs, saying "a PCA entered these values" or recording an
    approving review must be backed by a token. Farms with no credentials keep the
    existing free-text behaviour, so the demo and every pre-pilot workflow are
    untouched — enrolling a farm is what turns enforcement on.
    """
    today = clock.current_date()
    return any(
        pca_authority.authorization_is_active(auth, today)
        for auth in list_farm_authorizations(db, farm_id)
    )


def ensure_pca_authority(
    db: Session, farm_id: int, credential: models.PcaCredential | None, *, claim: str
) -> None:
    """Enforce that a PCA-authority claim on an enrolled farm is credential-backed."""
    if not farm_requires_pca_credential(db, farm_id):
        return
    if credential is None:
        raise PcaAuthorityError(
            pca_authority.DENY_NO_TOKEN,
            f"{claim} requires an authorized PCA credential on this farm — present "
            f"it in the {pca_authority.TOKEN_HEADER} header",
        )
    reason = pca_authority.authorize(
        credential, credential.authorizations, farm_id, today=clock.current_date()
    )
    if reason is not None:
        raise PcaAuthorityError(reason)


# ---------------------------------------------------------------------------- Blocks
def list_blocks(db: Session, farm_id: int) -> list[models.Block]:
    return list(
        db.scalars(
            select(models.Block)
            .where(models.Block.farm_id == farm_id)
            .order_by(models.Block.name)
        )
    )


def get_block(db: Session, block_id: int) -> models.Block | None:
    return db.get(models.Block, block_id)


def create_block(db: Session, farm_id: int, data: schemas.BlockCreate) -> models.Block:
    ensure_demo_real_separation(db, farm_id, data)
    block = models.Block(farm_id=farm_id, **data.model_dump())
    db.add(block)
    db.commit()
    db.refresh(block)
    return block


def ensure_block_on_farm(db: Session, farm_id: int, block_id: int | None) -> None:
    """Reject a block reference that does not belong to `farm_id`.

    `farm_id` is the only isolation boundary this system has (there is no tenant
    model), so a cross-farm block_id is exactly a tenancy violation: it would let one
    farm's records be counted into another farm's pilot arm and outcomes.
    """
    if block_id is None:
        return
    block = db.get(models.Block, block_id)
    if block is None:
        raise CrossFarmReferenceError(f"block {block_id} does not exist")
    if block.farm_id != farm_id:
        raise CrossFarmReferenceError(
            f"block {block_id} belongs to farm {block.farm_id}, not farm {farm_id} — "
            f"records can never reference another farm's block"
        )


# ---------------------------------------------------- Pilot observations (append-only)
def _ensure_supersede_target(db: Session, model, farm_id: int, supersedes_id: int | None):
    """A correction may only supersede a row on the same farm."""
    if supersedes_id is None:
        return
    prior = db.get(model, supersedes_id)
    if prior is None:
        raise CrossFarmReferenceError(f"record {supersedes_id} to supersede does not exist")
    if prior.farm_id != farm_id:
        raise CrossFarmReferenceError(
            f"record {supersedes_id} belongs to another farm and cannot be superseded here"
        )


def create_weather_observation(
    db: Session, farm_id: int, data: schemas.WeatherObservationCreate
) -> models.WeatherObservation:
    """Append one weather reading. Corrections supersede; nothing is ever edited."""
    ensure_demo_real_separation(db, farm_id, data)
    ensure_block_on_farm(db, farm_id, data.block_id)
    _ensure_supersede_target(db, models.WeatherObservation, farm_id, data.supersedes_id)
    row = models.WeatherObservation(
        farm_id=farm_id, recorded_at=clock.current_datetime(), **data.model_dump()
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_weather_observations(
    db: Session, farm_id: int, block_id: int | None = None
) -> list[models.WeatherObservation]:
    stmt = select(models.WeatherObservation).where(
        models.WeatherObservation.farm_id == farm_id
    )
    if block_id is not None:
        stmt = stmt.where(models.WeatherObservation.block_id == block_id)
    return list(db.scalars(stmt.order_by(models.WeatherObservation.observed_at)))


def incidence_pct(units_affected: int, units_inspected: int) -> float | None:
    """The ONE place incidence is computed — always from a stated denominator."""
    if not units_inspected:
        return None
    return round(100.0 * units_affected / units_inspected, 2)


def create_scouting_sample(
    db: Session, farm_id: int, data: schemas.ScoutingSampleCreate
) -> models.ScoutingSample:
    ensure_demo_real_separation(db, farm_id, data)
    ensure_block_on_farm(db, farm_id, data.block_id)
    _ensure_supersede_target(db, models.ScoutingSample, farm_id, data.supersedes_id)
    row = models.ScoutingSample(
        farm_id=farm_id,
        recorded_at=clock.current_datetime(),
        incidence_pct=incidence_pct(data.units_affected, data.units_inspected),
        **data.model_dump(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_scouting_samples(
    db: Session, farm_id: int, block_id: int | None = None
) -> list[models.ScoutingSample]:
    stmt = select(models.ScoutingSample).where(models.ScoutingSample.farm_id == farm_id)
    if block_id is not None:
        stmt = stmt.where(models.ScoutingSample.block_id == block_id)
    return list(db.scalars(stmt.order_by(models.ScoutingSample.observed_at)))


def superseded_ids(rows) -> set[int]:
    """Ids that some later row replaces — the corrected-away set.

    Mirrors `active_input_values`: the current picture is every row that nothing
    supersedes, and the replaced rows stay on file rather than being deleted.
    """
    return {
        r.supersedes_id for r in rows if getattr(r, "supersedes_id", None) is not None
    }


def active_rows(rows) -> list:
    replaced = superseded_ids(rows)
    return [r for r in rows if r.id not in replaced]


# ------------------------------------------------------- Risk input snapshots
# The pilot's disease target. Single-target by design: the Botrytis deferral
# hypothesis is what the pilot exists to falsify, and a generalized multi-disease
# surface would be speculative platform work.
PILOT_TARGET = "botrytis_fruit_rot"


def create_risk_snapshot(
    db: Session,
    planned: models.PlannedSpray,
    *,
    as_of: datetime | None = None,
    horizon_hours: int = 72,
) -> models.RiskInputSnapshot:
    """Freeze what is knowable right now for this decision's block.

    Note what is NOT passed to `risk_snapshot.build_snapshot`: this function has the
    planned spray, its review, its outcome, and the whole session in scope, and hands
    over only the block and the observations. That narrowing is the leakage boundary
    — see app/risk_snapshot.py.
    """
    if planned.block_id is None:
        raise CrossFarmReferenceError(
            "this decision is not linked to a block — a risk assessment is always "
            "about a specific block, and the block is never guessed from `field_block`"
        )
    block = get_block(db, planned.block_id)
    as_of = as_of or clock.current_datetime()

    draft = risk_snapshot.build_snapshot(
        as_of=as_of,
        horizon_hours=horizon_hours,
        target=PILOT_TARGET,
        block=block,
        weather_observations=list_weather_observations(db, planned.farm_id),
        scouting_samples=list_scouting_samples(db, planned.farm_id, planned.block_id),
    )

    row = models.RiskInputSnapshot(
        farm_id=planned.farm_id,
        block_id=planned.block_id,
        planned_spray_id=planned.id,
        as_of=as_of,
        horizon_hours=horizon_hours,
        target=PILOT_TARGET,
        snapshot_version=risk_snapshot.SNAPSHOT_VERSION,
        payload=draft.as_payload(),
        input_digest=draft.input_digest,
        excluded=draft.excluded,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_risk_snapshots(db: Session, planned_spray_id: int) -> list[models.RiskInputSnapshot]:
    return list(
        db.scalars(
            select(models.RiskInputSnapshot)
            .where(models.RiskInputSnapshot.planned_spray_id == planned_spray_id)
            .order_by(models.RiskInputSnapshot.as_of)
        )
    )


def latest_risk_snapshot(
    db: Session, planned_spray_id: int
) -> models.RiskInputSnapshot | None:
    snapshots = list_risk_snapshots(db, planned_spray_id)
    return snapshots[-1] if snapshots else None


class SnapshotRequiredError(Exception):
    """Raised when an assessment is requested for a decision with no snapshot."""


def active_pilot_protocol(db: Session, farm_id: int) -> models.PilotProtocol | None:
    """The protocol version currently in force for this farm, if any."""
    today = clock.current_date()
    protocols = list(
        db.scalars(
            select(models.PilotProtocol)
            .where(models.PilotProtocol.farm_id == farm_id)
            .order_by(models.PilotProtocol.effective_from.desc())
        )
    )
    for protocol in protocols:
        if protocol.effective_from > today:
            continue
        if protocol.effective_to is not None and protocol.effective_to < today:
            continue
        return protocol
    return None


def farm_is_unblinded(db: Session, farm_id: int) -> bool:
    """Has this farm's pilot protocol reached its recorded unblinding moment?

    Reads `PilotProtocol.unblinded_at` — a protocol-versioned event with a recorded
    date, deliberately NOT a config toggle or an environment variable, because when
    the PCA started seeing risk output is itself part of the pilot's evidence.

    No protocol means no unblinding: a farm cannot drift out of shadow mode by having
    its protocol row deleted or never created.
    """
    protocol = active_pilot_protocol(db, farm_id)
    if protocol is None or protocol.unblinded_at is None:
        return False
    return protocol.unblinded_at <= clock.current_datetime()


def create_disease_risk_assessment(
    db: Session,
    planned: models.PlannedSpray,
    *,
    model_version: str = disease_risk.DEFAULT_MODEL_VERSION,
    snapshot: models.RiskInputSnapshot | None = None,
) -> models.DiseaseRiskAssessment:
    """Run a versioned rule over this decision's latest snapshot and store the result.

    Append-only: there is no update path. Re-running produces a NEW row, so a changed
    model version or a later snapshot is visible as a sequence rather than overwriting
    what was shown at the time.
    """
    snapshot = snapshot or latest_risk_snapshot(db, planned.id)
    if snapshot is None:
        raise SnapshotRequiredError(
            "no risk snapshot exists for this decision — an assessment must be "
            "anchored to the inputs that were knowable when it was made"
        )

    result = disease_risk.assess(
        snapshot.payload,
        model_version=model_version,
        input_digest=snapshot.input_digest,
    )

    row = models.DiseaseRiskAssessment(
        snapshot_id=snapshot.id,
        planned_spray_id=planned.id,
        farm_id=planned.farm_id,
        block_id=snapshot.block_id,
        model_family=result.model_family,
        model_version=result.model_version,
        input_digest=result.input_digest,
        risk_band=result.risk_band,
        probability=result.probability_or_index,
        evidence_grade=result.evidence_grade,
        horizon_hours=result.horizon_hours,
        abstained=result.abstained,
        abstain_reason=result.abstain_reason,
        missing_inputs=list(result.missing_or_unreliable_inputs),
        calibration_status=result.calibration_status,
        local_validation_status=result.local_validation_status,
        citation=result.citation,
        calculation=result.calculation or None,
        # Shadow unless the protocol says otherwise. Defaulting the other way would
        # mean a wiring mistake silently unblinds the pilot.
        is_shadow=not farm_is_unblinded(db, planned.farm_id),
    )
    db.add(row)
    _add_audit_event(
        db, planned, "risk_assessment_computed",
        actor="lumos-rule-engine",
        after={
            "model_version": result.model_version,
            "risk_band": result.risk_band,
            "abstained": result.abstained,
            "abstain_reason": result.abstain_reason,
            "input_digest": result.input_digest,
            "is_shadow": row.is_shadow,
        },
    )
    db.commit()
    db.refresh(row)
    return row


def list_disease_risk_assessments(
    db: Session, planned_spray_id: int
) -> list[models.DiseaseRiskAssessment]:
    return list(
        db.scalars(
            select(models.DiseaseRiskAssessment)
            .where(models.DiseaseRiskAssessment.planned_spray_id == planned_spray_id)
            .order_by(models.DiseaseRiskAssessment.computed_at)
        )
    )


def list_shadow_assessments(
    db: Session, farm_id: int | None = None
) -> list[models.DiseaseRiskAssessment]:
    """Operator-only view. The single place shadow rows are readable before unblinding."""
    stmt = select(models.DiseaseRiskAssessment)
    if farm_id is not None:
        stmt = stmt.where(models.DiseaseRiskAssessment.farm_id == farm_id)
    return list(db.scalars(stmt.order_by(models.DiseaseRiskAssessment.computed_at.desc())))


# ------------------------------------------------------------------ PcaDispositions
def create_pca_disposition(
    db: Session,
    planned: models.PlannedSpray,
    data: schemas.PcaDispositionCreate,
    credential: models.PcaCredential,
) -> models.PcaDisposition:
    """Record the PCA's professional judgement. Append-only, attributed, anchored.

    THE ORTHOGONALITY INVARIANT: this function writes exactly one new row and one
    audit event. It does NOT touch `decision_outcome`, `decision_severity`,
    `decision_authority`, `review_status`, `review_required` or `outcome` — not as a
    convenience, not as a side effect. A PCA choosing to defer is a different fact
    from the engine's verdict, from a completed review, and from the spray actually
    not happening; a pilot that cannot tell them apart measures nothing.

    In particular `defer` does not unlock applied outcomes and does not satisfy a
    required review — deferring and being cleared to spray are unrelated decisions.
    """
    snapshot = latest_risk_snapshot(db, planned.id)
    if snapshot is None:
        raise SnapshotRequiredError(
            "no risk snapshot exists for this decision — a disposition must be "
            "anchored to what was knowable when it was made"
        )

    # Recorded even while blinded: the PCA did not see it, but the join is what lets
    # the rule be scored against their independent judgement later.
    assessments = list_disease_risk_assessments(db, planned.id)
    assessment_id = assessments[-1].id if assessments else None

    row = models.PcaDisposition(
        planned_spray_id=planned.id,
        pca_credential_id=credential.id,
        disposition=data.disposition,
        rationale=data.rationale,
        assessment_id=assessment_id,
        snapshot_digest_at_decision=snapshot.input_digest,
        supersedes_id=data.supersedes_id,
    )
    db.add(row)
    _add_audit_event(
        db, planned, "pca_disposition_recorded",
        actor=pca_authority.attribution(credential).get("display_name"),
        rationale=data.rationale,
        after={
            "disposition": data.disposition,
            "pca_credential_id": credential.id,
            "snapshot_digest_at_decision": snapshot.input_digest,
            "assessment_id": assessment_id,
            "supersedes_id": data.supersedes_id,
        },
    )
    db.commit()
    db.refresh(row)
    return row


def list_pca_dispositions(
    db: Session, planned_spray_id: int
) -> list[models.PcaDisposition]:
    """The full chain, superseded rows included — corrections never hide what they replace."""
    return list(
        db.scalars(
            select(models.PcaDisposition)
            .where(models.PcaDisposition.planned_spray_id == planned_spray_id)
            .order_by(models.PcaDisposition.decided_at)
        )
    )


# ---------------------------------------------------------- Pilot protocol + arms
def create_pilot_protocol(
    db: Session, farm_id: int, data: schemas.PilotProtocolCreate
) -> models.PilotProtocol:
    protocol = models.PilotProtocol(farm_id=farm_id, **data.model_dump())
    db.add(protocol)
    db.commit()
    db.refresh(protocol)
    return protocol


def list_pilot_protocols(db: Session, farm_id: int) -> list[models.PilotProtocol]:
    return list(
        db.scalars(
            select(models.PilotProtocol)
            .where(models.PilotProtocol.farm_id == farm_id)
            .order_by(models.PilotProtocol.effective_from.desc())
        )
    )


def get_pilot_protocol(db: Session, protocol_id: int) -> models.PilotProtocol | None:
    return db.get(models.PilotProtocol, protocol_id)


def create_block_assignment(
    db: Session, protocol: models.PilotProtocol, data: schemas.BlockAssignmentCreate
) -> models.BlockAssignment:
    """Record an offline randomization/matching decision. Never edited, only superseded.

    The block must belong to the protocol's farm — a cross-farm assignment would
    silently pollute another grower's comparison.
    """
    ensure_block_on_farm(db, protocol.farm_id, data.block_id)
    assignment = models.BlockAssignment(
        pilot_protocol_id=protocol.id, **data.model_dump()
    )
    db.add(assignment)
    db.commit()
    db.refresh(assignment)
    return assignment


def list_block_assignments(
    db: Session, pilot_protocol_id: int
) -> list[models.BlockAssignment]:
    return list(
        db.scalars(
            select(models.BlockAssignment)
            .where(models.BlockAssignment.pilot_protocol_id == pilot_protocol_id)
            .order_by(models.BlockAssignment.assigned_on, models.BlockAssignment.id)
        )
    )


# ------------------------------------------------------------------ Block outcomes
def create_block_outcome(
    db: Session, farm_id: int, data: schemas.BlockOutcomeObservationCreate
) -> models.BlockOutcomeObservation:
    """Append one measured block outcome. There is no update and no delete."""
    ensure_block_on_farm(db, farm_id, data.block_id)
    if data.pilot_protocol_id is not None:
        protocol = get_pilot_protocol(db, data.pilot_protocol_id)
        if protocol is None or protocol.farm_id != farm_id:
            raise CrossFarmReferenceError(
                "that pilot protocol belongs to a different farm"
            )
    row = models.BlockOutcomeObservation(**data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_block_outcomes(
    db: Session, farm_id: int, block_id: int | None = None
) -> list[models.BlockOutcomeObservation]:
    stmt = (
        select(models.BlockOutcomeObservation)
        .join(models.Block, models.Block.id == models.BlockOutcomeObservation.block_id)
        .where(models.Block.farm_id == farm_id)
    )
    if block_id is not None:
        stmt = stmt.where(models.BlockOutcomeObservation.block_id == block_id)
    return list(
        db.scalars(stmt.order_by(models.BlockOutcomeObservation.observed_on.desc()))
    )


# ----------------------------------------------------------------------- SprayEvents
def list_spray_events(db: Session, farm_id: int) -> list[models.SprayEvent]:
    return list(
        db.scalars(
            select(models.SprayEvent)
            .where(models.SprayEvent.farm_id == farm_id)
            .order_by(models.SprayEvent.application_date.desc())
        )
    )


def resolve_treated_area_unit(db: Session, farm_id: int) -> str | None:
    """The unit a farm's `treated_acres` numbers are actually in.

    Reads `Farm.area_unit` — the farm already declares whether it measures in acres or
    m2, so the unit is recorded rather than implied by the acre-named column. Returns
    None when the farm never declared one; that stays honestly unspecified and is
    never assumed to be acres (see pilot_evidence._sum_treated_area).
    """
    farm = db.get(models.Farm, farm_id)
    return getattr(farm, "area_unit", None) if farm else None


def create_spray_event(
    db: Session, farm_id: int, data: schemas.SprayEventCreate
) -> models.SprayEvent:
    ensure_demo_real_separation(db, farm_id, data)
    ensure_block_on_farm(db, farm_id, data.block_id)
    event = models.SprayEvent(farm_id=farm_id, **data.model_dump())
    if event.treated_acres is not None:
        event.treated_area_unit = resolve_treated_area_unit(db, farm_id)
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
    ensure_demo_real_separation(db, farm_id, data)
    ensure_block_on_farm(db, farm_id, data.block_id)
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


# The one critical input that is not a planned-spray attribute: the harvest date is
# the farm's, so it is passed in rather than read off the object.
_HARVEST_DATE_FIELD = "expected_harvest_date"


def _planned_input_rows(planned_like, harvest_date) -> list[tuple[str, object, str | None]]:
    """(field_name, raw value, unit) for every critical input that has a value.

    Driven by CRITICAL_INPUT_FIELDS so the declared set of provenance-tracked fields
    and the rows actually written cannot drift apart — a field declared critical but
    never written would silently have no provenance at all.
    """
    units = {
        "rate_amount": getattr(planned_like, "rate_unit", None),
        "pre_harvest_interval_days": "days",
        "re_entry_interval_hours": "hours",
    }
    rows = []
    for name in CRITICAL_INPUT_FIELDS:
        value = (
            harvest_date
            if name == _HARVEST_DATE_FIELD
            else getattr(planned_like, name, None)
        )
        if value is None or str(value).strip() == "":
            continue
        rows.append((name, value, units.get(name)))
    return rows


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
    pca_credential: models.PcaCredential | None = None,
    commit: bool = True,
) -> models.PlannedSpray:
    """Run the pre-spray decision check against current records and persist the snapshot.

    Also writes the field-level provenance rows (DecisionInputValue) for every critical
    input and the immutable "created" audit event. `input_source_type` overrides the
    provenance derived from `values_source` (the CSV import passes
    "imported_unverified"); imported values can never back a definitive result.
    """
    ensure_demo_real_separation(db, farm.id, data)
    ensure_block_on_farm(db, farm.id, data.block_id)
    # `values_source="pca_entered"` maps to pca_verified provenance, which can lift the
    # decision to `pca_authorized` — i.e. a client string could grant itself PCA
    # authority. On an enrolled farm that claim must be credential-backed.
    if data.values_source == "pca_entered":
        ensure_pca_authority(
            db, farm.id, pca_credential, claim="claiming PCA-entered values"
        )
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
        label_context=build_label_context(db, data, farm),
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
    if planned.treated_acres is not None:
        planned.treated_area_unit = getattr(farm, "area_unit", None)
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
    # Where a PCA-verified label exists, its values supersede what was entered BEFORE
    # this decision is stored as something anyone might act on — otherwise the PHI
    # arithmetic would run on the entered value while the label sat beside it
    # disagreeing. A no-op unless a verified label record covers this product and crop.
    db.flush()
    apply_label_values(db, planned, commit=False)
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
        label_context=build_label_context(db, planned, farm),
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
    db: Session,
    planned: models.PlannedSpray,
    data: schemas.PlannedSprayReviewUpdate,
    *,
    pca_credential: models.PcaCredential | None = None,
) -> models.PlannedSpray:
    """Record the PCA/agronomist's review of a pre-spray decision.

    History is never overwritten: the prior state goes into an immutable audit event,
    and every structured `proposed_*` edit appends a superseding pca_verified
    DecisionInputValue (the old value row stays). When values changed, the decision is
    re-evaluated against the updated values; the pre-review snapshot survives in the
    audit event's `before`.
    """
    # An approval or edit unlocks applying the spray and marks values pca_verified —
    # on an enrolled farm that must come from an authorized credential, not a name in
    # a text field. A rejection is deliberately NOT gated: refusing a spray is always
    # allowed to be easier than authorizing one.
    if data.action in decision_status.APPLIED_OUTCOME_UNLOCK_STATUSES:
        ensure_pca_authority(
            db, planned.farm_id, pca_credential, claim=f"recording an {data.action} review"
        )

    before = _decision_snapshot(planned)
    before["decision_payload"] = planned.decision_payload

    planned.review_status = data.action
    planned.review_comment = data.review_comment
    planned.reviewed_by = data.reviewed_by
    if pca_credential is not None:
        planned.reviewed_by_credential_id = pca_credential.id
        # The credential's own name wins over whatever the client typed: attribution
        # must match the thing that was actually verified.
        planned.reviewed_by = pca_credential.display_name
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
            # MoA belongs to the planned chemistry — never carried onto a changed product.
            moa_group=None if changed else planned.moa_group,
            target_pest_or_disease=planned.target_pest_or_disease,
            field_block=planned.field_block,
            application_date=data.application_date or planned.intended_date,
            cost=None if changed else planned.estimated_cost,
            # The planned rate was for the planned product; a changed product's rate
            # must be re-entered (same rule as PHI/REI below). Treated area carries.
            rate_amount=None if changed else planned.rate_amount,
            rate_unit=None if changed else planned.rate_unit,
            treated_acres=planned.treated_acres,
            treated_area_unit=planned.treated_area_unit,
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
    elif record_type == csv_import.RECORD_TYPE_SPRAY_EVENTS:
        for s in list_spray_events(db, farm_id):
            label = f"spray event #{s.id} ({s.product_name} on {s.application_date})"
            if s.external_record_id:
                keys[csv_import.duplicate_key_for_spray_event(
                    s.external_record_id, None, None
                )] = label
            keys[csv_import.duplicate_key_for_spray_event(
                None, s.product_name, s.application_date, s.field_block
            )] = label
    elif record_type == csv_import.RECORD_TYPE_WEATHER:
        for w in list_weather_observations(db, farm_id):
            keys[csv_import.duplicate_key_for_weather(w.station_id, w.observed_at)] = (
                f"weather reading #{w.id} ({w.station_id} at {w.observed_at})"
            )
    elif record_type == csv_import.RECORD_TYPE_SCOUTING_SAMPLES:
        blocks = {b.id: b.name for b in list_blocks(db, farm_id)}
        for s in list_scouting_samples(db, farm_id):
            label = f"scouting sample #{s.id} ({s.target} at {s.observed_at})"
            if s.external_record_id:
                keys[csv_import.duplicate_key_for_scouting_sample(
                    s.external_record_id, None, None, None
                )] = label
            keys[csv_import.duplicate_key_for_scouting_sample(
                None, blocks.get(s.block_id), s.target, s.observed_at
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


def block_names_for_import(db: Session, farm_id: int) -> set[str]:
    """Lower-cased block names, so the dry run can reject an unknown block itself."""
    return {(b.name or "").strip().lower() for b in list_blocks(db, farm_id)}


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
    ensure_demo_real_separation(
        db, farm.id,
        SimpleNamespace(data_source=data_source, data_confidence=data_confidence),
    )
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
    elif record_type == csv_import.RECORD_TYPE_SPRAY_EVENTS:
        for row in report.importable_rows:
            values = row.values
            event = models.SprayEvent(
                farm_id=farm.id,
                product_name=values["product_name"],
                epa_reg_no=values.get("epa_reg_no"),
                active_ingredient=values.get("active_ingredient"),
                moa_group=values.get("moa_group"),
                pesticide_class=values.get("pesticide_class"),
                target_pest_or_disease=values.get("target_pest_or_disease"),
                application_date=values["application_date"],
                rate_amount=values.get("rate_amount"),
                rate_unit=values.get("rate_unit"),
                treated_acres=values.get("treated_acres"),
                treated_area_unit=(
                    resolve_treated_area_unit(db, farm.id)
                    if values.get("treated_acres") is not None else None
                ),
                cost=values.get("cost"),
                pre_harvest_interval_days=values.get("pre_harvest_interval_days"),
                re_entry_interval_hours=values.get("re_entry_interval_hours"),
                field_block=values.get("field_block"),
                external_record_id=values.get("external_record_id"),
                source_system=source_system,
                source_filename=source_filename,
                notes=values.get("notes"),
                data_source=data_source,
                data_confidence=data_confidence,
                pilot_import_batch_id=batch.id,
            )
            db.add(event)
            db.flush()
            created_ids.append(event.id)
        batch.spray_event_count = len(created_ids)
    elif record_type == csv_import.RECORD_TYPE_WEATHER:
        for row in report.importable_rows:
            values = row.values
            reading = models.WeatherObservation(
                farm_id=farm.id,
                station_id=values["station_id"],
                station_name=values.get("station_name"),
                station_distance_km=values.get("station_distance_km"),
                observed_at=values["observed_at"],
                recorded_at=clock.current_datetime(),
                temperature_c=values.get("temperature_c"),
                relative_humidity_pct=values.get("relative_humidity_pct"),
                rainfall_mm=values.get("rainfall_mm"),
                leaf_wetness_minutes=values.get("leaf_wetness_minutes"),
                # Unstated provenance is recorded as NOT measured: assuming a sensor
                # reading would overstate the evidence grade of every imported hour.
                wetness_is_measured=values.get("wetness_is_measured"),
                quality_flag=values.get("quality_flag"),
                source_type="imported_unverified",
                source_reference=(
                    values.get("source_reference")
                    or f"{source_filename or entry_source} row {row.row_number}"
                ),
                data_source=data_source,
                data_confidence=data_confidence,
            )
            db.add(reading)
            db.flush()
            created_ids.append(reading.id)
        batch.weather_observation_count = len(created_ids)
    elif record_type == csv_import.RECORD_TYPE_SCOUTING_SAMPLES:
        blocks_by_name = {
            (b.name or "").strip().lower(): b.id for b in list_blocks(db, farm.id)
        }
        for row in report.importable_rows:
            values = row.values
            block_id = blocks_by_name.get((values["block_name"] or "").strip().lower())
            if block_id is None:
                # validate_rows already rejects unknown blocks when the caller passes
                # known_block_names; this is the belt-and-braces for any caller that
                # does not. A sample is never attached to a guessed block.
                raise CrossFarmReferenceError(
                    f"block '{values['block_name']}' does not exist on this farm"
                )
            sample = models.ScoutingSample(
                farm_id=farm.id,
                block_id=block_id,
                observed_at=values["observed_at"],
                recorded_at=clock.current_datetime(),
                method=values["method"],
                target=values["target"],
                units_inspected=values["units_inspected"],
                units_affected=values["units_affected"],
                incidence_pct=incidence_pct(
                    values["units_affected"], values["units_inspected"]
                ),
                # A severity index without its scale cannot be compared to anything,
                # so it is dropped rather than stored as if it were comparable.
                severity_index=(
                    values.get("severity_index")
                    if values.get("severity_scale") else None
                ),
                severity_scale=values.get("severity_scale"),
                scout_name=values.get("scout_name"),
                notes=values.get("notes"),
                external_record_id=values.get("external_record_id"),
                source_type="imported_unverified",
                source_reference=(
                    f"{source_filename or entry_source} row {row.row_number}"
                ),
                data_source=data_source,
                data_confidence=data_confidence,
            )
            db.add(sample)
            db.flush()
            created_ids.append(sample.id)
        batch.scouting_sample_count = len(created_ids)
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
            "spray_event_count": batch.spray_event_count,
            "weather_observation_count": batch.weather_observation_count,
            "scouting_sample_count": batch.scouting_sample_count,
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
        date_format=req.date_format,
        # So a sample naming an unknown block fails in the dry run rather than at
        # commit — a dry run that says "importable" and then fails is worse than none.
        known_block_names=block_names_for_import(db, farm.id),
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
        date_format=req.date_format,
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


class DecisionHasEvidenceError(Exception):
    """Raised when deleting a decision would destroy accumulated evidence."""


def decision_deletion_blockers(db: Session, planned: models.PlannedSpray) -> list[str]:
    """Everything that makes this decision undeletable, named.

    `input_values`, `audit_events` and `follow_up_events` cascade delete-orphan, so an
    unguarded DELETE silently destroys the immutable audit trail — the one record whose
    entire purpose is to be undestroyable. Snapshots and assessments do not cascade and
    would be left dangling instead.

    The legitimate use of DELETE is removing a check that was just mistyped, so the
    guard triggers on evidence accumulated BEYOND creation rather than on existence:
    a decision that has only its "created" audit event is still deletable.
    """
    blockers = []
    if planned.outcome and planned.outcome != decision_status.OUTCOME_PLANNED:
        blockers.append(f"a recorded outcome ({planned.outcome})")
    if planned.review_status in decision_status.RESOLVED_REVIEW_STATUSES:
        blockers.append(f"a completed PCA review ({planned.review_status})")
    if list_follow_up_events(db, planned.id):
        blockers.append("follow-up events")
    if list_risk_snapshots(db, planned.id):
        blockers.append("a risk-input snapshot")
    if list_disease_risk_assessments(db, planned.id):
        blockers.append("a disease-risk assessment")
    if list_pca_dispositions(db, planned.id):
        blockers.append("a PCA disposition")
    if planned.input_plan_items:
        blockers.append("linked procurement (input plan items)")

    other_events = [
        e for e in (planned.audit_events or []) if e.event_type != "created"
    ]
    if other_events:
        kinds = sorted({e.event_type for e in other_events})
        blockers.append(f"audit history ({', '.join(kinds)})")
    return blockers


def delete_planned_spray(db: Session, planned: models.PlannedSpray) -> None:
    blockers = decision_deletion_blockers(db, planned)
    if blockers:
        raise DecisionHasEvidenceError(
            "this decision cannot be deleted because it carries "
            + ", ".join(blockers)
            + ". Pilot evidence is append-only: record a corrected decision instead "
            "of removing this one."
        )
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
            # Explicit real provenance — omitting it would fall through to the ORM
            # column default ("demo"/"simulated") and mistag a real pilot's records.
            data_source="manual_entry",
            data_confidence="user_provided",
        ))

    if data.scouting_concern:
        db.add(models.ScoutObservation(
            farm_id=farm.id,
            observation_date=clock.current_date(),
            visible_issue=data.scouting_concern,
            severity_1_to_5=data.scouting_severity_1_to_5,
            data_source="manual_entry",
            data_confidence="user_provided",
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
    ensure_demo_real_separation(db, farm.id, data)
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
    ensure_demo_real_separation(db, farm_id, data)
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
    ensure_demo_real_separation(db, farm_id, data)
    baseline = models.SprayBaseline(farm_id=farm_id, **data.model_dump())
    db.add(baseline)
    db.commit()
    db.refresh(baseline)
    return baseline


# ------------------------------------------------- Demo/real farm separation
# Farm-scoped record types whose provenance defines whether a farm is a demo farm.
# (Procurement rows enforce the same rule separately against their plan/decision —
# see _validate_plan_item — and always trace back to one of these.)
_FARM_RECORD_MODELS = (
    models.SprayEvent, models.ScoutObservation, models.PlannedSpray,
    models.SprayBaseline, models.PcaPolicy, models.Block,
    # A label verification is farm-scoped precisely so this guard covers it: a demo farm
    # can then only ever hold a simulated verification, and
    # label_data.promotable_to_authoritative refuses to promote from one. That is what
    # stops a demo decision from ever showing a label-grounded verdict.
    models.ProductLabelVerification,
)


def ensure_demo_real_separation(db: Session, farm_id: int, new_record) -> None:
    """Reject a record whose demo-ness contradicts the farm's existing records.

    The descriptive surfaces (analytics, compliance snapshot, weekly report,
    reduction, audit packet) deliberately read every row on a farm; keeping each
    farm all-demo or all-real is what keeps those surfaces honest without
    re-filtering six code paths. Farm-level mirror of the procurement guard in
    `_validate_plan_item`. A farm with no records yet accepts either kind — the
    first record sets the farm's nature.
    """
    new_is_demo = decision_status.is_demo_record(new_record)
    for model in _FARM_RECORD_MODELS:
        for row in db.scalars(select(model).where(model.farm_id == farm_id)):
            if decision_status.is_demo_record(row) != new_is_demo:
                have, adding = (
                    ("simulated demo", "a real") if new_is_demo is False
                    else ("real", "a simulated demo")
                )
                raise DemoMixingError(
                    f"simulated demo records and real records can never mix on one "
                    f"farm — this farm already has {have} records and this would add "
                    f"{adding} one. Create a separate farm for real pilot data."
                )


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
    # Farm-level demo/real separation (the item/decision-level checks below guard
    # the chain's internal consistency; this guards the plan against the farm).
    ensure_demo_real_separation(db, farm.id, data)
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


def _add_plan_event(
    db: Session,
    plan: models.InputPlan,
    event_type: str,
    *,
    actor: str | None = None,
    notes: str | None = None,
    payload: dict | None = None,
) -> models.InputPlanEvent:
    """The single writer for plan audit events (add, not commit) — append-only.

    Called only alongside the transition-guarded mutations below, so the plan
    transition map is already the validity guard; payload carries the prior and
    resulting state.
    """
    event = models.InputPlanEvent(
        input_plan_id=plan.id,
        event_type=event_type,
        occurred_on=clock.current_date(),
        actor=actor,
        notes=notes,
        payload=payload,
        data_source=plan.data_source,
        data_confidence=plan.data_confidence,
    )
    db.add(event)
    return event


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
    prior_status = plan.status
    plan.status = procurement_status.PLAN_SUBMITTED
    plan.submitted_at = clock.current_datetime()
    plan.submitted_by = data.submitted_by
    _add_plan_event(
        db, plan, procurement_status.PLAN_EVENT_SUBMITTED,
        actor=data.submitted_by,
        payload={
            "from_status": prior_status,
            "to_status": plan.status,
            "item_count": len(plan.items),
        },
    )
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
    prior_status = plan.status
    plan.status = procurement_status.PLAN_CANCELLED
    plan.cancelled_at = clock.current_datetime()
    plan.cancelled_reason = data.reason
    _add_plan_event(
        db, plan, procurement_status.PLAN_EVENT_CANCELLED,
        actor=data.actor,
        payload={
            "from_status": prior_status,
            "to_status": plan.status,
            "reason": data.reason,
        },
    )
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
    prior_status = plan.status
    quote.status = procurement_status.QUOTE_SELECTED
    plan.selected_quote_id = quote.id
    plan.selected_by = data.selected_by
    plan.selection_reason = data.reason
    plan.status = procurement_status.PLAN_QUOTE_SELECTED
    _add_plan_event(
        db, plan, procurement_status.PLAN_EVENT_QUOTE_SELECTED,
        actor=data.selected_by,
        payload={
            "from_status": prior_status,
            "to_status": plan.status,
            "supplier_quote_id": quote.id,
            "supplier_name": quote.supplier_name,
            "total_cost": quote.total_cost,
            "reason": data.reason,
        },
    )
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
    """The grower's one-shot select/decline of INDICATIVE terms — never a loan,
    never an approval, never money movement."""
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
    if data.action == procurement_status.OFFER_SELECTED:
        for sibling_quote in plan.quotes:
            for sibling in sibling_quote.financing_offers:
                if sibling.status == procurement_status.OFFER_SELECTED:
                    raise ProcurementStateError(
                        "another financing offer on this plan is already selected"
                    )
    offer.status = data.action
    offer.decided_by = data.actor
    offer.decided_at = clock.current_datetime()
    offer.decision_notes = data.notes
    _add_plan_event(
        db, plan,
        (
            procurement_status.PLAN_EVENT_FINANCING_OFFER_SELECTED
            if data.action == procurement_status.OFFER_SELECTED
            else procurement_status.PLAN_EVENT_FINANCING_OFFER_DECLINED
        ),
        actor=data.actor,
        notes=data.notes,
        payload={
            "financing_offer_id": offer.id,
            "provider_name": offer.provider_name,
            "financed_amount": offer.financed_amount,
            "supplier_quote_id": offer.supplier_quote_id,
            "from_offer_status": procurement_status.OFFER_INDICATIVE,
            "to_offer_status": offer.status,
        },
    )
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
    selected_offer = next(
        (
            o for o in quote.financing_offers
            if o.status == procurement_status.OFFER_SELECTED
        ),
        None,
    )
    order = models.PurchaseOrder(
        farm_id=plan.farm_id,
        input_plan_id=plan.id,
        selected_quote_id=quote.id,
        accepted_financing_offer_id=selected_offer.id if selected_offer else None,
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
            "reason": plan.selection_reason,
        },
    )
    if selected_offer is not None:
        _add_order_event(
            db, order, procurement_status.EVENT_FINANCING_SELECTED,
            occurred_on=today, actor=selected_offer.decided_by,
            payload={
                "financing_offer_id": selected_offer.id,
                "provider_name": selected_offer.provider_name,
                "financed_amount": selected_offer.financed_amount,
            },
        )
    prior_status = plan.status
    plan.status = procurement_status.PLAN_ORDERED
    _add_plan_event(
        db, plan, procurement_status.PLAN_EVENT_ORDERED,
        actor=data.placed_by,
        payload={
            "from_status": prior_status,
            "to_status": plan.status,
            "purchase_order_id": order.id,
        },
    )
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


# ------------------------------------------------------------- pesticide labels
# Read + load only. Nothing here writes a DecisionInputValue or touches a decision:
# applying label values to a decision is a separate, gated step (see the plan's Phase 3),
# so this layer landing cannot change any existing verdict.
def list_pesticide_products(db: Session) -> list[models.PesticideProduct]:
    return list(
        db.scalars(select(models.PesticideProduct).order_by(models.PesticideProduct.id))
    )


def get_pesticide_product(db: Session, product_id: int) -> models.PesticideProduct | None:
    return db.get(models.PesticideProduct, product_id)


def get_product_by_reg_no(db: Session, epa_reg_no: str | None) -> models.PesticideProduct | None:
    """Exact registration-number lookup. The ONLY way a product is identified."""
    normalized = label_data.normalize_epa_reg_no(epa_reg_no)
    if not normalized:
        return None
    return db.scalar(
        select(models.PesticideProduct).where(
            models.PesticideProduct.epa_reg_no_normalized == normalized
        )
    )


def resolve_product_identity(db: Session, epa_reg_no: str | None):
    """(product, None) on an exact match, else (None, reason).

    A base-registration match is reported as a REASON, never resolved: `100-1234` and
    `100-1234-5905` are different labels with different use directions, so guessing here
    would apply the wrong PHI to a real decision.
    """
    normalized = label_data.normalize_epa_reg_no(epa_reg_no)
    if not normalized:
        return None, "this decision has no EPA registration number, so no label can be matched"

    exact = get_product_by_reg_no(db, normalized)
    if exact is not None:
        return exact, None

    base = label_data.epa_reg_base(normalized)
    if base:
        related = list(
            db.scalars(
                select(models.PesticideProduct).where(
                    models.PesticideProduct.epa_reg_base == base
                )
            )
        )
        if related:
            names = ", ".join(sorted(p.epa_reg_no for p in related))
            return None, (
                f"registration number {epa_reg_no!r} matches only the base registration "
                f"of {names} — a supplemental registration is a different label, so a "
                f"human must confirm which applies"
            )
    return None, f"no label record on file for registration number {epa_reg_no!r}"


def label_record_for_decision(db: Session, epa_reg_no: str | None, crop: str | None):
    """The live label record for a (registration number, crop), or (None, reason)."""
    product, reason = resolve_product_identity(db, epa_reg_no)
    if product is None:
        return None, reason
    return label_data.resolve_label_record(product.label_records, crop)


def list_label_verifications(
    db: Session, label_record_id: int
) -> list[models.ProductLabelVerification]:
    """Every verification on a record, including revoked ones (append-only history)."""
    return list(
        db.scalars(
            select(models.ProductLabelVerification)
            .where(
                models.ProductLabelVerification.product_label_record_id == label_record_id
            )
            .order_by(models.ProductLabelVerification.id)
        )
    )


def label_verifications_for_farm(
    db: Session, label_record_id: int, farm_id: int | None
) -> list[models.ProductLabelVerification]:
    """Live (non-revoked) verifications of a record FOR ONE FARM.

    Farm-scoping is the whole point of the verification model: a PCA authorized for one
    farm must not be able to vouch for another farm's decisions. Passing no farm returns
    nothing rather than everything — an unscoped query here would silently be the global
    "this record is verified" flag the design rejected.
    """
    if farm_id is None:
        return []
    return list(
        db.scalars(
            select(models.ProductLabelVerification)
            .where(
                models.ProductLabelVerification.product_label_record_id == label_record_id,
                models.ProductLabelVerification.farm_id == farm_id,
                models.ProductLabelVerification.revoked_at.is_(None),
            )
            .order_by(models.ProductLabelVerification.id)
        )
    )


def resolve_label_for_decision(
    db: Session, epa_reg_no: str | None, crop: str | None, farm_id: int | None
):
    """(record, unresolved_reason, promotion_blocked_reason) for one farm's decision.

    The single resolution path: the operator diagnostic and the decision writer must not
    be able to disagree about whether a label applies. Two reasons come back separately
    because they are different problems — no record found at all, versus a record found
    that nobody has verified yet — and a PCA fixes them in different ways.
    """
    record, unresolved_reason = label_record_for_decision(db, epa_reg_no, crop)
    if record is None:
        return None, unresolved_reason, None
    blocked = label_data.promotable_to_authoritative(
        record, label_verifications_for_farm(db, record.id, farm_id)
    )
    return record, None, blocked


def _live_label_record(
    product: models.PesticideProduct, crop_normalized: str
) -> models.ProductLabelRecord | None:
    for record in label_data.active_label_records(product.label_records):
        if record.registered_crop_normalized == crop_normalized:
            return record
    return None


# The decision inputs a verified label may supersede. Deliberately short, and
# deliberately missing three things:
#   * `product_name` — the grower's trade name for what is in the shed is their own
#     fact, and a label record is not entitled to rewrite it;
#   * `crop` — what is planted is the farm's fact, not the label's;
#   * `epa_reg_no` — it is the join key. A label rewriting the key it was found by
#     would make the match unfalsifiable.
LABEL_SUPERSEDABLE_FIELDS = (
    "pre_harvest_interval_days",
    "re_entry_interval_hours",
    "active_ingredient",
    "moa_group",
)

_LABEL_FIELD_UNITS = {
    "pre_harvest_interval_days": "days",
    "re_entry_interval_hours": "hours",
}


def _label_reference(product, record) -> str:
    """Stable citation for a label-sourced value: what label, which crop, which revision."""
    return (
        f"label:{product.epa_reg_no}:{record.registered_crop_normalized}:"
        f"{record.label_version or 'unversioned'}"
    )


def _label_field_values(product, record) -> dict:
    """The label's value for each supersedable field (absent when the label is silent)."""
    values = {
        "pre_harvest_interval_days": record.pre_harvest_interval_days,
        "re_entry_interval_hours": record.re_entry_interval_hours,
        "active_ingredient": product.active_ingredient,
        "moa_group": product.moa_group,
    }
    return {name: value for name, value in values.items() if value is not None}


_LABEL_COMPARABLE_FIELDS = ("pre_harvest_interval_days", "re_entry_interval_hours")


def _entered_values_behind_label(planned_like) -> dict:
    """What a HUMAN entered for each field, looking past any label row on top of it.

    Walks back through the supersede chain rather than trusting the denormalized column,
    because the writer keeps that column in sync with the latest verified value (the
    same convention the PCA-review path uses). Without this, applying a label value
    would erase the very disagreement it should have reported.

    Falls back to the object's own attributes — which is the whole answer at creation
    time, before any provenance row exists. A field whose chain contains nothing but
    label values is omitted: there is no human value there to disagree with.
    """
    entered: dict = {
        name: getattr(planned_like, name)
        for name in _LABEL_COMPARABLE_FIELDS
        if getattr(planned_like, name, None) is not None
    }
    rows = list(getattr(planned_like, "input_values", None) or [])
    if not rows:
        return entered

    by_id = {row.id: row for row in rows}
    for field_name, row in active_input_values(planned_like).items():
        seen = set()
        while (
            row is not None
            and row.source_type == label_data.SOURCE_AUTHORITATIVE
            and row.supersedes_input_value_id is not None
            and row.supersedes_input_value_id not in seen
        ):
            seen.add(row.supersedes_input_value_id)
            row = by_id.get(row.supersedes_input_value_id)
        if row is None or row.source_type == label_data.SOURCE_AUTHORITATIVE:
            entered.pop(field_name, None)
            continue  # nothing but label values in this chain — nobody to disagree with
        value = row.normalized_value
        if value is None or field_name not in _LABEL_COMPARABLE_FIELDS:
            continue
        try:
            entered[field_name] = int(value)
        except ValueError:
            continue
    return entered


def build_label_context(db: Session, planned_like, farm: models.Farm):
    """Resolve everything the engine's label-dependent checks need, for one decision.

    All the database-shaped questions — which product a registration number identifies,
    which record is live, whether a licensed PCA verified it FOR THIS FARM — are
    answered here so the engine stays framework-free and unit-testable.

    Returns the empty context (every check disclosed as not run) whenever anything is
    missing, which is the normal state until a label has been transcribed and verified.

    `planned_like` is a stored PlannedSpray or the create schema, so the same resolution
    runs on the first evaluation as on every later one.
    """
    epa_reg_no = getattr(planned_like, "epa_reg_no", None)
    crop = getattr(planned_like, "crop", None)
    record, unresolved_reason, blocked = resolve_label_for_decision(
        db, epa_reg_no, crop, farm.id
    )
    product, product_reason = resolve_product_identity(db, epa_reg_no)

    # The registered-crop list may only be compared against when a human has confirmed
    # it is COMPLETE and at least one record backing it is PCA-verified for this farm.
    # Otherwise a partial transcription would emit a false "not registered" block.
    registered_crops: tuple[str, ...] = ()
    if product is None:
        crop_registration_reason = product_reason
    elif not product.registered_crops_transcription_complete:
        crop_registration_reason = (
            "the list of crops registered on this product's label has not been "
            "transcribed in full, so a crop missing from it is not evidence that the "
            "product is unregistered for that crop"
        )
    else:
        verified = [
            live for live in label_data.active_label_records(product.label_records)
            if label_data.promotable_to_authoritative(
                live, label_verifications_for_farm(db, live.id, farm.id)
            ) is None
        ]
        registered_crops = tuple(live.registered_crop for live in verified)
        crop_registration_reason = None if verified else (
            "no label record for this product has been verified by a licensed PCA for "
            "this farm, so its registered-crop list cannot back a decision"
        )

    season_start = getattr(farm, "planting_date", None)
    season_reason = None if season_start is not None else (
        "no planting date is recorded for this farm, so there is no season window to "
        "count applications or add up rates over"
    )

    return LabelContext(
        record=record,
        unresolved_reason=unresolved_reason,
        promotion_blocked_reason=blocked,
        reference=_label_reference(product, record) if record is not None else None,
        registered_crops=registered_crops,
        crop_registration_reason=crop_registration_reason,
        entered_values=_entered_values_behind_label(planned_like),
        season_start=season_start,
        season_reason=season_reason,
    )


def apply_label_values(
    db: Session, planned: models.PlannedSpray, *, commit: bool = True
) -> list[str]:
    """Supersede a decision's entered values with the verified label's. Returns the fields.

    Mirrors the PCA-review supersede path: nothing is edited in place, each value
    appends a row pointing at the one it replaces, an audit event records the before and
    after, and the decision is re-run against the result.

    REFUSES on a decision that is no longer open. A label sync must never rewrite what a
    PCA already signed or what has already been applied in the field — the signature and
    the record have to keep meaning what they meant at the time. A later label revision
    on a reviewed decision surfaces as `decision_status.label_reference_stale` instead.
    """
    if planned.outcome != "planned" or planned.review_status != "not_reviewed":
        return []

    record, _, blocked = resolve_label_for_decision(
        db, planned.epa_reg_no, planned.crop, planned.farm_id
    )
    if record is None or blocked is not None:
        return []
    product = get_pesticide_product(db, record.product_id)
    if product is None:  # pragma: no cover - FK guarantees this
        return []

    reference = _label_reference(product, record)
    current = active_input_values(planned)
    now = clock.current_datetime()
    applied: list[str] = []

    for field_name, label_value in _label_field_values(product, record).items():
        if field_name not in LABEL_SUPERSEDABLE_FIELDS:
            continue
        prior = current.get(field_name)
        # Already carrying THIS label's value from THIS record: appending an identical
        # row on every re-sync would turn an audit trail into noise.
        if (
            prior is not None
            and prior.source_type == label_data.SOURCE_AUTHORITATIVE
            and prior.source_reference == reference
        ):
            continue
        before_value = getattr(planned, field_name, None)
        db.add(models.DecisionInputValue(
            planned_spray_id=planned.id,
            field_name=field_name,
            raw_value=str(label_value),
            normalized_value=_normalized_input(field_name, label_value),
            unit=_LABEL_FIELD_UNITS.get(field_name),
            source_type=label_data.SOURCE_AUTHORITATIVE,
            source_reference=reference,
            confidence="label_verified",
            verified_by=reference,
            verified_at=now,
            effective_date=record.label_effective_date,
            supersedes_input_value_id=prior.id if prior else None,
        ))
        # Denormalized display copy follows the latest verified value, exactly as it
        # does after a PCA edit. The human's original value stays readable in the
        # superseded row and in the audit event below.
        setattr(planned, field_name, label_value)
        applied.append(field_name)
        _add_audit_event(
            db, planned, "input_value_superseded",
            actor=reference,
            rationale="verified pesticide label",
            after={"field": field_name, "from": before_value, "to": label_value},
        )

    if not applied:
        return []

    _add_audit_event(
        db, planned, "label_values_applied",
        actor=reference,
        rationale="verified pesticide label",
        after={
            "fields": applied,
            "label_reference": reference,
            "label_record_id": record.id,
            "label_effective_date": (
                record.label_effective_date.isoformat()
                if record.label_effective_date else None
            ),
        },
    )
    db.flush()  # assign input-value ids before re-resolving
    _rerun_decision(db, planned)
    if commit:
        db.commit()
        db.refresh(planned)
    return applied


def ai_concentrations_for_farm(db: Session, farm_id: int) -> dict:
    """{normalized EPA reg no: (concentration amount, unit)} for PROMOTABLE labels.

    Scoped to labels a licensed PCA has verified FOR THIS FARM, for the same reason
    every other label read is: an unverified transcription is on file, not in force,
    and a quantity computed from one would be a number nobody attested to.

    A product with no concentration transcribed is simply absent, which makes the
    active-ingredient metric refuse rather than silently omit that application.
    """
    concentrations: dict[str, tuple[float, str]] = {}
    for product in list_pesticide_products(db):
        amount = product.active_ingredient_concentration_amount
        unit = product.active_ingredient_concentration_unit
        if amount is None or not unit:
            continue
        promotable = any(
            label_data.promotable_to_authoritative(
                record, label_verifications_for_farm(db, record.id, farm_id)
            ) is None
            for record in label_data.active_label_records(product.label_records)
        )
        if promotable:
            concentrations[product.epa_reg_no_normalized] = (float(amount), unit)
    return concentrations


def create_label_record(
    db: Session, data: schemas.ProductLabelRecordCreate
) -> models.ProductLabelRecord:
    """Commit ONE human-reviewed label use as an `ai_extracted_unverified` record.

    The tier is set here, never by the caller: a row that a model proposed and a
    human corrected is unverified no matter how careful the correction was, and it
    stays unusable until a licensed PCA attests to it for a specific farm.

    Append-only, exactly like the transcription loader: a row for a (product, crop)
    that already has a live record SUPERSEDES it rather than editing it, so the
    value a decision relied on last month is still readable.
    """
    normalized = label_data.normalize_epa_reg_no(data.epa_reg_no)
    product = get_product_by_reg_no(db, normalized)
    if product is None:
        product = models.PesticideProduct(
            epa_reg_no=data.epa_reg_no,
            epa_reg_no_normalized=normalized,
            epa_reg_base=label_data.epa_reg_base(normalized),
            product_name=data.product_name,
            registrant=data.registrant,
            active_ingredient=data.active_ingredient,
            active_ingredient_concentration_amount=(
                data.active_ingredient_concentration_amount
            ),
            active_ingredient_concentration_unit=(
                data.active_ingredient_concentration_unit
            ),
            moa_group=data.moa_group,
        )
        db.add(product)
        db.flush()

    crop_normalized = crop_aliases.normalize(data.registered_crop)
    existing = _live_label_record(product, crop_normalized)
    record = models.ProductLabelRecord(
        product_id=product.id,
        registered_crop=data.registered_crop,
        registered_crop_normalized=crop_normalized,
        target_pest_or_disease=data.target_pest_or_disease,
        pre_harvest_interval_days=data.pre_harvest_interval_days,
        re_entry_interval_hours=data.re_entry_interval_hours,
        max_seasonal_rate_amount=data.max_seasonal_rate_amount,
        max_seasonal_rate_unit=data.max_seasonal_rate_unit,
        max_applications_per_season=data.max_applications_per_season,
        min_retreatment_interval_days=data.min_retreatment_interval_days,
        label_version=data.label_version,
        label_effective_date=data.label_effective_date,
        # Server-set. A model proposed these values and a human corrected them;
        # that is not verification, and no request field can say otherwise.
        source_tier=label_data.TIER_AI_EXTRACTED,
        source_document_reference=data.source_document_reference,
        source_section_or_page=data.source_section_or_page,
        source_snippet=data.source_snippet,
        transcribed_by=data.reviewed_by,
        transcribed_at=clock.current_datetime(),
        supersedes_label_record_id=existing.id if existing is not None else None,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def create_label_verification(
    db: Session,
    farm: models.Farm,
    data: schemas.ProductLabelVerificationCreate,
    credential: models.PcaCredential,
) -> models.ProductLabelVerification:
    """Record a PCA's attestation that a label record matches the primary document.

    This is the act that makes a stored value usable — everything else in the label
    layer is on-file, not in-force. So it is credential-gated at the route, attributed
    from the CREDENTIAL rather than a client string, farm-scoped, and append-only.

    Demo separation applies by construction: the verification is a farm record, so
    `ensure_demo_real_separation` gives a demo farm a simulated verification, and
    `label_data.promotable_to_authoritative` refuses to promote from one.
    """
    record = db.get(models.ProductLabelRecord, data.product_label_record_id)
    if record is None:
        raise ValueError("label record not found")

    verification = models.ProductLabelVerification(
        product_label_record_id=record.id,
        farm_id=farm.id,
        verified_by_credential_id=credential.id,
        # The credential's own name wins over anything a client could send:
        # attribution must match the thing that was actually verified.
        verified_by=credential.display_name,
        attestation=data.attestation,
        # Explicit rather than relying on the column default, which does not apply
        # until flush — the mixing guard below reads these before the row exists.
        data_source="manual_entry",
        data_confidence="user_provided",
    )
    ensure_demo_real_separation(db, farm.id, verification)
    db.add(verification)
    db.commit()
    db.refresh(verification)
    return verification


def sync_transcribed_labels(db: Session) -> schemas.LabelSyncResult:
    """Load `app/label_table.TRANSCRIBED_LABEL_USES` into the append-only record table.

    Idempotent WITHOUT an UPDATE, which is the whole design: each entry is content-
    addressed (`label_data.transcription_digest`), so an unchanged digest is a no-op and a
    changed digest appends a row superseding the previous one. Re-running after editing a
    transcription therefore leaves the original readable, which is what makes a corrected
    label value auditable rather than silently rewritten.

    Existing product metadata is never overwritten. If a later transcription disagrees
    about a product's active ingredient, that disagreement is REPORTED in `notes` — a
    silent overwrite would resolve a factual conflict by whoever synced last.
    """
    entries = label_table.TRANSCRIBED_LABEL_USES
    result = {
        "transcribed_entries": len(entries),
        "products_created": 0,
        "records_created": 0,
        "records_superseded": 0,
        "unchanged": 0,
    }
    notes: list[str] = []
    now = clock.current_datetime()

    for entry in entries:
        normalized = label_data.normalize_epa_reg_no(entry.epa_reg_no)
        product = get_product_by_reg_no(db, normalized)
        if product is None:
            product = models.PesticideProduct(
                epa_reg_no=entry.epa_reg_no,
                epa_reg_no_normalized=normalized,
                epa_reg_base=label_data.epa_reg_base(normalized),
                product_name=entry.product_name,
                registrant=entry.registrant,
                active_ingredient=entry.active_ingredient,
                active_ingredient_concentration_amount=(
                    entry.active_ingredient_concentration_amount
                ),
                active_ingredient_concentration_unit=(
                    entry.active_ingredient_concentration_unit
                ),
                moa_group=entry.moa_group,
            )
            db.add(product)
            db.flush()
            result["products_created"] += 1
        else:
            for field_name in (
                "active_ingredient", "moa_group", "registrant",
                "active_ingredient_concentration_amount",
                "active_ingredient_concentration_unit",
            ):
                new_value = getattr(entry, field_name)
                current = getattr(product, field_name)
                if new_value is None:
                    continue
                if current is None:
                    setattr(product, field_name, new_value)
                elif current != new_value:
                    notes.append(
                        f"{entry.epa_reg_no}: transcription says {field_name}="
                        f"{new_value!r} but the stored product says {current!r} — kept "
                        f"the stored value; resolve this against the label"
                    )

        crop_normalized = crop_aliases.normalize(entry.registered_crop)
        digest = label_data.transcription_digest(entry.as_values())
        existing = _live_label_record(product, crop_normalized)
        if existing is not None and existing.transcription_digest == digest:
            result["unchanged"] += 1
            continue

        db.add(models.ProductLabelRecord(
            product_id=product.id,
            registered_crop=entry.registered_crop,
            registered_crop_normalized=crop_normalized,
            target_pest_or_disease=entry.target_pest_or_disease,
            pre_harvest_interval_days=entry.pre_harvest_interval_days,
            re_entry_interval_hours=entry.re_entry_interval_hours,
            max_seasonal_rate_amount=entry.max_seasonal_rate_amount,
            max_seasonal_rate_unit=entry.max_seasonal_rate_unit,
            max_applications_per_season=entry.max_applications_per_season,
            min_retreatment_interval_days=entry.min_retreatment_interval_days,
            label_version=entry.label_version,
            label_effective_date=entry.label_effective_date,
            # A transcription is UNVERIFIED however careful the transcriber was. It
            # becomes label-verified only through an attributed PCA act (Phase 4).
            source_tier=label_data.TIER_TRANSCRIBED,
            source_document_reference=entry.source_document_reference,
            source_section_or_page=entry.source_section_or_page,
            source_snippet=entry.source_snippet,
            transcribed_by=entry.transcribed_by,
            transcribed_at=now,
            transcription_digest=digest,
            supersedes_label_record_id=existing.id if existing is not None else None,
        ))
        if existing is not None:
            result["records_superseded"] += 1
        result["records_created"] += 1

    db.commit()
    return schemas.LabelSyncResult(**result, notes=notes)
