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
from datetime import date, datetime, timedelta

from app import clock, models, schemas
from app.database import Base, SessionLocal, engine, init_db
from app.decision_engine import evaluate_planned_spray


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
            greenhouse_area=18.0,  # 18 acres (US farms store area in acres)
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
            notes="Several infected berries per bed in the low, shaded rows.",
        )
        db.add(farm3_obs)

        # ------------------------------------------------------------------ #
        # Demo scenario 1 (risky spray CHANGED after PCA review):             #
        #   a 4th captan cover spray planned 1 day before harvest is BLOCKED  #
        #   (PHI conflict + repeated chemistry), the demo PCA edits the       #
        #   guidance to a PHI-0 alternative, and the grower records           #
        #   "changed product" — Lumos changed a risky spray.                  #
        #   All demo/simulated: excluded from real pilot evidence by design.  #
        # ------------------------------------------------------------------ #
        # Values entered by the demo PCA -> the block is PCA-AUTHORIZED under
        # authority gating (grower-entered values would make it provisional).
        planned_data = schemas.PlannedSprayCreate(
            intended_date=today,  # checked and resolved the same day it was intended
            product_name="Captan 80 WDG",
            active_ingredient="captan",
            target_pest_or_disease="gray mold (Botrytis) on ripening fruit, spreading",
            pre_harvest_interval_days=4,
            re_entry_interval_hours=24,
            estimated_cost=120.0,
            values_source="pca_entered",
            values_entered_by="Demo PCA (simulated)",
            data_source="demo",
            data_confidence="simulated",
        )
        # Run the real decision engine (anchored to the same demo date) so the demo
        # snapshot is authentic and internally consistent.
        decision = evaluate_planned_spray(
            farm3, planned_data, farm3_sprays, [farm3_obs], today=today
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
            reviewed_at=datetime.combine(today, datetime.min.time()),
            pca_next_action=switch_note,
            outcome="changed_product",
            outcome_reason=(
                "Followed the PCA's edited guidance: applied Switch 62.5 WG instead of a "
                "4th captan this close to harvest."
            ),
            outcome_date=today,
            outcome_product_name="Switch 62.5 WG",
            outcome_active_ingredient="cyprodinil + fludioxonil",
            # Anchor the record timestamps to the same demo day so the story's
            # check -> review -> outcome all read as one consistent day.
            created_at=datetime.combine(today, datetime.min.time()),
        )
        db.add(planned1)

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
            notes="Applied instead of a 4th captan after the pre-spray check was blocked "
            "and the demo PCA edited the guidance.",
        )
        db.add(switch_event)
        db.flush()  # assign switch_event.id
        planned1.spray_event_id = switch_event.id

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

        # The follow-up inspection the INSPECT FIRST outcome asked for (same demo day):
        # lygus pressure logged at severity 2 — below the PCA-entered threshold of 3.
        db.add(models.ScoutObservation(
            farm_id=farm3.id,
            observation_date=today,
            crop_stage="fruiting",
            visible_issue="lygus bug",
            severity_1_to_5=2,
            notes="Follow-up inspection after the pre-spray check returned INSPECT "
            "FIRST: a few lygus on field edges, below the entered action threshold.",
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

        db.commit()
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
