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
from app.database import SessionLocal, init_db


def run() -> None:
    init_db()
    db = SessionLocal()
    try:
        # Reset for a clean, repeatable demo.
        db.query(models.Recommendation).delete()
        db.query(models.SprayEvent).delete()
        db.query(models.ScoutObservation).delete()
        db.query(models.Farm).delete()
        db.commit()

        today = date.today()

        # ------------------------------------------------------------------ #
        # Farm 1 — HIGH RISK                                                  #
        # ------------------------------------------------------------------ #
        farm1 = models.Farm(
            name="Green Valley Greenhouse",
            location="Antalya, Türkiye",
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

        db.commit()
        print(f"Seeded HIGH-risk farm: {farm1.name} (id={farm1.id})")
        print(f"Seeded LOW-risk  farm: {farm2.name} (id={farm2.id})")
    finally:
        db.close()


if __name__ == "__main__":
    run()
