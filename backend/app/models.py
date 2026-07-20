"""SQLAlchemy ORM models for Lumos Spray Copilot."""
from datetime import date, datetime

from sqlalchemy import (
    JSON, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app import clock, decision_status, procurement_status
from app.database import Base

# All created_at defaults go through the app clock so a pinned LUMOS_DEMO_TODAY keeps
# seeded and live records on the same timeline (see app/clock.py).


class Farm(Base):
    __tablename__ = "farms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    location: Mapped[str | None] = mapped_column(String(200))
    # Two-letter market/country code, e.g. "US" or "TR". Drives PCA vs. agronomist wording.
    country: Mapped[str] = mapped_column(String(2), default="US")
    crop_type: Mapped[str] = mapped_column(String(100), default="greenhouse_tomato")
    greenhouse_area: Mapped[float | None] = mapped_column(Float)  # in area_unit
    # Explicit unit for greenhouse_area ("acres" / "m2"). Historically the unit was
    # implied by country (m² in TR, acres in US) — the column makes it data instead.
    area_unit: Mapped[str | None] = mapped_column(String(10))
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
    pca_policies: Mapped[list["PcaPolicy"]] = relationship(
        back_populates="farm", cascade="all, delete-orphan"
    )
    input_plans: Mapped[list["InputPlan"]] = relationship(
        back_populates="farm", cascade="all, delete-orphan"
    )
    purchase_orders: Mapped[list["PurchaseOrder"]] = relationship(
        back_populates="farm", cascade="all, delete-orphan"
    )
    blocks: Mapped[list["Block"]] = relationship(
        back_populates="farm", cascade="all, delete-orphan"
    )


class Block(Base):
    """A field block — the unit of pilot assignment and outcome measurement.

    Deliberately NOT derived from the existing free-text `field_block` column on
    sprays/scouting/planned sprays. That string is grower shorthand entered per
    record; inferring block identity from it would fabricate structure nobody
    recorded, and two records reading "north 3" are not evidence of one block.
    `field_block` is left exactly as it is; records join a block only through the
    explicit nullable `block_id`.

    A block is needed because control/intervention assignment, marketable packout,
    cull rates, and cultivar/phenology are all measured per block per harvest — none
    of which can hang off a string.
    """
    __tablename__ = "blocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    crop: Mapped[str | None] = mapped_column(String(100))
    cultivar: Mapped[str | None] = mapped_column(String(120))
    area: Mapped[float | None] = mapped_column(Float)  # in area_unit
    area_unit: Mapped[str | None] = mapped_column(String(10))  # "acres" / "m2"
    planting_date: Mapped[date | None] = mapped_column(Date)
    expected_harvest_date: Mapped[date | None] = mapped_column(Date)
    # Phenology as OBSERVED, with the date of that observation. Never inferred from
    # the planting date — a computed growth stage would be an agronomic claim nobody
    # made, and the risk snapshot must be able to tell "recorded" from "guessed".
    phenology_stage: Mapped[str | None] = mapped_column(String(60))
    phenology_observed_on: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    # Concierge-pilot provenance (see SprayEvent for the allowed values). Defaults to
    # real entry, not demo — a block created through the API is a real block unless
    # the caller says otherwise (the demo seed sets these explicitly).
    data_source: Mapped[str | None] = mapped_column(String(40), default="manual_entry")
    data_confidence: Mapped[str | None] = mapped_column(String(40), default="user_provided")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)

    farm: Mapped["Farm"] = relationship(back_populates="blocks")


class SprayEvent(Base):
    __tablename__ = "spray_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), nullable=False)
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    active_ingredient: Mapped[str | None] = mapped_column(String(200))
    # FRAC/IRAC/HRAC mode-of-action group, when known (needed for MoA-rotation checks).
    moa_group: Mapped[str | None] = mapped_column(String(40))
    pesticide_class: Mapped[str | None] = mapped_column(String(100))
    target_pest_or_disease: Mapped[str | None] = mapped_column(String(200))
    # Legacy free-text dose; structured rate lives in rate_amount + rate_unit.
    dose: Mapped[str | None] = mapped_column(String(100))
    # Structured applied quantity (entered, not label-verified; units are NOT yet
    # normalized or converted — captured so quantity evidence becomes possible).
    rate_amount: Mapped[float | None] = mapped_column(Float)
    rate_unit: Mapped[str | None] = mapped_column(String(40))
    # `treated_acres` is acre-NAMED but not acre-guaranteed: it predates Farm.area_unit
    # and a m2 farm stored square metres in it. `treated_area_unit` records what the
    # number actually is, defaulted from the farm at write time. NOTHING converts
    # between units — a mixed set is refused, never silently added up.
    treated_acres: Mapped[float | None] = mapped_column(Float)
    treated_area_unit: Mapped[str | None] = mapped_column(String(10))
    application_date: Mapped[date] = mapped_column(Date, nullable=False)
    cost: Mapped[float | None] = mapped_column(Float)
    pre_harvest_interval_days: Mapped[int | None] = mapped_column(Integer)
    re_entry_interval_hours: Mapped[int | None] = mapped_column(Integer)
    # Field/block within the farm (same vocabulary as PlannedSpray/ScoutObservation).
    field_block: Mapped[str | None] = mapped_column(String(120))
    # Optional link to a real Block entity. Never backfilled from `field_block`.
    block_id: Mapped[int | None] = mapped_column(ForeignKey("blocks.id"), index=True)
    # Pilot CSV-import provenance (mirrors ScoutObservation/PlannedSpray).
    external_record_id: Mapped[str | None] = mapped_column(String(120))
    source_system: Mapped[str | None] = mapped_column(String(120))
    source_filename: Mapped[str | None] = mapped_column(String(255))
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
    # Purchase orders whose delivered input this application consumed (set only by
    # the explicit input-applied endpoint; one in practice, viewonly here).
    source_orders: Mapped[list["PurchaseOrder"]] = relationship(
        foreign_keys="PurchaseOrder.spray_event_id", viewonly=True
    )

    @property
    def source_order_id(self) -> int | None:
        orders = self.source_orders or []
        return orders[0].id if orders else None


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
    # Pilot CSV-import fields (all optional; provenance for real scouting records).
    external_record_id: Mapped[str | None] = mapped_column(String(120))
    field_block: Mapped[str | None] = mapped_column(String(120))
    # Optional link to a real Block entity. Never backfilled from `field_block`.
    block_id: Mapped[int | None] = mapped_column(ForeignKey("blocks.id"), index=True)
    severity_scale: Mapped[str | None] = mapped_column(String(40))  # e.g. "1-5", "1-10"
    count_value: Mapped[float | None] = mapped_column(Float)
    observer: Mapped[str | None] = mapped_column(String(120))
    source_system: Mapped[str | None] = mapped_column(String(120))
    source_filename: Mapped[str | None] = mapped_column(String(255))
    # Concierge-pilot provenance (see SprayEvent for the allowed values).
    data_source: Mapped[str | None] = mapped_column(String(40), default="demo")
    data_confidence: Mapped[str | None] = mapped_column(String(40), default="simulated")
    pilot_import_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("pilot_import_batches.id")
    )

    farm: Mapped["Farm"] = relationship(back_populates="scout_observations")


class WeatherObservation(Base):
    """One weather reading, append-only, as an input to a disease-risk assessment.

    No weather has ever been persisted in this system: `app/weather.py` computes an
    advisory disease-pressure number on the fly from a hardcoded per-city dict that
    never varies with time. That is fine for an advisory card and useless as model
    input — a risk assessment has to be reproducible from the exact readings that
    existed at the decision moment.

    TWO timestamps, and both matter:
      * `observed_at` — when the weather happened.
      * `recorded_at` — when Lumos learned about it.
    A reading about Tuesday that was entered on Friday is still hindsight, so the
    snapshot builder admits a row only when BOTH are at or before the prediction
    time. Filtering on `observed_at` alone is the subtle leak this column exists to
    prevent.

    Ingestion is CSV/concierge only — no weather-provider integration exists, and none
    should be built before the provider and field requirements are known.
    """
    __tablename__ = "weather_observations"
    __table_args__ = (
        # At most ONE original reading per station per timestamp. A duplicated hour
        # would double-count wetness inside a risk window and silently change a
        # snapshot digest, so this is enforced by the database rather than trusted to
        # the import's dedupe.
        #
        # PARTIAL (supersedes_id IS NULL) because corrections deliberately repeat the
        # station+timestamp of the row they replace — a plain unique index would make
        # the append-only correction path impossible.
        Index(
            "uq_weather_observation_station_hour",
            "station_id", "observed_at",
            unique=True,
            sqlite_where=text("supersedes_id IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), nullable=False, index=True)
    # Weather is usually recorded per station, not per block; nullable by design.
    block_id: Mapped[int | None] = mapped_column(ForeignKey("blocks.id"), index=True)
    station_id: Mapped[str] = mapped_column(String(80), nullable=False)
    station_name: Mapped[str | None] = mapped_column(String(160))
    # How far the station is from the block. Distance degrades the evidence grade and
    # past a threshold forces abstention — it is never assumed to be zero.
    station_distance_km: Mapped[float | None] = mapped_column(Float)
    observed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=clock.current_datetime
    )
    temperature_c: Mapped[float | None] = mapped_column(Float)
    relative_humidity_pct: Mapped[float | None] = mapped_column(Float)
    rainfall_mm: Mapped[float | None] = mapped_column(Float)
    leaf_wetness_minutes: Mapped[float | None] = mapped_column(Float)
    # True only when a sensor measured wetness. A value derived from humidity is a
    # different kind of evidence and must never be presented as a measurement.
    wetness_is_measured: Mapped[bool | None] = mapped_column(Boolean)
    source_type: Mapped[str] = mapped_column(String(40), default="manual_entry")
    source_reference: Mapped[str | None] = mapped_column(String(255))
    # Operator/station-reported quality note (e.g. "sensor fault"). Any value here
    # excludes the row from assessment rather than being silently averaged over.
    quality_flag: Mapped[str | None] = mapped_column(String(60))
    # Corrections append a new row pointing at the one they replace — never an edit.
    supersedes_id: Mapped[int | None] = mapped_column(
        ForeignKey("weather_observations.id")
    )
    data_source: Mapped[str | None] = mapped_column(String(40), default="manual_entry")
    data_confidence: Mapped[str | None] = mapped_column(String(40), default="user_provided")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)


class ScoutingSample(Base):
    """A standardized scouting sample: a numerator over a STATED denominator.

    Distinct from `ScoutObservation`, which stays exactly as it is for the existing
    decision engine. That model cannot support a threshold: its `count_value` is a
    bare number with no denominator and no consumer anywhere in the codebase, and its
    `severity_scale` is free text the engine never read (an imported 1-10 severity was
    silently compared against a 1-5 threshold — see
    `decision_engine.severity_is_comparable_to_threshold`).

    Incidence here is DERIVED server-side from `units_affected / units_inspected`, so
    a percentage can never be asserted without the sample it came from.
    """
    __tablename__ = "scouting_samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), nullable=False, index=True)
    # A sample is always OF a block — that is what makes it comparable across arms.
    block_id: Mapped[int] = mapped_column(ForeignKey("blocks.id"), nullable=False, index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=clock.current_datetime
    )
    # Sampling method, from a fixed vocabulary (see schemas.ScoutingMethod). Two
    # samples taken by different methods are not directly comparable.
    method: Mapped[str] = mapped_column(String(40), nullable=False)
    target: Mapped[str] = mapped_column(String(200), nullable=False)
    units_inspected: Mapped[int] = mapped_column(Integer, nullable=False)
    units_affected: Mapped[int] = mapped_column(Integer, nullable=False)
    # Derived, never accepted from input.
    incidence_pct: Mapped[float | None] = mapped_column(Float)
    severity_index: Mapped[float | None] = mapped_column(Float)
    severity_scale: Mapped[str | None] = mapped_column(String(40))
    scout_name: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(40), default="manual_entry")
    source_reference: Mapped[str | None] = mapped_column(String(255))
    external_record_id: Mapped[str | None] = mapped_column(String(120))
    supersedes_id: Mapped[int | None] = mapped_column(ForeignKey("scouting_samples.id"))
    data_source: Mapped[str | None] = mapped_column(String(40), default="manual_entry")
    data_confidence: Mapped[str | None] = mapped_column(String(40), default="user_provided")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)


class RiskInputSnapshot(Base):
    """Exactly what was knowable at one prediction moment. Immutable.

    There is no update and no delete. The whole value of this row is that it can be
    re-read years later and shown to contain only information that existed at
    `as_of` — a mutable snapshot proves nothing.

    `excluded` records what was left OUT and why (future reading, recorded late,
    superseded, quality-flagged, demo). "We did not use this, and here is why" is
    part of the evidence, not an implementation detail.

    See `app/risk_snapshot.py` for the two-timestamp admissibility rule this stores
    the result of.
    """
    __tablename__ = "risk_input_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), nullable=False, index=True)
    block_id: Mapped[int] = mapped_column(ForeignKey("blocks.id"), nullable=False, index=True)
    planned_spray_id: Mapped[int | None] = mapped_column(
        ForeignKey("planned_sprays.id"), index=True
    )
    # The prediction moment. Everything in `payload` was observable AND recorded by it.
    as_of: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    horizon_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    target: Mapped[str] = mapped_column(String(80), nullable=False)
    snapshot_version: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    # sha256 over the canonical payload — re-snapshotting the same as_of must
    # reproduce this exactly, which is what makes an assessment auditable.
    input_digest: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    excluded: Mapped[list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)


class DiseaseRiskAssessment(Base):
    """One versioned rule's output for one snapshot. Append-only.

    Anchored to a snapshot (NOT NULL) because an assessment whose inputs cannot be
    reproduced is not evidence — it is an opinion with a timestamp.

    `is_shadow` is the load-bearing column of the pilot. While True the row is omitted
    from every PCA-facing serializer — not hidden in the UI, absent from the payload —
    so the PCA's disposition is recorded without having seen it. That is what makes
    their decision usable as an unbiased baseline to score the rule against later.
    Unblinding is a protocol-versioned event (PilotProtocol.unblinded_at), not a flag
    someone can flip.

    There is no product, rate or action column here, mirroring
    `disease_risk.RiskAssessment`: this row cannot express a pesticide recommendation.
    """
    __tablename__ = "disease_risk_assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("risk_input_snapshots.id"), nullable=False, index=True
    )
    planned_spray_id: Mapped[int | None] = mapped_column(
        ForeignKey("planned_sprays.id"), index=True
    )
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), nullable=False, index=True)
    block_id: Mapped[int] = mapped_column(ForeignKey("blocks.id"), nullable=False, index=True)

    model_family: Mapped[str] = mapped_column(String(60), nullable=False)
    model_version: Mapped[str] = mapped_column(String(60), nullable=False)
    # Ties the result to the exact inputs it saw; reproducible from the audit record.
    input_digest: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    risk_band: Mapped[str] = mapped_column(String(20), nullable=False)
    probability: Mapped[float | None] = mapped_column(Float)
    evidence_grade: Mapped[str | None] = mapped_column(String(2))
    horizon_hours: Mapped[int] = mapped_column(Integer, nullable=False)

    abstained: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    abstain_reason: Mapped[str | None] = mapped_column(String(80))
    # Every reason, not just the first — the full evidence gap is the useful artifact.
    missing_inputs: Mapped[list | None] = mapped_column(JSON)

    # Never derived from agreement with a PCA; only from realized outcomes (Phase 2).
    calibration_status: Mapped[str] = mapped_column(
        String(40), default="not_calibrated", nullable=False
    )
    local_validation_status: Mapped[str | None] = mapped_column(Text)
    citation: Mapped[str | None] = mapped_column(Text)
    calculation: Mapped[dict | None] = mapped_column(JSON)

    is_shadow: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)
    data_source: Mapped[str] = mapped_column(String(40), default="rule_engine")
    data_confidence: Mapped[str] = mapped_column(String(40), default="computed")


class PcaDisposition(Base):
    """What the licensed PCA decided about a scheduled application. Append-only.

    A first-class, attributed record, deliberately separate from all three of its
    neighbours: the deterministic verdict (`PlannedSpray.decision_*`), the review
    (`review_*`), and what actually happened (`outcome`). Those are four different
    facts about four different moments. Collapsing any pair would make the pilot
    unable to distinguish "the rule said defer" from "the PCA chose to defer" from
    "the spray was in fact deferred" — which is the entire measurement.

    Invariants enforced in crud and pinned by tests:
      * Recording one NEVER writes a decision_* or review_* column.
      * `defer` does not unlock applied outcomes and does not satisfy a required
        review. Deferring and being cleared to spray are orthogonal.
      * It must be anchored to a snapshot digest, so the judgement is always tied to
        what was knowable at the time.
      * Corrections append a superseding row. Nothing is ever edited.

    `assessment_id` is recorded even while blinded — the PCA did not see it, but the
    join is what lets the rule be scored against their independent judgement later.
    """
    __tablename__ = "pca_dispositions"
    __table_args__ = (
        # One live disposition per decision. PARTIAL (supersedes_id IS NULL) for the
        # same reason as the weather index: a correction repeats the planned_spray_id
        # of the row it replaces, and a plain unique index would make the append-only
        # correction path impossible.
        Index(
            "uq_pca_disposition_live_per_decision",
            "planned_spray_id",
            unique=True,
            sqlite_where=text("supersedes_id IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    planned_spray_id: Mapped[int] = mapped_column(
        ForeignKey("planned_sprays.id"), nullable=False, index=True
    )
    # NOT NULL: an unattributed professional decision is not a professional decision.
    pca_credential_id: Mapped[int] = mapped_column(
        ForeignKey("pca_credentials.id"), nullable=False, index=True
    )
    disposition: Mapped[str] = mapped_column(String(40), nullable=False)
    # Mandatory and non-empty (enforced in the schema). A disposition without a stated
    # reason is unusable as evidence — this is the field the pilot actually learns from.
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    assessment_id: Mapped[int | None] = mapped_column(
        ForeignKey("disease_risk_assessments.id"), index=True
    )
    snapshot_digest_at_decision: Mapped[str] = mapped_column(String(64), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime, default=clock.current_datetime, nullable=False
    )
    supersedes_id: Mapped[int | None] = mapped_column(ForeignKey("pca_dispositions.id"))
    data_source: Mapped[str] = mapped_column(String(40), default="pca_entered")
    data_confidence: Mapped[str] = mapped_column(String(40), default="pca_reviewed")


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
    # Pilot CSV-import / real-record fields (all optional).
    external_record_id: Mapped[str | None] = mapped_column(String(120))
    field_block: Mapped[str | None] = mapped_column(String(120))
    # Optional link to a real Block entity. Never backfilled from `field_block`.
    block_id: Mapped[int | None] = mapped_column(ForeignKey("blocks.id"), index=True)
    crop: Mapped[str | None] = mapped_column(String(100))
    # See SprayEvent.treated_area_unit — the unit is data, not implied by the column name.
    treated_acres: Mapped[float | None] = mapped_column(Float)
    treated_area_unit: Mapped[str | None] = mapped_column(String(10))
    epa_reg_no: Mapped[str | None] = mapped_column(String(60))
    # FRAC/IRAC/HRAC mode-of-action group, when known.
    moa_group: Mapped[str | None] = mapped_column(String(40))
    rate_amount: Mapped[float | None] = mapped_column(Float)
    rate_unit: Mapped[str | None] = mapped_column(String(40))
    recommendation_author: Mapped[str | None] = mapped_column(String(120))
    source_system: Mapped[str | None] = mapped_column(String(120))
    source_filename: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)
    pilot_import_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("pilot_import_batches.id")
    )
    # Who supplied the PHI/REI values: grower_entered / pca_entered (never a verified
    # label today — there is deliberately no label database yet).
    values_source: Mapped[str] = mapped_column(String(30), default="grower_entered")
    values_entered_by: Mapped[str | None] = mapped_column(String(120))
    # Decision snapshot (what the decision engine said at creation time).
    # outcome: approve / block / delay / inspect_first / pca_review_required
    decision_outcome: Mapped[str] = mapped_column(String(30), default="pca_review_required")
    decision_severity: Mapped[str] = mapped_column(String(20), default="none")
    decision_confidence: Mapped[str] = mapped_column(String(20), default="low")
    # Authority gating: verified_label_grounded / pca_authorized / provisional
    # (see app/decision_engine.py). Provisional always requires PCA confirmation.
    decision_authority: Mapped[str] = mapped_column(String(30), default="provisional")
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
    # The credential that backed an approve/edit, when the farm is enrolled. Free-text
    # `reviewed_by` records what someone typed; this records who could prove it.
    reviewed_by_credential_id: Mapped[int | None] = mapped_column(
        ForeignKey("pca_credentials.id")
    )
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)

    farm: Mapped["Farm"] = relationship(back_populates="planned_sprays")
    input_values: Mapped[list["DecisionInputValue"]] = relationship(
        back_populates="planned_spray", cascade="all, delete-orphan"
    )
    audit_events: Mapped[list["DecisionAuditEvent"]] = relationship(
        back_populates="planned_spray", cascade="all, delete-orphan"
    )
    follow_up_events: Mapped[list["DecisionFollowUpEvent"]] = relationship(
        back_populates="planned_spray", cascade="all, delete-orphan"
    )
    # Procurement raised from this decision (Inputs & finance): the reverse edge
    # of InputPlanItem.planned_spray_id, so the decision surface can show that a
    # plan/order already exists instead of re-offering "Request supplier quotes".
    input_plan_items: Mapped[list["InputPlanItem"]] = relationship(
        back_populates="planned_spray"
    )

    # Derived status fields (read-only, from the canonical app/decision_status.py).
    # Serialized on schemas.PlannedSpray so the frontend never re-derives them.
    @property
    def review_state(self) -> str:
        return decision_status.review_state(self)

    @property
    def needs_review(self) -> bool:
        return decision_status.needs_review(self)

    @property
    def applied_outcome_allowed(self) -> bool:
        return decision_status.applied_outcome_allowed(self)

    @property
    def is_open(self) -> bool:
        return decision_status.is_open(self)

    @property
    def open_conflict(self) -> bool:
        return decision_status.open_conflict(self)

    @property
    def harvest_date_changed_since_check(self) -> bool:
        return decision_status.harvest_date_changed_since_check(
            self, self.farm.expected_harvest_date if self.farm else None
        )

    @property
    def follow_up_required(self) -> bool:
        return decision_status.follow_up_required(self)

    @property
    def follow_up_event_count(self) -> int:
        return len(self.follow_up_events or [])

    @property
    def procurement_eligible(self) -> bool:
        return decision_status.procurement_eligible(self)

    @property
    def workflow_state(self) -> str:
        return decision_status.workflow_state(self)

    @property
    def evidence_state(self) -> str:
        return decision_status.evidence_state(self, self.follow_up_events)

    @property
    def current_next_action(self) -> str:
        return decision_status.current_next_action(self, self.follow_up_events)

    @property
    def procurement_links(self) -> list[dict]:
        """Every plan (and its order) ever raised from this decision, newest first."""
        seen: dict[int, dict] = {}
        for item in self.input_plan_items or []:
            plan = item.input_plan
            if plan is None or plan.id in seen:
                continue
            seen[plan.id] = {
                "input_plan_id": plan.id,
                "plan_status": plan.status,
                "order_id": plan.order_id,
                "order_status": plan.order.status if plan.order is not None else None,
            }
        return [seen[k] for k in sorted(seen, reverse=True)]


class DecisionInputValue(Base):
    """Field-level provenance for one compliance/decision-critical input value.

    Append-only via a supersede chain: a correction or PCA verification never edits a
    row — it appends a new row whose `supersedes_input_value_id` points at the old one.
    The latest non-superseded row per field is what drives the decision engine (crud
    resolves it and keeps the PlannedSpray's denormalized display columns in sync).
    Imported values are `imported_unverified` and NEVER silently become verified —
    only an attributed PCA action can append a `pca_verified` row.
    """
    __tablename__ = "decision_input_values"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    planned_spray_id: Mapped[int] = mapped_column(
        ForeignKey("planned_sprays.id"), nullable=False
    )
    # e.g. product_name / epa_reg_no / crop / target_pest_or_disease / rate_amount /
    # pre_harvest_interval_days / re_entry_interval_hours / intended_date /
    # expected_harvest_date / active_ingredient / moa_group
    field_name: Mapped[str] = mapped_column(String(60), nullable=False)
    raw_value: Mapped[str | None] = mapped_column(String(500))
    normalized_value: Mapped[str | None] = mapped_column(String(500))
    unit: Mapped[str | None] = mapped_column(String(40))
    # demo / user_entered / imported_unverified / pca_verified / authoritative_provider
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    # Where the value came from (filename+row, form, reviewer action, ...).
    source_reference: Mapped[str | None] = mapped_column(String(255))
    confidence: Mapped[str | None] = mapped_column(String(40))
    verified_by: Mapped[str | None] = mapped_column(String(120))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    effective_date: Mapped[date | None] = mapped_column(Date)
    supersedes_input_value_id: Mapped[int | None] = mapped_column(
        ForeignKey("decision_input_values.id")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)

    planned_spray: Mapped["PlannedSpray"] = relationship(back_populates="input_values")


class DecisionAuditEvent(Base):
    """One append-only audit event on a pre-spray decision. NEVER updated or deleted.

    Reviews/outcomes still update the PlannedSpray's current-state columns, but every
    change appends one of these first, with the prior state in `before` — so history
    is immutable even though the current-state row is convenient to read.
    """
    __tablename__ = "decision_audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    planned_spray_id: Mapped[int] = mapped_column(
        ForeignKey("planned_sprays.id"), nullable=False
    )
    # created / reviewed / outcome_recorded / input_value_superseded / follow_up_added
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    actor: Mapped[str | None] = mapped_column(String(120))
    rationale: Mapped[str | None] = mapped_column(Text)
    # The engine's outcome at the moment of this event (what the human saw).
    system_recommendation: Mapped[str | None] = mapped_column(String(30))
    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)

    planned_spray: Mapped["PlannedSpray"] = relationship(back_populates="audit_events")


class DecisionFollowUpEvent(Base):
    """One append-only follow-up observation after a decision's recorded outcome.

    One-to-many per planned spray: the follow-up story is a timeline of events
    (scouting_observation / actual_application / rescue_application / harvest_outcome /
    yield_quality_outcome / note), never a single mutable record. Confirmed metrics are
    derived read-only from this timeline; earlier observations are never overwritten.
    """
    __tablename__ = "decision_follow_up_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    planned_spray_id: Mapped[int] = mapped_column(
        ForeignKey("planned_sprays.id"), nullable=False
    )
    # scouting_observation / actual_application / rescue_application / harvest_outcome /
    # yield_quality_outcome / note
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    observed_at: Mapped[date] = mapped_column(Date, nullable=False)
    severity: Mapped[int | None] = mapped_column(Integer)
    severity_scale: Mapped[str | None] = mapped_column(String(40))
    actual_product: Mapped[str | None] = mapped_column(String(200))
    actual_rate_amount: Mapped[float | None] = mapped_column(Float)
    actual_rate_unit: Mapped[str | None] = mapped_column(String(40))
    actual_treated_acres: Mapped[float | None] = mapped_column(Float)
    cost: Mapped[float | None] = mapped_column(Float)
    rescue_required: Mapped[bool | None] = mapped_column(Boolean)
    # positive / neutral / negative / unknown
    yield_impact: Mapped[str | None] = mapped_column(String(20))
    quality_impact: Mapped[str | None] = mapped_column(String(20))
    rejected_or_downgraded: Mapped[bool | None] = mapped_column(Boolean)
    evidence_notes: Mapped[str | None] = mapped_column(Text)
    entered_by: Mapped[str | None] = mapped_column(String(120))
    # demo / user_entered / imported_unverified / pca_verified / authoritative_provider
    source_type: Mapped[str | None] = mapped_column(String(40))
    source_reference: Mapped[str | None] = mapped_column(String(255))
    confidence: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)

    planned_spray: Mapped["PlannedSpray"] = relationship(back_populates="follow_up_events")


class AiJudgment(Base):
    """One append-only record of an AI output (extraction, risk note, evidence action).

    NEVER updated or deleted. Every AI suggestion is logged with its model, prompt
    version, an input digest, its confidence, and whether it abstained — so that once
    real outcomes exist, predictions can be compared against reality (calibration)
    instead of being taken on faith. AI outputs are suggestions for humans and inputs
    to the deterministic engine; they never decide anything, and judgments are never
    fabricated (no seeded/demo judgments).
    """
    __tablename__ = "ai_judgments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # extraction / risk_note / next_evidence_action
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    farm_id: Mapped[int | None] = mapped_column(Integer)
    planned_spray_id: Mapped[int | None] = mapped_column(Integer)
    model_id: Mapped[str] = mapped_column(String(80), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(40), nullable=False)
    # sha256 of the exact inputs sent to the model (reproducibility / audit).
    input_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    output: Mapped[dict | None] = mapped_column(JSON)
    # low / medium / high / none (none when the judgment abstained)
    confidence: Mapped[str] = mapped_column(String(20), default="none")
    abstained: Mapped[bool] = mapped_column(Boolean, default=False)
    abstain_reason: Mapped[str | None] = mapped_column(Text)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)


class PcaPolicy(Base):
    """A PCA-entered action threshold for one target on one farm.

    "Treat <target> only when scouting severity >= <min_severity_to_treat>." The
    decision engine reads it in the scouting-evidence rule with
    source_authority="pca_entered" and the entered_by attribution — Lumos NEVER
    invents a threshold; without a policy the rule stays a plain heuristic.
    Latest row per (farm, target) wins, mirroring SprayBaseline.
    """
    __tablename__ = "pca_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), nullable=False)
    target_pest_or_disease: Mapped[str] = mapped_column(String(200), nullable=False)
    min_severity_to_treat: Mapped[int] = mapped_column(Integer, nullable=False)
    entered_by: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)
    # Provenance (mirrors SprayEvent).
    data_source: Mapped[str | None] = mapped_column(String(40), default="manual_entry")
    data_confidence: Mapped[str | None] = mapped_column(String(40), default="user_provided")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)

    farm: Mapped["Farm"] = relationship(back_populates="pca_policies")


class PcaCredential(Base):
    """A licensed PCA who may record dispositions, and the farms they may act on.

    Everywhere else in this system a PCA is a free-text string (`reviewed_by`,
    `entered_by`, `actor`) — unvalidated, uncorrelated, and impossible to hold to
    account. That is tolerable for advisory notes; it is not tolerable for a
    professional decision that authorizes deferring a scheduled fungicide.

    This is deliberately NOT authentication: there is no login, no session, no
    password, and no user model. An operator issues a token out of band; only its
    sha256 is stored, so a database leak does not yield usable tokens. Authorization
    is farm-scoped through PcaFarmAuthorization, and because `farm_id` is this
    system's only isolation boundary, that scoping IS the tenant boundary.
    """
    __tablename__ = "pca_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    # The professional licence this credential claims. Recorded and shown verbatim;
    # Lumos does NOT verify it against any registry — see BOTRYTIS_PILOT.md.
    license_identifier: Mapped[str] = mapped_column(String(60), nullable=False)
    license_state: Mapped[str] = mapped_column(String(2), default="CA")
    # sha256 of the issued token. The token itself is shown once at issuance and is
    # never stored, logged, or recoverable.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    # First few characters, so an operator can tell two tokens apart in the UI
    # without the system holding anything that could be replayed.
    token_prefix: Mapped[str | None] = mapped_column(String(12))
    issued_by: Mapped[str | None] = mapped_column(String(120))
    active_from: Mapped[date | None] = mapped_column(Date)
    active_to: Mapped[date | None] = mapped_column(Date)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)

    authorizations: Mapped[list["PcaFarmAuthorization"]] = relationship(
        back_populates="credential", cascade="all, delete-orphan"
    )


class PcaFarmAuthorization(Base):
    """Which farms one PCA credential may act on. Revoked, never deleted."""
    __tablename__ = "pca_farm_authorizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pca_credential_id: Mapped[int] = mapped_column(
        ForeignKey("pca_credentials.id"), nullable=False, index=True
    )
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), nullable=False, index=True)
    granted_on: Mapped[date | None] = mapped_column(Date)
    granted_by: Mapped[str | None] = mapped_column(String(120))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)

    credential: Mapped["PcaCredential"] = relationship(back_populates="authorizations")


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)

    farm: Mapped["Farm"] = relationship(back_populates="spray_baselines")


class PilotFeedback(Base):
    """Feedback captured after a demo with a grower / PCA / agronomist / etc.

    Not tied to a farm — it records pilot signals and discovery answers.
    """
    __tablename__ = "pilot_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)
    # check_started / check_completed / check_abandoned / review_recorded /
    # outcome_recorded / import_used
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    farm_id: Mapped[int | None] = mapped_column(Integer)
    planned_spray_id: Mapped[int | None] = mapped_column(Integer)
    # How the data got in: manual_form / csv_paste / concierge / seed ...
    entry_source: Mapped[str | None] = mapped_column(String(40))
    meta: Mapped[dict | None] = mapped_column(JSON)


class InputPlan(Base):
    """What a farm intends to purchase — the plan IS the RFQ (Inputs & finance v1).

    Status carries the whole RFQ lifecycle (see app/procurement_status.py); header
    and items are mutable only while `draft`. "Financing requested" is a flag here,
    never an offer row — a request is structurally incapable of looking like an
    approval. No money moves anywhere in this module.
    """
    __tablename__ = "input_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), nullable=False, index=True)
    # draft / submitted_for_quotes / quoted / quote_selected / ordered / cancelled
    status: Mapped[str] = mapped_column(String(30), default=procurement_status.PLAN_DRAFT)
    requested_by: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)
    financing_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    financing_requested_by: Mapped[str | None] = mapped_column(String(120))
    financing_notes: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    submitted_by: Mapped[str | None] = mapped_column(String(120))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime)
    cancelled_reason: Mapped[str | None] = mapped_column(Text)
    # Soft reference to supplier_quotes.id (no FK constraint — the quote table
    # already FKs back to this one and SQLite can't ALTER in the reverse edge).
    selected_quote_id: Mapped[int | None] = mapped_column(Integer)
    selected_by: Mapped[str | None] = mapped_column(String(120))
    # Why THIS quote — always entered by the human selecting it, never inferred.
    selection_reason: Mapped[str | None] = mapped_column(Text)
    # Concierge-pilot provenance (see SprayEvent for the allowed values).
    data_source: Mapped[str | None] = mapped_column(String(40), default="manual_entry")
    data_confidence: Mapped[str | None] = mapped_column(String(40), default="user_provided")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)

    farm: Mapped["Farm"] = relationship(back_populates="input_plans")
    items: Mapped[list["InputPlanItem"]] = relationship(
        back_populates="input_plan", cascade="all, delete-orphan"
    )
    quotes: Mapped[list["SupplierQuote"]] = relationship(
        back_populates="input_plan", cascade="all, delete-orphan"
    )
    order: Mapped["PurchaseOrder | None"] = relationship(
        back_populates="input_plan", uselist=False
    )
    events: Mapped[list["InputPlanEvent"]] = relationship(
        back_populates="input_plan",
        cascade="all, delete-orphan",
        order_by="(InputPlanEvent.created_at, InputPlanEvent.id)",
    )

    @property
    def financing_state(self) -> str:
        offers = [o for q in (self.quotes or []) for o in (q.financing_offers or [])]
        return procurement_status.financing_state(self, offers, clock.current_date())

    @property
    def quote_count(self) -> int:
        return sum(
            1 for q in (self.quotes or [])
            if q.status != procurement_status.QUOTE_WITHDRAWN
        )

    @property
    def order_id(self) -> int | None:
        return self.order.id if self.order is not None else None

    @property
    def needed_by(self) -> date | None:
        dates = [i.needed_by_date for i in (self.items or []) if i.needed_by_date]
        return min(dates) if dates else None

    @property
    def overdue(self) -> bool:
        return procurement_status.procurement_overdue(
            self.needed_by,
            self.status,
            self.order.status if self.order is not None else None,
            clock.current_date(),
        )


class InputPlanItem(Base):
    """One input the plan asks suppliers to quote.

    Product fields are a SNAPSHOT at item creation (a later PCA edit to the source
    decision never silently rewrites an RFQ already sent out); `planned_spray_id`
    keeps the provenance link. Deletable only while the plan is draft; there is no
    update endpoint at all.
    """
    __tablename__ = "input_plan_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    input_plan_id: Mapped[int] = mapped_column(
        ForeignKey("input_plans.id"), nullable=False, index=True
    )
    # Source decision, when the item was created from a PCA-reviewed planned spray.
    planned_spray_id: Mapped[int | None] = mapped_column(
        ForeignKey("planned_sprays.id"), index=True
    )
    field_block: Mapped[str | None] = mapped_column(String(120))
    crop: Mapped[str | None] = mapped_column(String(100))
    # fungicide / insecticide / herbicide / miticide / fertilizer / adjuvant / other
    category: Mapped[str] = mapped_column(String(40), default="other")
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    active_ingredient: Mapped[str | None] = mapped_column(String(200))
    moa_group: Mapped[str | None] = mapped_column(String(40))
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(40), nullable=False)
    acres: Mapped[float | None] = mapped_column(Float)
    needed_by_date: Mapped[date] = mapped_column(Date, nullable=False)
    intended_use: Mapped[str | None] = mapped_column(String(200))
    estimated_cost: Mapped[float | None] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(120))
    data_source: Mapped[str | None] = mapped_column(String(40), default="manual_entry")
    data_confidence: Mapped[str | None] = mapped_column(String(40), default="user_provided")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)

    input_plan: Mapped["InputPlan"] = relationship(back_populates="items")
    planned_spray: Mapped["PlannedSpray | None"] = relationship(
        back_populates="input_plan_items"
    )

    @property
    def source_decision_review_state(self) -> str:
        if self.planned_spray is None:
            return "not_linked"
        return decision_status.review_state(self.planned_spray)

    @property
    def source_decision_procurement_eligible(self) -> bool | None:
        if self.planned_spray is None:
            return None
        return decision_status.procurement_eligible(self.planned_spray)


class SupplierQuote(Base):
    """One supplier's quote against an input plan (concierge-entered in Phase 1).

    Never edited: a wrong quote is withdrawn and re-entered, so what the grower
    saw is preserved without a parallel audit system. There is no ranking column
    anywhere — quotes are returned in entry order and compared on transparent
    totals only (Lumos takes no commission and never ranks suppliers).
    """
    __tablename__ = "supplier_quotes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    input_plan_id: Mapped[int] = mapped_column(
        ForeignKey("input_plans.id"), nullable=False, index=True
    )
    supplier_name: Mapped[str] = mapped_column(String(200), nullable=False)
    supplier_contact: Mapped[str | None] = mapped_column(String(200))
    # submitted / selected / withdrawn (stored; expiry/not_selected are derived)
    status: Mapped[str] = mapped_column(String(20), default=procurement_status.QUOTE_SUBMITTED)
    delivery_cost: Mapped[float] = mapped_column(Float, default=0.0)
    fees: Mapped[float] = mapped_column(Float, default=0.0)
    payment_terms_cash: Mapped[str | None] = mapped_column(String(200))
    expected_delivery_date: Mapped[date | None] = mapped_column(Date)
    # in_stock / partial / backordered / unknown
    availability: Mapped[str] = mapped_column(String(20), default="unknown")
    expires_on: Mapped[date | None] = mapped_column(Date)
    # concierge_entered / supplier_confirmed (simulated-ness lives in provenance)
    verification: Mapped[str] = mapped_column(String(30), default="concierge_entered")
    notes: Mapped[str | None] = mapped_column(Text)
    entered_by: Mapped[str | None] = mapped_column(String(120))
    data_source: Mapped[str | None] = mapped_column(String(40), default="manual_entry")
    data_confidence: Mapped[str | None] = mapped_column(String(40), default="user_provided")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)

    input_plan: Mapped["InputPlan"] = relationship(back_populates="quotes")
    items: Mapped[list["SupplierQuoteItem"]] = relationship(
        back_populates="supplier_quote", cascade="all, delete-orphan"
    )
    financing_offers: Mapped[list["FinancingOffer"]] = relationship(
        back_populates="supplier_quote", cascade="all, delete-orphan"
    )

    @property
    def items_subtotal(self) -> float:
        return round(sum(i.quantity * i.unit_price for i in (self.items or [])), 2)

    @property
    def total_cost(self) -> float:
        return round(self.items_subtotal + (self.delivery_cost or 0) + (self.fees or 0), 2)

    @property
    def quote_state(self) -> str:
        return procurement_status.quote_state(self, self.input_plan, clock.current_date())


class SupplierQuoteItem(Base):
    """One quoted line, keyed to the requested input-plan item it answers."""
    __tablename__ = "supplier_quote_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    supplier_quote_id: Mapped[int] = mapped_column(
        ForeignKey("supplier_quotes.id"), nullable=False, index=True
    )
    input_plan_item_id: Mapped[int] = mapped_column(
        ForeignKey("input_plan_items.id"), nullable=False, index=True
    )
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_substitution: Mapped[bool] = mapped_column(Boolean, default=False)
    substitution_reason: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(40), nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    supplier_quote: Mapped["SupplierQuote"] = relationship(back_populates="items")

    @property
    def line_total(self) -> float:
        return round(self.quantity * self.unit_price, 2)


class FinancingOffer(Base):
    """A manually entered INDICATIVE financing offer against one supplier quote.

    Phase 1 never moves money: no underwriting, no origination, no repayment
    collection. An offer is created `indicative`; the grower's accept/decline is
    one-shot; `expired` is derived from expires_on and never stored, so a stale
    offer can never be accepted. Every serialized offer carries the disclaimer.
    """
    __tablename__ = "financing_offers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    supplier_quote_id: Mapped[int] = mapped_column(
        ForeignKey("supplier_quotes.id"), nullable=False, index=True
    )
    provider_name: Mapped[str] = mapped_column(String(200), nullable=False)
    requested_amount: Mapped[float] = mapped_column(Float, nullable=False)
    down_payment: Mapped[float] = mapped_column(Float, default=0.0)
    financed_amount: Mapped[float] = mapped_column(Float, nullable=False)
    total_repayment: Mapped[float] = mapped_column(Float, nullable=False)
    fees_total: Mapped[float] = mapped_column(Float, default=0.0)
    schedule_summary: Mapped[str | None] = mapped_column(String(300))
    expires_on: Mapped[date | None] = mapped_column(Date)
    required_documents: Mapped[str | None] = mapped_column(Text)
    conditions: Mapped[str | None] = mapped_column(Text)
    # indicative / selected / declined / withdrawn (expired is derived, never stored)
    status: Mapped[str] = mapped_column(String(20), default=procurement_status.OFFER_INDICATIVE)
    decided_by: Mapped[str | None] = mapped_column(String(120))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    decision_notes: Mapped[str | None] = mapped_column(Text)
    entered_by: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)
    data_source: Mapped[str | None] = mapped_column(String(40), default="manual_entry")
    data_confidence: Mapped[str | None] = mapped_column(String(40), default="user_provided")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)

    supplier_quote: Mapped["SupplierQuote"] = relationship(back_populates="financing_offers")

    @property
    def offer_state(self) -> str:
        return procurement_status.offer_state(self, clock.current_date())


class PurchaseOrder(Base):
    """The order created from a plan's selected quote (one per plan in Phase 1).

    Order lines are the selected quote's items — there is no separate item table.
    `status` is a convenient current-state column mutated ONLY by event-appending
    crud (same pattern as PlannedSpray's columns + DecisionAuditEvent): every
    change appends an OrderEvent first. `spray_event_id`/`applied_planned_spray_id`
    are set ONLY by the explicit input-applied endpoint — delivery alone never
    marks an input as applied.
    """
    __tablename__ = "purchase_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), nullable=False, index=True)
    input_plan_id: Mapped[int] = mapped_column(
        ForeignKey("input_plans.id"), nullable=False, unique=True, index=True
    )
    selected_quote_id: Mapped[int] = mapped_column(
        ForeignKey("supplier_quotes.id"), nullable=False
    )
    # The SELECTED indicative offer (status "selected"). Column name predates the
    # accepted→selected vocabulary correction; renaming it is deferred debt (see
    # ENGINEERING_GUIDELINES.md follow-ups) — the stored status and all user-visible copy already
    # say "selected".
    accepted_financing_offer_id: Mapped[int | None] = mapped_column(
        ForeignKey("financing_offers.id")
    )
    # placed / confirmed / shipped / delivered / partially_delivered / cancelled
    status: Mapped[str] = mapped_column(String(30), default=procurement_status.ORDER_PLACED)
    spray_event_id: Mapped[int | None] = mapped_column(ForeignKey("spray_events.id"))
    applied_planned_spray_id: Mapped[int | None] = mapped_column(
        ForeignKey("planned_sprays.id")
    )
    placed_by: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)
    data_source: Mapped[str | None] = mapped_column(String(40), default="manual_entry")
    data_confidence: Mapped[str | None] = mapped_column(String(40), default="user_provided")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)

    farm: Mapped["Farm"] = relationship(back_populates="purchase_orders")
    input_plan: Mapped["InputPlan"] = relationship(back_populates="order")
    selected_quote: Mapped["SupplierQuote"] = relationship(
        foreign_keys=[selected_quote_id]
    )
    accepted_financing_offer: Mapped["FinancingOffer | None"] = relationship(
        foreign_keys=[accepted_financing_offer_id]
    )
    events: Mapped[list["OrderEvent"]] = relationship(
        back_populates="purchase_order", cascade="all, delete-orphan"
    )

    @property
    def supplier_name(self) -> str | None:
        return self.selected_quote.supplier_name if self.selected_quote else None

    @property
    def total_cost(self) -> float | None:
        return self.selected_quote.total_cost if self.selected_quote else None

    @property
    def overdue(self) -> bool:
        plan = self.input_plan
        return procurement_status.procurement_overdue(
            plan.needed_by if plan is not None else None,
            plan.status if plan is not None else None,
            self.status,
            clock.current_date(),
        )


class OrderEvent(Base):
    """One append-only event on a purchase order. NEVER updated or deleted.

    The order's lifecycle IS this timeline; the PurchaseOrder.status column is a
    read convenience kept in sync by crud. `occurred_on` is the real-world date;
    `created_at` is when it was entered (mirrors DecisionFollowUpEvent).
    """
    __tablename__ = "order_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    purchase_order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id"), nullable=False, index=True
    )
    # created / quote_selected / financing_selected / supplier_confirmed / shipped /
    # delivered / partially_delivered / cancelled / input_applied / exception_reported
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False)
    actor: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)
    # Linked ids / amounts detail (quote_id, offer_id, spray_event_id, ...).
    payload: Mapped[dict | None] = mapped_column(JSON)
    data_source: Mapped[str | None] = mapped_column(String(40), default="manual_entry")
    data_confidence: Mapped[str | None] = mapped_column(String(40), default="user_provided")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)

    purchase_order: Mapped["PurchaseOrder"] = relationship(back_populates="events")


class InputPlanEvent(Base):
    """One append-only audit event on an input plan. NEVER updated or deleted.

    The plan's user-decision history IS this timeline; InputPlan's status /
    selected_quote_id / selection_reason columns are read conveniences kept in
    sync by crud (the OrderEvent pattern). A dedicated table exists because the
    decision audit trail (DecisionAuditEvent) is keyed to a non-null
    planned_spray_id with decision-specific vocabulary — a plan can exist with no
    decision link, or link several — and OrderEvent requires an order, which does
    not exist yet for pre-order actions. Farm scoping comes through the plan;
    demo/real separation through the inherited provenance columns.
    """
    __tablename__ = "input_plan_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    input_plan_id: Mapped[int] = mapped_column(
        ForeignKey("input_plans.id"), nullable=False, index=True
    )
    # submitted / quote_selected / financing_offer_selected /
    # financing_offer_declined / ordered / cancelled
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False)
    actor: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)
    # Prior/resulting state and linked ids (from_status, to_status, quote_id,
    # offer_id, reason, ...).
    payload: Mapped[dict | None] = mapped_column(JSON)
    data_source: Mapped[str | None] = mapped_column(String(40), default="manual_entry")
    data_confidence: Mapped[str | None] = mapped_column(String(40), default="user_provided")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)

    input_plan: Mapped["InputPlan"] = relationship(back_populates="events")


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
    # CSV pilot imports: what kind of records the batch carried and the file it came from.
    record_type: Mapped[str | None] = mapped_column(String(40))
    source_filename: Mapped[str | None] = mapped_column(String(255))
    # Set when the batch's rows came from an AI extraction (links to the judgment log).
    ai_judgment_id: Mapped[int | None] = mapped_column(ForeignKey("ai_judgments.id"))
    spray_event_count: Mapped[int] = mapped_column(Integer, default=0)
    scouting_observation_count: Mapped[int] = mapped_column(Integer, default=0)
    planned_spray_count: Mapped[int] = mapped_column(Integer, default=0)
    # Pilot record types (weather readings and standardized scouting samples).
    weather_observation_count: Mapped[int] = mapped_column(Integer, default=0)
    scouting_sample_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)

    farm: Mapped["Farm"] = relationship(back_populates="pilot_import_batches")
