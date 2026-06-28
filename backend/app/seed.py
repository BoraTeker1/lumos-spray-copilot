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
from datetime import date, timedelta

from app import models
from app.database import Base, SessionLocal, engine, init_db


def run() -> None:
    # Recreate the schema so a clean demo always matches the current models
    # (there is no migration tooling; the SQLite file is disposable demo data).
    Base.metadata.drop_all(bind=engine)
    init_db()
    db = SessionLocal()
    try:

        today = date.today()

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

        db.add_all([
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
        ])

        # High-severity scouting -> elevated pressure flag.
        db.add(
            models.ScoutObservation(
                farm_id=farm3.id,
                observation_date=today - timedelta(days=2),
                crop_stage="fruiting",
                visible_issue="gray mold (Botrytis) on ripening fruit, spreading",
                severity_1_to_5=4,
                notes="Several infected berries per bed in the low, shaded rows.",
            )
        )

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
    finally:
        db.close()


if __name__ == "__main__":
    run()
