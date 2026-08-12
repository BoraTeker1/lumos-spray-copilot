"""No feature may read data that was recorded after the moment it claims to describe.

This is the platform-wide version of `tests/test_leakage.py`, which guards the same rule
for the Botrytis snapshot. If it fails, every number this layer produces is worthless in
the specific way that matters: the value would have been computed from information nobody
had at `as_of`, so any accuracy claim built on it is fiction.

The central test is written as a LOOP OVER `base.REGISTRY` rather than as one test per
feature, so a feature added next year is covered without anyone remembering to add a
test. That is the only structure that survives the people who wrote it.
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app import pit
from app.database import SessionLocal
from app.features import base, compute

AS_OF = datetime(2026, 7, 8, 6, 0, 0)
BEFORE = AS_OF - timedelta(hours=6)
AFTER = AS_OF + timedelta(hours=6)


@pytest.fixture()
def db(client):
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def weather_row(id, observed_at, recorded_at, **kw):
    row = {
        "id": id, "observed_at": observed_at, "recorded_at": recorded_at,
        "temperature_c": 15.0, "relative_humidity_pct": 92.0,
        "leaf_wetness_minutes": 60.0, "wetness_is_measured": True,
        "quality_flag": None, "supersedes_id": None,
        "data_source": "provider_api", "data_confidence": "provider_reported",
    }
    row.update(kw)
    return SimpleNamespace(**row)


def spray_row(id, application_date, created_at, **kw):
    row = {
        "id": id, "application_date": application_date, "created_at": created_at,
        "product_name": "Switch 62.5WG", "epa_reg_no": "100-953", "moa_group": "9",
        "rate_amount": 14.0, "rate_unit": "oz/acre",
        "treated_acres": 4.0, "treated_area_unit": "acres",
        "data_source": "manual_entry", "data_confidence": "user_provided",
    }
    row.update(kw)
    return SimpleNamespace(**row)


def sample_row(id, observed_at, recorded_at, **kw):
    row = {
        "id": id, "observed_at": observed_at, "recorded_at": recorded_at,
        "quality_flag": None, "supersedes_id": None,
        "data_source": "manual_entry", "data_confidence": "user_provided",
    }
    row.update(kw)
    return SimpleNamespace(**row)


def base_row(id, observed_at, recorded_at, **kw):
    """A generic point-in-time row: the dual-timestamp shape `pit.admissible` reads.

    Structurally identical to `sample_row` — kept separate because the agronomy features
    consume soil tests, irrigation events and energy records, and calling all three
    `sample_row` would read as scouting data at every use site.
    """
    row = {
        "id": id, "observed_at": observed_at, "recorded_at": recorded_at,
        "quality_flag": None, "supersedes_id": None,
        "data_source": "manual_entry", "data_confidence": "user_provided",
    }
    row.update(kw)
    return SimpleNamespace(**row)


CONCENTRATIONS = {"100-953": (62.5, "%w/w")}


def clean_inputs() -> dict:
    """Inputs every feature can consume, all knowable at AS_OF."""
    return {
        "observations": [
            weather_row(1, BEFORE, BEFORE),
            weather_row(2, BEFORE + timedelta(hours=1), BEFORE + timedelta(hours=1)),
        ],
        "applications": [
            spray_row(1, (AS_OF - timedelta(days=6)).date(), AS_OF - timedelta(days=6)),
            spray_row(2, (AS_OF - timedelta(days=3)).date(), AS_OF - timedelta(days=3),
                      moa_group="12"),
        ],
        "samples": [sample_row(1, BEFORE, BEFORE)],
        "planted_area_ha": 1.62,
        "concentrations": CONCENTRATIONS,
        "as_of": AS_OF,
        # Agronomy inputs (2026-08-07). Given real rows rather than empty lists so the
        # loop below actually exercises these features — an empty list in and an empty
        # list out would make them pass this test vacuously forever.
        "soil_tests": [base_row(1, AS_OF - timedelta(days=30), AS_OF - timedelta(days=30))],
        "irrigation_events": [
            base_row(1, AS_OF - timedelta(days=5), AS_OF - timedelta(days=5),
                     depth_mm=12.0),
        ],
        "records_irrigation": True,
        "energy_records": [
            base_row(1, AS_OF - timedelta(days=5), AS_OF - timedelta(days=5), kwh=140.0),
        ],
    }


def poisoned_inputs() -> dict:
    """The same inputs plus rows that describe an EARLIER time but were recorded LATER.

    This is the subtle shape of the leak. Filtering on `observed_at` alone admits every
    one of these, looks correct in review, and passes any test someone would think to
    write — while quietly scoring a model on hindsight.
    """
    inputs = clean_inputs()
    inputs["observations"] = inputs["observations"] + [
        weather_row(99, BEFORE + timedelta(hours=2), AFTER, leaf_wetness_minutes=600.0)
    ]
    inputs["applications"] = inputs["applications"] + [
        spray_row(99, (AS_OF - timedelta(days=1)).date(), AFTER,
                  epa_reg_no="99999-1", moa_group=None)
    ]
    inputs["samples"] = inputs["samples"] + [
        sample_row(99, BEFORE + timedelta(hours=3), AFTER)
    ]
    # Agronomy poison rows, each chosen to move its feature if admitted: a NEWER soil
    # test (would cut recency days), extra irrigation depth and extra energy (would both
    # raise their totals).
    inputs["soil_tests"] = inputs["soil_tests"] + [
        base_row(99, AS_OF - timedelta(days=1), AFTER)
    ]
    inputs["irrigation_events"] = inputs["irrigation_events"] + [
        base_row(99, AS_OF - timedelta(days=1), AFTER, depth_mm=999.0)
    ]
    inputs["energy_records"] = inputs["energy_records"] + [
        base_row(99, AS_OF - timedelta(days=1), AFTER, kwh=9999.0)
    ]
    return inputs


def test_no_registered_feature_reads_data_recorded_after_as_of():
    """The loop that covers features nobody has written yet.

    Each poison row is chosen to CHANGE the answer if it were admitted: 600 minutes of
    wetness, an application with no label concentration (which would force an
    abstention), an application with no MoA group (likewise), and a newer scouting
    sample. If a feature's value, reasons or digest move, it read the future.
    """
    for spec in base.REGISTRY.values():
        clean = spec.compute(**clean_inputs())
        poisoned = spec.compute(**poisoned_inputs())

        assert poisoned.value == clean.value, (
            f"{spec.name} changed its VALUE when a late-recorded row was added"
        )
        assert poisoned.abstained == clean.abstained, (
            f"{spec.name} changed its abstention state on late-recorded data"
        )
        assert poisoned.reasons == clean.reasons, (
            f"{spec.name} changed its REASONS on late-recorded data"
        )


def test_the_poison_rows_would_actually_change_the_answer_if_admitted():
    """Guards the guard.

    If the poison rows were inert, the test above would pass vacuously forever. Here
    they are given an `as_of` late enough to admit them, and every affected feature must
    move — proving the rows have teeth.
    """
    late = AFTER + timedelta(hours=1)
    inputs = poisoned_inputs()
    inputs["as_of"] = late

    from app.features import agronomy, pest, weather

    # 600 minutes of wetness lands.
    assert weather.leaf_wetness_hours(**inputs).value > 2.0
    # The unpriceable product forces an abstention.
    assert pest.active_ingredient_kg_per_ha(**inputs).abstained
    # The MoA-less application forces an abstention.
    assert pest.moa_rotation_diversity(**inputs).abstained

    # Agronomy: the newer soil test cuts recency well below the clean 30 days, and the
    # oversized irrigation and energy rows dominate their totals.
    clean = clean_inputs()
    clean["as_of"] = late
    assert agronomy.soil_test_recency_days(**inputs).value < (
        agronomy.soil_test_recency_days(**clean).value
    )
    assert agronomy.applied_irrigation_mm(**inputs).value > 900.0
    assert agronomy.energy_use_kwh_per_ha(**inputs).value > 900.0


def test_recomputing_at_a_fixed_as_of_reproduces_the_digest_after_more_data_arrives(
    db, client
):
    """The property that makes `feature_values` a leak detector.

    Because admissibility excludes anything recorded after `as_of`, a recompute at an
    unchanged `as_of` must produce the identical inputs digest no matter how much data
    has since arrived. A digest that moves is proof of a leak, and it is the cheapest
    such detector in the system.
    """
    from app import models

    farm = client.post(
        "/farms",
        json={"name": "Leak Ranch", "location": "Watsonville, CA", "country": "US",
              "crop_type": "strawberry", "area": 10.0},
    ).json()
    field = models.Field(farm_id=farm["id"], name="Block A",
                         centroid_lat=36.91, centroid_lon=-121.75)
    db.add(field)
    db.commit()
    db.refresh(field)

    spec = base.get("weather_data_staleness_hours")

    db.add(models.WeatherObservation(
        farm_id=farm["id"], field_id=field.id, station_id="111",
        station_distance_km=3.0, observed_at=BEFORE, recorded_at=BEFORE,
        temperature_c=15.0, data_source="provider_api",
        data_confidence="provider_reported", source_type="station_export",
    ))
    db.commit()

    _, first_digest = compute.compute_one(db, spec, field.id, AS_OF)

    # A reading about an earlier hour, learned LATER. Admissibility must exclude it.
    db.add(models.WeatherObservation(
        farm_id=farm["id"], field_id=field.id, station_id="111",
        station_distance_km=3.0, observed_at=BEFORE + timedelta(hours=1),
        recorded_at=AFTER, temperature_c=16.0, data_source="provider_api",
        data_confidence="provider_reported", source_type="station_export",
    ))
    db.commit()

    result, second_digest = compute.compute_one(db, spec, field.id, AS_OF)
    assert second_digest == first_digest, (
        "the inputs digest moved at a fixed as_of; a late-recorded row became visible"
    )
    assert not result.abstained


def test_a_drifting_digest_is_recorded_rather_than_silently_overwriting(db, client):
    """When the detector fires, the evidence survives.

    Overwriting the stored value would destroy the only signal that a leak happened,
    which is the one thing this table exists to preserve.
    """
    from app import models

    farm = client.post(
        "/farms",
        json={"name": "Drift Ranch", "location": "Watsonville, CA", "country": "US",
              "crop_type": "strawberry", "area": 10.0},
    ).json()
    field = models.Field(farm_id=farm["id"], name="Block A")
    db.add(field)
    db.commit()
    db.refresh(field)

    spec = base.get("weather_data_staleness_hours")
    result, digest = compute.compute_one(db, spec, field.id, AS_OF)
    stored = compute.persist(db, spec, field.id, AS_OF, result, digest,
                             farm_id=farm["id"])
    original_digest = stored.inputs_digest

    # Simulate drift by persisting the same as_of under a different digest.
    compute.persist(db, spec, field.id, AS_OF, result, "0" * 64, farm_id=farm["id"])

    db.refresh(stored)
    assert stored.inputs_digest == original_digest, "the stored value was overwritten"
    issue = db.query(models.IngestionIssue).filter(
        models.IngestionIssue.code == compute.DIGEST_DRIFT_CODE
    ).one()
    assert "impossible unless an input became visible" in issue.message


def test_feature_modules_stay_framework_free():
    """The pure modules cannot reach a session, so they cannot widen their own inputs.

    `compute.py` is deliberately excluded — it is the one module here that IS allowed a
    database, which is exactly why the others must not be.
    """
    import inspect

    from app.features import pest, pit_view, weather

    forbidden = ("sqlalchemy", "fastapi", "SessionLocal", "get_db", "import crud")
    for module in (base, pit_view, weather, pest):
        source = inspect.getsource(module)
        for token in forbidden:
            assert token not in source, f"{module.__name__} must not reference {token}"


def test_pit_partition_is_what_every_feature_reaches_for():
    """One admissibility rule, in one place.

    A feature writing its own date filter is how the two-timestamp rule gets half
    implemented. `pit.partition` computes the supersede set internally, which is the
    step that is easy to forget and impossible to notice missing.
    """
    import inspect

    from app.features import pest, weather

    for module in (weather, pest):
        source = inspect.getsource(module)
        assert "pit.partition" in source or "_admissible" in source
        # No hand-rolled comparison against as_of on a recorded_at field.
        assert "recorded_at >" not in source
        assert "recorded_at <=" not in source
