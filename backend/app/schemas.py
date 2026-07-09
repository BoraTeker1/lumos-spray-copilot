"""Pydantic schemas (request/response contracts), separate from ORM models."""
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Concierge-pilot provenance vocabularies (validated, so bad values give a clean 422).
DataSource = Literal[
    "demo", "grower_interview", "spreadsheet", "whatsapp", "email", "manual_entry",
    "photo_ai", "unknown"
]
DataConfidence = Literal["simulated", "user_provided", "pca_reviewed", "incomplete"]


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
    pesticide_class: str | None = None
    target_pest_or_disease: str | None = None
    dose: str | None = None
    application_date: date
    cost: float | None = None
    pre_harvest_interval_days: int | None = None
    re_entry_interval_hours: int | None = None
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
PlannedSprayOutcome = Literal["sprayed", "skipped", "postponed"]


class PlannedSprayCreate(BaseModel):
    """An intended spray to check *before* it happens (pre-spray decision point)."""
    intended_date: date
    product_name: str
    active_ingredient: str | None = None
    target_pest_or_disease: str | None = None
    pre_harvest_interval_days: int | None = Field(default=None, ge=0)
    re_entry_interval_hours: int | None = Field(default=None, ge=0)
    estimated_cost: float | None = None
    data_source: DataSource = "manual_entry"
    data_confidence: DataConfidence = "user_provided"


class PlannedSprayOutcomeUpdate(BaseModel):
    """The grower/PCA's recorded decision on a planned spray.

    A reason is mandatory for skipped/postponed so every non-spray is documented honestly.
    `application_date` (sprayed only) defaults to the intended date.
    """
    outcome: PlannedSprayOutcome
    outcome_reason: str | None = None
    application_date: date | None = None

    @model_validator(mode="after")
    def _require_reason_when_not_sprayed(self):
        if self.outcome in ("skipped", "postponed") and not (self.outcome_reason or "").strip():
            raise ValueError(
                "outcome_reason is required when the outcome is 'skipped' or 'postponed'"
            )
        return self


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
    check_risk_level: str
    check_text: str
    outcome: str
    outcome_reason: str | None = None
    outcome_date: date | None = None
    spray_event_id: int | None = None
    data_source: str | None = None
    data_confidence: str | None = None
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
