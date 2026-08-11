"""SQLAlchemy ORM models for Lumos Spray Copilot."""
from datetime import date, datetime

from sqlalchemy import (
    JSON, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint, select,
)
from sqlalchemy.orm import Mapped, mapped_column, object_session, relationship

from app import clock, decision_status, procurement_status
from app.database import Base, partial_unique_index

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
    # An operator-run REFERENCE farm: real (non-demo) provenance, so a licensed PCA can
    # verify a label against it and the label-dependent checks can actually run — but
    # NOT a customer. It exists to demonstrate capability on real regulatory data.
    #
    # This is a third thing, and it needs its own column precisely because the existing
    # demo/real split cannot express it. `data_source="demo"` would make every label
    # verification simulated, which `label_data.promotable_to_authoritative` refuses —
    # so a reference farm must be real-mode. But real-mode alone would let its decisions
    # be counted as pilot evidence, which would be a traction claim about a farm that
    # has no grower. The flag keeps both facts true at once.
    is_reference: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    # ---- locale primitives (platform Phase 0)
    # Currency, timezone and jurisdiction were previously INFERRED from `country` in
    # main.py's display helpers ("$" if US else "TRY"). That inference is what makes a
    # second market a rewrite, so the facts are columns now. Backfilled from the old
    # rule, so no existing behaviour changes.
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id"), index=True
    )
    currency_code: Mapped[str | None] = mapped_column(String(3))
    timezone: Mapped[str | None] = mapped_column(String(60))
    jurisdiction_code: Mapped[str | None] = mapped_column(String(10))

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
    fields: Mapped[list["Field"]] = relationship(
        back_populates="farm", cascade="all, delete-orphan"
    )
    crop_cycles: Mapped[list["CropCycle"]] = relationship(
        back_populates="farm", cascade="all, delete-orphan"
    )
    organization: Mapped["Organization | None"] = relationship(back_populates="farms")


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
    # ---- canonical spine links (platform Phase 0). NULLABLE and backfilled: reads
    # migrate to the spine gradually, and a record created by an older client is still
    # valid. See the "canonical spine" section at the end of this module.
    field_id: Mapped[int | None] = mapped_column(ForeignKey("fields.id"), index=True)
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

    # ---- canonical spine links (platform Phase 0). NULLABLE and backfilled;
    # reads migrate gradually. See the "canonical spine" section below.
    crop_cycle_id: Mapped[int | None] = mapped_column(ForeignKey("crop_cycles.id"), index=True)
    field_id: Mapped[int | None] = mapped_column(ForeignKey("fields.id"), index=True)
    operation_id: Mapped[int | None] = mapped_column(ForeignKey("operations.id"), index=True)
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # EPA registration number, when known. This is the join key to a product's label
    # record: without it a past application cannot be tied to a product identity, so
    # the label's seasonal-count and retreatment-interval checks cannot see it at all.
    epa_reg_no: Mapped[str | None] = mapped_column(String(60))
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

    # ---- canonical spine links (platform Phase 0). NULLABLE and backfilled;
    # reads migrate gradually. See the "canonical spine" section below.
    crop_cycle_id: Mapped[int | None] = mapped_column(ForeignKey("crop_cycles.id"), index=True)
    field_id: Mapped[int | None] = mapped_column(ForeignKey("fields.id"), index=True)
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

    No weather has ever been persisted in this system: `app/advisory_weather.py` computes an
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

    Ingestion is CSV/concierge OR a registered provider adapter (`app/ingest/`). A
    provider-written row is distinguishable at a glance and by query: `source_type` is
    `station_export`, `data_source` is `provider_api`, `data_confidence` is
    `provider_reported`, and `ingestion_run_id` points at the run that wrote it.
    """
    __tablename__ = "weather_observations"
    __table_args__ = (
        # At most ONE original reading per farm per station per timestamp. A duplicated
        # hour would double-count wetness inside a risk window and silently change a
        # snapshot digest, so this is enforced by the database rather than trusted to
        # the import's dedupe.
        #
        # SCOPED BY FARM because a public station serves many farms: two growers
        # subscribing to the same CIMIS station must both be able to hold that hour,
        # and without `farm_id` the second one's insert simply fails. It is also the
        # semantically right key — `station_distance_km` is measured to THIS farm's
        # field, so the same station-hour is genuinely different evidence for a farm
        # 2 km away than for one 14 km away.
        #
        # PARTIAL (supersedes_id IS NULL) because corrections deliberately repeat the
        # station+timestamp of the row they replace — a plain unique index would make
        # the append-only correction path impossible.
        partial_unique_index(
            "uq_weather_observation_station_hour",
            "farm_id", "station_id", "observed_at",
            where="supersedes_id IS NULL",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), nullable=False, index=True)

    # ---- canonical spine links (platform Phase 0). NULLABLE and backfilled;
    # reads migrate gradually. See the "canonical spine" section below.
    field_id: Mapped[int | None] = mapped_column(ForeignKey("fields.id"), index=True)
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
    # Which ingestion run wrote this row, when a provider adapter did. A join rather
    # than a string stuffed into `source_reference`: the audit question is "what else
    # did that run write, and what did it drop", which a free-text field cannot answer.
    # Deliberately NOT serialized by `risk_snapshot._weather_payload`, so adding it
    # leaves every stored snapshot digest byte-identical.
    ingestion_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("ingestion_runs.id"), index=True
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

    # ---- canonical spine links (platform Phase 0). NULLABLE and backfilled;
    # reads migrate gradually. See the "canonical spine" section below.
    crop_cycle_id: Mapped[int | None] = mapped_column(ForeignKey("crop_cycles.id"), index=True)
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
    # Which admissibility rule produced this row: point_in_time (both timestamps, the
    # proof-grade basis the live pilot uses) or retrospective_reconstruction
    # (observed_at only, the historical scan's weaker basis). Nullable with a
    # point-in-time default so every row written before this column existed reads
    # correctly — they were all point-in-time, because nothing else could build one.
    # See `app/risk_snapshot.py` for why the two must never be confused.
    basis: Mapped[str | None] = mapped_column(
        String(40), default="point_in_time", index=True
    )
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


class OpportunityScan(Base):
    """One historical opportunity scan over a past season. Append-only.

    Deliberately NOT a flag on `DiseaseRiskAssessment`. That table is the prospective
    pilot's record of what a rule said about an upcoming spray, and the pilot's central
    design commitment is keeping four moments strictly separate (see `PcaDisposition`).
    A retrospective scan is a fifth thing: it reads a weaker snapshot basis, it makes a
    weaker claim, and its rows must never be counted in a calibration join or appear in
    a PCA-facing serializer. Giving it its own table makes all of that true by
    construction rather than by a WHERE clause somebody has to remember.

    There is no avoided-spray column and no reduction column, mirroring
    `backtest.ScanResult`. A scan cannot express that a spray was avoidable, because
    every historical outcome followed the actual spray.
    """
    __tablename__ = "opportunity_scans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), nullable=False, index=True)
    block_id: Mapped[int] = mapped_column(ForeignKey("blocks.id"), nullable=False, index=True)

    scan_version: Mapped[str] = mapped_column(String(40), nullable=False)
    model_version: Mapped[str] = mapped_column(String(60), nullable=False)
    target: Mapped[str] = mapped_column(String(80), nullable=False)
    # Always retrospective_reconstruction today. Stored rather than assumed so a future
    # point-in-time scan (possible once a farm has been ingesting prospectively for a
    # season) is distinguishable from this one without reading the code that wrote it.
    basis: Mapped[str] = mapped_column(String(40), nullable=False, index=True)

    horizon_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    lookback_hours: Mapped[int] = mapped_column(Integer, nullable=False)

    dates_scanned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    assessed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    band_counts: Mapped[dict | None] = mapped_column(JSON)
    # The useful output while the threshold table is empty: a per-farm work list of
    # exactly what stopped each date from being assessable.
    reason_counts: Mapped[dict | None] = mapped_column(JSON)
    grade_counts: Mapped[dict | None] = mapped_column(JSON)

    run_by: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)

    items: Mapped[list["OpportunityScanItem"]] = relationship(
        back_populates="scan", cascade="all, delete-orphan"
    )


class OpportunityScanItem(Base):
    """One replayed decision date within a scan. Append-only.

    Carries its snapshot digest so a reader can reproduce the inputs behind any single
    date — the same auditability property `RiskInputSnapshot` gives the live pilot.
    """
    __tablename__ = "opportunity_scan_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_id: Mapped[int] = mapped_column(
        ForeignKey("opportunity_scans.id"), nullable=False, index=True
    )
    as_of: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    risk_band: Mapped[str] = mapped_column(String(20), nullable=False)
    abstained: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Every reason, not just the first.
    reasons: Mapped[list | None] = mapped_column(JSON)
    evidence_grade: Mapped[str | None] = mapped_column(String(2))
    probability_or_index: Mapped[float | None] = mapped_column(Float)
    input_digest: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    excluded_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    scan: Mapped["OpportunityScan"] = relationship(back_populates="items")


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
        partial_unique_index(
            "uq_pca_disposition_live_per_decision",
            "planned_spray_id",
            where="supersedes_id IS NULL",
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


class PilotProtocol(Base):
    """A versioned reference to the pilot protocol document. Deliberately thin.

    This is NOT a protocol-authoring tool. The protocol is a document that humans
    agree on; this row records which version was in force, what it declared as its
    primary metric, and how blocks were assigned — so a result can never be read
    without knowing the rules it was collected under.

    `assignment_method` is load-bearing for honesty: only `randomized` or `matched`
    can support a comparison, and `observational` must produce descriptive counts with
    an explicit "not a controlled comparison" note.

    `unblinded_at` is the ONLY thing that lifts shadow mode. It is a recorded,
    protocol-versioned event with a date — not a config toggle or an environment
    variable — because when the PCA started seeing risk output is itself part of the
    pilot's evidence.
    """
    __tablename__ = "pilot_protocols"
    __table_args__ = (
        partial_unique_index(
            "uq_pilot_protocol_active_version",
            "farm_id", "version",
            where="effective_to IS NULL",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Where the actual protocol lives (doc URL, signed PDF reference, ticket).
    document_reference: Mapped[str | None] = mapped_column(Text)
    assignment_method: Mapped[str] = mapped_column(String(20), nullable=False)
    target: Mapped[str] = mapped_column(String(80), nullable=False)
    primary_metric: Mapped[str] = mapped_column(String(120), nullable=False)
    secondary_metrics: Mapped[list | None] = mapped_column(JSON)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    unblinded_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)
    data_source: Mapped[str] = mapped_column(String(40), default="manual_entry")
    data_confidence: Mapped[str] = mapped_column(String(40), default="user_provided")


class BlockAssignment(Base):
    """Which arm a block belongs to under one protocol version.

    Randomization is performed offline (a PCA with a spreadsheet and a seed, not a
    button in this app), and the seed plus method are recorded so the assignment is
    reproducible and auditable years later.

    An assignment is never edited. Changing arms mid-pilot invalidates the comparison,
    so a genuine change means a new protocol version with its own assignments.
    """
    __tablename__ = "block_assignments"
    __table_args__ = (
        Index(
            "uq_block_assignment_per_protocol",
            "pilot_protocol_id", "block_id",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pilot_protocol_id: Mapped[int] = mapped_column(
        ForeignKey("pilot_protocols.id"), nullable=False, index=True
    )
    block_id: Mapped[int] = mapped_column(ForeignKey("blocks.id"), nullable=False, index=True)
    arm: Mapped[str] = mapped_column(String(20), nullable=False)
    matched_pair_key: Mapped[str | None] = mapped_column(String(60), index=True)
    assigned_on: Mapped[date] = mapped_column(Date, nullable=False)
    assigned_by: Mapped[str | None] = mapped_column(String(120))
    assignment_seed: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)
    data_source: Mapped[str] = mapped_column(String(40), default="manual_entry")
    data_confidence: Mapped[str] = mapped_column(String(40), default="user_provided")


class BlockOutcomeObservation(Base):
    """A measured outcome for one block at one time. Append-only.

    A SEPARATE model from DecisionFollowUpEvent, on purpose. Packout, cull and yield
    are measured per block per harvest — not per decision. One harvest outcome is
    evidence for many decisions and for none in particular, and
    DecisionFollowUpEvent.planned_spray_id is non-null, so forcing it there would
    repeat exactly the modelling error the procurement work already hit and fixed with
    InputPlanEvent (ENGINEERING_GUIDELINES.md section 5). Both models are kept; they are joined only
    in reporting.

    `unit` is required whenever `value` is present, and nothing here converts between
    units — an unlabelled number is not a measurement.
    """
    __tablename__ = "block_outcome_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    block_id: Mapped[int] = mapped_column(ForeignKey("blocks.id"), nullable=False, index=True)
    pilot_protocol_id: Mapped[int | None] = mapped_column(
        ForeignKey("pilot_protocols.id"), index=True
    )
    observed_on: Mapped[date] = mapped_column(Date, nullable=False)
    # Dual timestamps, same discipline as the observation models: when it happened and
    # when it was written down are different facts.
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime, default=clock.current_datetime, nullable=False
    )
    outcome_type: Mapped[str] = mapped_column(String(40), nullable=False)
    value: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(40))
    # e.g. berries inspected, trays harvested — the denominator a rate refers to.
    denominator: Mapped[float | None] = mapped_column(Float)
    method: Mapped[str | None] = mapped_column(String(80))
    notes: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[str | None] = mapped_column(String(40))
    supersedes_id: Mapped[int | None] = mapped_column(
        ForeignKey("block_outcome_observations.id")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)
    data_source: Mapped[str] = mapped_column(String(40), default="manual_entry")
    data_confidence: Mapped[str] = mapped_column(String(40), default="user_provided")


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

    # ---- canonical spine links (platform Phase 0). NULLABLE and backfilled;
    # reads migrate gradually. See the "canonical spine" section below.
    crop_cycle_id: Mapped[int | None] = mapped_column(ForeignKey("crop_cycles.id"), index=True)
    field_id: Mapped[int | None] = mapped_column(ForeignKey("fields.id"), index=True)
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
    def label_reference_stale(self) -> bool:
        """Has the label record this decision was checked against been revised since?

        The query only runs for a decision that actually cites a label record, so this
        costs nothing until label data exists for the product in question.
        """
        checked = decision_status.label_record_checked_against(self)
        session = object_session(self)
        if checked is None or session is None:
            return False
        superseding = session.scalar(
            select(ProductLabelRecord.id).where(
                ProductLabelRecord.supersedes_label_record_id == checked
            )
        )
        return decision_status.label_reference_stale(self, superseding)

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

    # ---- canonical spine links (platform Phase 0). NULLABLE and backfilled;
    # reads migrate gradually. See the "canonical spine" section below.
    crop_cycle_id: Mapped[int | None] = mapped_column(ForeignKey("crop_cycles.id"), index=True)
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
    # The structured link, added 2026-08-07. NULLABLE on purpose: `supplier_name` above
    # stays authoritative for what was actually entered, and a quote for a supplier
    # nobody has registered keeps working rather than being blocked or attached to a
    # guess. Same discipline as SprayEvent.treated_acres + treated_area_unit.
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), index=True)
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
    # The catalogue link, added 2026-08-07, and the reason `InputProduct` stopped being
    # an orphan. NULLABLE: an unlinked line is EXCLUDED from price dispersion and
    # counted, never bucketed by name — see procurement_analytics.build_report. Grouping
    # free text would report three spellings of one product as three products with no
    # spread each, which reads as "prices are consistent".
    input_product_id: Mapped[int | None] = mapped_column(
        ForeignKey("input_products.id"), index=True
    )
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


# --------------------------------------------------------------- pesticide labels
class PesticideProduct(Base):
    """A registered pesticide product — the identity that label records hang off.

    This is the first time this system knows what a product IS. Until now product
    identity was free text (`product_name` plus an optional `active_ingredient`,
    `epa_reg_no` and `moa_group`) duplicated independently across PlannedSpray,
    SprayEvent, InputPlanItem and two outcome columns, with nothing validating,
    deduplicating or cross-checking any of it. Four label-dependent checks in
    `decision_engine` cannot run without a product to look up.

    TWO registration columns, and the distinction is load-bearing:
      * `epa_reg_no_normalized` — the full number, hyphen structure preserved. The only
        thing that identifies one label.
      * `epa_reg_base` — the first two segments, i.e. the registrant's product family.
        Recorded so a near-miss can be RECOGNIZED, never so it can be matched. `100-1234`
        and `100-1234-5905` are different labels with different use directions, and
        applying the wrong one's PHI is the worst thing this feature could do.
    """
    __tablename__ = "pesticide_products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # As written on the label, for display.
    epa_reg_no: Mapped[str] = mapped_column(String(60), nullable=False)
    # Canonical join key (see app/label_data.normalize_epa_reg_no).
    epa_reg_no_normalized: Mapped[str] = mapped_column(
        String(60), nullable=False, unique=True, index=True
    )
    # First two segments only — for recognizing a related product, never for matching.
    epa_reg_base: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    registrant: Mapped[str | None] = mapped_column(String(200))
    active_ingredient: Mapped[str | None] = mapped_column(String(200))
    # Concentration with its unit in the column name, needed before any active-ingredient
    # quantity can be computed. Absent means the quantity metric stays not-calculated.
    active_ingredient_concentration_amount: Mapped[float | None] = mapped_column(Float)
    active_ingredient_concentration_unit: Mapped[str | None] = mapped_column(String(40))
    moa_group: Mapped[str | None] = mapped_column(String(40))
    # Set by a human who has transcribed EVERY registered crop from the label. Until then
    # the crop/use registration check must not run at all: the absence of a crop record is
    # not evidence the crop is unregistered, and a false BLOCK on a partial transcription
    # would destroy a PCA's trust in the feature permanently.
    registered_crops_transcription_complete: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)

    label_records: Mapped[list["ProductLabelRecord"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )


class ProductLabelRecord(Base):
    """One product's label directions for one registered crop. APPEND-ONLY.

    No update and no delete, and no mutable status column, because the supersede chain
    already expresses both things that happen to a label:
      * a REVISION is a new row with a later `label_effective_date` superseding the old;
      * a WITHDRAWAL is a new row with every regulatory value NULL and `withdrawal_reason`
        set, superseding the old. Resolution then finds no values and the dependent checks
        correctly go back to reporting that they did not run.
    A boolean `is_current` would have needed an UPDATE and could disagree with the dates.

    Every regulatory column is nullable because real labels state some values and not
    others. NULL means THE LABEL IS SILENT. It must never be read as "no limit" — that
    reading is the difference between a missing check and a fabricated clearance.
    """
    __tablename__ = "product_label_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("pesticide_products.id"), nullable=False, index=True
    )
    registered_crop: Mapped[str] = mapped_column(String(120), nullable=False)
    # Canonical form (app/crop_aliases.normalize) so the join does not depend on spelling.
    registered_crop_normalized: Mapped[str] = mapped_column(String(120), nullable=False)
    # The specific pest/disease these directions are for, when the label splits by target.
    target_pest_or_disease: Mapped[str | None] = mapped_column(String(200))

    pre_harvest_interval_days: Mapped[int | None] = mapped_column(Integer)
    re_entry_interval_hours: Mapped[int | None] = mapped_column(Integer)
    max_seasonal_rate_amount: Mapped[float | None] = mapped_column(Float)
    max_seasonal_rate_unit: Mapped[str | None] = mapped_column(String(40))
    max_applications_per_season: Mapped[int | None] = mapped_column(Integer)
    min_retreatment_interval_days: Mapped[int | None] = mapped_column(Integer)

    # Which revision of the label this is, and from when. Without both, a reader cannot
    # tell whether this describes the label in the applicator's hand today.
    label_version: Mapped[str | None] = mapped_column(String(120))
    label_effective_date: Mapped[date | None] = mapped_column(Date)
    # How this record was obtained (app/label_data.LABEL_SOURCE_TIERS). Deliberately a
    # separate vocabulary from a decision input value's source_type.
    source_tier: Mapped[str] = mapped_column(String(40), nullable=False)
    source_document_reference: Mapped[str | None] = mapped_column(String(400))
    source_section_or_page: Mapped[str | None] = mapped_column(String(200))
    # Verbatim text of the directions being transcribed — what a PCA checks against.
    source_snippet: Mapped[str | None] = mapped_column(Text)
    transcribed_by: Mapped[str | None] = mapped_column(String(120))
    transcribed_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Content address of the transcribed fields, so the loader is idempotent without
    # ever issuing an UPDATE (unchanged digest = no-op; changed digest = new row).
    transcription_digest: Mapped[str | None] = mapped_column(String(64), index=True)
    # Set only on a withdrawal row (all regulatory values NULL).
    withdrawal_reason: Mapped[str | None] = mapped_column(Text)
    supersedes_label_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_label_records.id"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)

    product: Mapped["PesticideProduct"] = relationship(back_populates="label_records")
    verifications: Mapped[list["ProductLabelVerification"]] = relationship(
        back_populates="label_record", cascade="all, delete-orphan"
    )


class ProductLabelVerification(Base):
    """A licensed PCA attesting that one label record matches the primary document.

    APPEND-ONLY; revocation is a timestamp, never a delete, so a decision that relied on
    this attestation stays attributable after it is withdrawn (same rule as PcaCredential).

    FARM-SCOPED, which is the design decision worth reading twice. A global "this record
    is verified" flag would have needed a second, weaker authorization path alongside
    `crud.require_pca_for_farm`, and would let a PCA authorized for one farm silently
    vouch for every other farm's decisions. Scoping it to a farm means:
      * the existing single authorization entry point covers it;
      * `ensure_demo_real_separation` covers it, because it is a farm record — so a demo
        farm can only ever hold a `simulated` verification, and
        `label_data.promotable_to_authoritative` refuses to promote from one. Demo
        decisions therefore can never display a label-grounded verdict, which keeps the
        demo honest without a single special case in the engine.
    """
    __tablename__ = "product_label_verifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_label_record_id: Mapped[int] = mapped_column(
        ForeignKey("product_label_records.id"), nullable=False, index=True
    )
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), nullable=False, index=True)
    # NOT NULL: an unattributed attestation is not a professional act.
    verified_by_credential_id: Mapped[int] = mapped_column(
        ForeignKey("pca_credentials.id"), nullable=False
    )
    # Display name resolved from the credential, never a client-supplied string.
    verified_by: Mapped[str | None] = mapped_column(String(120))
    verified_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)
    # What the PCA is attesting to, in their words (e.g. which revision and page).
    attestation: Mapped[str] = mapped_column(Text, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    data_source: Mapped[str | None] = mapped_column(String(40), default="manual_entry")
    data_confidence: Mapped[str | None] = mapped_column(String(40), default="user_provided")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)

    label_record: Mapped["ProductLabelRecord"] = relationship(back_populates="verifications")


# ============================================================ platform infrastructure
# Everything below this line is substrate, not domain: stored documents and the job
# queue. They carry no agronomic or financial meaning and are deliberately generic —
# a domain concept that needs one of these references it, never the other way round.


class Document(Base):
    """A stored document: the pointer, the hash, and what it is evidence of.

    The bytes live in object storage (see `app/storage.py`); this row is how the rest of
    the system finds and verifies them. `sha256` is stored redundantly with the key so a
    citation can be checked without a round trip, and so an object whose bytes changed
    is detectable rather than merely unlikely.

    `subject_type`/`subject_id` are a deliberate soft polymorphic reference rather than
    a dozen nullable foreign keys: a document can be evidence for a label record, a soil
    test, a parcel's ownership, an insurance policy, or an ingestion run, and that list
    will keep growing. The cost is no referential integrity on that edge; the benefit is
    that adding a new subject kind is not a migration.
    """
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Object-storage key. Content-addressed: contains the sha256 (see storage.content_key).
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    filename: Mapped[str | None] = mapped_column(String(300))
    content_type: Mapped[str | None] = mapped_column(String(120))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    # Soft reference to whatever this document is evidence for.
    subject_type: Mapped[str | None] = mapped_column(String(60), index=True)
    subject_id: Mapped[int | None] = mapped_column(Integer, index=True)
    farm_id: Mapped[int | None] = mapped_column(ForeignKey("farms.id"), index=True)
    uploaded_by: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)
    data_source: Mapped[str | None] = mapped_column(String(40), default="manual_entry")
    data_confidence: Mapped[str | None] = mapped_column(String(40), default="user_provided")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)


class Job(Base):
    """One unit of background work: current state, mutated only by the queue.

    The queue is the database. That is a deliberate choice over Redis/Celery: the
    platform needs exactly one durable, transactional place where "this ingestion window
    has already been processed" is true, and adding a second datastore to get a queue
    would mean that fact lives somewhere that can disagree with the rows it produced.
    Postgres `FOR UPDATE SKIP LOCKED` makes this correct under concurrent workers, and
    `app/jobs/queue.py` is a thin enough seam to swap if throughput ever demands it.

    `idempotency_key` is what makes a job safe to enqueue twice — a scheduler that fires
    late, a retry, a duplicate webhook. It is unique across LIVE jobs only (partial
    index), because a key must be re-usable once the work it named has finished.
    """
    __tablename__ = "jobs"
    __table_args__ = (
        partial_unique_index(
            "uq_job_live_idempotency_key",
            "idempotency_key",
            where="status IN ('pending', 'running')",
        ),
        Index("ix_job_claimable", "status", "run_at", "priority"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    queue: Mapped[str] = mapped_column(String(40), nullable=False, default="default", index=True)
    task_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    payload: Mapped[dict | None] = mapped_column(JSON)
    idempotency_key: Mapped[str | None] = mapped_column(String(200))
    # pending / running / succeeded / failed / dead
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    # Lower runs first. Monitoring beats nightly recomputation.
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    # Earliest time this may run: scheduling and retry backoff are the same mechanism.
    run_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=clock.current_datetime)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    # Which data source this job belongs to, when it is an ingestion job. Lets the
    # operator console answer "is the weather feed healthy" without parsing task names.
    source_key: Mapped[str | None] = mapped_column(String(80), index=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime)
    locked_by: Mapped[str | None] = mapped_column(String(120))
    last_error: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)

    runs: Mapped[list["JobRun"]] = relationship(
        back_populates="job", cascade="all, delete-orphan",
        order_by="(JobRun.attempt, JobRun.id)",
    )

    @property
    def is_terminal(self) -> bool:
        return self.status in ("succeeded", "dead")


class JobRun(Base):
    """One attempt at a job. Append-only — a retry is a new row, never an overwrite.

    Without this, a job that failed four times and succeeded on the fifth looks exactly
    like a job that succeeded first time, and "is this feed actually healthy" becomes
    unanswerable.
    """
    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), nullable=False, index=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    worker_id: Mapped[str | None] = mapped_column(String(120))
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=clock.current_datetime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    # succeeded / failed
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict | None] = mapped_column(JSON)

    job: Mapped["Job"] = relationship(back_populates="runs")


class IngestionRun(Base):
    """One attempt to bring outside data in, and everything that happened to it.

    The counts are the point. A run that fetched 24 rows and admitted 24 is not the
    same event as one that fetched 24 and admitted 3, and the difference — 21 rows
    dropped for reasons that are individually recorded in `ingestion_issues` — is the
    only way an operator learns that a feed has quietly degraded. A pipeline that
    logged only success/failure would report both of those as "succeeded".

    `skipped_no_credential` is a first-class status, not a failure. A deployment
    without an API key is correctly configured and simply cannot fetch; recording that
    as `failed` would make a healthy system look broken and train the operator to stop
    reading the column.

    Not uniquely indexed on anything. Idempotency lives in two places that are both
    stronger than a constraint here: the job queue's live idempotency key stops a
    duplicate run being enqueued, and the partial unique index on
    `weather_observations` plus a value-digest comparison stops a duplicate ROW being
    written. Re-running a window is therefore safe and observable — you get a second
    run whose `duplicate_count` equals the batch size and whose `admitted_count` is 0.
    """
    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    domain: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    farm_id: Mapped[int | None] = mapped_column(ForeignKey("farms.id"), index=True)
    field_id: Mapped[int | None] = mapped_column(ForeignKey("fields.id"), index=True)
    window_start: Mapped[datetime | None] = mapped_column(DateTime)
    window_end: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    adapter_version: Mapped[str | None] = mapped_column(String(20))
    # sha256 over the REDACTED request description. A credential must never reach a
    # digest, because a digest is stored and a stored secret is a leaked secret.
    request_digest: Mapped[str | None] = mapped_column(String(64))

    fetched_count: Mapped[int] = mapped_column(Integer, default=0)
    parsed_count: Mapped[int] = mapped_column(Integer, default=0)
    admitted_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    superseded_count: Mapped[int] = mapped_column(Integer, default=0)
    issue_count: Mapped[int] = mapped_column(Integer, default=0)

    started_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"), index=True)

    data_source: Mapped[str | None] = mapped_column(String(40), default="manual_entry")
    data_confidence: Mapped[str | None] = mapped_column(String(40), default="user_provided")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)

    issues: Mapped[list["IngestionIssue"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="IngestionIssue.id"
    )


class IngestionIssue(Base):
    """Something that went wrong with one row, or with a run.

    ISSUES ARE RECORDED, NEVER RAISED. That is the whole design of the pipeline. A bad
    row in hour 14 must not abort a 720-row backfill, and "we dropped this reading and
    here is why" is part of the evidence rather than a detail — the same stance the
    risk snapshot takes when it records an exclusion reason instead of silently
    filtering.

    `detail` carries small structured facts that make an issue actionable: the unit
    that refused to convert, the station that was not asked for. It must never carry a
    credential or a raw response body.
    """
    __tablename__ = "ingestion_issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ingestion_run_id: Mapped[int] = mapped_column(
        ForeignKey("ingestion_runs.id"), nullable=False, index=True
    )
    stage: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    code: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    row_index: Mapped[int | None] = mapped_column(Integer)
    natural_key: Mapped[str | None] = mapped_column(String(200))
    detail: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)

    run: Mapped["IngestionRun"] = relationship(back_populates="issues")


class FeatureValue(Base):
    """One computed feature, for one entity, at one `as_of`.

    FULLY unique on (entity_type, entity_id, name, version, as_of) — no supersede chain,
    unlike every observation table here. That difference is deliberate and follows from
    point-in-time correctness: `pit.admissible` excludes anything recorded after `as_of`,
    so recomputing at a FIXED `as_of` must reproduce the identical `inputs_digest`
    forever, no matter how much data has arrived since.

    Which makes this table a leak detector, and the cheapest one in the system. If a
    recompute at an unchanged `as_of` produces a DIFFERENT digest, some input reached the
    computation that should not have been visible then. `compute.persist` therefore
    upserts only when the digest matches and records an issue when it does not, rather
    than overwriting and losing the evidence.

    An abstention is stored as a row with `value IS NULL` and non-empty `reasons`. The
    pair is enforced in `features.base.FeatureResult`, so a row here cannot say "no
    value" and "no reason" at once.
    """
    __tablename__ = "feature_values"
    __table_args__ = (
        UniqueConstraint(
            "entity_type", "entity_id", "name", "version", "as_of",
            name="uq_feature_value_entity_name_version_as_of",
        ),
        Index("ix_feature_value_lookup", "entity_type", "entity_id", "name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    farm_id: Mapped[int | None] = mapped_column(ForeignKey("farms.id"), index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    value: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(20))
    evidence_grade: Mapped[str | None] = mapped_column(String(10))
    abstained: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reasons: Mapped[list | None] = mapped_column(JSON)
    excluded: Mapped[list | None] = mapped_column(JSON)
    inputs_digest: Mapped[str | None] = mapped_column(String(64))

    computed_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=clock.current_datetime
    )
    data_source: Mapped[str | None] = mapped_column(String(40), default="manual_entry")
    data_confidence: Mapped[str | None] = mapped_column(String(40), default="user_provided")


# ================================================================== canonical spine
# The entity backbone every domain hangs off. Added 2026-07-28 (platform Phase 0).
#
# The problem this solves: until now the deepest thing this system could describe was a
# Farm with ONE crop_type, ONE planting_date and ONE expected_harvest_date. Two seasons
# of strawberries on the same ground were indistinguishable, a farm with three fields was
# one row, and there was nowhere to put a cost, a yield, a loan, or a pledge that belonged
# to a particular planting rather than to the whole farm forever.
#
# `CropCycle` is the load-bearing addition. It is simultaneously the agronomic unit (what
# is planted where, when), the economic unit (its costs and its revenue), the credit unit
# (what is being financed), the collateral unit (its expected harvest), and the risk unit
# (its weather exposure and insurance). Everything the platform adds later joins here.
#
# Nothing in this section is required by the spray/compliance workflow, which continues to
# work farm-scoped. The links from existing models are all NULLABLE and are populated by a
# backfill; reads migrate to the spine gradually rather than in one cut.


class Organization(Base):
    """The ownership boundary: who a set of farms belongs to.

    Not a tenant and not an auth construct — there is still no login. This exists so a
    grower with several farms, a lender's portfolio, and a supplier's customers each have
    a subject. `organization_id` is denormalised onto top-level tables as it is added, so
    the tenancy enforcement of a much later phase is a WHERE clause rather than a
    migration of every relationship in the system.
    """
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(300))
    # Locale primitives live HERE and on Farm, never implied by country in application
    # code. ENGINEERING_GUIDELINES.md's US/TR wording helpers infer currency from `Farm.country`; that
    # habit is what makes a second market a rewrite instead of a configuration.
    jurisdiction_code: Mapped[str | None] = mapped_column(String(10))  # e.g. "US-CA"
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    timezone: Mapped[str | None] = mapped_column(String(60))
    notes: Mapped[str | None] = mapped_column(Text)
    data_source: Mapped[str | None] = mapped_column(String(40), default="manual_entry")
    data_confidence: Mapped[str | None] = mapped_column(String(40), default="user_provided")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)

    farms: Mapped[list["Farm"]] = relationship(back_populates="organization")
    parties: Mapped[list["Party"]] = relationship(back_populates="organization")


class Party(Base):
    """A person or company that acts in the system.

    Everywhere else in this codebase an actor is a free-text string — `reviewed_by`,
    `entered_by`, `requested_by`, `supplier_name`, `provider_name`. That is survivable
    for attribution and impossible for anything that needs HISTORY: "this grower's
    repayment record", "this supplier's on-time rate", "this buyer's contract
    performance" all need the actor to be a row.

    Existing string columns are deliberately left in place. A `*_by_party_id` column is
    added beside one only when something actually needs to join on it, so this is
    additive rather than a rewrite of every attribution in the system.
    """
    __tablename__ = "parties"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), index=True)
    # person / organization
    party_type: Mapped[str] = mapped_column(String(20), nullable=False, default="person")
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(300))
    email: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(60))
    jurisdiction_code: Mapped[str | None] = mapped_column(String(10))
    # External identifiers keyed by issuer (PCA licence no, tax id, assessor id, DUNS).
    # A dict rather than columns because the set is jurisdiction-specific and open-ended.
    external_ids: Mapped[dict | None] = mapped_column(JSON)
    notes: Mapped[str | None] = mapped_column(Text)
    data_source: Mapped[str | None] = mapped_column(String(40), default="manual_entry")
    data_confidence: Mapped[str | None] = mapped_column(String(40), default="user_provided")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)

    organization: Mapped["Organization | None"] = relationship(back_populates="parties")
    roles: Mapped[list["PartyRole"]] = relationship(
        back_populates="party", cascade="all, delete-orphan"
    )


class PartyRole(Base):
    """What a party IS, to whom, and when.

    A party is not intrinsically "a supplier" — it is a supplier to someone, over a
    period. The same company can be a supplier and a buyer; a PCA can advise several
    organizations. Roles are dated so a relationship that ended stays visible instead of
    being deleted.
    """
    __tablename__ = "party_roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    party_id: Mapped[int] = mapped_column(ForeignKey("parties.id"), nullable=False, index=True)
    # grower / pca / agronomist / supplier / lender / insurer / buyer / operator / agent
    role: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    # The organization this role is held TOWARDS, when it is relational.
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), index=True)
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)

    party: Mapped["Party"] = relationship(back_populates="roles")


class Field(Base):
    """The agronomic unit: a piece of ground that gets planted and managed as one thing.

    Distinct from `LandParcel`, which is the LEGAL unit, and the distinction is not
    pedantry: you farm fields and you pledge parcels. A field may straddle two parcels
    and a parcel may hold three fields, so collateral, tenure, and insurance cannot be
    reasoned about from field geometry alone.

    GEOMETRY, and why it is GeoJSON text today. PostGIS is the Phase 0 target and the
    cutover migration adds real `geography(MultiPolygon, 4326)` columns populated from
    `boundary_geojson`. Until then the GeoJSON is the portable, losslessly round-trippable
    form, and `area_m2`/`centroid_*` are stored explicitly rather than computed — so no
    caller has to branch on whether spatial functions exist yet. The GeoJSON remains the
    interchange representation after the cutover; the geometry column is the index.
    """
    __tablename__ = "fields"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), nullable=False, index=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    boundary_geojson: Mapped[str | None] = mapped_column(Text)
    centroid_lat: Mapped[float | None] = mapped_column(Float)
    centroid_lon: Mapped[float | None] = mapped_column(Float)
    # Canonical area in square metres (see app/units.py). Every area in the platform is
    # stored canonically and displayed in the farm's unit; the pair below records what
    # the human actually said, so a converted number never silently replaces an entered
    # one in the record of what someone claimed.
    area_m2: Mapped[float | None] = mapped_column(Float)
    display_area: Mapped[float | None] = mapped_column(Float)
    display_area_unit: Mapped[str | None] = mapped_column(String(10))
    irrigation_type: Mapped[str | None] = mapped_column(String(60))
    water_source: Mapped[str | None] = mapped_column(String(60))
    notes: Mapped[str | None] = mapped_column(Text)
    data_source: Mapped[str | None] = mapped_column(String(40), default="manual_entry")
    data_confidence: Mapped[str | None] = mapped_column(String(40), default="user_provided")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)

    farm: Mapped["Farm"] = relationship(back_populates="fields")
    crop_cycles: Mapped[list["CropCycle"]] = relationship(
        back_populates="field", cascade="all, delete-orphan"
    )


class LandParcel(Base):
    """The legal unit: what a deed, a lease, a lien, or an assessor's roll describes.

    Exists separately from `Field` because collateral and tenure attach to legal
    descriptions, not to agronomic ones. A lease that expires inside a loan tenor is an
    underwriting fact, and it is a fact ABOUT A PARCEL.
    """
    __tablename__ = "land_parcels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), index=True)
    farm_id: Mapped[int | None] = mapped_column(ForeignKey("farms.id"), index=True)
    # Assessor's parcel number or equivalent registry identifier, as printed.
    parcel_identifier: Mapped[str | None] = mapped_column(String(120), index=True)
    registry_name: Mapped[str | None] = mapped_column(String(160))
    county: Mapped[str | None] = mapped_column(String(120))
    jurisdiction_code: Mapped[str | None] = mapped_column(String(10))
    boundary_geojson: Mapped[str | None] = mapped_column(Text)
    area_m2: Mapped[float | None] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(Text)
    data_source: Mapped[str | None] = mapped_column(String(40), default="manual_entry")
    data_confidence: Mapped[str | None] = mapped_column(String(40), default="user_provided")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)

    tenure_rights: Mapped[list["TenureRight"]] = relationship(
        back_populates="land_parcel", cascade="all, delete-orphan"
    )


class TenureRight(Base):
    """Who holds what right over a parcel, for how long, evidenced by what.

    Dated on purpose. "Owned" and "leased until March" are the same shape of fact and
    differ only in a date that changes what can be pledged and for how long.
    """
    __tablename__ = "tenure_rights"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    land_parcel_id: Mapped[int] = mapped_column(
        ForeignKey("land_parcels.id"), nullable=False, index=True
    )
    holder_party_id: Mapped[int | None] = mapped_column(ForeignKey("parties.id"), index=True)
    # owned / leased / licensed / sharecrop / other
    tenure_type: Mapped[str] = mapped_column(String(30), nullable=False)
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    annual_cost_amount: Mapped[float | None] = mapped_column(Float)
    currency_code: Mapped[str | None] = mapped_column(String(3))
    # The document that evidences it (deed, lease). Soft ref to documents.id.
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"))
    notes: Mapped[str | None] = mapped_column(Text)
    data_source: Mapped[str | None] = mapped_column(String(40), default="manual_entry")
    data_confidence: Mapped[str | None] = mapped_column(String(40), default="user_provided")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)

    land_parcel: Mapped["LandParcel"] = relationship(back_populates="tenure_rights")


class FieldParcelOverlap(Base):
    """How much of a field sits on a parcel. The agronomic-to-legal join.

    Carries an area because the relationship is partial: pledging a parcel does not
    pledge a whole field, and a coverage calculation that assumed it did would overstate
    collateral.
    """
    __tablename__ = "field_parcel_overlaps"
    __table_args__ = (
        Index("uq_field_parcel_overlap", "field_id", "land_parcel_id", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    field_id: Mapped[int] = mapped_column(ForeignKey("fields.id"), nullable=False, index=True)
    land_parcel_id: Mapped[int] = mapped_column(
        ForeignKey("land_parcels.id"), nullable=False, index=True
    )
    overlap_area_m2: Mapped[float | None] = mapped_column(Float)
    # "declared" (a human said so) or "computed" (from geometry). Never conflated: a
    # computed overlap inherits the accuracy of two boundaries nobody surveyed.
    determination_method: Mapped[str | None] = mapped_column(String(30), default="declared")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)


class CropCycle(Base):
    """One planting of one crop on one field in one season. THE join key.

    Everything the platform adds after Phase 0 references this row: costs, yield
    forecasts, revenue, credit applications, collateral pledges, insurance coverage,
    monitoring events. It is what makes "this season" a thing that can be reasoned about
    separately from "this farm", which is the distinction the previous schema could not
    make at all.

    `crop` and `variety_name` are strings for now, matching the existing `Farm.crop_type`
    vocabulary. Catalog tables for crop and variety arrive with the crop plan in a later
    phase, when something actually consumes traits — adding empty catalog tables now would
    be a table per noun with no consumer.

    Areas follow the same rule as Field: canonical m2 plus what the human said.
    """
    __tablename__ = "crop_cycles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), nullable=False, index=True)
    field_id: Mapped[int] = mapped_column(ForeignKey("fields.id"), nullable=False, index=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), index=True)
    crop: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    variety_name: Mapped[str | None] = mapped_column(String(160))
    # The season this planting belongs to. `season_year` is what queries group by;
    # `season_label` is what humans call it ("2026 spring plant") and may not be a year.
    season_year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    season_label: Mapped[str | None] = mapped_column(String(60))
    planting_date: Mapped[date | None] = mapped_column(Date)
    expected_harvest_start: Mapped[date | None] = mapped_column(Date)
    expected_harvest_end: Mapped[date | None] = mapped_column(Date)
    actual_harvest_start: Mapped[date | None] = mapped_column(Date)
    actual_harvest_end: Mapped[date | None] = mapped_column(Date)
    planted_area_m2: Mapped[float | None] = mapped_column(Float)
    display_area: Mapped[float | None] = mapped_column(Float)
    display_area_unit: Mapped[str | None] = mapped_column(String(10))
    target_market: Mapped[str | None] = mapped_column(String(60))
    target_grade: Mapped[str | None] = mapped_column(String(60))
    # planned / planted / growing / harvesting / closed / abandoned
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="growing", index=True)
    currency_code: Mapped[str | None] = mapped_column(String(3))
    notes: Mapped[str | None] = mapped_column(Text)
    data_source: Mapped[str | None] = mapped_column(String(40), default="manual_entry")
    data_confidence: Mapped[str | None] = mapped_column(String(40), default="user_provided")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)

    farm: Mapped["Farm"] = relationship(back_populates="crop_cycles")
    field: Mapped["Field"] = relationship(back_populates="crop_cycles")
    operations: Mapped[list["Operation"]] = relationship(
        back_populates="crop_cycle", cascade="all, delete-orphan"
    )


class Operation(Base):
    """Anything done to a crop cycle: the thin supertype over typed detail.

    Deliberately thin, and deliberately NOT a rewrite of `SprayEvent`. A spray keeps its
    own table, its own regulatory columns, and its own engine; it gains an `operation_id`
    so that "what happened on this cycle, in order, at what cost" is answerable in one
    query across sprays, irrigations, fertiliser passes, and harvests. Typed detail tables
    for the other operation types arrive with the crop plan.

    The alternative — forcing sprays into a generic operation table with a JSON detail
    blob — would have meant the PHI/REI/MoA columns the decision engine reads become
    untyped, which is a real regression in exchange for a tidier diagram.
    """
    __tablename__ = "operations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), nullable=False, index=True)
    crop_cycle_id: Mapped[int | None] = mapped_column(ForeignKey("crop_cycles.id"), index=True)
    field_id: Mapped[int | None] = mapped_column(ForeignKey("fields.id"), index=True)
    block_id: Mapped[int | None] = mapped_column(ForeignKey("blocks.id"), index=True)
    # planting / irrigation / fertilization / crop_protection / scouting / harvest /
    # tillage / other
    operation_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    planned_on: Mapped[date | None] = mapped_column(Date)
    performed_on: Mapped[date | None] = mapped_column(Date, index=True)
    area_m2: Mapped[float | None] = mapped_column(Float)
    display_area: Mapped[float | None] = mapped_column(Float)
    display_area_unit: Mapped[str | None] = mapped_column(String(10))
    cost_amount: Mapped[float | None] = mapped_column(Float)
    currency_code: Mapped[str | None] = mapped_column(String(3))
    performed_by: Mapped[str | None] = mapped_column(String(120))
    performed_by_party_id: Mapped[int | None] = mapped_column(ForeignKey("parties.id"))
    notes: Mapped[str | None] = mapped_column(Text)
    data_source: Mapped[str | None] = mapped_column(String(40), default="manual_entry")
    data_confidence: Mapped[str | None] = mapped_column(String(40), default="user_provided")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)

    crop_cycle: Mapped["CropCycle | None"] = relationship(back_populates="operations")


class InputProduct(Base):
    """Canonical identity for anything a farm buys and applies.

    `PesticideProduct` stays exactly as it is and becomes a SPECIALISATION of this row,
    linked 1:1. That direction matters: the label layer's identity rules (exact-or-
    ambiguous EPA registration matching, append-only label records, farm-scoped
    verification) are the strictest thing in the codebase and must not be loosened to
    accommodate a fertiliser, which has no registration number and needs none.
    """
    __tablename__ = "input_products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # seed / fertilizer / crop_protection / biological / adjuvant / other
    category: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    manufacturer: Mapped[str | None] = mapped_column(String(200))
    # Normalised lookup key within a category (lowercased name, or the normalised EPA
    # registration number for a pesticide). Not unique: two registrants may ship the
    # same trade name, and collapsing them would be exactly the identity error the
    # label layer refuses to make.
    canonical_key: Mapped[str | None] = mapped_column(String(200), index=True)
    # The pesticide specialisation, when this product is one.
    pesticide_product_id: Mapped[int | None] = mapped_column(
        ForeignKey("pesticide_products.id"), index=True
    )
    unit_of_sale: Mapped[str | None] = mapped_column(String(30))
    notes: Mapped[str | None] = mapped_column(Text)
    data_source: Mapped[str | None] = mapped_column(String(40), default="manual_entry")
    data_confidence: Mapped[str | None] = mapped_column(String(40), default="user_provided")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)


# ---------------------------------------------------------------------------
# Marketplace (2026-08-07).
#
# Procurement existed before this as a concierge workflow: an operator typed a
# supplier's name as free text on each quote, and nothing linked one quote's
# "Switch 62.5WG" to another's "Switch 62.5 WG". These three tables are what turn
# that into a marketplace — a supplier is an entity, a quoted line points at a
# catalogued product, and an RFQ leaving the building is a recorded act.
#
# What did NOT change: quotes are still returned in entry order, there is still no
# ranking column anywhere, and Lumos still takes no commission. The catalogue makes
# comparison POSSIBLE; it does not make Lumos a broker.
# ---------------------------------------------------------------------------
class Supplier(Base):
    """A supplier as an entity rather than a string on each quote.

    `SupplierQuote.supplier_name` is kept and still populated — the same discipline as
    `SprayEvent.treated_acres` + `treated_area_unit`: record what the human actually
    said, and carry the structured link beside it. A quote entered before this table
    existed, or for a supplier nobody has registered yet, keeps working with
    `supplier_id` NULL rather than being blocked or silently attached to a guess.
    """
    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Normalised name for exact-match lookup. NOT unique: two legally distinct
    # businesses can share a trading name, and collapsing them would misattribute a
    # quote — the same identity rule `PesticideProduct.epa_reg_base` follows.
    canonical_name: Mapped[str | None] = mapped_column(String(200), index=True)
    contact_name: Mapped[str | None] = mapped_column(String(200))
    contact_email: Mapped[str | None] = mapped_column(String(200))
    contact_phone: Mapped[str | None] = mapped_column(String(60))
    service_area: Mapped[str | None] = mapped_column(String(200))
    # active / inactive. A supplier is never deleted: quotes reference them, and a
    # deleted supplier would orphan a decision a grower already acted on.
    status: Mapped[str] = mapped_column(String(20), default="active")
    notes: Mapped[str | None] = mapped_column(Text)
    data_source: Mapped[str | None] = mapped_column(String(40), default="manual_entry")
    data_confidence: Mapped[str | None] = mapped_column(String(40), default="user_provided")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)

    catalog_entries: Mapped[list["SupplierProduct"]] = relationship(
        back_populates="supplier", cascade="all, delete-orphan"
    )


class SupplierProduct(Base):
    """A supplier offers a catalogued product. The catalogue, finally joined up.

    `InputProduct` has existed since the entity-spine phase with zero references
    anywhere else in the codebase. This is the table that gives it one, and the reason
    it matters is `procurement_analytics`: dispersion must be grouped by product
    IDENTITY, because grouping by free-text name reports three spellings of one product
    as three products with no spread each — which reads as "prices are consistent".

    Carries no price. A price belongs to a quote, at a moment, for a quantity; a price
    on a catalogue row would be a list price that nobody quoted and that would go stale
    invisibly.
    """
    __tablename__ = "supplier_products"
    __table_args__ = (
        Index("uq_supplier_product", "supplier_id", "input_product_id", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    supplier_id: Mapped[int] = mapped_column(
        ForeignKey("suppliers.id"), nullable=False, index=True
    )
    input_product_id: Mapped[int] = mapped_column(
        ForeignKey("input_products.id"), nullable=False, index=True
    )
    supplier_sku: Mapped[str | None] = mapped_column(String(120))
    pack_size: Mapped[str | None] = mapped_column(String(60))
    typical_lead_time_days: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)

    supplier: Mapped["Supplier"] = relationship(back_populates="catalog_entries")


class RfqTransmission(Base):
    """An append-only record of an RFQ being sent to a supplier.

    Before this, "submit for quotes" set a status and stopped: the RFQ was never
    transmitted anywhere, and a human was expected to notice it in an operator dropdown.
    That is a real gap between what the state machine claims and what happens, and it is
    the kind of gap that only becomes visible when a grower asks why nobody quoted.

    Append-only, like every other consequential act here: a transmission is a thing that
    either happened or did not, and re-sending is a NEW row rather than an edit of the
    old one. `status` records the outcome, including `skipped_no_transport` — which is
    what every row says today, because no transport is configured and the adapter ships
    inert exactly like `ingest/cimis.py` without an AppKey.
    """
    __tablename__ = "rfq_transmissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    input_plan_id: Mapped[int] = mapped_column(
        ForeignKey("input_plans.id"), nullable=False, index=True
    )
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), index=True)
    # As-addressed, kept even when supplier_id is set: what we actually sent to.
    sent_to: Mapped[str | None] = mapped_column(String(200))
    transport: Mapped[str] = mapped_column(String(40), nullable=False)
    # queued / sent / failed / skipped_no_transport
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    requested_by: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)


# ---------------------------------------------------------------------------
# Finance persistence (2026-08-07, third pass).
#
# The decision models existed and computed on read, so nothing survived the request.
# `credit_scoring.Score.inputs_digest` was built to answer "what did you know when you
# declined me" — a question with legal weight — and had nowhere to live.
#
# THE INVARIANT ACROSS ALL FOUR ASSESSMENT TABLES: a row records EITHER an outcome OR a
# refusal, never both and never neither. `refusal_code IS NULL` iff the assessment
# produced a result. This is the same construction as `FeatureValue` storing an
# abstention as `value IS NULL` + non-empty `reasons`, and it exists for the same
# reason: a refusal is a real event about a real farm on a real date, and dropping it
# would leave a borrower unable to see that no assessment was even possible.
#
# All four are APPEND-ONLY. There is no update path and no delete path. A reassessment
# is a new row at a new `as_of`; a correction to an input produces a new row too. What
# a lender or a grower saw on a date must stay recoverable.
# ---------------------------------------------------------------------------
class CreditAssessment(Base):
    """One executed scorecard, or one recorded refusal to score. Append-only.

    `inputs_digest` is the point-in-time guarantee: recomputing at the same `as_of` must
    reproduce it, exactly as `FeatureValue.inputs_digest` does. A digest that moves is
    proof an input became visible that should not have been — and here that means an
    assessment was made on information the farm did not have at the time.
    """
    __tablename__ = "credit_assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), nullable=False, index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)

    # Which scorecard ran. Recorded per row rather than referenced, because a scorecard
    # is transcribed from a lender document that may be re-transcribed later — and an
    # assessment must stay readable against the card as it was when it ran.
    scorecard_lender: Mapped[str | None] = mapped_column(String(200))
    scorecard_name: Mapped[str | None] = mapped_column(String(200))
    scorecard_version: Mapped[str | None] = mapped_column(String(60))

    total: Mapped[float | None] = mapped_column(Float)
    minimum_score: Mapped[float | None] = mapped_column(Float)
    maximum_score: Mapped[float | None] = mapped_column(Float)
    inputs_digest: Mapped[str | None] = mapped_column(String(64), index=True)
    factors: Mapped[list | None] = mapped_column(JSON)

    refusal_code: Mapped[str | None] = mapped_column(String(60), index=True)
    refusal_detail: Mapped[str | None] = mapped_column(Text)

    assessed_by: Mapped[str | None] = mapped_column(String(120))
    data_source: Mapped[str | None] = mapped_column(String(40), default="manual_entry")
    data_confidence: Mapped[str | None] = mapped_column(String(40), default="user_provided")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)


class UnderwritingDecision(Base):
    """One policy evaluation, or one recorded refusal. Append-only.

    `outcome` is never "approved" — the vocabulary is conditions_met /
    conditions_not_met / referred_to_human, and there is no column here that could
    carry an approval. Storing the evaluation does not turn it into one.
    """
    __tablename__ = "underwriting_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), nullable=False, index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    # The assessment this was evaluated against, when one backed it.
    credit_assessment_id: Mapped[int | None] = mapped_column(
        ForeignKey("credit_assessments.id"), index=True
    )

    policy_lender: Mapped[str | None] = mapped_column(String(200))
    policy_version: Mapped[str | None] = mapped_column(String(60))
    outcome: Mapped[str | None] = mapped_column(String(40), index=True)
    rules: Mapped[list | None] = mapped_column(JSON)
    # Kept as their own columns, not derived from `rules` at read time: the count of
    # conditions that could not be tested is the number most likely to be quietly
    # dropped from a summary, and it is the one that must not be.
    failed_rule_ids: Mapped[list | None] = mapped_column(JSON)
    not_evaluated_rule_ids: Mapped[list | None] = mapped_column(JSON)

    refusal_code: Mapped[str | None] = mapped_column(String(60), index=True)
    refusal_detail: Mapped[str | None] = mapped_column(Text)

    decided_by: Mapped[str | None] = mapped_column(String(120))
    data_source: Mapped[str | None] = mapped_column(String(40), default="manual_entry")
    data_confidence: Mapped[str | None] = mapped_column(String(40), default="user_provided")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)


class CollateralAsset(Base):
    """A registered asset. An INPUT, unlike the three assessment tables.

    Append-only with a supersede chain rather than an update, matching every other
    correctable record here: a revaluation is a new row superseding the old one, so what
    an asset was assessed at when a decision referenced it stays recoverable.

    `assessed_value` is nullable on purpose — an asset can be registered before anyone
    values it, and `collateral.value_assets` refuses on it rather than assuming. The
    valuation basis is required whenever a value is present, because 60% of an insured
    value and 60% of a market estimate are different numbers.
    """
    __tablename__ = "collateral_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), nullable=False, index=True)
    collateral_type: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    assessed_value: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    valuation_basis: Mapped[str | None] = mapped_column(String(200))
    valued_on: Mapped[date | None] = mapped_column(Date)
    # The legal unit the asset attaches to, when it is land-backed.
    land_parcel_id: Mapped[int | None] = mapped_column(
        ForeignKey("land_parcels.id"), index=True
    )
    supersedes_id: Mapped[int | None] = mapped_column(
        ForeignKey("collateral_assets.id"), index=True
    )
    registered_by: Mapped[str | None] = mapped_column(String(120))
    data_source: Mapped[str | None] = mapped_column(String(40), default="manual_entry")
    data_confidence: Mapped[str | None] = mapped_column(String(40), default="user_provided")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)


class MonitoringSnapshot(Base):
    """Covenant standing at one moment, or a recorded refusal. Append-only.

    `standing` carries the three-value vocabulary from `monitoring.py` — good_standing /
    in_breach / unknown — and `unknown` is reachable and common. A two-value column here
    would have forced "nothing checked" into whichever value was the default, and the
    one that reads well is compliant.
    """
    __tablename__ = "monitoring_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), nullable=False, index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)

    lender: Mapped[str | None] = mapped_column(String(200))
    facility_reference: Mapped[str | None] = mapped_column(String(120))
    standing: Mapped[str | None] = mapped_column(String(40), index=True)
    covenants: Mapped[list | None] = mapped_column(JSON)
    breached_covenant_ids: Mapped[list | None] = mapped_column(JSON)
    unevaluated_covenant_ids: Mapped[list | None] = mapped_column(JSON)

    refusal_code: Mapped[str | None] = mapped_column(String(60), index=True)
    refusal_detail: Mapped[str | None] = mapped_column(Text)

    data_source: Mapped[str | None] = mapped_column(String(40), default="manual_entry")
    data_confidence: Mapped[str | None] = mapped_column(String(40), default="user_provided")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)


class CoverageAssessment(Base):
    """One insurance coverage match, or a recorded refusal. Append-only.

    Carries no premium and has no column that could hold one — coverage is matched here,
    never priced. The valuable column is `missing_evidence`: telling a grower today which
    claim evidence they do not have beats discovering it at claim time, months later.
    """
    __tablename__ = "coverage_assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), nullable=False, index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)

    crop: Mapped[str | None] = mapped_column(String(80))
    peril: Mapped[str | None] = mapped_column(String(80))
    products: Mapped[list | None] = mapped_column(JSON)

    refusal_code: Mapped[str | None] = mapped_column(String(60), index=True)
    refusal_detail: Mapped[str | None] = mapped_column(Text)

    assessed_by: Mapped[str | None] = mapped_column(String(120))
    data_source: Mapped[str | None] = mapped_column(String(40), default="manual_entry")
    data_confidence: Mapped[str | None] = mapped_column(String(40), default="user_provided")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)


class ResidueReferenceRecord(Base):
    """One (commodity, pesticide, program year) summary from a USDA PDP release.

    APPEND-ONLY, and unique on the pair plus the source digest. Unlike
    `ProductLabelRecord` there is no supersede chain, and the reason is the same one
    `feature_values` gives for having none: at a fixed program year computed from fixed
    published bytes, the aggregate must reproduce forever. A row that changed while its
    digest stayed the same would be proof of a loader bug, and the uniqueness constraint
    turns that into an integrity error instead of a silent rewrite. USDA re-releasing a
    corrected year produces a different digest and therefore a visibly different row.

    NOT a regulatory source. `epa_tolerance_value` is USDA's transcription of an EPA
    tolerance into their own reference workbook — a secondary source. It travels with
    `residue_reference.AUTHORITY_REFERENCE_DATASET` and must never back a definitive
    verdict or override a transcribed label (ENGINEERING_GUIDELINES.md §4, §5 authority gating).

    `epa_tolerance_value` NULL means the workbook stated a non-numeric basis (NT / EX /
    SU) held in `epa_tolerance_basis`, or stated nothing. As everywhere else in this
    schema, NULL means THE SOURCE IS SILENT — never "no limit".
    """
    __tablename__ = "residue_reference_records"
    __table_args__ = (
        UniqueConstraint(
            "commodity_code", "commodity_type", "pesticide_code", "program_year",
            "domestic_only", "source_digest",
            name="uq_residue_reference_pair_release",
        ),
        Index("ix_residue_reference_lookup", "commodity_code", "pesticide_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # PDP's own codes and names, stored verbatim. Matching to this product's crop
    # vocabulary happens at read time through app/crop_aliases.py — never by rewriting
    # USDA's names on the way in.
    commodity_code: Mapped[str] = mapped_column(String(4), nullable=False)
    commodity_name: Mapped[str] = mapped_column(String(120), nullable=False)
    commodity_type: Mapped[str] = mapped_column(String(4), nullable=False, default="")
    pesticide_code: Mapped[str] = mapped_column(String(8), nullable=False)
    pesticide_name: Mapped[str] = mapped_column(String(160), nullable=False)

    program_year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    # Assays run for this pair, INCLUDING non-detects. The denominator of any rate.
    samples_tested: Mapped[int] = mapped_column(Integer, nullable=False)
    samples_with_detection: Mapped[int] = mapped_column(Integer, nullable=False)
    # NULL when nothing was detected: there is no maximum of an empty set, and 0.0 would
    # read as "detected at zero" rather than "never detected".
    max_concentration: Mapped[float | None] = mapped_column(Float)
    median_detected_concentration: Mapped[float | None] = mapped_column(Float)
    concentration_unit: Mapped[str | None] = mapped_column(String(8))
    unit_conflict: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # True when only ORIGIN=1 (US-grown) samples were counted.
    domestic_only: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    epa_tolerance_value: Mapped[float | None] = mapped_column(Float)
    # NT / EX / SU when the workbook stated a code instead of a number.
    epa_tolerance_basis: Mapped[str | None] = mapped_column(String(4))
    tolerance_unit: Mapped[str | None] = mapped_column(String(8))

    # Provenance: the release this came from and a digest of the exact bytes read.
    source_reference: Mapped[str] = mapped_column(Text, nullable=False)
    source_digest: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    loaded_by: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.current_datetime)
