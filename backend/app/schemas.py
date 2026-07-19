"""Pydantic schemas (request/response contracts), separate from ORM models."""
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.procurement_status import FINANCING_OFFER_DISCLAIMER

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
# CSV pilot-import record types. spray_events = historical *actual* applications —
# the reduction baseline's denominator.
ImportRecordType = Literal["planned_sprays", "scout_observations", "spray_events"]
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


# --------------------------------------------------------------------- SprayEvent
class SprayEventBase(BaseModel):
    product_name: str
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
