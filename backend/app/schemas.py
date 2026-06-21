"""Pydantic schemas (request/response contracts), separate from ORM models."""
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------- Farm
class FarmBase(BaseModel):
    name: str
    location: str | None = None
    country: str = "US"
    crop_type: str = "greenhouse_tomato"
    greenhouse_area: float | None = None
    planting_date: date | None = None
    expected_harvest_date: date | None = None


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


class ScoutObservationCreate(ScoutObservationBase):
    pass


class ScoutObservation(ScoutObservationBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    farm_id: int


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
