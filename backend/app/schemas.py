"""Pydantic schemas (request/response contracts), separate from ORM models."""
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app import backtest
from app.procurement_status import FINANCING_OFFER_DISCLAIMER

# Concierge-pilot provenance vocabularies (validated, so bad values give a clean 422).
#
# "provider_api" / "provider_reported" were added for the ingestion layer (2026-08-05).
# Neither existing value could be reused honestly: `manual_entry` would be a false claim
# about who entered the reading, and `pca_reviewed` would be a lie with legal weight,
# since nobody reviewed it. A provider's number is real data of a specific and limited
# kind — machine-fetched, unreviewed — and it needed its own word.
DataSource = Literal[
    "demo", "grower_interview", "spreadsheet", "whatsapp", "email", "manual_entry",
    "photo_ai", "ai_extracted", "provider_api", "unknown"
]
DataConfidence = Literal[
    "simulated", "user_provided", "pca_reviewed", "provider_reported", "incomplete"
]

# Field-level provenance for compliance/decision-critical input values.
# "authoritative_provider" is deliberately unreachable today (no label-data provider
# exists); the vocabulary is in place so the gate is already correct when one does.
InputSourceType = Literal[
    "demo", "user_entered", "imported_unverified", "pca_verified",
    "authoritative_provider",
]
# How a stored label record was obtained. A SEPARATE vocabulary from InputSourceType on
# purpose: one says how a label record came to exist, the other how a decision's input
# value was sourced. Only pca_verified_transcription and registrant_provider_feed map to
# "authoritative_provider" (see label_data.LABEL_TIER_TO_INPUT_SOURCE) — a human typing
# from a PDF is unverified until a licensed PCA attests to it against the document.
LabelSourceTier = Literal[
    "transcribed_unverified", "ai_extracted_unverified",
    "pca_verified_transcription", "registrant_provider_feed",
]
# Append-only follow-up timeline event types (never a single mutable outcome record).
FollowUpEventType = Literal[
    "scouting_observation", "actual_application", "rescue_application",
    "harvest_outcome", "yield_quality_outcome", "note",
]
ImpactLevel = Literal["positive", "neutral", "negative", "unknown"]
# CSV pilot-import record types. spray_events = historical *actual* applications —
# the reduction baseline's denominator. The three pilot types (weather, standardized
# scouting samples, block outcomes) are CSV-only: AI extraction is deliberately NOT
# offered for them, mirroring the spray_events decision.
ImportRecordType = Literal[
    "planned_sprays", "scout_observations", "spray_events",
    "weather_observations", "scouting_samples",
]

# Standardized scouting methods. Two samples taken by different methods are not
# directly comparable, so the method travels with every sample and is never inferred.
ScoutingMethod = Literal[
    "whole_plant_count", "fruit_count", "flower_count", "leaf_count",
    "trap_count", "transect_walk", "other",
]

# Where an observation came from. Separate from `data_source` (the concierge-pilot
# provenance vocabulary) because an observation's origin and its trustworthiness are
# different questions.
ObservationSourceType = Literal[
    "manual_entry", "station_export", "imported_unverified", "pca_verified", "demo",
]
# Import date-format modes; "auto" rejects ambiguous m/d-vs-d/m dates (never guessed).
ImportDateFormat = Literal["auto", "iso", "mdy", "dmy"]


# --------------------------------------------------------------------------- Farm
class FarmBase(BaseModel):
    name: str
    location: str | None = None
    country: str = "US"
    crop_type: str = "greenhouse_tomato"
    greenhouse_area: float | None = None
    # Unit of greenhouse_area ("acres" / "m2") — explicit data, not implied by country.
    area_unit: Literal["acres", "m2"] | None = None
    planting_date: date | None = None
    expected_harvest_date: date | None = None
    advisor_involved: bool | None = None


class FarmCreate(FarmBase):
    pass


class FarmUpdate(BaseModel):
    name: str | None = None
    location: str | None = None
    country: str | None = None
    crop_type: str | None = None
    greenhouse_area: float | None = None
    area_unit: Literal["acres", "m2"] | None = None
    planting_date: date | None = None
    expected_harvest_date: date | None = None
    advisor_involved: bool | None = None


class Farm(FarmBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    # Read-only on purpose: deliberately absent from FarmCreate/FarmUpdate. Marking a
    # farm as a reference farm removes it from customer evidence counts, so it must be
    # an operator act (`python -m app.reference_farm`) rather than something any client
    # can toggle — in either direction.
    is_reference: bool = False


# ----------------------------------------------------------------- PCA credentials
class PcaCredentialCreate(BaseModel):
    """Issue a credential. The token is generated server-side and never supplied."""
    display_name: str = Field(min_length=1)
    license_identifier: str = Field(min_length=1)
    license_state: str = "CA"
    issued_by: str | None = None
    active_from: date | None = None
    active_to: date | None = None


class PcaCredential(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    display_name: str
    license_identifier: str
    license_state: str
    token_prefix: str | None = None
    issued_by: str | None = None
    active_from: date | None = None
    active_to: date | None = None
    revoked_at: datetime | None = None
    # Stated by the operator at issuance; Lumos has no registry to check it against
    # and never implies otherwise.
    license_verified_by_lumos: bool = False


class PcaCredentialIssued(PcaCredential):
    """The issuance response — the ONLY time the plaintext token exists in a payload.

    It is not stored and cannot be re-read; a lost token is revoked and reissued.
    """
    token: str
    token_notice: str = (
        "Store this token now — only its hash is kept, so it can never be shown "
        "again. If it is lost, revoke this credential and issue a new one."
    )


class PcaFarmAuthorizationCreate(BaseModel):
    farm_id: int
    granted_on: date | None = None
    granted_by: str | None = None


class PcaFarmAuthorization(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    pca_credential_id: int
    farm_id: int
    granted_on: date | None = None
    granted_by: str | None = None
    revoked_at: datetime | None = None


# -------------------------------------------------------------------------- Block
class BlockBase(BaseModel):
    name: str
    crop: str | None = None
    cultivar: str | None = None
    area: float | None = Field(default=None, gt=0)
    area_unit: Literal["acres", "m2"] | None = None
    planting_date: date | None = None
    expected_harvest_date: date | None = None
    # Phenology is recorded as observed, with its observation date — never computed
    # from the planting date. A stage without a date is refused rather than dated
    # silently (see the validator below).
    phenology_stage: str | None = None
    phenology_observed_on: date | None = None
    notes: str | None = None
    data_source: DataSource | None = "manual_entry"
    data_confidence: DataConfidence | None = "user_provided"

    @model_validator(mode="after")
    def _phenology_needs_a_date(self):
        if self.phenology_stage and self.phenology_observed_on is None:
            raise ValueError(
                "phenology_observed_on is required when phenology_stage is given — a "
                "growth stage without an observation date cannot be placed in time, "
                "and dating it for you would invent an observation."
            )
        return self


class BlockCreate(BlockBase):
    pass


class Block(BlockBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    farm_id: int


# ------------------------------------------------------------ WeatherObservation
class WeatherObservationCreate(BaseModel):
    block_id: int | None = None
    station_id: str = Field(min_length=1)
    station_name: str | None = None
    station_distance_km: float | None = Field(default=None, ge=0)
    observed_at: datetime
    temperature_c: float | None = None
    relative_humidity_pct: float | None = Field(default=None, ge=0, le=100)
    rainfall_mm: float | None = Field(default=None, ge=0)
    leaf_wetness_minutes: float | None = Field(default=None, ge=0)
    # Must be stated when wetness is given: a derived value is a different kind of
    # evidence from a measurement, and the risk assessment grades them differently.
    wetness_is_measured: bool | None = None
    source_type: ObservationSourceType = "manual_entry"
    source_reference: str | None = None
    quality_flag: str | None = None
    supersedes_id: int | None = None
    data_source: DataSource | None = "manual_entry"
    data_confidence: DataConfidence | None = "user_provided"

    @model_validator(mode="after")
    def _wetness_provenance_is_explicit(self):
        if self.leaf_wetness_minutes is not None and self.wetness_is_measured is None:
            raise ValueError(
                "wetness_is_measured is required when leaf_wetness_minutes is given — "
                "a sensor measurement and a value derived from humidity are different "
                "evidence, and assuming either one would misstate the evidence grade"
            )
        return self


class WeatherObservation(WeatherObservationCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    farm_id: int
    recorded_at: datetime


# --------------------------------------------------------------- ScoutingSample
class ScoutingSampleCreate(BaseModel):
    """A sample is a numerator over a stated denominator. Incidence is DERIVED."""
    block_id: int
    observed_at: datetime
    method: ScoutingMethod
    target: str = Field(min_length=1)
    units_inspected: int = Field(gt=0)
    units_affected: int = Field(ge=0)
    severity_index: float | None = Field(default=None, ge=0)
    severity_scale: str | None = None
    scout_name: str | None = None
    notes: str | None = None
    source_type: ObservationSourceType = "manual_entry"
    source_reference: str | None = None
    external_record_id: str | None = None
    supersedes_id: int | None = None
    data_source: DataSource | None = "manual_entry"
    data_confidence: DataConfidence | None = "user_provided"

    @model_validator(mode="after")
    def _affected_within_inspected(self):
        if self.units_affected > self.units_inspected:
            raise ValueError(
                f"units_affected ({self.units_affected}) cannot exceed units_inspected "
                f"({self.units_inspected}) — an incidence above 100% is a recording "
                f"error, not a reading"
            )
        return self

    @model_validator(mode="after")
    def _severity_index_needs_its_scale(self):
        if self.severity_index is not None and not self.severity_scale:
            raise ValueError(
                "severity_scale is required when severity_index is given — a severity "
                "without its scale cannot be compared to anything"
            )
        return self


class ScoutingSample(ScoutingSampleCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    farm_id: int
    recorded_at: datetime
    # Derived server-side from units_affected / units_inspected; never accepted as
    # input, so a percentage can never be asserted without the sample behind it.
    incidence_pct: float | None = None


# ----------------------------------------------------------- RiskInputSnapshot
class RiskSnapshotCreate(BaseModel):
    """Freeze the inputs for a decision. `as_of` defaults to now.

    An explicit `as_of` is accepted so an operator can reconstruct a snapshot for a
    past decision moment — the two-timestamp filter makes that safe, because a
    reading entered after that moment is excluded no matter when it was observed.
    """
    as_of: datetime | None = None
    horizon_hours: int = Field(default=72, gt=0, le=168)


class RiskInputSnapshot(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    farm_id: int
    block_id: int
    planned_spray_id: int | None = None
    as_of: datetime
    horizon_hours: int
    target: str
    snapshot_version: str
    payload: dict
    input_digest: str
    # What was deliberately left out, and why (future / recorded late / superseded /
    # quality-flagged / demo). Part of the evidence, not a detail.
    excluded: list | None = None
    created_at: datetime


class DiseaseRiskAssessmentCreate(BaseModel):
    """Operator-triggered. Runs against the decision's latest snapshot."""
    model_config = ConfigDict(protected_namespaces=())
    model_version: str | None = None


class DiseaseRiskAssessment(BaseModel):
    """OPERATOR-FACING ONLY.

    This schema is deliberately not referenced by any PCA-facing response model. While
    `is_shadow` is True the PCA must not see a risk band, and the guarantee is that the
    field is absent from their payload — not that the UI declines to draw it. The only
    route that returns this is the operator-gated shadow view.

    Note the fields that do not exist: no product, no rate, no recommended action.
    """
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())
    id: int
    snapshot_id: int
    planned_spray_id: int | None = None
    farm_id: int
    block_id: int
    model_family: str
    model_version: str
    input_digest: str
    risk_band: str
    probability: float | None = None
    evidence_grade: str | None = None
    horizon_hours: int
    abstained: bool
    abstain_reason: str | None = None
    missing_inputs: list | None = None
    calibration_status: str
    local_validation_status: str | None = None
    citation: str | None = None
    calculation: dict | None = None
    is_shadow: bool
    computed_at: datetime


# ------------------------------------------------------- historical opportunity scan
class OpportunityScanCreate(BaseModel):
    """Operator-triggered replay of past decision dates for one block.

    `decision_dates` are the dates sprays were ACTUALLY scheduled for — supplied by the
    operator from the partner's records, never inferred from the spray table. A spray
    that happened is evidence of a decision; a date nobody scheduled is not, and
    generating a regular grid of dates would silently invent the denominator that the
    whole opportunity figure is a fraction of.
    """
    block_id: int
    decision_dates: list[datetime] = Field(min_length=1)
    horizon_hours: int = 72
    lookback_hours: int = 168
    run_by: str | None = None


class OpportunityScanItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    as_of: datetime
    risk_band: str
    abstained: bool
    reasons: list | None = None
    evidence_grade: str | None = None
    probability_or_index: float | None = None
    input_digest: str
    excluded_count: int


class OpportunityScan(BaseModel):
    """OPERATOR-FACING ONLY, like its shadow-assessment neighbour.

    Note the fields that do not exist, and must not be added: no avoided count, no
    reduction percentage, no recommendation. `backtest.SCAN_CANNOT_CONCLUDE` travels on
    the response instead, stating why each of those is absent.
    """
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())
    id: int
    farm_id: int
    block_id: int
    scan_version: str
    model_version: str
    target: str
    basis: str
    horizon_hours: int
    lookback_hours: int
    dates_scanned: int
    assessed_count: int
    band_counts: dict | None = None
    reason_counts: dict | None = None
    grade_counts: dict | None = None
    run_by: str | None = None
    created_at: datetime
    items: list[OpportunityScanItem] = []
    # Defaulted, never read from the ORM row, so EVERY serialization of a scan carries
    # its own claim ceiling. A caller cannot receive the histogram without also
    # receiving the statement of what it does not establish.
    cannot_conclude: dict = Field(
        default_factory=lambda: dict(backtest.SCAN_CANNOT_CONCLUDE)
    )


PcaDispositionValue = Literal[
    "follow_baseline", "defer", "rescout", "insufficient_evidence"
]


class PcaDispositionCreate(BaseModel):
    """The PCA's professional judgement. Rationale is mandatory and non-empty.

    Note what a client cannot supply: the credential (it comes from the token), the
    snapshot digest (server-read, so the anchor cannot be forged), or the assessment
    link (server-resolved). A client can state a decision and a reason; everything
    that makes it evidence is recorded by the server.
    """
    disposition: PcaDispositionValue
    rationale: str = Field(min_length=1)
    supersedes_id: int | None = None

    @field_validator("rationale")
    @classmethod
    def _rationale_must_say_something(cls, v: str) -> str:
        if not v.strip():
            raise ValueError(
                "a rationale is required — a disposition without a stated reason is "
                "not usable as pilot evidence"
            )
        return v.strip()


class PcaDisposition(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    planned_spray_id: int
    pca_credential_id: int
    disposition: str
    rationale: str
    assessment_id: int | None = None
    snapshot_digest_at_decision: str
    decided_at: datetime
    supersedes_id: int | None = None
    data_source: str
    data_confidence: str


# --------------------------------------------------------------- Pilot protocol
AssignmentMethod = Literal["randomized", "matched", "observational"]
TrialArm = Literal["control", "intervention"]
BlockOutcomeType = Literal[
    "disease_incidence", "rescue_treatment", "yield", "marketable_packout",
    "cull", "cost", "adverse_event",
]


class PilotProtocolCreate(BaseModel):
    """A versioned reference to the protocol document — not the protocol itself."""
    version: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=200)
    document_reference: str | None = None
    assignment_method: AssignmentMethod
    target: str = Field(min_length=1, max_length=80)
    primary_metric: str = Field(min_length=1, max_length=120)
    secondary_metrics: list[str] | None = None
    effective_from: date
    effective_to: date | None = None

    @model_validator(mode="after")
    def _effective_range_is_ordered(self):
        if self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("effective_to cannot precede effective_from")
        return self


class PilotProtocol(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    farm_id: int
    version: str
    name: str
    document_reference: str | None = None
    assignment_method: str
    target: str
    primary_metric: str
    secondary_metrics: list | None = None
    effective_from: date
    effective_to: date | None = None
    # The only thing that lifts shadow mode, and a recorded event when it does.
    unblinded_at: datetime | None = None
    created_at: datetime


class BlockAssignmentCreate(BaseModel):
    """Randomization happens offline; the seed is recorded so it stays reproducible."""
    block_id: int
    arm: TrialArm
    matched_pair_key: str | None = None
    assigned_on: date
    assigned_by: str | None = None
    assignment_seed: str | None = None


class BlockAssignment(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    pilot_protocol_id: int
    block_id: int
    arm: str
    matched_pair_key: str | None = None
    assigned_on: date
    assigned_by: str | None = None
    assignment_seed: str | None = None
    created_at: datetime


class BlockOutcomeObservationCreate(BaseModel):
    """A measured outcome for one block. A value without a unit is not a measurement."""
    block_id: int
    pilot_protocol_id: int | None = None
    observed_on: date
    outcome_type: BlockOutcomeType
    value: float | None = None
    unit: str | None = None
    denominator: float | None = Field(default=None, gt=0)
    method: str | None = None
    notes: str | None = None
    source_type: str | None = None
    supersedes_id: int | None = None
    # Provenance, so an outcome entered on a demo farm is tagged simulated like
    # every other record there. Without these the schema silently dropped the
    # caller's tag and the ORM default made it look like a real measurement.
    data_source: DataSource | None = "manual_entry"
    data_confidence: DataConfidence | None = "user_provided"

    @model_validator(mode="after")
    def _value_requires_a_unit(self):
        if self.value is not None and not (self.unit or "").strip():
            raise ValueError(
                "a unit is required whenever a value is given — nothing here converts "
                "between units, and an unlabelled number is not a measurement"
            )
        return self


class BlockOutcomeObservation(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    block_id: int
    # Exposed because a caller listing a farm's outcomes has to be able to tell which
    # season each one belongs to. It was persisted and unreadable at first, and the
    # season page's client-side filter silently matched nothing as a result.
    crop_cycle_id: int | None = None
    pilot_protocol_id: int | None = None
    observed_on: date
    recorded_at: datetime
    outcome_type: str
    value: float | None = None
    unit: str | None = None
    denominator: float | None = None
    method: str | None = None
    notes: str | None = None
    source_type: str | None = None
    supersedes_id: int | None = None
    data_source: str | None = None
    data_confidence: str | None = None
    created_at: datetime


# --------------------------------------------------------------------- SprayEvent
class SprayEventBase(BaseModel):
    product_name: str
    # Join key to a product's label record (see models.SprayEvent.epa_reg_no).
    epa_reg_no: str | None = None
    active_ingredient: str | None = None
    moa_group: str | None = None
    pesticide_class: str | None = None
    target_pest_or_disease: str | None = None
    dose: str | None = None
    # Structured applied quantity (entered values; units not normalized/converted).
    rate_amount: float | None = Field(default=None, gt=0)
    rate_unit: str | None = None
    treated_acres: float | None = Field(default=None, gt=0)
    application_date: date
    cost: float | None = None
    pre_harvest_interval_days: int | None = None
    re_entry_interval_hours: int | None = None
    field_block: str | None = None
    # Optional link to a real Block. Never inferred from `field_block`.
    block_id: int | None = None
    external_record_id: str | None = None
    source_system: str | None = None
    source_filename: str | None = None
    notes: str | None = None
    # Default = a real manual entry. (Explicit None used to fall through to the ORM
    # column default "demo"/"simulated", silently tagging real API records as demo.)
    data_source: DataSource | None = "manual_entry"
    data_confidence: DataConfidence | None = "user_provided"
    pilot_import_batch_id: int | None = None


class SprayEventCreate(SprayEventBase):
    pass


class SprayEvent(SprayEventBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    farm_id: int
    # Server-derived from Farm.area_unit, never client-supplied: what unit
    # `treated_acres` is actually in. None = never declared, not "assume acres".
    treated_area_unit: str | None = None
    # The purchase order whose delivered input this application consumed, when it
    # was procured through Inputs & finance (derived; None for everything else —
    # most applications are NOT procured through Lumos and carry no link).
    source_order_id: int | None = None


# --------------------------------------------------------------- ScoutObservation
class ScoutObservationBase(BaseModel):
    observation_date: date
    crop_stage: str | None = None
    visible_issue: str | None = None
    severity_1_to_5: int | None = Field(default=None, ge=1, le=5)
    image_url_optional: str | None = None
    notes: str | None = None
    # Pilot CSV-import provenance (all optional).
    external_record_id: str | None = None
    field_block: str | None = None
    # Optional link to a real Block. Never inferred from `field_block`.
    block_id: int | None = None
    severity_scale: str | None = None
    count_value: float | None = None
    observer: str | None = None
    source_system: str | None = None
    source_filename: str | None = None
    # Default = a real manual entry (see SprayEventBase for why not None).
    data_source: DataSource | None = "manual_entry"
    data_confidence: DataConfidence | None = "user_provided"
    pilot_import_batch_id: int | None = None


class ScoutObservationCreate(ScoutObservationBase):
    pass


class ScoutObservation(ScoutObservationBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    farm_id: int


# ------------------------------------------------------------- Photo analysis
class PhotoObservationSuggestion(BaseModel):
    """A draft scouting observation pre-filled from a photo, for human confirmation."""
    observation_date: str
    visible_issue: str | None = None
    severity_1_to_5: int | None = None
    crop_stage: str | None = None
    notes: str | None = None
    data_source: str = "photo_ai"
    data_confidence: str = "user_provided"


class PhotoAnalysisResult(BaseModel):
    """Result of analysing one uploaded field photo (decision support, not a diagnosis)."""
    detected_issue: str | None = None
    suggested_severity: int | None = None
    confidence: str = "low"
    observations: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    model: str = ""
    is_ai_generated: bool = True
    is_mock: bool = False
    disclaimer: str = ""
    suggested_observation: PhotoObservationSuggestion


# ----------------------------------------------------------------- PlannedSpray
# Decision outcomes (mirrors app/decision_engine.py).
DecisionOutcome = Literal[
    "approve", "block", "delay", "inspect_first", "pca_review_required"
]
# Recorded real-world outcomes. Applied outcomes (sprayed_as_planned / changed_product)
# create the linked SprayEvent; the others document a non-application honestly.
# CANONICAL LIST: decision_status.PLANNED_SPRAY_OUTCOMES. Spelled out here because a
# Literal cannot be built from a runtime tuple readably; test_invariants asserts parity.
PlannedSprayOutcome = Literal[
    "sprayed_as_planned", "changed_product", "delayed", "avoided", "inspected_first"
]
ReviewAction = Literal["approved", "edited", "rejected"]
# Who supplied the PHI/REI values for the check. "verified_label" is deliberately NOT
# accepted from clients — nothing can claim label verification until label data exists.
ValuesSource = Literal["grower_entered", "pca_entered"]


class PlannedSprayCreate(BaseModel):
    """An intended spray to check *before* it happens (pre-spray decision point)."""
    intended_date: date
    product_name: str
    active_ingredient: str | None = None
    target_pest_or_disease: str | None = None
    pre_harvest_interval_days: int | None = Field(default=None, ge=0)
    re_entry_interval_hours: int | None = Field(default=None, ge=0)
    estimated_cost: float | None = None
    # Real-record / import fields (all optional).
    external_record_id: str | None = None
    field_block: str | None = None
    # Optional link to a real Block. Never inferred from `field_block`.
    block_id: int | None = None
    crop: str | None = None
    treated_acres: float | None = Field(default=None, gt=0)
    epa_reg_no: str | None = None
    moa_group: str | None = None
    rate_amount: float | None = Field(default=None, gt=0)
    rate_unit: str | None = None
    recommendation_author: str | None = None
    source_system: str | None = None
    source_filename: str | None = None
    notes: str | None = None
    values_source: ValuesSource = "grower_entered"
    values_entered_by: str | None = None
    data_source: DataSource = "manual_entry"
    data_confidence: DataConfidence = "user_provided"


class PlannedSprayReviewUpdate(BaseModel):
    """PCA / agronomist review of a pre-spray decision (approve / edit / reject).

    An edit must include the PCA's replacement guidance and/or structured field edits;
    a rejection must say why. Structured `proposed_*` edits append superseding
    pca_verified input values (the old values are never overwritten — history is an
    append-only supersede chain plus an immutable audit event) and the decision is
    re-evaluated against the updated values.
    """
    action: ReviewAction
    review_comment: str | None = None
    reviewed_by: str | None = None
    pca_next_action: str | None = None
    # Structured field edits (all optional; each appends a pca_verified input value).
    proposed_product_name: str | None = None
    # Product-identity and matching keys. A PCA correcting a mis-entered registration
    # number, crop, MoA group or target is correcting the join keys the label and
    # scouting checks run on, so these need the same superseding provenance trail as a
    # corrected PHI — not a silent edit.
    proposed_epa_reg_no: str | None = None
    proposed_crop: str | None = None
    proposed_moa_group: str | None = None
    proposed_target_pest_or_disease: str | None = None
    proposed_active_ingredient: str | None = None
    proposed_rate_amount: float | None = Field(default=None, gt=0)
    proposed_rate_unit: str | None = None
    proposed_intended_date: date | None = None
    proposed_pre_harvest_interval_days: int | None = Field(default=None, ge=0)
    proposed_re_entry_interval_hours: int | None = Field(default=None, ge=0)
    # Which evidence the reviewer relied on (free text, kept in the audit event).
    relied_on_evidence: str | None = None

    def proposed_field_edits(self) -> dict:
        """Map of planned-spray field -> proposed value (only the ones provided)."""
        mapping = {
            "product_name": self.proposed_product_name,
            "epa_reg_no": self.proposed_epa_reg_no,
            "crop": self.proposed_crop,
            "moa_group": self.proposed_moa_group,
            "target_pest_or_disease": self.proposed_target_pest_or_disease,
            "active_ingredient": self.proposed_active_ingredient,
            "rate_amount": self.proposed_rate_amount,
            "rate_unit": self.proposed_rate_unit,
            "intended_date": self.proposed_intended_date,
            "pre_harvest_interval_days": self.proposed_pre_harvest_interval_days,
            "re_entry_interval_hours": self.proposed_re_entry_interval_hours,
        }
        return {k: v for k, v in mapping.items() if v is not None}

    @model_validator(mode="after")
    def _require_substance(self):
        if self.action == "edited" and not (
            (self.pca_next_action or "").strip() or self.proposed_field_edits()
        ):
            raise ValueError(
                "an 'edited' review needs pca_next_action and/or at least one proposed_* "
                "field edit"
            )
        if self.action == "rejected" and not (self.review_comment or "").strip():
            raise ValueError("review_comment is required when the review action is 'rejected'")
        return self


class PlannedSprayOutcomeUpdate(BaseModel):
    """The grower/PCA's recorded real-world outcome for a planned spray.

    A reason is mandatory for every non-as-planned outcome so the record stays honest.
    `changed_product` must say what was actually applied. `application_date` (applied
    outcomes only) defaults to the intended date. `outcome_date` (when it was decided/
    done) defaults to today's date; chronology is validated server-side — an outcome
    can never predate its check, and an application can never predate its plan.
    """
    outcome: PlannedSprayOutcome
    outcome_reason: str | None = None
    outcome_date: date | None = None
    application_date: date | None = None
    outcome_product_name: str | None = None
    outcome_active_ingredient: str | None = None

    @model_validator(mode="after")
    def _require_reason_and_product(self):
        if self.outcome != "sprayed_as_planned" and not (self.outcome_reason or "").strip():
            raise ValueError(
                "outcome_reason is required for every outcome other than 'sprayed_as_planned'"
            )
        if self.outcome == "changed_product" and not (self.outcome_product_name or "").strip():
            raise ValueError(
                "outcome_product_name is required when the outcome is 'changed_product'"
            )
        return self


class PlannedSprayDecisionRule(BaseModel):
    """One evaluated rule from the decision snapshot (triggered or not)."""
    rule_id: str
    name: str
    triggered: bool
    severity: str
    detail: str
    calculation: str | None = None
    inputs: dict = Field(default_factory=dict)


class PlannedSprayDecision(BaseModel):
    """The explainable pre-spray decision snapshot.

    Not currently used as a response model — the decision reaches clients through the
    untyped `PlannedSpray.decision_payload` dict. It still declares every key the engine
    emits, because wiring this up while it was missing `not_evaluated` or the authority
    fields would silently strip the label-gap disclosure out of the API.
    """
    outcome: str
    severity: str
    confidence: str
    authority_level: str
    authority_basis: str = ""
    rules: list[PlannedSprayDecisionRule] = Field(default_factory=list)
    inputs_used: dict = Field(default_factory=dict)
    missing_information: list[str] = Field(default_factory=list)
    # Label-dependent checks that did NOT run, each with its own reason.
    not_evaluated: list[dict] = Field(default_factory=list)
    required_next_action: str
    review_required: bool
    disclaimer: str


class PlannedSpray(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    farm_id: int
    intended_date: date
    product_name: str
    active_ingredient: str | None = None
    target_pest_or_disease: str | None = None
    pre_harvest_interval_days: int | None = None
    re_entry_interval_hours: int | None = None
    estimated_cost: float | None = None
    external_record_id: str | None = None
    field_block: str | None = None
    block_id: int | None = None
    crop: str | None = None
    treated_acres: float | None = None
    # Server-derived from Farm.area_unit (see SprayEvent.treated_area_unit).
    treated_area_unit: str | None = None
    epa_reg_no: str | None = None
    moa_group: str | None = None
    rate_amount: float | None = None
    rate_unit: str | None = None
    recommendation_author: str | None = None
    source_system: str | None = None
    source_filename: str | None = None
    notes: str | None = None
    pilot_import_batch_id: int | None = None
    values_source: str
    values_entered_by: str | None = None
    decision_outcome: str
    decision_severity: str
    decision_confidence: str
    decision_authority: str
    required_next_action: str
    review_required: bool
    decision_payload: dict | None = None
    check_risk_level: str
    check_text: str
    review_status: str
    review_comment: str | None = None
    reviewed_by: str | None = None
    # Set when an approve/edit was backed by an authorized PCA credential. None means
    # the attribution is an unverified free-text name (the pre-pilot behaviour).
    reviewed_by_credential_id: int | None = None
    reviewed_at: datetime | None = None
    pca_next_action: str | None = None
    outcome: str
    outcome_reason: str | None = None
    outcome_date: date | None = None
    outcome_product_name: str | None = None
    outcome_active_ingredient: str | None = None
    spray_event_id: int | None = None
    data_source: str | None = None
    data_confidence: str | None = None
    created_at: datetime
    # Derived status fields (canonical app/decision_status.py, via ORM properties).
    # The frontend renders these — it must never re-derive review/open semantics.
    review_state: str = "not_required"  # not_required / pending / approved / edited / rejected
    needs_review: bool = False
    applied_outcome_allowed: bool = True
    is_open: bool = True
    open_conflict: bool = False
    # True when the farm's harvest date was edited after this check ran (stale snapshot).
    harvest_date_changed_since_check: bool = False
    # True when the label record this decision cites has since been revised. A stored
    # decision is never silently recomputed, so it has to say when its source moved on.
    label_reference_stale: bool = False
    # Follow-up gating: outcomes other than a clean as-planned application require a
    # follow-up event timeline before anything about them can be called "confirmed".
    follow_up_required: bool = False
    follow_up_event_count: int = 0
    # Composed states (canonical app/decision_status.py). The verdict
    # (decision_outcome) is the immutable historical decision; workflow_state says
    # whether anyone still owes an action, evidence_state whether the documentation
    # story is finished, current_next_action the one concrete step to take NOW
    # (required_next_action stays the engine's check-time instruction).
    workflow_state: str = "needs_action"  # needs_action / awaiting_pca / resolved
    # missing_documentation / complete / follow_up_required / follow_up_in_progress / verified
    evidence_state: str = "missing_documentation"
    # await_pca_review / resolve_conflict / inspect / record_outcome / record_follow_up / none
    current_next_action: str = "record_outcome"
    # May this decision back a purchasable input-plan item? (Inputs & finance;
    # canonical decision_status.procurement_eligible — the UI never re-derives it.)
    procurement_eligible: bool = False
    # Procurement already raised from this decision (newest first) — the UI shows
    # the existing plan/order instead of re-offering "Request supplier quotes".
    procurement_links: list["ProcurementLink"] = Field(default_factory=list)


class ProcurementLink(BaseModel):
    """A compact pointer from a decision to a plan/order raised from it."""
    input_plan_id: int
    plan_status: str
    order_id: int | None = None
    order_status: str | None = None


PlannedSpray.model_rebuild()


# ------------------------------------------------- Decision input provenance
class DecisionInputValue(BaseModel):
    """Field-level provenance row (append-only supersede chain)."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    planned_spray_id: int
    field_name: str
    raw_value: str | None = None
    normalized_value: str | None = None
    unit: str | None = None
    source_type: str
    source_reference: str | None = None
    confidence: str | None = None
    verified_by: str | None = None
    verified_at: datetime | None = None
    effective_date: date | None = None
    supersedes_input_value_id: int | None = None
    created_at: datetime


class DecisionAuditEvent(BaseModel):
    """Immutable audit event on a pre-spray decision (read-only; append-only)."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    planned_spray_id: int
    event_type: str
    actor: str | None = None
    rationale: str | None = None
    system_recommendation: str | None = None
    before: dict | None = None
    after: dict | None = None
    created_at: datetime


# ------------------------------------------------------- Follow-up timeline
class FollowUpEventCreate(BaseModel):
    """One append-only follow-up observation after a recorded outcome.

    Impact fields default to None (i.e. not yet assessed) — an outcome is NEVER
    silently assumed positive; yield/quality stay unknown until someone records them.
    """
    event_type: FollowUpEventType
    observed_at: date
    severity: int | None = Field(default=None, ge=0)
    severity_scale: str | None = None
    actual_product: str | None = None
    actual_rate_amount: float | None = Field(default=None, gt=0)
    actual_rate_unit: str | None = None
    actual_treated_acres: float | None = Field(default=None, gt=0)
    cost: float | None = Field(default=None, ge=0)
    rescue_required: bool | None = None
    yield_impact: ImpactLevel | None = None
    quality_impact: ImpactLevel | None = None
    rejected_or_downgraded: bool | None = None
    evidence_notes: str | None = None
    entered_by: str | None = None
    source_type: InputSourceType = "user_entered"
    source_reference: str | None = None
    confidence: DataConfidence = "user_provided"

    @model_validator(mode="after")
    def _require_substance(self):
        if self.event_type in ("actual_application", "rescue_application") and not (
            self.actual_product or ""
        ).strip():
            raise ValueError(
                "actual_product is required for actual_application / rescue_application "
                "events"
            )
        if self.event_type == "scouting_observation" and self.severity is None:
            raise ValueError("severity is required for scouting_observation events")
        return self


class FollowUpEvent(FollowUpEventCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    planned_spray_id: int
    created_at: datetime


# ---------------------------------------------------------- AI judgment log
class AiJudgment(BaseModel):
    """Append-only record of one AI output (read-only; never edited or deleted)."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: str
    farm_id: int | None = None
    planned_spray_id: int | None = None
    model_id: str
    prompt_version: str
    input_digest: str
    output: dict | None = None
    confidence: str
    abstained: bool
    abstain_reason: str | None = None
    is_mock: bool
    created_at: datetime


# ------------------------------------------------- Row import (AI extraction commit)
class RowImportRequest(BaseModel):
    """Commit path for human-reviewed extracted rows (and any pre-structured rows).

    Rows are re-validated server-side with the SAME validation/duplicate detection as
    the CSV import before anything is written; dry_run previews without writing.
    """
    record_type: ImportRecordType
    rows: list[dict]
    dry_run: bool = True
    date_format: ImportDateFormat = "auto"
    source_label: str | None = None
    source_filename: str | None = None
    imported_by: str | None = None
    notes: str | None = None
    # Links committed rows back to the extraction judgment they came from.
    ai_judgment_id: int | None = None


# ------------------------------------------------------- Ingestion (operator)
class IngestionRunRequest(BaseModel):
    """Ask for one ingestion run over one window.

    `station_id` is REQUIRED and never inferred. Resolution in the pipeline is
    deterministic precisely because the operator names farm, field and station up
    front — a reading from a station nobody asked for is recorded as an issue rather
    than silently joined to whatever field looked closest.

    Note that `field_id` is optional but effectively required in practice: a run whose
    field has no centroid drops every row with `no_field_geolocation`, because a NULL
    station distance reads downstream as "in range and close".
    """
    farm_id: int
    station_id: str = Field(min_length=1)
    field_id: int | None = None
    lookback_hours: int = Field(default=6, ge=1, le=24 * 90)


# ------------------------------------------------------- CSV pilot import
class CsvImportRequest(BaseModel):
    """CSV pilot import (dry-run by default — nothing is written until dry_run=False).

    `mapping` optionally overrides the auto-detected header->field mapping
    (header text -> canonical field name, or "ignore" to drop a column).
    """
    record_type: ImportRecordType
    csv_text: str
    mapping: dict[str, str] | None = None
    dry_run: bool = True
    # How slash dates are read; "auto" errors on ambiguous m/d-vs-d/m rows instead
    # of guessing (a wrong guess silently shifts PHI/REI math by months).
    date_format: ImportDateFormat = "auto"
    source_system: str | None = None
    source_filename: str | None = None
    imported_by: str | None = None
    notes: str | None = None


# ------------------------------------------------------------------ Pilot events
PilotEventType = Literal[
    "check_started", "check_completed", "check_abandoned",
    "review_recorded", "outcome_recorded", "import_used",
]


class PilotEventCreate(BaseModel):
    """One workflow-telemetry event (fire-and-forget from the UI or logged server-side)."""
    event_type: PilotEventType
    farm_id: int | None = None
    planned_spray_id: int | None = None
    entry_source: str | None = None
    meta: dict | None = None


class PilotEvent(PilotEventCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime


# ---------------------------------------------------------------- Recommendation
class RecommendationUpdate(BaseModel):
    """Agronomist review action."""
    agronomist_status: str | None = None  # pending / approved / rejected / edited
    agronomist_comment: str | None = None
    recommendation_text: str | None = None


class Recommendation(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    farm_id: int
    created_at: datetime
    risk_level: str
    next_action: str
    recommendation_text: str
    agronomist_status: str
    agronomist_comment: str | None = None


# --------------------------------------------------------------- Spray baseline
# Defined above the pilot intake because PilotFarmIntake embeds SprayBaselineCreate:
# the baseline is captured during onboarding, not bolted on afterwards.
BaselineMethod = Literal["stated_cadence", "prior_period", "calendar_program"]
CalendarProgram = Literal[
    "weekly", "every_10_days", "biweekly", "every_3_weeks", "monthly"
]


class SprayBaselineCreate(BaseModel):
    """A grower/PCA-declared baseline to measure reduction against (one per farm)."""
    method: BaselineMethod
    cadence_days: int | None = Field(default=None, gt=0)
    season_spray_count: int | None = Field(default=None, gt=0)
    baseline_period_start: date | None = None
    baseline_period_end: date | None = None
    calendar_program: CalendarProgram | None = None
    data_source: DataSource = "grower_interview"
    data_confidence: DataConfidence = "user_provided"
    declared_by: str | None = None
    notes: str | None = None


class SprayBaseline(SprayBaselineCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    farm_id: int
    created_at: datetime


# ---------------------------------------------------------------- Pilot intake
class PilotSprayEvent(BaseModel):
    """A spray line in the pilot-farm intake bundle (all fields optional but product)."""
    product_name: str
    active_ingredient: str | None = None
    application_date: date | None = None
    cost: float | None = None
    pre_harvest_interval_days: int | None = None
    re_entry_interval_hours: int | None = None


class PilotFarmIntake(BaseModel):
    """One-shot intake: create a farm plus its last few sprays and a scouting concern."""
    name: str
    location: str | None = None
    country: str = "US"
    crop_type: str = "strawberry"
    greenhouse_area: float | None = None
    expected_harvest_date: date | None = None
    advisor_involved: bool | None = None
    spray_events: list[PilotSprayEvent] = Field(default_factory=list)
    scouting_concern: str | None = None
    scouting_severity_1_to_5: int | None = Field(default=None, ge=1, le=5)
    # Captured at intake because reduction is unmeasurable without it, and asking a
    # grower "how often did you spray last season?" is a 20-second question during
    # onboarding and an awkward one six weeks later. Optional: a farm with no baseline
    # is still a valid farm, it just cannot produce a reduction figure — compute_reduction
    # returns its "No baseline captured yet" empty result rather than guessing.
    # Declared here rather than defaulted: `SprayBaselineCreate.data_confidence` is
    # "user_provided", which is in reduction._TRUSTED_CONFIDENCE, so an intake-captured
    # baseline can back a headline figure. That is only honest because a human typed it.
    spray_baseline: SprayBaselineCreate | None = None


# ----------------------------------------------------- Concierge pilot import
class PilotImportSpray(BaseModel):
    """A spray line in a concierge import (manually transcribed from a call/sheet/chat)."""
    product_name: str
    active_ingredient: str | None = None
    application_date: date | None = None
    cost: float | None = None
    pre_harvest_interval_days: int | None = None
    re_entry_interval_hours: int | None = None
    target_pest_or_disease: str | None = None
    notes: str | None = None


class PilotImportScouting(BaseModel):
    """A scouting line in a concierge import."""
    observation_date: date | None = None
    crop_stage: str | None = None
    visible_issue: str | None = None
    severity_1_to_5: int | None = Field(default=None, ge=1, le=5)
    notes: str | None = None


class PilotImport(BaseModel):
    """Manual/concierge pilot data captured from grower/PCA conversations.

    Not an automated integration — a human transcribes what they heard/collected.
    """
    source_label: str
    data_source: DataSource = "manual_entry"
    data_confidence: DataConfidence = "user_provided"
    imported_by: str | None = None
    notes: str | None = None
    spray_events: list[PilotImportSpray] = Field(default_factory=list)
    scouting_observations: list[PilotImportScouting] = Field(default_factory=list)


# ----------------------------------------------------------------- PCA policy
class PcaPolicyCreate(BaseModel):
    """A PCA-entered action threshold: treat <target> only when scouting severity
    >= <min_severity_to_treat>. Always attributed — Lumos never invents thresholds."""
    target_pest_or_disease: str
    min_severity_to_treat: int = Field(ge=1, le=5)
    entered_by: str | None = None
    notes: str | None = None
    data_source: DataSource = "manual_entry"
    data_confidence: DataConfidence = "user_provided"


class PcaPolicy(PcaPolicyCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    farm_id: int
    created_at: datetime


# -------------------------------------------------------------- Pilot feedback
class PilotFeedbackCreate(BaseModel):
    person_type: str  # grower / PCA / agronomist / exporter / input_supplier / other
    crop: str | None = None
    region: str | None = None
    current_records_method: str | None = None
    biggest_pain: str | None = None
    would_use_real_data: str | None = None  # yes / no / maybe
    would_pay: str | None = None            # yes / no / maybe
    requested_pilot: bool | None = None
    notes: str | None = None


class PilotFeedback(PilotFeedbackCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime


# ------------------------------------------------------------ Inputs & finance
# Phase 1 procurement (RFQ model, concierge-operated, simulated/no-real-money).
# Status vocabularies mirror app/procurement_status.py — the single source of truth.
InputCategory = Literal[
    "fungicide", "insecticide", "herbicide", "miticide", "fertilizer", "adjuvant",
    "other",
]
QuoteAvailability = Literal["in_stock", "partial", "backordered", "unknown"]
QuoteVerification = Literal["concierge_entered", "supplier_confirmed"]
# "selected", never "accepted": choosing indicative terms is not an approval,
# not funding, and not a binding agreement.
FinancingDecisionAction = Literal["selected", "declined"]
# Only these are postable via the generic concierge order-events endpoint;
# created/quote_selected/financing_selected are written by order creation, and
# input_applied has its own endpoint (delivery must never imply application).
ConciergeOrderEventType = Literal[
    "supplier_confirmed", "shipped", "delivered", "partially_delivered",
    "cancelled", "exception_reported",
]

class InputPlanItemCreate(BaseModel):
    """One input to be quoted. Product fields are a snapshot; `planned_spray_id`
    links the source decision (crud enforces procurement eligibility)."""
    planned_spray_id: int | None = None
    field_block: str | None = None
    crop: str | None = None
    category: InputCategory = "other"
    product_name: str
    active_ingredient: str | None = None
    moa_group: str | None = None
    quantity: float = Field(gt=0)
    unit: str
    acres: float | None = Field(default=None, gt=0)
    needed_by_date: date
    intended_use: str | None = None
    estimated_cost: float | None = Field(default=None, ge=0)
    notes: str | None = None
    created_by: str | None = None
    data_source: DataSource = "manual_entry"
    data_confidence: DataConfidence = "user_provided"


class InputPlanItem(InputPlanItemCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    input_plan_id: int
    created_at: datetime
    # Derived from the linked decision ("not_linked" for manual items) — the UI
    # never re-derives review/eligibility semantics.
    source_decision_review_state: str = "not_linked"
    source_decision_procurement_eligible: bool | None = None


class InputPlanCreate(BaseModel):
    """A new draft input plan (the plan IS the RFQ), optionally with initial items."""
    requested_by: str | None = None
    notes: str | None = None
    financing_requested: bool = False
    financing_requested_by: str | None = None
    financing_notes: str | None = None
    data_source: DataSource = "manual_entry"
    data_confidence: DataConfidence = "user_provided"
    items: list[InputPlanItemCreate] = Field(default_factory=list)


class FinancingOfferCreate(BaseModel):
    """A manually entered INDICATIVE financing offer (concierge only, Phase 1).

    Never an approval: offers are created `indicative`; internal-consistency
    checks keep the arithmetic honest (financed = requested - down payment,
    repayment >= financed).
    """
    provider_name: str
    requested_amount: float = Field(ge=0)
    down_payment: float = Field(default=0.0, ge=0)
    financed_amount: float = Field(ge=0)
    total_repayment: float = Field(ge=0)
    fees_total: float = Field(default=0.0, ge=0)
    schedule_summary: str | None = None
    expires_on: date | None = None
    required_documents: str | None = None
    conditions: str | None = None
    entered_by: str | None = None
    notes: str | None = None
    data_source: DataSource = "manual_entry"
    data_confidence: DataConfidence = "user_provided"

    @model_validator(mode="after")
    def _amounts_consistent(self):
        if abs(self.financed_amount - (self.requested_amount - self.down_payment)) > 0.01:
            raise ValueError(
                "financed_amount must equal requested_amount minus down_payment"
            )
        if self.total_repayment < self.financed_amount:
            raise ValueError("total_repayment cannot be less than financed_amount")
        return self


class FinancingOffer(FinancingOfferCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    supplier_quote_id: int
    status: str
    decided_by: str | None = None
    decided_at: datetime | None = None
    decision_notes: str | None = None
    created_at: datetime
    # Derived (expiry is never stored, so a stale offer can't claim to be live).
    offer_state: str = "indicative"
    disclaimer: str = FINANCING_OFFER_DISCLAIMER


class FinancingOfferDecision(BaseModel):
    """The grower's one-shot select/decline of an indicative offer.

    Selecting records a preference for INDICATIVE terms only — it is not a loan
    approval, implies no lender confirmation, and moves no money.
    """
    action: FinancingDecisionAction
    actor: str | None = None
    notes: str | None = None


class SupplierQuoteItemCreate(BaseModel):
    """One quoted line answering one requested input-plan item."""
    input_plan_item_id: int
    product_name: str
    # The catalogue link (2026-08-07). Optional, because a supplier may quote something
    # nobody has catalogued yet and blocking the quote over it would be worse. But
    # WITHOUT this field the catalogue is decorative: `product_name` is free text, so an
    # unlinked line can never enter a price comparison — see
    # procurement_analytics.build_report, which counts unlinked lines rather than
    # bucketing them by name.
    input_product_id: int | None = None
    is_substitution: bool = False
    substitution_reason: str | None = None
    quantity: float = Field(gt=0)
    unit: str
    unit_price: float = Field(ge=0)
    notes: str | None = None

    @model_validator(mode="after")
    def _require_substitution_reason(self):
        if self.is_substitution and not (self.substitution_reason or "").strip():
            raise ValueError(
                "substitution_reason is required when is_substitution is true"
            )
        return self


class SupplierQuoteItem(SupplierQuoteItemCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    supplier_quote_id: int
    line_total: float = 0.0


class SupplierQuoteCreate(BaseModel):
    """A concierge-entered supplier quote (Phase 1 has no supplier portal).

    Quotes are never edited — withdraw and re-enter is the correction path.
    """
    supplier_name: str
    # The structured link (2026-08-07). `supplier_name` above stays authoritative for
    # what was actually entered; this is optional so a quote from a supplier nobody has
    # registered still goes in, rather than being blocked or attached to a guess.
    supplier_id: int | None = None
    supplier_contact: str | None = None
    delivery_cost: float = Field(default=0.0, ge=0)
    fees: float = Field(default=0.0, ge=0)
    payment_terms_cash: str | None = None
    expected_delivery_date: date | None = None
    availability: QuoteAvailability = "unknown"
    expires_on: date | None = None
    verification: QuoteVerification = "concierge_entered"
    notes: str | None = None
    entered_by: str | None = None
    data_source: DataSource = "manual_entry"
    data_confidence: DataConfidence = "user_provided"
    items: list[SupplierQuoteItemCreate] = Field(min_length=1)


class SupplierQuote(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    input_plan_id: int
    supplier_name: str
    supplier_contact: str | None = None
    status: str
    delivery_cost: float
    fees: float
    payment_terms_cash: str | None = None
    expected_delivery_date: date | None = None
    availability: str
    expires_on: date | None = None
    verification: str
    notes: str | None = None
    entered_by: str | None = None
    data_source: str | None = None
    data_confidence: str | None = None
    created_at: datetime
    items: list[SupplierQuoteItem] = Field(default_factory=list)
    financing_offers: list[FinancingOffer] = Field(default_factory=list)
    # Derived server-side so comparison math can never drift between surfaces.
    items_subtotal: float = 0.0
    total_cost: float = 0.0
    quote_state: str = "submitted"


class InputPlan(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    farm_id: int
    status: str
    requested_by: str | None = None
    notes: str | None = None
    financing_requested: bool = False
    financing_requested_by: str | None = None
    financing_notes: str | None = None
    submitted_at: datetime | None = None
    submitted_by: str | None = None
    cancelled_at: datetime | None = None
    cancelled_reason: str | None = None
    selected_quote_id: int | None = None
    selected_by: str | None = None
    selection_reason: str | None = None
    data_source: str | None = None
    data_confidence: str | None = None
    created_at: datetime
    items: list[InputPlanItem] = Field(default_factory=list)
    # Derived (canonical app/procurement_status.py, via ORM properties).
    financing_state: str = "cash"
    quote_count: int = 0
    order_id: int | None = None
    needed_by: date | None = None
    overdue: bool = False


class InputPlanEvent(BaseModel):
    """One append-only plan audit event (see models.InputPlanEvent)."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    input_plan_id: int
    event_type: str
    occurred_on: date
    actor: str | None = None
    notes: str | None = None
    payload: dict | None = None
    data_source: str | None = None
    data_confidence: str | None = None
    created_at: datetime


class InputPlanDetail(InputPlan):
    """Plan + everything needed to compare quotes and see the order (detail page)."""
    quotes: list[SupplierQuote] = Field(default_factory=list)
    order: "PurchaseOrder | None" = None
    events: list[InputPlanEvent] = Field(default_factory=list)


class InputPlanSubmit(BaseModel):
    submitted_by: str | None = None


class InputPlanCancel(BaseModel):
    reason: str
    actor: str | None = None


class SelectQuoteRequest(BaseModel):
    """Selecting a quote requires saying WHY — the reason is entered by the human
    (grower or concierge operator), stored, audited, and exported; it is never
    inferred from the numbers."""
    supplier_quote_id: int
    selected_by: str | None = None
    reason: str = Field(min_length=3)


class PurchaseOrderCreate(BaseModel):
    placed_by: str | None = None
    notes: str | None = None


class OrderEvent(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    purchase_order_id: int
    event_type: str
    occurred_on: date
    actor: str | None = None
    notes: str | None = None
    payload: dict | None = None
    data_source: str | None = None
    data_confidence: str | None = None
    created_at: datetime


class OrderEventCreate(BaseModel):
    """A concierge-posted order lifecycle event (append-only; transition-guarded).

    input_applied is deliberately NOT postable here — linking an application
    requires the explicit input-applied endpoint so delivery can never be
    conflated with application.
    """
    event_type: ConciergeOrderEventType
    occurred_on: date
    actor: str | None = None
    notes: str | None = None


class InputAppliedRequest(BaseModel):
    """Explicit link from a delivered order to the actual application record.

    Exactly one of spray_event_id / planned_spray_id must be provided; the
    referenced planned spray must have an applied outcome.
    """
    spray_event_id: int | None = None
    planned_spray_id: int | None = None
    actor: str | None = None
    occurred_on: date | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _require_exactly_one_reference(self):
        if (self.spray_event_id is None) == (self.planned_spray_id is None):
            raise ValueError(
                "provide exactly one of spray_event_id or planned_spray_id"
            )
        return self


class PurchaseOrder(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    farm_id: int
    input_plan_id: int
    selected_quote_id: int
    accepted_financing_offer_id: int | None = None
    status: str
    spray_event_id: int | None = None
    applied_planned_spray_id: int | None = None
    placed_by: str | None = None
    notes: str | None = None
    data_source: str | None = None
    data_confidence: str | None = None
    created_at: datetime
    # Derived from the selected quote (order lines ARE the quote's lines).
    supplier_name: str | None = None
    total_cost: float | None = None
    # Derived (procurement_status.procurement_overdue) — never stored.
    overdue: bool = False


class PurchaseOrderDetail(PurchaseOrder):
    """Order + derived lines, financing, and the append-only event timeline."""
    selected_quote: SupplierQuote | None = None
    accepted_financing_offer: FinancingOffer | None = None
    events: list[OrderEvent] = Field(default_factory=list)


InputPlanDetail.model_rebuild()


# ------------------------------------------------------------- pesticide labels
# Read models only in this phase. There is deliberately no client-facing schema that
# can set `source_tier="pca_verified_transcription"` or write a verification: promotion
# to label-verified happens through an attributed PCA act (Phase 4), never a request field.
class ProductLabelVerification(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    product_label_record_id: int
    farm_id: int
    verified_by_credential_id: int
    verified_by: str | None = None
    verified_at: datetime
    attestation: str
    revoked_at: datetime | None = None
    data_source: str | None = None
    data_confidence: str | None = None


class ProductLabelRecord(BaseModel):
    """One label's directions for one registered crop (append-only).

    Every regulatory field may be null because a real label states some and not others.
    Null means the label is SILENT on that value — never that there is no limit.
    """
    model_config = ConfigDict(from_attributes=True)
    id: int
    product_id: int
    registered_crop: str
    registered_crop_normalized: str
    target_pest_or_disease: str | None = None
    pre_harvest_interval_days: int | None = None
    re_entry_interval_hours: int | None = None
    max_seasonal_rate_amount: float | None = None
    max_seasonal_rate_unit: str | None = None
    max_applications_per_season: int | None = None
    min_retreatment_interval_days: int | None = None
    label_version: str | None = None
    label_effective_date: date | None = None
    source_tier: LabelSourceTier
    source_document_reference: str | None = None
    source_section_or_page: str | None = None
    source_snippet: str | None = None
    transcribed_by: str | None = None
    transcribed_at: datetime | None = None
    transcription_digest: str | None = None
    withdrawal_reason: str | None = None
    supersedes_label_record_id: int | None = None
    created_at: datetime
    verifications: list[ProductLabelVerification] = Field(default_factory=list)


class PesticideProduct(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    epa_reg_no: str
    epa_reg_no_normalized: str
    epa_reg_base: str
    product_name: str
    registrant: str | None = None
    active_ingredient: str | None = None
    active_ingredient_concentration_amount: float | None = None
    active_ingredient_concentration_unit: str | None = None
    moa_group: str | None = None
    registered_crops_transcription_complete: bool
    notes: str | None = None
    created_at: datetime
    label_records: list[ProductLabelRecord] = Field(default_factory=list)


class LabelSyncResult(BaseModel):
    """What `crud.sync_transcribed_labels` did. Idempotent: re-running changes nothing.

    `unchanged` is the interesting number on a second run — a loader that reported
    "created" every time would be issuing UPDATEs against an append-only table.
    """
    transcribed_entries: int
    products_created: int
    records_created: int
    records_superseded: int
    unchanged: int
    notes: list[str] = Field(default_factory=list)


class ProductLabelRecordCreate(BaseModel):
    """One human-reviewed label use, committed from an AI extraction.

    There is deliberately NO `source_tier` field. The server sets
    `ai_extracted_unverified` — a client cannot declare its own row verified, which
    is the same rule that keeps `authoritative_provider` unreachable from a request.

    Every regulatory value is optional and every one means "the label is silent"
    when omitted. `source_snippet` and `source_document_reference` are required
    because a value nobody can trace back to a document cannot later be promoted:
    `label_data.promotable_to_authoritative` would refuse it anyway, so accepting a
    row without them would only store something permanently unusable.
    """
    epa_reg_no: str = Field(min_length=1)
    product_name: str = Field(min_length=1)
    registrant: str | None = None
    registered_crop: str = Field(min_length=1)
    target_pest_or_disease: str | None = None

    pre_harvest_interval_days: int | None = Field(default=None, ge=0)
    re_entry_interval_hours: int | None = Field(default=None, ge=0)
    max_seasonal_rate_amount: float | None = Field(default=None, gt=0)
    max_seasonal_rate_unit: str | None = None
    max_applications_per_season: int | None = Field(default=None, ge=0)
    min_retreatment_interval_days: int | None = Field(default=None, ge=0)

    active_ingredient: str | None = None
    active_ingredient_concentration_amount: float | None = Field(default=None, gt=0)
    active_ingredient_concentration_unit: str | None = None
    moa_group: str | None = None

    label_version: str = Field(min_length=1)
    label_effective_date: date
    source_document_reference: str = Field(min_length=1)
    source_section_or_page: str | None = None
    source_snippet: str = Field(min_length=1)
    reviewed_by: str = Field(min_length=1)
    # The AI judgment this row was reviewed from, when it came from an extraction.
    ai_judgment_id: int | None = None

    @model_validator(mode="after")
    def _require_a_regulatory_value(self):
        if not any(
            getattr(self, name) is not None
            for name in (
                "pre_harvest_interval_days", "re_entry_interval_hours",
                "max_seasonal_rate_amount", "max_applications_per_season",
                "min_retreatment_interval_days",
            )
        ):
            raise ValueError(
                "a label record that states no regulatory value has nothing to "
                "contribute to a decision — omit the row instead"
            )
        if (self.max_seasonal_rate_amount is None) != (self.max_seasonal_rate_unit is None):
            raise ValueError(
                "max_seasonal_rate_amount and max_seasonal_rate_unit must be given "
                "together — a rate without its unit cannot be compared to anything"
            )
        return self


class ProductLabelVerificationCreate(BaseModel):
    """A licensed PCA attesting that one stored label record matches the document.

    `verified_by` is absent on purpose: the attribution comes from the presented
    credential, never from a client-supplied name. An attestation is required and
    must be substantive — "ok" is not a professional act anyone can audit.
    """
    product_label_record_id: int
    attestation: str = Field(min_length=10)


class LabelResolution(BaseModel):
    """What a given (registration number, crop) resolves to today, and why not, if not.

    A diagnostic, deliberately shaped around the REASONS rather than the values: the
    question an operator actually has is "why is this decision still saying the label
    check did not run", and every unresolved case here answers it with the same sentence
    the decision record shows. `promotable` false with a resolved record is the normal
    state for a fresh transcription — it means the values exist but no licensed PCA has
    verified them against the primary document for this farm yet.
    """
    epa_reg_no: str | None = None
    crop: str | None = None
    farm_id: int | None = None
    product: PesticideProduct | None = None
    label_record: ProductLabelRecord | None = None
    # Why no record resolved. None when one did.
    unresolved_reason: str | None = None
    # Whether the resolved record may back a decision as label-verified, and why not.
    promotable: bool = False
    promotion_blocked_reason: str | None = None


# --------------------------------------------------------------- Marketplace
# Added 2026-08-07. Note what is absent from every schema here: no price on a
# catalogue entry, no rating on a supplier, no ranking field anywhere.
class SupplierCreate(BaseModel):
    """Register a supplier. `canonical_name` is derived server-side, never supplied."""
    name: str = Field(min_length=1, max_length=200)
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    service_area: str | None = None
    status: Literal["active", "inactive"] = "active"
    notes: str | None = None
    data_source: DataSource = "manual_entry"
    data_confidence: DataConfidence = "user_provided"


class Supplier(SupplierCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    canonical_name: str | None = None
    created_at: datetime


class InputProductCreate(BaseModel):
    """A catalogue product. `canonical_key` is derived server-side."""
    category: Literal[
        "seed", "fertilizer", "crop_protection", "biological", "adjuvant", "other"
    ]
    name: str = Field(min_length=1, max_length=200)
    manufacturer: str | None = None
    pesticide_product_id: int | None = None
    unit_of_sale: str | None = None
    notes: str | None = None
    data_source: DataSource = "manual_entry"
    data_confidence: DataConfidence = "user_provided"


class InputProduct(InputProductCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    canonical_key: str | None = None
    created_at: datetime


class SupplierProductCreate(BaseModel):
    """A supplier offers a catalogue product. Deliberately carries NO price — a price
    belongs to a quote, at a moment, for a quantity; on a catalogue row it would be a
    list price nobody quoted that goes stale invisibly."""
    input_product_id: int
    supplier_sku: str | None = None
    pack_size: str | None = None
    typical_lead_time_days: int | None = Field(default=None, gt=0)
    notes: str | None = None


class SupplierProduct(SupplierProductCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    supplier_id: int
    created_at: datetime


class RfqTransmissionRequest(BaseModel):
    """Which suppliers to send an RFQ to. Named explicitly — never auto-selected, since
    choosing recipients on the grower's behalf is a form of ranking."""
    supplier_ids: list[int] = Field(min_length=1)
    requested_by: str | None = None


class RfqTransmission(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    input_plan_id: int
    supplier_id: int | None = None
    sent_to: str | None = None
    transport: str
    status: str
    detail: str | None = None
    requested_by: str | None = None
    created_at: datetime


# ------------------------------------------------------- Finance persistence
# Every assessment schema carries BOTH the outcome fields and the refusal fields, all
# optional, because a stored row is one or the other. No schema here has a field that
# could hold an approval, a premium, a rate or a disbursement.
class CollateralAssetCreate(BaseModel):
    """Register or revalue a collateral asset. Append-only: revaluation supersedes."""
    collateral_type: Literal[
        "standing_crop", "harvested_inventory", "equipment", "land", "receivable"
    ]
    currency: str = Field(min_length=3, max_length=3)
    description: str | None = None
    assessed_value: float | None = Field(default=None, gt=0)
    valuation_basis: str | None = None
    valued_on: date | None = None
    land_parcel_id: int | None = None
    supersedes_id: int | None = None
    registered_by: str | None = None
    data_source: DataSource = "manual_entry"
    data_confidence: DataConfidence = "user_provided"

    @model_validator(mode="after")
    def _value_requires_a_basis(self):
        """60% of an insured value and 60% of a market estimate are different numbers."""
        if self.assessed_value is not None and not (self.valuation_basis or "").strip():
            raise ValueError(
                "valuation_basis is required whenever assessed_value is given: an "
                "advance rate assumes a basis, and applying one to a value from a "
                "different basis is wrong in a way the output would not show"
            )
        return self


class CollateralAsset(CollateralAssetCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    farm_id: int
    created_at: datetime


class CreditAssessment(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    farm_id: int
    as_of: datetime
    scorecard_lender: str | None = None
    scorecard_name: str | None = None
    scorecard_version: str | None = None
    total: float | None = None
    minimum_score: float | None = None
    maximum_score: float | None = None
    inputs_digest: str | None = None
    factors: list | None = None
    refusal_code: str | None = None
    refusal_detail: str | None = None
    assessed_by: str | None = None
    created_at: datetime


class UnderwritingDecision(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    farm_id: int
    as_of: datetime
    credit_assessment_id: int | None = None
    policy_lender: str | None = None
    policy_version: str | None = None
    outcome: str | None = None
    rules: list | None = None
    failed_rule_ids: list | None = None
    not_evaluated_rule_ids: list | None = None
    refusal_code: str | None = None
    refusal_detail: str | None = None
    decided_by: str | None = None
    created_at: datetime


class UnderwritingRequest(BaseModel):
    exposure_amount: float | None = Field(default=None, gt=0)
    evidence_keys: list[str] = Field(default_factory=list)
    decided_by: str | None = None


class MonitoringSnapshot(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    farm_id: int
    as_of: datetime
    lender: str | None = None
    facility_reference: str | None = None
    standing: str | None = None
    covenants: list | None = None
    breached_covenant_ids: list | None = None
    unevaluated_covenant_ids: list | None = None
    refusal_code: str | None = None
    refusal_detail: str | None = None
    created_at: datetime


class CoverageAssessmentRequest(BaseModel):
    crop: str
    peril: str
    evidence_keys: list[str] = Field(default_factory=list)
    assessed_by: str | None = None


class CoverageAssessment(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    farm_id: int
    as_of: datetime
    crop: str | None = None
    peril: str | None = None
    products: list | None = None
    refusal_code: str | None = None
    refusal_detail: str | None = None
    assessed_by: str | None = None
    created_at: datetime


# --------------------------------------------------- Crop cycles (the season)
# `CropCycle` and `Operation` have existed in models.py since the entity-spine
# phase with no route and no writer. These are the schemas that make the season
# reachable, so decisions, applications, costs and harvest outcomes can hang off
# the economic unit they belong to.
CropCycleStatus = Literal[
    "planned", "planted", "growing", "harvesting", "closed", "abandoned"
]
OperationType = Literal[
    "planting", "irrigation", "fertilization", "crop_protection", "scouting",
    "harvest", "tillage", "other",
]
# A lightweight grouping for the season's cost breakdown. Eight buckets, chosen to be
# the ones a grower would name out loud — not a chart of accounts.
CostCategory = Literal[
    "crop_protection", "fertilizer_nutrition", "irrigation", "labor",
    "equipment_operations", "planting_materials", "harvest_postharvest", "other",
]
# Defaulted from the operation type ONLY where the mapping is unambiguous. Scouting,
# tillage and "other" are deliberately absent: scouting cost is usually labour but may
# be a contracted service, and tillage may be owned equipment or a hired operator.
# Guessing there would put a number in a bucket nobody chose.
COST_CATEGORY_FOR_OPERATION: dict[str, str] = {
    "planting": "planting_materials",
    "irrigation": "irrigation",
    "fertilization": "fertilizer_nutrition",
    "crop_protection": "crop_protection",
    "harvest": "harvest_postharvest",
}


class CropCycleCreate(BaseModel):
    # Optional: a farm with no field entities yet gets a whole-farm one, so a season
    # can be started without building the entity spine by hand first.
    field_id: int | None = None
    crop: str
    season_year: int
    variety_name: str | None = None
    season_label: str | None = None
    planting_date: date | None = None
    expected_harvest_start: date | None = None
    expected_harvest_end: date | None = None
    display_area: float | None = Field(default=None, gt=0)
    display_area_unit: str | None = None
    target_market: str | None = None
    target_grade: str | None = None
    status: CropCycleStatus = "growing"
    currency_code: str | None = None
    notes: str | None = None
    data_source: DataSource | None = "manual_entry"
    data_confidence: DataConfidence | None = "user_provided"


class CropCycleUpdate(BaseModel):
    """Closing a cycle is the common case; every field is optional."""
    status: CropCycleStatus | None = None
    variety_name: str | None = None
    season_label: str | None = None
    planting_date: date | None = None
    expected_harvest_start: date | None = None
    expected_harvest_end: date | None = None
    actual_harvest_start: date | None = None
    actual_harvest_end: date | None = None
    display_area: float | None = Field(default=None, gt=0)
    display_area_unit: str | None = None
    target_market: str | None = None
    target_grade: str | None = None
    notes: str | None = None


class CropCycle(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    farm_id: int
    field_id: int
    crop: str
    variety_name: str | None = None
    season_year: int
    season_label: str | None = None
    planting_date: date | None = None
    expected_harvest_start: date | None = None
    expected_harvest_end: date | None = None
    actual_harvest_start: date | None = None
    actual_harvest_end: date | None = None
    planted_area_m2: float | None = None
    display_area: float | None = None
    display_area_unit: str | None = None
    target_market: str | None = None
    target_grade: str | None = None
    status: str
    currency_code: str | None = None
    notes: str | None = None
    data_source: str | None = None
    data_confidence: str | None = None
    created_at: datetime


class OperationCreate(BaseModel):
    """A non-spray thing done to a crop cycle, and what it cost.

    Applications keep their own table and their own cost column — the ledger reads
    both. This is for the irrigation / fertiliser / harvest passes that have never
    had anywhere to go.
    """
    operation_type: OperationType
    # Left unset, the server fills it from `operation_type` where that mapping is
    # unambiguous and leaves it None otherwise. Never guessed past the obvious.
    cost_category: CostCategory | None = None
    performed_on: date | None = None
    planned_on: date | None = None
    field_id: int | None = None
    block_id: int | None = None
    display_area: float | None = Field(default=None, gt=0)
    display_area_unit: str | None = None
    cost_amount: float | None = Field(default=None, ge=0)
    currency_code: str | None = None
    performed_by: str | None = None
    notes: str | None = None
    data_source: DataSource | None = "manual_entry"
    data_confidence: DataConfidence | None = "user_provided"


class Operation(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    farm_id: int
    crop_cycle_id: int | None = None
    field_id: int | None = None
    block_id: int | None = None
    operation_type: str
    cost_category: str | None = None
    planned_on: date | None = None
    performed_on: date | None = None
    area_m2: float | None = None
    display_area: float | None = None
    display_area_unit: str | None = None
    cost_amount: float | None = None
    currency_code: str | None = None
    performed_by: str | None = None
    notes: str | None = None
    data_source: str | None = None
    data_confidence: str | None = None
    created_at: datetime


# ------------------------------------------------- Sales (the revenue half)
# The first money the platform records coming IN. A recorded transaction only —
# a quoted market price is a forecast, not revenue, and nothing here reads one.

# Real settlements round per line, so quantity x unit_price rarely lands exactly on
# the stated gross. This is the width of that rounding, not a licence to accept a
# figure that disagrees: 0.5%, or one unit of currency for a small sale.
_SALE_CONSISTENCY_TOLERANCE_FRACTION = 0.005
_SALE_CONSISTENCY_TOLERANCE_FLOOR = 1.0


class SaleRecordCreate(BaseModel):
    """A recorded sale or settlement against a crop cycle.

    Gross, deductions and net stay three separate numbers. What the crop sold for and
    what the farm received are different facts, and a packer settlement nets out
    commission and freight between them.
    """
    sale_date: date
    quantity: float | None = Field(default=None, gt=0)
    unit: str | None = None
    unit_price: float | None = Field(default=None, ge=0)
    gross_amount: float | None = Field(default=None, ge=0)
    deductions_amount: float | None = Field(default=None, ge=0)
    currency_code: str | None = None
    buyer_name: str | None = None
    reference: str | None = None
    grade: str | None = None
    market: str | None = None
    notes: str | None = None
    supersedes_id: int | None = None
    entered_by: str | None = None
    data_source: DataSource | None = "manual_entry"
    data_confidence: DataConfidence | None = "user_provided"

    @model_validator(mode="after")
    def _quantity_requires_a_unit(self):
        if self.quantity is not None and not (self.unit or "").strip():
            raise ValueError(
                "a unit is required whenever a quantity is given — an unlabelled "
                "number is not a measurement, and a season total cannot be built "
                "from one"
            )
        return self

    @model_validator(mode="after")
    def _a_sale_states_an_amount(self):
        """Either the gross, or enough to derive it. A sale that states no money is not one."""
        derivable = self.quantity is not None and self.unit_price is not None
        if self.gross_amount is None and not derivable:
            raise ValueError(
                "a sale needs either a gross amount, or both a quantity and a unit "
                "price to derive one — nothing here invents a figure from a market "
                "price"
            )
        return self

    @model_validator(mode="after")
    def _stated_figures_agree(self):
        """All three supplied? They must be consistent. A contradictory settlement is not storable."""
        if self.quantity is None or self.unit_price is None or self.gross_amount is None:
            return self
        expected = self.quantity * self.unit_price
        tolerance = max(
            abs(expected) * _SALE_CONSISTENCY_TOLERANCE_FRACTION,
            _SALE_CONSISTENCY_TOLERANCE_FLOOR,
        )
        if abs(expected - self.gross_amount) > tolerance:
            raise ValueError(
                f"quantity x unit price is {expected:,.2f} but the gross amount says "
                f"{self.gross_amount:,.2f} — the record contradicts itself. Correct "
                "one of the three, or leave the gross blank and let it be derived."
            )
        return self

    @model_validator(mode="after")
    def _deductions_do_not_exceed_the_gross(self):
        if self.deductions_amount is None:
            return self
        gross = self.gross_amount
        if gross is None and self.quantity is not None and self.unit_price is not None:
            gross = self.quantity * self.unit_price
        if gross is not None and self.deductions_amount > gross:
            raise ValueError(
                "deductions exceed the gross amount, which would make the net "
                "negative — that is a data-entry error, not a season"
            )
        return self


class SaleRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    crop_cycle_id: int
    farm_id: int
    sale_date: date
    quantity: float | None = None
    unit: str | None = None
    unit_price: float | None = None
    gross_amount: float | None = None
    deductions_amount: float | None = None
    currency_code: str | None = None
    buyer_name: str | None = None
    reference: str | None = None
    grade: str | None = None
    market: str | None = None
    notes: str | None = None
    supersedes_id: int | None = None
    entered_by: str | None = None
    recorded_at: datetime
    data_source: str | None = None
    data_confidence: str | None = None
    created_at: datetime
