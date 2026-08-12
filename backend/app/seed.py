"""Seed the database with demo greenhouse tomato farms for the Lumos demo.

Run with:  python -m app.seed

Creates two clearly contrasting farms:

  1. Green Valley Greenhouse  -> HIGH RISK
       * repeated active ingredient (mancozeb applied 3x in 30 days)
       * pre-harvest interval risk (harvest falls inside a spray's PHI window)
       * high-severity scouting observation (severity 4/5)
       * visible pesticide cost history
  2. Sunrise Tomato House     -> LOW RISK
       * one targeted spray, low-severity scouting -> engine suggests "inspect first"

Idempotent: clears existing rows first so re-running gives a clean demo state.
"""
from datetime import date, datetime, time, timedelta

from sqlalchemy import select

from app import clock, crud, models, schemas
from app.database import Base, SessionLocal, engine, init_db
from app.decision_engine import evaluate_planned_spray


def _seed_decision_trail(
    db, planned: models.PlannedSpray, *, source_type: str, entered_by: str | None,
    ts: datetime, review_rationale: str | None = None,
    review_ts: datetime | None = None, outcome_ts: datetime | None = None,
) -> None:
    """Field-level input values + immutable audit events for a seeded decision.

    Mirrors what crud.create_planned_spray / review / outcome write live, so demo
    decision records show the same provenance/audit surfaces as real ones. Rows
    anchor to the seeded timestamps: ``ts`` for creation/input values, optional
    ``review_ts``/``outcome_ts`` when the story spans more than one moment
    (defaulting to ``ts`` keeps single-day scenarios unchanged).
    """
    review_ts = review_ts or ts
    outcome_ts = outcome_ts or ts
    for name, value, unit in crud._planned_input_rows(planned, None):
        db.add(models.DecisionInputValue(
            planned_spray_id=planned.id,
            field_name=name,
            raw_value=str(value),
            normalized_value=crud._normalized_input(name, value),
            unit=unit,
            source_type=source_type,
            source_reference="demo seed (simulated)",
            confidence="simulated",
            verified_by=entered_by if source_type == "pca_verified" else None,
            verified_at=ts if source_type == "pca_verified" else None,
            created_at=ts,
        ))
    snapshot = crud._decision_snapshot(planned)
    db.add(models.DecisionAuditEvent(
        planned_spray_id=planned.id, event_type="created",
        actor=entered_by, system_recommendation=planned.decision_outcome,
        after={**snapshot, "review_status": "not_reviewed", "outcome": "planned",
               "input_source_type": source_type},
        created_at=ts,
    ))
    if planned.review_status != "not_reviewed":
        db.add(models.DecisionAuditEvent(
            planned_spray_id=planned.id, event_type="reviewed",
            actor=planned.reviewed_by, rationale=review_rationale or planned.review_comment,
            system_recommendation=planned.decision_outcome,
            before={**snapshot, "review_status": "not_reviewed", "outcome": "planned"},
            after={**snapshot, "outcome": "planned",
                   "review_action": planned.review_status},
            created_at=review_ts,
        ))
    if planned.outcome != "planned":
        db.add(models.DecisionAuditEvent(
            planned_spray_id=planned.id, event_type="outcome_recorded",
            rationale=planned.outcome_reason,
            system_recommendation=planned.decision_outcome,
            before={**snapshot, "outcome": "planned"},
            after=snapshot,
            created_at=outcome_ts,
        ))


def _at(day: date, hour: int, minute: int = 0) -> datetime:
    """A deterministic seeded timestamp on the given demo day (no clock reads)."""
    return datetime.combine(day, time(hour, minute))


def demo_today() -> date:
    """The anchor date every seeded record is relative to.

    Defaults to the real today (re-seed before a demo and the story is always fresh);
    set LUMOS_DEMO_TODAY=YYYY-MM-DD to pin the whole demo to a fixed date for
    screenshots / deterministic tests. Delegates to the app clock so seeded records
    and live API computations share one timeline (see app/clock.py).
    """
    return clock.current_date()


def run() -> None:
    # Recreate the schema so a clean demo always matches the current models
    # (there is no migration tooling; the SQLite file is disposable demo data).
    Base.metadata.drop_all(bind=engine)
    init_db()
    db = SessionLocal()
    try:

        today = demo_today()

        # ------------------------------------------------------------------ #
        # Farm 1 — HIGH RISK                                                  #
        # ------------------------------------------------------------------ #
        farm1 = models.Farm(
            name="Green Valley Greenhouse",
            location="Antalya, Türkiye",
            country="TR",
            crop_type="greenhouse_tomato",
            greenhouse_area=4000.0,
            area_unit="m2",
            planting_date=today - timedelta(days=70),
            # Harvest very soon -> falls inside the 7-day PHI of recent sprays.
            expected_harvest_date=today + timedelta(days=3),
        )
        db.add(farm1)
        db.flush()

        # Same active ingredient (mancozeb) three times in 30 days -> over-use warning.
        db.add_all([
            models.SprayEvent(
                farm_id=farm1.id,
                product_name="Dithane M-45",
                active_ingredient="mancozeb",
                pesticide_class="dithiocarbamate fungicide",
                target_pest_or_disease="early blight",
                dose="2.5 g/L",
                application_date=today - timedelta(days=2),   # PHI 7 -> clears after harvest
                cost=45.0,
                pre_harvest_interval_days=7,
                notes="Preventive spray on lower canopy.",
            ),
            models.SprayEvent(
                farm_id=farm1.id,
                product_name="Dithane M-45",
                active_ingredient="mancozeb",
                pesticide_class="dithiocarbamate fungicide",
                target_pest_or_disease="early blight",
                dose="2.5 g/L",
                application_date=today - timedelta(days=12),
                cost=45.0,
                pre_harvest_interval_days=7,
                notes="Repeat application.",
            ),
            models.SprayEvent(
                farm_id=farm1.id,
                product_name="Dithane M-45",
                active_ingredient="mancozeb",
                pesticide_class="dithiocarbamate fungicide",
                target_pest_or_disease="early blight",
                dose="2.5 g/L",
                application_date=today - timedelta(days=22),
                cost=45.0,
                pre_harvest_interval_days=7,
                notes="Third application — same chemistry, no rotation.",
            ),
            # A second product, so cost history looks realistic.
            models.SprayEvent(
                farm_id=farm1.id,
                product_name="Confidor 200 SL",
                active_ingredient="imidacloprid",
                pesticide_class="neonicotinoid insecticide",
                target_pest_or_disease="whitefly",
                dose="0.5 ml/L",
                application_date=today - timedelta(days=8),
                cost=70.0,
                pre_harvest_interval_days=3,
                notes="Whitefly pressure on upper leaves.",
            ),
        ])

        # High-severity scouting observation -> elevated pressure warning.
        db.add(
            models.ScoutObservation(
                farm_id=farm1.id,
                observation_date=today - timedelta(days=1),
                crop_stage="fruiting",
                visible_issue="spreading leaf spots on lower canopy",
                severity_1_to_5=4,
                notes="Lesions enlarging and moving up the plant.",
            )
        )

        # ------------------------------------------------------------------ #
        # Farm 2 — LOW RISK                                                   #
        # ------------------------------------------------------------------ #
        farm2 = models.Farm(
            name="Sunrise Tomato House",
            location="Mersin, Türkiye",
            country="TR",
            crop_type="greenhouse_tomato",
            greenhouse_area=2500.0,
            area_unit="m2",
            planting_date=today - timedelta(days=40),
            # Harvest far away -> no PHI risk.
            expected_harvest_date=today + timedelta(days=45),
        )
        db.add(farm2)
        db.flush()

        db.add(
            models.SprayEvent(
                farm_id=farm2.id,
                product_name="Vertimec 1.8 EC",
                active_ingredient="abamectin",
                pesticide_class="avermectin insecticide",
                target_pest_or_disease="two-spotted spider mite",
                dose="0.5 ml/L",
                application_date=today - timedelta(days=18),
                cost=60.0,
                pre_harvest_interval_days=7,
                notes="Single targeted application after scouting.",
            )
        )

        # Low-severity scouting -> engine should suggest inspecting first.
        db.add(
            models.ScoutObservation(
                farm_id=farm2.id,
                observation_date=today - timedelta(days=3),
                crop_stage="vegetative",
                visible_issue="a few mites on one plant",
                severity_1_to_5=2,
                notes="Isolated, keeping an eye on it.",
            )
        )

        # ------------------------------------------------------------------ #
        # Farm 3 — U.S. SPECIALTY CROP (the YC / U.S. wedge demo farm)        #
        #   California strawberries: triggers repeated-AI, PHI, REI, and      #
        #   high-severity scouting all at once. Costs in USD.                 #
        # ------------------------------------------------------------------ #
        farm3 = models.Farm(
            name="Golden Coast Strawberry Ranch",
            location="Watsonville, California",
            country="US",
            crop_type="strawberry",
            greenhouse_area=18.0,
            area_unit="acres",
            planting_date=today - timedelta(days=90),
            # Harvest in 2 days -> falls inside a recent spray's PHI window.
            expected_harvest_date=today + timedelta(days=2),
        )
        db.add(farm3)
        db.flush()

        farm3_sprays = [
            # Captan applied yesterday: PHI 4 -> clears after harvest (PHI risk),
            # REI 24h -> worker re-entry window may still be active.
            models.SprayEvent(
                farm_id=farm3.id,
                product_name="Captan 80 WDG",
                active_ingredient="captan",
                pesticide_class="phthalimide fungicide",
                target_pest_or_disease="botrytis / gray mold",
                dose="3 lb/acre",
                application_date=today - timedelta(days=1),
                cost=120.0,
                pre_harvest_interval_days=4,
                re_entry_interval_hours=24,
                field_block="Field 7",
                notes="Preventive cover spray ahead of cool, humid weather.",
            ),
            models.SprayEvent(
                farm_id=farm3.id,
                product_name="Captan 80 WDG",
                active_ingredient="captan",
                pesticide_class="phthalimide fungicide",
                target_pest_or_disease="botrytis / gray mold",
                dose="3 lb/acre",
                application_date=today - timedelta(days=10),
                cost=120.0,
                pre_harvest_interval_days=4,
                re_entry_interval_hours=24,
                field_block="Field 7",
                notes="Repeat application.",
            ),
            models.SprayEvent(
                farm_id=farm3.id,
                product_name="Captan 80 WDG",
                active_ingredient="captan",
                pesticide_class="phthalimide fungicide",
                target_pest_or_disease="botrytis / gray mold",
                dose="3 lb/acre",
                application_date=today - timedelta(days=20),
                cost=120.0,
                pre_harvest_interval_days=4,
                re_entry_interval_hours=24,
                field_block="Field 7",
                notes="Third captan application — same chemistry, no rotation.",
            ),
            # A different product, for cost variety and resistance contrast.
            models.SprayEvent(
                farm_id=farm3.id,
                product_name="Brigade WSB",
                active_ingredient="bifenthrin",
                pesticide_class="pyrethroid insecticide",
                target_pest_or_disease="lygus bug",
                dose="16 oz/acre",
                application_date=today - timedelta(days=6),
                cost=180.0,
                pre_harvest_interval_days=3,
                re_entry_interval_hours=12,
                field_block="North Block",
                notes="Lygus pressure on field edges.",
            ),
        ]
        db.add_all(farm3_sprays)

        # High-severity scouting -> elevated pressure flag.
        farm3_obs = models.ScoutObservation(
            farm_id=farm3.id,
            observation_date=today - timedelta(days=2),
            crop_stage="fruiting",
            visible_issue="gray mold (Botrytis) on ripening fruit, spreading",
            severity_1_to_5=4,
            field_block="Field 7",
            notes="Several infected berries per bed in the low, shaded rows.",
        )
        db.add(farm3_obs)

        # ------------------------------------------------------------------ #
        # Blocks — the Botrytis pilot's unit of comparison.                   #
        #                                                                     #
        # Without these, every pilot surface (disposition card, operator      #
        # card, opportunity scan) renders empty and the product looks half    #
        # built. They exist ONLY on the U.S. wedge farm; the TR contrast      #
        # farms are not in the pilot's declared scope.                        #
        #                                                                     #
        # The names deliberately echo the free-text `field_block` values      #
        # already used above, and the link is still made EXPLICITLY on each   #
        # record below. That distinction is the whole point of Block's        #
        # docstring: authoring a demo block called "Field 7" is a decision    #
        # someone made, whereas deriving one from the string would fabricate  #
        # structure nobody recorded.                                          #
        # ------------------------------------------------------------------ #
        block_field7 = models.Block(
            farm_id=farm3.id,
            name="Field 7",
            crop="strawberry",
            cultivar="Monterey",
            area=6.0,
            area_unit="acres",
            planting_date=farm3.planting_date,
            expected_harvest_date=farm3.expected_harvest_date,
            phenology_stage="fruiting",
            phenology_observed_on=today - timedelta(days=2),
            notes="Low, shaded rows — the block carrying the gray-mold pressure.",
            data_source="demo",
            data_confidence="simulated",
        )
        block_south = models.Block(
            farm_id=farm3.id,
            name="South Block",
            crop="strawberry",
            cultivar="Albion",
            area=5.0,
            area_unit="acres",
            planting_date=farm3.planting_date,
            expected_harvest_date=farm3.expected_harvest_date,
            phenology_stage="fruiting",
            phenology_observed_on=today - timedelta(days=6),
            notes="Warmer, better airflow — the contrast block.",
            data_source="demo",
            data_confidence="simulated",
        )
        db.add_all([block_field7, block_south])
        db.flush()

        # Station weather, two-hourly across the snapshot's 7-day lookback so the
        # record has no gap beyond `disease_risk.MAX_GAP_HOURS`.
        #
        # `recorded_at` == `observed_at`: the demo story is a station reporting as the
        # weather happens. It is NOT back-dated history — that distinction is the one
        # `app/pit.py` exists to protect, and a seed that quietly violated it would
        # teach exactly the wrong thing to whoever reads this next.
        #
        # NOTE WHAT THIS DOES NOT PRODUCE, because it surprises people. These rows are
        # demo/simulated, so `pit.admissible` excludes every one of them and any
        # assessment over this block abstains. That is correct and worth demonstrating:
        # the demo/real guard is not a UI filter, it reaches all the way into the risk
        # path. A demo farm can never show a risk band, for the same structural reason
        # it can never show a label-grounded decision (ENGINEERING_GUIDELINES.md §5, reference farm).
        #
        # THE CONFUSING PART: the abstention reads `no_weather_in_window`, NOT
        # `demo_or_simulated_input_present`. Demo rows are filtered out at the snapshot
        # layer, so `disease_risk._weather_problems` never sees them and honestly
        # reports that no ADMISSIBLE weather exists. Someone looking at 85 visible
        # weather rows will read that as a bug. It is not — the real reason is on
        # `RiskInputSnapshot.excluded`, every row tagged `demo_or_simulated_source`.
        #
        # `leaf_wetness_minutes` stays None on purpose: no wetness sensor exists on any
        # farm in this system, and seeding a wetness number would fabricate the exact
        # measurement the pilot is blocked on.
        weather_rows = []
        for step in range(85):
            observed = _at(today, 6) - timedelta(hours=2 * step)
            weather_rows.append(
                models.WeatherObservation(
                    farm_id=farm3.id,
                    block_id=block_field7.id,
                    station_id="CIMIS-111",
                    station_name="Watsonville West (demo)",
                    station_distance_km=4.2,
                    observed_at=observed,
                    recorded_at=observed,
                    temperature_c=round(13.5 + 3.5 * ((step % 12) / 12.0), 1),
                    relative_humidity_pct=round(78.0 + 14.0 * ((step % 9) / 9.0), 1),
                    rainfall_mm=0.0,
                    leaf_wetness_minutes=None,
                    wetness_is_measured=None,
                    source_type="manual_entry",
                    source_reference="Demo station export (simulated)",
                    data_source="demo",
                    data_confidence="simulated",
                )
            )
        db.add_all(weather_rows)

        # Standardized scouting samples — the pilot's counted-units format, which is a
        # different record from the free-text `ScoutObservation` above. Both exist
        # because a severity 1-5 impression and "9 of 200 fruit affected" are not the
        # same evidence, and the pilot needs the countable one.
        db.add_all([
            models.ScoutingSample(
                farm_id=farm3.id,
                block_id=block_field7.id,
                observed_at=_at(today - timedelta(days=2), 8),
                recorded_at=_at(today - timedelta(days=2), 8),
                method="fruit_count",
                target="botrytis_fruit_rot",
                units_inspected=200,
                units_affected=9,
                incidence_pct=4.5,
                scout_name="Demo scout (simulated)",
                notes="Low shaded rows; infected berries clustered.",
                source_type="manual_entry",
                data_source="demo",
                data_confidence="simulated",
            ),
            models.ScoutingSample(
                farm_id=farm3.id,
                block_id=block_south.id,
                observed_at=_at(today - timedelta(days=6), 8),
                recorded_at=_at(today - timedelta(days=6), 8),
                method="fruit_count",
                target="botrytis_fruit_rot",
                units_inspected=200,
                units_affected=2,
                incidence_pct=1.0,
                scout_name="Demo scout (simulated)",
                notes="Contrast block — better airflow, little pressure.",
                source_type="manual_entry",
                data_source="demo",
                data_confidence="simulated",
            ),
        ])

        # ------------------------------------------------------------------ #
        # Demo scenario 1 (risky spray CHANGED after PCA review):             #
        #   a 4th captan cover spray planned 1 day before harvest is BLOCKED  #
        #   (PHI conflict + repeated chemistry), the demo PCA edits the       #
        #   guidance to a PHI-0 alternative, and the grower records           #
        #   "changed product" — Lumos changed a risky spray.                  #
        #   Chronology: checked and PCA-reviewed the MORNING BEFORE the       #
        #   intended date (procurement needs the review to precede the plan   #
        #   and the delivery to precede the application); the replacement is  #
        #   applied on the intended day itself.                               #
        #   All demo/simulated: excluded from real pilot evidence by design.  #
        # ------------------------------------------------------------------ #
        # The day the check ran and the whole procurement chain was set up.
        prev = today - timedelta(days=1)
        # Values entered by the demo PCA -> the block is PCA-AUTHORIZED under
        # authority gating (grower-entered values would make it provisional).
        planned_data = schemas.PlannedSprayCreate(
            intended_date=today,  # checked the day before, applied as intended
            product_name="Captan 80 WDG",
            active_ingredient="captan",
            target_pest_or_disease="gray mold (Botrytis) on ripening fruit, spreading",
            pre_harvest_interval_days=4,
            re_entry_interval_hours=24,
            estimated_cost=120.0,
            field_block="Field 7",
            values_source="pca_entered",
            values_entered_by="Demo PCA (simulated)",
            data_source="demo",
            data_confidence="simulated",
        )
        # Run the real decision engine anchored to the CHECK day (prev): the recent
        # captans (prev, prev-9, prev-19) and the fresh scouting are all inside the
        # window, and the PHI conflict is date math on intended vs harvest — so the
        # verdict is a real engine output, not a fabricated snapshot. The assert
        # makes any future engine/history drift fail loudly at reseed time.
        decision = evaluate_planned_spray(
            farm3, planned_data, farm3_sprays, [farm3_obs], today=prev
        )
        assert decision.outcome == "block", (
            f"seed expects the captan check to BLOCK, got '{decision.outcome}' — "
            "the demo story or engine rules drifted"
        )
        harvest_label = farm3.expected_harvest_date.isoformat()
        # A named replacement product is ONLY allowed as explicit PCA-entered guidance
        # (this note), never as engine output.
        switch_note = (
            f"Blocked as planned: captan's entered PHI cannot clear before the expected "
            f"{harvest_label} harvest, and this would be the 4th captan in 30 days. "
            f"Switch to Switch 62.5 WG (cyprodinil + fludioxonil, entered PHI 0 days) "
            f"for this application and rotate chemistry."
        )
        planned1 = models.PlannedSpray(
            farm_id=farm3.id,
            **planned_data.model_dump(),
            decision_outcome=decision.outcome,
            decision_severity=decision.severity,
            decision_confidence=decision.confidence,
            decision_authority=decision.authority_level,
            required_next_action=decision.required_next_action,
            review_required=decision.review_required,
            decision_payload=decision.as_payload(),
            check_risk_level="elevated",
            check_text=decision.narrative,
            review_status="edited",
            review_comment="Agree with the block — do not apply captan this close to harvest.",
            reviewed_by="Demo PCA (simulated)",
            reviewed_at=_at(prev, 9),
            pca_next_action=switch_note,
            outcome="changed_product",
            outcome_reason=(
                "Followed the PCA's edited guidance: applied Switch 62.5 WG instead of a "
                "4th captan this close to harvest."
            ),
            outcome_date=today,
            outcome_product_name="Switch 62.5 WG",
            outcome_active_ingredient="cyprodinil + fludioxonil",
            # Checked the morning before the intended date; reviewed an hour later;
            # outcome recorded on the intended day after the actual application.
            created_at=_at(prev, 8),
        )
        db.add(planned1)
        # Linked EXPLICITLY, not inferred from `field_block="Field 7"` above. Without a
        # block_id `crud.create_risk_snapshot` refuses outright — a risk assessment is
        # always about a specific block, and the block is never guessed from free text.
        planned1.block_id = block_field7.id

        # The spray that actually happened after the changed-product outcome —
        # created and LINKED to the decision, exactly like a live recorded outcome.
        switch_event = models.SprayEvent(
            farm_id=farm3.id,
            product_name="Switch 62.5 WG",
            active_ingredient="cyprodinil + fludioxonil",
            pesticide_class="anilinopyrimidine + phenylpyrrole fungicide",
            target_pest_or_disease="gray mold (Botrytis) on ripening fruit, spreading",
            dose="14 oz/acre",
            application_date=today,
            cost=210.0,
            pre_harvest_interval_days=0,
            re_entry_interval_hours=12,
            field_block="Field 7",
            notes="Applied instead of a 4th captan after the pre-spray check was blocked "
            "and the demo PCA edited the guidance.",
        )
        db.add(switch_event)
        db.flush()  # assign switch_event.id
        planned1.spray_event_id = switch_event.id

        demo_ts = datetime.combine(today, datetime.min.time())
        # Field-level provenance + immutable audit trail (PCA-entered -> pca_verified):
        # created/values at the check, review an hour later, outcome the next day
        # after the actual application.
        _seed_decision_trail(
            db, planned1, source_type="pca_verified",
            entered_by="Demo PCA (simulated)", ts=_at(prev, 8),
            review_ts=_at(prev, 9), outcome_ts=_at(today, 9, 30),
        )
        # Follow-up timeline: the replacement application actually happened. No
        # pesticide-reduction claim is attached — a different product was applied.
        db.add(models.DecisionFollowUpEvent(
            planned_spray_id=planned1.id,
            event_type="actual_application",
            observed_at=today,
            actual_product="Switch 62.5 WG",
            actual_rate_amount=14.0,
            actual_rate_unit="oz/acre",
            actual_treated_acres=18.0,
            cost=210.0,
            evidence_notes=(
                "Replacement product applied per the PCA's edited guidance. Demo/"
                "simulated record — no reduction or savings claim."
            ),
            entered_by="Demo grower (simulated)",
            source_type="demo",
            confidence="simulated",
            created_at=_at(today, 9, 30),  # recorded right after the application
        ))

        # ------------------------------------------------------------------ #
        # Demo scenario 2 (unnecessary routine spray AVOIDED — the pesticide- #
        # reduction story):                                                   #
        #   the demo PCA has entered an action threshold for lygus ("treat    #
        #   only if scouting severity >= 3"); a routine PyGanic cover spray   #
        #   is checked with no lygus scouting on record -> INSPECT FIRST      #
        #   (policy-cited, provisional). The follow-up inspection finds       #
        #   severity 2 — below the entered threshold — and the recorded       #
        #   outcome is AVOIDED. The threshold is PCA-entered and attributed;  #
        #   Lumos never invents one. All demo/simulated.                      #
        # ------------------------------------------------------------------ #
        lygus_policy = models.PcaPolicy(
            farm_id=farm3.id,
            target_pest_or_disease="lygus bug",
            min_severity_to_treat=3,
            entered_by="Demo PCA (simulated)",
            notes="Demo policy: hold routine lygus cover sprays below scouting severity 3.",
            data_source="demo",
            data_confidence="simulated",
            created_at=datetime.combine(today, datetime.min.time()),
        )
        db.add(lygus_policy)

        planned2_data = schemas.PlannedSprayCreate(
            intended_date=today,
            product_name="PyGanic EC 5.0",
            active_ingredient="pyrethrins",
            target_pest_or_disease="lygus bug",
            pre_harvest_interval_days=0,   # PHI 0 is a real entered value, not missing
            re_entry_interval_hours=12,
            estimated_cost=95.0,
            field_block="North Block",
            values_source="grower_entered",
            values_entered_by="Demo grower (simulated)",
            data_source="demo",
            data_confidence="simulated",
        )
        # Evaluate against the records as they stood BEFORE this check's own follow-up
        # (no lygus scouting yet, Switch spray not part of the pre-check history).
        decision2 = evaluate_planned_spray(
            farm3, planned2_data, farm3_sprays, [farm3_obs],
            pca_policies=[lygus_policy], today=today,
        )
        assert decision2.outcome == "inspect_first", decision2.outcome

        planned2 = models.PlannedSpray(
            farm_id=farm3.id,
            **planned2_data.model_dump(),
            decision_outcome=decision2.outcome,
            decision_severity=decision2.severity,
            decision_confidence=decision2.confidence,
            decision_authority=decision2.authority_level,
            required_next_action=decision2.required_next_action,
            review_required=decision2.review_required,
            decision_payload=decision2.as_payload(),
            check_risk_level="moderate",
            check_text=decision2.narrative,
            review_status="edited",
            review_comment=(
                "Hold this application — inspect first, per the entered lygus action "
                "threshold."
            ),
            reviewed_by="Demo PCA (simulated)",
            reviewed_at=datetime.combine(today, datetime.min.time()),
            pca_next_action=(
                "Hold the routine PyGanic application. Scout the field edges today; "
                "treat only if lygus severity reaches 3 or more (entered action "
                "threshold). Re-scout in 3–4 days."
            ),
            outcome="avoided",
            outcome_reason=(
                "Inspected first: lygus severity 2, below the PCA-entered action "
                "threshold (treat only if severity >= 3). Routine cover spray not "
                "applied."
            ),
            outcome_date=today,
            created_at=datetime.combine(today, datetime.min.time()),
        )
        db.add(planned2)
        # DELIBERATELY left unlinked. Its `field_block` is "North Block", for which no
        # Block row was authored — so this decision shows the real, common state of a
        # farm partway through adopting blocks. `block_id` is nullable precisely for
        # this, and a risk snapshot correctly refuses on it rather than guessing.

        db.flush()  # assign planned2.id for its provenance/audit/follow-up rows
        _seed_decision_trail(
            db, planned2, source_type="user_entered",
            entered_by="Demo grower (simulated)", ts=demo_ts,
        )
        # Follow-up timeline: the inspection happened, pressure stayed below the
        # entered threshold, no rescue was needed. Yield impact deliberately stays
        # UNKNOWN — nothing here was measured, and unknown is reported as unknown.
        db.add(models.DecisionFollowUpEvent(
            planned_spray_id=planned2.id,
            event_type="scouting_observation",
            observed_at=today,
            severity=2,
            severity_scale="1-5",
            cost=35.0,
            rescue_required=False,
            evidence_notes=(
                "Follow-up inspection: lygus severity 2, below the PCA-entered "
                "threshold of 3. No application made; no rescue needed so far. Yield "
                "impact unknown (not measured). Demo/simulated record."
            ),
            entered_by="Demo PCA (simulated)",
            source_type="demo",
            confidence="simulated",
            created_at=demo_ts,
        ))

        # The follow-up inspection the INSPECT FIRST outcome asked for (same demo day):
        # lygus pressure logged at severity 2 — below the PCA-entered threshold of 3.
        db.add(models.ScoutObservation(
            farm_id=farm3.id,
            observation_date=today,
            crop_stage="fruiting",
            visible_issue="lygus bug",
            severity_1_to_5=2,
            field_block="North Block",
            notes="Follow-up inspection after the pre-spray check returned INSPECT "
            "FIRST: a few lygus on field edges, below the entered action threshold.",
        ))

        # ------------------------------------------------------------------ #
        # Demo scenario 3 (FAILED reduction attempt — shown honestly):        #
        #   a miticide was planned for twospotted spider mite at scouting     #
        #   severity 2 (below the PCA-entered threshold of 3), the check said #
        #   INSPECT FIRST, the PCA held it — and the pressure then ROSE to    #
        #   severity 4, forcing a RESCUE application days later. Net result   #
        #   is negative (extra scouting + rescue cost, no spray avoided).     #
        #   The product must show failures like this or its evidence is not  #
        #   credible. All demo/simulated.                                     #
        # ------------------------------------------------------------------ #
        check_day = today - timedelta(days=6)
        check_ts = datetime.combine(check_day, datetime.min.time())
        mite_policy = models.PcaPolicy(
            farm_id=farm3.id,
            target_pest_or_disease="twospotted spider mite",
            min_severity_to_treat=3,
            entered_by="Demo PCA (simulated)",
            notes="Demo policy: treat mites only at scouting severity 3 or more.",
            data_source="demo",
            data_confidence="simulated",
            created_at=check_ts,
        )
        db.add(mite_policy)

        mite_obs_before = models.ScoutObservation(
            farm_id=farm3.id,
            observation_date=today - timedelta(days=8),
            crop_stage="fruiting",
            visible_issue="twospotted spider mite",
            severity_1_to_5=2,
            field_block="South Block",
            notes="Scattered mites on lower leaves; below the entered action threshold.",
        )
        db.add(mite_obs_before)

        planned3_data = schemas.PlannedSprayCreate(
            intended_date=today - timedelta(days=5),
            product_name="Agri-Mek SC",
            active_ingredient="abamectin",
            target_pest_or_disease="twospotted spider mite",
            pre_harvest_interval_days=3,
            re_entry_interval_hours=12,
            estimated_cost=190.0,
            field_block="South Block",
            values_source="grower_entered",
            values_entered_by="Demo grower (simulated)",
            data_source="demo",
            data_confidence="simulated",
        )
        # Evaluate against the records as they stood on the check day (sprays applied
        # later did not exist yet), anchored to that day.
        decision3 = evaluate_planned_spray(
            farm3, planned3_data,
            [s for s in farm3_sprays if s.application_date <= check_day],
            [mite_obs_before],
            pca_policies=[mite_policy], today=check_day,
        )
        assert decision3.outcome == "inspect_first", decision3.outcome

        planned3 = models.PlannedSpray(
            farm_id=farm3.id,
            **planned3_data.model_dump(),
            decision_outcome=decision3.outcome,
            decision_severity=decision3.severity,
            decision_confidence=decision3.confidence,
            decision_authority=decision3.authority_level,
            required_next_action=decision3.required_next_action,
            review_required=decision3.review_required,
            decision_payload=decision3.as_payload(),
            check_risk_level="moderate",
            check_text=decision3.narrative,
            review_status="edited",
            review_comment=(
                "Mite pressure is below the entered threshold — hold and re-scout "
                "before treating."
            ),
            reviewed_by="Demo PCA (simulated)",
            reviewed_at=check_ts,
            pca_next_action=(
                "Delay the miticide. Re-scout the block in 2-3 days; treat only if "
                "severity reaches 3 or more (entered action threshold)."
            ),
            outcome="delayed",
            outcome_reason=(
                "Held per the PCA's guidance to verify pressure before treating."
            ),
            outcome_date=today - timedelta(days=5),
            created_at=check_ts,
        )
        db.add(planned3)
        planned3.block_id = block_south.id
        db.flush()
        _seed_decision_trail(
            db, planned3, source_type="user_entered",
            entered_by="Demo grower (simulated)", ts=check_ts,
        )

        # Follow-up timeline: pressure ROSE after the delay and a rescue was required.
        db.add_all([
            models.DecisionFollowUpEvent(
                planned_spray_id=planned3.id,
                event_type="scouting_observation",
                observed_at=today - timedelta(days=3),
                severity=3,
                severity_scale="1-5",
                cost=0.0,
                evidence_notes="Re-scout: mite pressure rising, at threshold.",
                entered_by="Demo PCA (simulated)",
                source_type="demo",
                confidence="simulated",
                created_at=datetime.combine(today - timedelta(days=3), datetime.min.time()),
            ),
            models.DecisionFollowUpEvent(
                planned_spray_id=planned3.id,
                event_type="scouting_observation",
                observed_at=today - timedelta(days=2),
                severity=4,
                severity_scale="1-5",
                cost=40.0,
                evidence_notes=(
                    "Re-scout: mite flare-up, severity 4 with visible stippling — "
                    "the delay did not hold."
                ),
                entered_by="Demo PCA (simulated)",
                source_type="demo",
                confidence="simulated",
                created_at=datetime.combine(today - timedelta(days=2), datetime.min.time()),
            ),
            models.DecisionFollowUpEvent(
                planned_spray_id=planned3.id,
                event_type="rescue_application",
                observed_at=today - timedelta(days=1),
                actual_product="Agri-Mek SC",
                actual_rate_amount=3.5,
                actual_rate_unit="oz/acre",
                actual_treated_acres=18.0,
                cost=260.0,
                rescue_required=True,
                evidence_notes=(
                    "Rescue miticide required after the flare-up — the attempted "
                    "delay FAILED: extra scouting cost plus a more expensive rescue, "
                    "no application avoided. Counted as a failure. Demo/simulated."
                ),
                entered_by="Demo grower (simulated)",
                source_type="demo",
                confidence="simulated",
                created_at=datetime.combine(today - timedelta(days=1), datetime.min.time()),
            ),
        ])

        # The farm-level records behind the follow-up story (scouting + rescue spray).
        db.add(models.ScoutObservation(
            farm_id=farm3.id,
            observation_date=today - timedelta(days=2),
            crop_stage="fruiting",
            visible_issue="twospotted spider mite",
            severity_1_to_5=4,
            field_block="South Block",
            notes="Mite flare-up after the delayed miticide — rescue treatment needed.",
        ))
        db.add(models.SprayEvent(
            farm_id=farm3.id,
            product_name="Agri-Mek SC",
            active_ingredient="abamectin",
            pesticide_class="avermectin miticide",
            target_pest_or_disease="twospotted spider mite",
            dose="3.5 oz/acre",
            application_date=today - timedelta(days=1),
            cost=260.0,
            pre_harvest_interval_days=3,
            re_entry_interval_hours=12,
            field_block="South Block",
            notes="Rescue application after the delayed miticide failed to hold.",
        ))

        # ------------------------------------------------------------------ #
        # Demo procurement scenario (Inputs & finance, workflow demo ONLY):   #
        #   the PCA-edited scenario-1 decision (Switch 62.5 WG) becomes an    #
        #   input-plan item -> RFQ -> two materially different simulated      #
        #   quotes (one cash-only, one with an indicative financing offer)    #
        #   -> quote selected (with the entered reason) -> order -> delivered #
        #   the next morning -> input applied, linked back to the already-    #
        #   seeded Switch application. Every row is demo/simulated. NO        #
        #   savings/impact claim anywhere — the scenario demonstrates the     #
        #   workflow, never a financial result.                               #
        #   Chronology (one honest day-and-a-morning, after the PCA review):  #
        #     prev 09:30 plan drafted   11:00 submitted for quotes            #
        #     prev 13:00/14:00 quotes entered   14:30 indicative offer        #
        #     prev 15:00 quote selected   16:00 offer selected                #
        #     prev 16:30 order placed   17:00 confirmed   17:30 shipped       #
        #     today 07:30 delivered   09:00 applied (the Switch SprayEvent)   #
        #     today 09:30 input_applied link recorded                         #
        # ------------------------------------------------------------------ #
        demo_selection_reason = (
            "Lower quoted total ($3,774.00 vs $3,920.80, both including delivery "
            "and fees) and indicative financing available; partial availability "
            "acceptable — delivery promised by the morning the input is needed."
        )
        demo_plan = models.InputPlan(
            farm_id=farm3.id,
            status="ordered",
            requested_by="Demo grower (simulated)",
            notes="Workflow demonstration — simulated prices.",
            financing_requested=True,
            financing_requested_by="Demo grower (simulated)",
            financing_notes="Asked for split-payment terms ahead of harvest cash flow.",
            submitted_at=_at(prev, 11),
            submitted_by="Demo grower (simulated)",
            selection_reason=demo_selection_reason,
            data_source="demo",
            data_confidence="simulated",
            created_at=_at(prev, 9, 30),  # drafted right after the PCA review
        )
        db.add(demo_plan)
        db.flush()
        demo_item = models.InputPlanItem(
            input_plan_id=demo_plan.id,
            planned_spray_id=planned1.id,  # eligible: PCA-edited review, applied outcome
            field_block="Field 7",
            crop="strawberry",
            category="fungicide",
            product_name="Switch 62.5 WG",
            active_ingredient="cyprodinil + fludioxonil",
            quantity=252.0,  # 14 oz/acre x 18 acres
            unit="oz",
            acres=18.0,
            needed_by_date=today,
            intended_use="gray mold (Botrytis) on ripening fruit",
            # The grower's own pre-quote estimate for the whole 252 oz line — the
            # documented baseline the value ledger compares the selected quote to.
            estimated_cost=3900.0,
            created_by="Demo grower (simulated)",
            data_source="demo",
            data_confidence="simulated",
            created_at=_at(prev, 9, 30),
        )
        db.add(demo_item)
        db.flush()

        # Quote A — cash only, in stock, same-day delivery, higher total.
        quote_a = models.SupplierQuote(
            input_plan_id=demo_plan.id,
            supplier_name="Coastal Ag Supply (simulated)",
            status="submitted",
            delivery_cost=40.0,
            fees=0.0,
            payment_terms_cash="Due on delivery",
            expected_delivery_date=prev,  # could have delivered the same afternoon
            availability="in_stock",
            expires_on=today + timedelta(days=7),
            verification="concierge_entered",
            notes="Simulated demo quote — concierge-entered for workflow demonstration.",
            entered_by="Lumos concierge (demo)",
            data_source="demo",
            data_confidence="simulated",
            created_at=_at(prev, 13),
        )
        # Quote B — lower unit price but partial availability, next-morning
        # delivery, Net 30 cash terms, and an indicative financing offer.
        # SELECTED (with the reason stored on the plan) so the demo exercises
        # quote_selected + financing_selected end to end. Its promised delivery
        # (today) is on-or-before the needed-by date and matches the actual
        # delivered event — the chain never contradicts itself.
        quote_b = models.SupplierQuote(
            input_plan_id=demo_plan.id,
            supplier_name="Valley Farm Inputs (simulated)",
            status="selected",
            delivery_cost=95.0,
            fees=25.0,
            payment_terms_cash="Net 30",
            expected_delivery_date=today,
            availability="partial",
            expires_on=today + timedelta(days=10),
            verification="concierge_entered",
            notes="Simulated demo quote — concierge-entered for workflow demonstration.",
            entered_by="Lumos concierge (demo)",
            data_source="demo",
            data_confidence="simulated",
            created_at=_at(prev, 14),
        )
        db.add_all([quote_a, quote_b])
        db.flush()
        db.add_all([
            models.SupplierQuoteItem(
                supplier_quote_id=quote_a.id,
                input_plan_item_id=demo_item.id,
                product_name="Switch 62.5 WG",
                quantity=252.0,
                unit="oz",
                unit_price=15.40,
            ),
            models.SupplierQuoteItem(
                supplier_quote_id=quote_b.id,
                input_plan_item_id=demo_item.id,
                product_name="Switch 62.5 WG",
                quantity=252.0,
                unit="oz",
                unit_price=14.50,
            ),
        ])
        demo_offer = models.FinancingOffer(
            supplier_quote_id=quote_b.id,
            provider_name="AgCredit Partners (simulated)",
            requested_amount=3700.0,
            down_payment=700.0,
            financed_amount=3000.0,
            total_repayment=3150.0,
            fees_total=45.0,
            schedule_summary="3 monthly payments of $1,050",
            expires_on=today + timedelta(days=14),
            required_documents="Simulated demo — none collected.",
            conditions="Indicative terms only; simulated demo data.",
            status="selected",
            decided_by="Demo grower (simulated)",
            decided_at=_at(prev, 16),
            decision_notes="Selected indicative terms (simulated demo — not a loan, "
            "not an approval).",
            entered_by="Lumos concierge (demo)",
            data_source="demo",
            data_confidence="simulated",
            created_at=_at(prev, 14, 30),  # terms visible BEFORE the quote was selected
        )
        db.add(demo_offer)
        db.flush()
        demo_plan.selected_quote_id = quote_b.id
        demo_plan.selected_by = "Demo grower (simulated)"

        # The plan's own append-only audit timeline (mirrors what live crud writes
        # at submit / select-quote / offer decision / order).
        demo_plan_events = [
            ("submitted", _at(prev, 11), prev, "Demo grower (simulated)", None, {
                "from_status": "draft", "to_status": "submitted_for_quotes",
                "item_count": 1,
            }),
            ("quote_selected", _at(prev, 15), prev, "Demo grower (simulated)", None, {
                "from_status": "quoted", "to_status": "quote_selected",
                "supplier_quote_id": quote_b.id,
                "supplier_name": quote_b.supplier_name,
                "total_cost": 3774.0,
                "reason": demo_selection_reason,
            }),
            ("financing_offer_selected", _at(prev, 16), prev,
             "Demo grower (simulated)",
             "Selected indicative terms (simulated demo — not a loan, not an "
             "approval).", {
                "financing_offer_id": demo_offer.id,
                "provider_name": demo_offer.provider_name,
                "financed_amount": demo_offer.financed_amount,
                "supplier_quote_id": quote_b.id,
                "from_offer_status": "indicative", "to_offer_status": "selected",
            }),
            ("ordered", _at(prev, 16, 30), prev, "Demo grower (simulated)", None, {
                "from_status": "quote_selected", "to_status": "ordered",
                "purchase_order_id": None,  # filled below once the order exists
            }),
        ]

        demo_order = models.PurchaseOrder(
            farm_id=farm3.id,
            input_plan_id=demo_plan.id,
            selected_quote_id=quote_b.id,
            accepted_financing_offer_id=demo_offer.id,
            status="delivered",
            spray_event_id=switch_event.id,
            applied_planned_spray_id=planned1.id,
            placed_by="Demo grower (simulated)",
            notes="Workflow demonstration — simulated prices.",
            data_source="demo",
            data_confidence="simulated",
            created_at=_at(prev, 16, 30),
        )
        db.add(demo_order)
        db.flush()
        for event_type, created, occurred, actor, note, payload in demo_plan_events:
            if event_type == "ordered":
                payload = {**payload, "purchase_order_id": demo_order.id}
            db.add(models.InputPlanEvent(
                input_plan_id=demo_plan.id,
                event_type=event_type,
                occurred_on=occurred,
                actor=actor,
                notes=note,
                payload=payload,
                data_source="demo",
                data_confidence="simulated",
                created_at=created,
            ))
        # Append-only order timeline (mirrors what live crud writes: created/
        # quote_selected/financing_selected are the order-creation provenance
        # events, the rest are lifecycle events). Ordered the afternoon before,
        # delivered the next morning BEFORE the application — the chain's dates
        # never contradict each other.
        demo_order_events = [
            ("created", _at(prev, 16, 30), prev,
             "Demo grower (simulated)", None, {"input_plan_id": demo_plan.id}),
            ("quote_selected", _at(prev, 16, 31), prev,
             "Demo grower (simulated)", None, {
                "supplier_quote_id": quote_b.id,
                "supplier_name": quote_b.supplier_name,
                "total_cost": 3774.0,  # 252 oz x $14.50 + $95 delivery + $25 fees
                "reason": demo_selection_reason,
            }),
            ("financing_selected", _at(prev, 16, 32), prev,
             "Demo grower (simulated)", None, {
                "financing_offer_id": demo_offer.id,
                "provider_name": demo_offer.provider_name,
                "financed_amount": demo_offer.financed_amount,
            }),
            ("supplier_confirmed", _at(prev, 17), prev, "Lumos concierge (demo)",
             "Supplier confirmed the order (simulated).", None),
            ("shipped", _at(prev, 17, 30), prev, "Lumos concierge (demo)", None, None),
            ("delivered", _at(today, 7, 30), today, "Lumos concierge (demo)",
             "Delivered to the barn at Field 7 (simulated).", None),
            ("input_applied", _at(today, 9, 30), today, "Demo grower (simulated)",
             "Applied per the PCA-edited guidance; see the linked decision record.",
             {
                "planned_spray_id": planned1.id,
                "spray_event_id": switch_event.id,
            }),
        ]
        for event_type, created, occurred, actor, note, payload in demo_order_events:
            db.add(models.OrderEvent(
                purchase_order_id=demo_order.id,
                event_type=event_type,
                occurred_on=occurred,
                actor=actor,
                notes=note,
                payload=payload,
                data_source="demo",
                data_confidence="simulated",
                created_at=created,
            ))

        # Declared spray baseline so the U.S. demo shows *measured* reduction, not just
        # descriptive metrics. Kept demo/simulated so the engine correctly flags the number as
        # illustrative (never present seed data as a real reduction result — see ENGINEERING_GUIDELINES.md §9).
        db.add(
            models.SprayBaseline(
                farm_id=farm3.id,
                method="stated_cadence",
                cadence_days=4,  # typical peak-season cover-spray cadence
                data_source="demo",
                data_confidence="simulated",
                declared_by="Grower (demo)",
                notes="Demo baseline: stated peak-botrytis cover-spray cadence. Illustrative only.",
            )
        )

        # ------------------------------------------------------------------ #
        # The season, for farm 3. `CropCycle` is the economic unit every cost   #
        # and outcome hangs off; without one seeded, the value ledger has       #
        # nothing to scope to and reads as broken rather than as empty.         #
        # Demo/simulated like every other seeded row — an avoided application   #
        # here is an illustration, never value anyone created (ENGINEERING_GUIDELINES.md §9).   #
        # ------------------------------------------------------------------ #
        field3 = models.Field(
            farm_id=farm3.id,
            name="Field 7",
            display_area=18.0,
            display_area_unit="acres",
            area_m2=18.0 * 4046.8564224,
            irrigation_type="drip",
            data_source="demo",
            data_confidence="simulated",
        )
        db.add(field3)
        db.flush()

        cycle3 = models.CropCycle(
            farm_id=farm3.id,
            field_id=field3.id,
            crop="strawberry",
            variety_name="Monterey",
            season_year=today.year,
            season_label=f"{today.year} spring plant",
            planting_date=farm3.planting_date,
            expected_harvest_start=farm3.expected_harvest_date,
            planted_area_m2=18.0 * 4046.8564224,
            display_area=18.0,
            display_area_unit="acres",
            status="harvesting",
            currency_code="USD",
            data_source="demo",
            data_confidence="simulated",
        )
        db.add(cycle3)
        db.flush()

        # Non-spray costs the season actually carried. These have had a column
        # (`Operation.cost_amount`) and no writer since the entity-spine phase.
        db.add_all([
            models.Operation(
                farm_id=farm3.id, crop_cycle_id=cycle3.id, field_id=field3.id,
                operation_type="fertilization", cost_category="fertilizer_nutrition",
                performed_on=today - timedelta(days=40),
                cost_amount=1450.0, currency_code="USD",
                notes="Pre-bloom fertigation pass.",
                data_source="demo", data_confidence="simulated",
            ),
            models.Operation(
                farm_id=farm3.id, crop_cycle_id=cycle3.id, field_id=field3.id,
                operation_type="irrigation", cost_category="irrigation",
                performed_on=today - timedelta(days=12),
                cost_amount=380.0, currency_code="USD",
                data_source="demo", data_confidence="simulated",
            ),
            models.Operation(
                farm_id=farm3.id, crop_cycle_id=cycle3.id, field_id=field3.id,
                operation_type="harvest", cost_category="labor",
                performed_on=today - timedelta(days=8),
                cost_amount=9200.0, currency_code="USD",
                notes="First and second pick — contract harvest crew.",
                data_source="demo", data_confidence="simulated",
            ),
            # Deliberately costless: the season is mid-flight and this pass has not
            # been invoiced. It is what makes the demo show a real cost-coverage gap
            # instead of a season that looks perfectly documented.
            models.Operation(
                farm_id=farm3.id, crop_cycle_id=cycle3.id, field_id=field3.id,
                operation_type="tillage",
                performed_on=today - timedelta(days=52),
                currency_code="USD",
                notes="Bed shaping — contractor has not invoiced yet.",
                data_source="demo", data_confidence="simulated",
            ),
        ])

        # A measured harvest outcome. Per block per harvest — one outcome is
        # evidence for many decisions and for none in particular.
        block3 = db.scalars(
            select(models.Block).where(models.Block.farm_id == farm3.id)
        ).first()
        if block3 is not None:
            db.add(models.BlockOutcomeObservation(
                block_id=block3.id,
                observed_on=today - timedelta(days=1),
                outcome_type="marketable_packout",
                value=87.5,
                unit="pct",
                denominator=1200.0,
                method="Trays graded at the cooler, first pick.",
                source_type="demo",
                data_source="demo",
                data_confidence="simulated",
            ))

        # Harvest weight per block, in lb — the unit a Watsonville settlement is
        # written in. The closeout normalises both to kg through exact factors, which
        # is the whole reason yield is recorded with a unit and never as a bare number.
        harvest_yields = [
            (block_field7, 34200.0, 9, "First and second pick, cooler scale tickets."),
            (block_south, 26800.0, 7, "First pick, cooler scale tickets."),
        ]
        for block, pounds, days_ago, method in harvest_yields:
            db.add(models.BlockOutcomeObservation(
                block_id=block.id,
                observed_on=today - timedelta(days=days_ago),
                outcome_type="yield",
                value=pounds,
                unit="lb",
                method=method,
                source_type="demo",
                data_source="demo",
                data_confidence="simulated",
            ))

        # Two recorded settlements. Gross, deductions and net stay three numbers:
        # the packer withholds commission and cooling before the grower sees a cheque,
        # and collapsing that into one "revenue" figure loses which is which.
        db.add_all([
            models.SaleRecord(
                farm_id=farm3.id, crop_cycle_id=cycle3.id,
                sale_date=today - timedelta(days=6),
                quantity=34200.0, unit="lb", unit_price=1.85,
                gross_amount=63270.0, deductions_amount=5061.60,
                currency_code="USD",
                buyer_name="Pajaro Valley Packing (demo)",
                reference="STL-2411-A",
                grade="US No. 1", market="fresh",
                notes="Commission 6% and cooling withheld at settlement.",
                data_source="demo", data_confidence="simulated",
            ),
            models.SaleRecord(
                farm_id=farm3.id, crop_cycle_id=cycle3.id,
                sale_date=today - timedelta(days=2),
                quantity=26800.0, unit="lb", unit_price=1.62,
                gross_amount=43416.0, deductions_amount=3473.28,
                currency_code="USD",
                buyer_name="Pajaro Valley Packing (demo)",
                reference="STL-2411-B",
                grade="US No. 1", market="fresh",
                data_source="demo", data_confidence="simulated",
            ),
        ])

        db.commit()
        # Attach the farm's existing sprays, decisions, scouting and input plans to
        # the season through the same backfill the API calls — so the demo exercises
        # the real code path rather than a seed-only shortcut.
        crud.link_records_to_cycle(db, cycle3)

        print(f"Seeded HIGH-risk farm:  {farm1.name} (id={farm1.id}, {farm1.country})")
        print(f"Seeded LOW-risk  farm:  {farm2.name} (id={farm2.id}, {farm2.country})")
        print(f"Seeded U.S. wedge farm: {farm3.name} (id={farm3.id}, {farm3.country})")
        # Summary for callers (the internal demo-reset endpoint returns this).
        return {
            "anchor": today.isoformat(),
            "farms": [
                {"id": f.id, "name": f.name, "country": f.country}
                for f in (farm1, farm2, farm3)
            ],
        }
    finally:
        db.close()


if __name__ == "__main__":
    run()
