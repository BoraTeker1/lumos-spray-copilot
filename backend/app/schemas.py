"""Pydantic schemas (request/response contracts), separate from ORM models."""
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Concierge-pilot provenance vocabularies (validated, so bad values give a clean 422).
DataSource = Literal[
    "demo", "grower_interview", "spreadsheet", "whatsapp", "email", "manual_entry",
    "photo_ai", "ai_extracted", "unknown"
]
DataConfidence = Literal["simulated", "user_provided", "pca_reviewed", "incomplete"]

# Field-level provenance for compliance/decision-critical input values.
# "authoritative_provider" is deliberately unreachable today (no label-data provider
# exists); the vocabulary is in place so the gate is already correct when one does.
InputSourceType = Literal[
    "demo", "user_entered", "imported_unverified", "pca_verified",
    "authoritative_provider",
]
# Append-only follow-up timeline event types (never a single mutable outcome record).
FollowUpEventType = Literal[
    "scouting_observation", "actual_application", "rescue_application",
    "harvest_outcome", "yield_quality_outcome", "note",
]
ImpactLevel = Literal["positive", "neutral", "negative", "unknown"]
# CSV pilot-import record types.
ImportRecordType = Literal["planned_sprays", "scout_observations"]


# --------------------------------------------------------------------------- Farm
class FarmBase(BaseModel):
    name: str
    location: str | None = None
    country: str = "US"
    crop_type: str = "greenhouse_tomato"
    greenhouse_area: float | None = None
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
    planting_date: date | None = None
    expected_harvest_date: date | None = None
    advisor_involved: bool | None = None


class Farm(FarmBase):
    model_config = ConfigDict(from_attributes=True)
    id: int


# --------------------------------------------------------------------- SprayEvent
class SprayEventBase(BaseModel):
    product_name: str
    active_ingredient: str | None = None
    moa_group: str | None = None
    pesticide_class: str | None = None
    target_pest_or_disease: str | None = None
    dose: str | None = None
    application_date: date
    cost: float | None = None
    pre_harvest_interval_days: int | None = None
    re_entry_interval_hours: int | None = None
    field_block: str | None = None
    notes: str | None = None
    data_source: str | None = None
    data_confidence: str | None = None
    pilot_import_batch_id: int | None = None


class SprayEventCreate(SprayEventBase):
    pass


class SprayEvent(SprayEventBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    farm_id: int


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
    severity_scale: str | None = None
    count_value: float | None = None
    observer: str | None = None
    source_system: str | None = None
    source_filename: str | None = None
    data_source: str | None = None
    data_confidence: str | None = None
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
    """The explainable pre-spray decision snapshot."""
    outcome: str
    severity: str
    confidence: str
    rules: list[PlannedSprayDecisionRule] = Field(default_factory=list)
    inputs_used: dict = Field(default_factory=dict)
    missing_information: list[str] = Field(default_factory=list)
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
    crop: str | None = None
    treated_acres: float | None = None
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
    source_label: str | None = None
    source_filename: str | None = None
    imported_by: str | None = None
    notes: str | None = None
    # Links committed rows back to the extraction judgment they came from.
    ai_judgment_id: int | None = None


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


# --------------------------------------------------------------- Spray baseline
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
