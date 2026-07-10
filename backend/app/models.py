"""SQLAlchemy ORM models for Lumos Spray Copilot."""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Farm(Base):
    __tablename__ = "farms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    location: Mapped[str | None] = mapped_column(String(200))
    # Two-letter market/country code, e.g. "US" or "TR". Drives PCA vs. agronomist wording.
    country: Mapped[str] = mapped_column(String(2), default="US")
    crop_type: Mapped[str] = mapped_column(String(100), default="greenhouse_tomato")
    greenhouse_area: Mapped[float | None] = mapped_column(Float)  # m² (TR) or acres (US)
    planting_date: Mapped[date | None] = mapped_column(Date)
    expected_harvest_date: Mapped[date | None] = mapped_column(Date)
    # Pilot intake: is a PCA/agronomist already involved with this farm?
    advisor_involved: Mapped[bool | None] = mapped_column(Boolean)

    spray_events: Mapped[list["SprayEvent"]] = relationship(
        back_populates="farm", cascade="all, delete-orphan"
    )
    scout_observations: Mapped[list["ScoutObservation"]] = relationship(
        back_populates="farm", cascade="all, delete-orphan"
    )
    recommendations: Mapped[list["Recommendation"]] = relationship(
        back_populates="farm", cascade="all, delete-orphan"
    )
    pilot_import_batches: Mapped[list["PilotImportBatch"]] = relationship(
        back_populates="farm", cascade="all, delete-orphan"
    )
    spray_baselines: Mapped[list["SprayBaseline"]] = relationship(
        back_populates="farm", cascade="all, delete-orphan"
    )
    planned_sprays: Mapped[list["PlannedSpray"]] = relationship(
        back_populates="farm", cascade="all, delete-orphan"
    )


class SprayEvent(Base):
    __tablename__ = "spray_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), nullable=False)
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    active_ingredient: Mapped[str | None] = mapped_column(String(200))
    pesticide_class: Mapped[str | None] = mapped_column(String(100))
    target_pest_or_disease: Mapped[str | None] = mapped_column(String(200))
    dose: Mapped[str | None] = mapped_column(String(100))
    application_date: Mapped[date] = mapped_column(Date, nullable=False)
    cost: Mapped[float | None] = mapped_column(Float)
    pre_harvest_interval_days: Mapped[int | None] = mapped_column(Integer)
    re_entry_interval_hours: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)
    # Concierge-pilot provenance: where this record came from and how trustworthy it is.
    # data_source: demo / grower_interview / spreadsheet / whatsapp / email / manual_entry / unknown
    data_source: Mapped[str | None] = mapped_column(String(40), default="demo")
    # data_confidence: simulated / user_provided / pca_reviewed / incomplete
    data_confidence: Mapped[str | None] = mapped_column(String(40), default="simulated")
    # Links the record to the concierge import batch it arrived in (audit trail).
    pilot_import_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("pilot_import_batches.id")
    )

    farm: Mapped["Farm"] = relationship(back_populates="spray_events")


class ScoutObservation(Base):
    __tablename__ = "scout_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), nullable=False)
    observation_date: Mapped[date] = mapped_column(Date, nullable=False)
    crop_stage: Mapped[str | None] = mapped_column(String(100))
    visible_issue: Mapped[str | None] = mapped_column(String(200))
    severity_1_to_5: Mapped[int | None] = mapped_column(Integer)
    image_url_optional: Mapped[str | None] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(Text)
    # Concierge-pilot provenance (see SprayEvent for the allowed values).
    data_source: Mapped[str | None] = mapped_column(String(40), default="demo")
    data_confidence: Mapped[str | None] = mapped_column(String(40), default="simulated")
    pilot_import_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("pilot_import_batches.id")
    )

    farm: Mapped["Farm"] = relationship(back_populates="scout_observations")


class PlannedSpray(Base):
    """An *intended* spray checked before it happens — the pre-spray decision point.

    The decision is snapshotted at creation time (`decision_*` + `decision_payload`,
    plus the legacy `check_risk_level` / `check_text`) so the record reflects what the
    grower/PCA actually saw when deciding. The PCA review (`review_*`) and the recorded
    real-world outcome are the humans' decisions — never a claim that the check caused
    them. PHI/REI values are user-entered and not verified against the current label.
    """
    __tablename__ = "planned_sprays"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), nullable=False)
    intended_date: Mapped[date] = mapped_column(Date, nullable=False)
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    active_ingredient: Mapped[str | None] = mapped_column(String(200))
    target_pest_or_disease: Mapped[str | None] = mapped_column(String(200))
    pre_harvest_interval_days: Mapped[int | None] = mapped_column(Integer)
    re_entry_interval_hours: Mapped[int | None] = mapped_column(Integer)
    estimated_cost: Mapped[float | None] = mapped_column(Float)
    # Who supplied the PHI/REI values: grower_entered / pca_entered (never a verified
    # label today — there is deliberately no label database yet).
    values_source: Mapped[str] = mapped_column(String(30), default="grower_entered")
    values_entered_by: Mapped[str | None] = mapped_column(String(120))
    # Decision snapshot (what the decision engine said at creation time).
    # outcome: approve / block / delay / inspect_first / pca_review_required
    decision_outcome: Mapped[str] = mapped_column(String(30), default="pca_review_required")
    decision_severity: Mapped[str] = mapped_column(String(20), default="none")
    decision_confidence: Mapped[str] = mapped_column(String(20), default="low")
    # Authority gating: definitive only when backed by verified-label / PCA-entered
    # sources; provisional results always require PCA confirmation.
    decision_authority: Mapped[str] = mapped_column(String(20), default="provisional")
    required_next_action: Mapped[str] = mapped_column(String(300), default="")
    review_required: Mapped[bool] = mapped_column(Boolean, default=True)
    # Full explainable snapshot: rules, inputs, calculations, missing info, disclaimer.
    decision_payload: Mapped[dict | None] = mapped_column(JSON)
    # Legacy snapshot fields kept for the weekly-report/audit surfaces.
    check_risk_level: Mapped[str] = mapped_column(String(20), default="low")
    check_text: Mapped[str] = mapped_column(Text, nullable=False)
    # PCA review of the decision: not_reviewed / approved / edited / rejected.
    review_status: Mapped[str] = mapped_column(String(20), default="not_reviewed")
    review_comment: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[str | None] = mapped_column(String(120))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    # PCA's replacement guidance when the review action is "edited".
    pca_next_action: Mapped[str | None] = mapped_column(Text)
    # Real-world outcome: planned / sprayed_as_planned / changed_product / delayed /
    # avoided / inspected_first.
    outcome: Mapped[str] = mapped_column(String(30), default="planned")
    outcome_reason: Mapped[str | None] = mapped_column(Text)
    outcome_date: Mapped[date | None] = mapped_column(Date)
    # What was actually applied when the outcome is changed_product.
    outcome_product_name: Mapped[str | None] = mapped_column(String(200))
    outcome_active_ingredient: Mapped[str | None] = mapped_column(String(200))
    # Set when outcome "sprayed" creates the real SprayEvent.
    spray_event_id: Mapped[int | None] = mapped_column(ForeignKey("spray_events.id"))
    # Concierge-pilot provenance (see SprayEvent for the allowed values).
    data_source: Mapped[str | None] = mapped_column(String(40), default="manual_entry")
    data_confidence: Mapped[str | None] = mapped_column(String(40), default="user_provided")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    farm: Mapped["Farm"] = relationship(back_populates="planned_sprays")


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    risk_level: Mapped[str] = mapped_column(String(20), default="low")
    next_action: Mapped[str] = mapped_column(String(120), default="")
    recommendation_text: Mapped[str] = mapped_column(Text, nullable=False)
    # agronomist workflow: pending / approved / rejected / edited
    agronomist_status: Mapped[str] = mapped_column(String(20), default="pending")
    agronomist_comment: Mapped[str | None] = mapped_column(Text)

    farm: Mapped["Farm"] = relationship(back_populates="recommendations")


class SprayBaseline(Base):
    """A grower/PCA-declared spray baseline used to measure reduction against (one per farm).

    A reduction figure is only as honest as its baseline, so this carries the same provenance
    fields as a concierge import (who declared it, how trustworthy it is). See `reduction.py`.
    """
    __tablename__ = "spray_baselines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), nullable=False)
    # method: stated_cadence / prior_period / calendar_program
    method: Mapped[str] = mapped_column(String(40), nullable=False)
    # stated_cadence: one of these two
    cadence_days: Mapped[int | None] = mapped_column(Integer)
    season_spray_count: Mapped[int | None] = mapped_column(Integer)
    # prior_period: a dated pre-Lumos window on this farm's own records
    baseline_period_start: Mapped[date | None] = mapped_column(Date)
    baseline_period_end: Mapped[date | None] = mapped_column(Date)
    # calendar_program: a named schedule (weekly / biweekly / ...)
    calendar_program: Mapped[str | None] = mapped_column(String(40))
    # provenance (mirrors SprayEvent)
    data_source: Mapped[str | None] = mapped_column(String(40), default="grower_interview")
    data_confidence: Mapped[str | None] = mapped_column(String(40), default="user_provided")
    declared_by: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    farm: Mapped["Farm"] = relationship(back_populates="spray_baselines")


class PilotFeedback(Base):
    """Feedback captured after a demo with a grower / PCA / agronomist / etc.

    Not tied to a farm — it records pilot signals and discovery answers.
    """
    __tablename__ = "pilot_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # grower / PCA / agronomist / exporter / input_supplier / other
    person_type: Mapped[str] = mapped_column(String(40), nullable=False)
    crop: Mapped[str | None] = mapped_column(String(100))
    region: Mapped[str | None] = mapped_column(String(120))
    # how they keep spray records today: paper / spreadsheet / whatsapp / software / none / other
    current_records_method: Mapped[str | None] = mapped_column(String(40))
    # cost / PHI / REI / residue / resistance / audits / labor / other
    biggest_pain: Mapped[str | None] = mapped_column(String(40))
    would_use_real_data: Mapped[str | None] = mapped_column(String(10))  # yes / no / maybe
    would_pay: Mapped[str | None] = mapped_column(String(10))            # yes / no / maybe
    requested_pilot: Mapped[bool | None] = mapped_column(Boolean)
    notes: Mapped[str | None] = mapped_column(Text)


class PilotEvent(Base):
    """One pilot-instrumentation event (check started/abandoned, review, outcome, import).

    Deliberately schemaless beyond the type: `meta` holds the per-event detail. Events are
    workflow telemetry for running a real pilot — they are never customer-facing metrics.
    """
    __tablename__ = "pilot_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # check_started / check_completed / check_abandoned / review_recorded /
    # outcome_recorded / import_used
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    farm_id: Mapped[int | None] = mapped_column(Integer)
    planned_spray_id: Mapped[int | None] = mapped_column(Integer)
    # How the data got in: manual_form / csv_paste / concierge / seed ...
    entry_source: Mapped[str | None] = mapped_column(String(40))
    meta: Mapped[dict | None] = mapped_column(JSON)


class PilotImportBatch(Base):
    """Audit-trail record of one concierge import (a batch of manually transcribed records).

    Persists the human provenance (who/where/notes) that the imported SprayEvent /
    ScoutObservation rows link back to via `pilot_import_batch_id`.
    """
    __tablename__ = "pilot_import_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), nullable=False)
    source_label: Mapped[str] = mapped_column(String(200), nullable=False)
    imported_by: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)
    data_source: Mapped[str | None] = mapped_column(String(40))
    data_confidence: Mapped[str | None] = mapped_column(String(40))
    spray_event_count: Mapped[int] = mapped_column(Integer, default=0)
    scouting_observation_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    farm: Mapped["Farm"] = relationship(back_populates="pilot_import_batches")
