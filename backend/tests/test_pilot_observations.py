"""Pilot observations: derived incidence, explicit evidence provenance, append-only.

These are the inputs a disease-risk assessment reads, so the properties that matter
are: a number can never be asserted without the sample it came from, a derived value
can never be mistaken for a measurement, and a correction never destroys what it
replaces.
"""
from datetime import date, datetime, timedelta

import pytest

NOW = datetime(2026, 7, 19, 6, 0, 0)


def _farm(client, name="Obs Farm"):
    res = client.post("/farms", json={
        "name": name, "country": "US", "crop_type": "strawberry",
        "expected_harvest_date": (date.today() + timedelta(days=30)).isoformat(),
    })
    assert res.status_code == 201
    return res.json()


def _block(client, farm_id, name="North 1"):
    res = client.post(f"/farms/{farm_id}/blocks", json={"name": name, "crop": "strawberry"})
    assert res.status_code == 201
    return res.json()


def _sample(client, farm_id, block_id, **overrides):
    payload = {
        "block_id": block_id,
        "observed_at": NOW.isoformat(),
        "method": "fruit_count",
        "target": "botrytis",
        "units_inspected": 100,
        "units_affected": 7,
    }
    payload.update(overrides)
    return client.post(f"/farms/{farm_id}/scouting-samples", json=payload)


def _weather(client, farm_id, **overrides):
    payload = {
        "station_id": "CIMIS-111",
        "observed_at": NOW.isoformat(),
        "temperature_c": 18.0,
        "relative_humidity_pct": 92.0,
    }
    payload.update(overrides)
    return client.post(f"/farms/{farm_id}/weather-observations", json=payload)


# ------------------------------------------------------- incidence is derived
def test_incidence_is_derived_from_the_stated_denominator(client):
    farm = _farm(client)
    block = _block(client, farm["id"])
    res = _sample(client, farm["id"], block["id"], units_inspected=200, units_affected=13)
    assert res.status_code == 201
    assert res.json()["incidence_pct"] == 6.5


def test_incidence_cannot_be_supplied_by_the_caller(client):
    """A percentage must never exist without the sample behind it."""
    farm = _farm(client)
    block = _block(client, farm["id"])
    res = _sample(
        client, farm["id"], block["id"],
        units_inspected=100, units_affected=1, incidence_pct=99.0,
    )
    assert res.status_code == 201
    # The claimed 99% is ignored; the sample decides.
    assert res.json()["incidence_pct"] == 1.0


def test_affected_above_inspected_is_refused(client):
    farm = _farm(client)
    block = _block(client, farm["id"])
    res = _sample(client, farm["id"], block["id"], units_inspected=10, units_affected=11)
    assert res.status_code == 422
    assert "cannot exceed" in res.text


def test_zero_inspected_is_refused_rather_than_dividing_by_zero(client):
    farm = _farm(client)
    block = _block(client, farm["id"])
    res = _sample(client, farm["id"], block["id"], units_inspected=0, units_affected=0)
    assert res.status_code == 422


def test_severity_index_requires_its_scale(client):
    farm = _farm(client)
    block = _block(client, farm["id"])
    res = _sample(client, farm["id"], block["id"], severity_index=3.0)
    assert res.status_code == 422
    assert "severity_scale" in res.text


def test_sampling_method_is_from_a_fixed_vocabulary(client):
    farm = _farm(client)
    block = _block(client, farm["id"])
    assert _sample(client, farm["id"], block["id"], method="vibes").status_code == 422


# ------------------------------------------------ measured vs derived wetness
def test_leaf_wetness_must_declare_whether_it_was_measured(client):
    """A sensor reading and a humidity-derived estimate are different evidence."""
    farm = _farm(client)
    res = _weather(client, farm["id"], leaf_wetness_minutes=240)
    assert res.status_code == 422
    assert "wetness_is_measured" in res.text

    ok = _weather(client, farm["id"], leaf_wetness_minutes=240, wetness_is_measured=False)
    assert ok.status_code == 201
    assert ok.json()["wetness_is_measured"] is False


def test_weather_records_both_observation_and_recording_times(client):
    """`recorded_at` is what makes hindsight detectable — it is set by the server."""
    farm = _farm(client)
    row = _weather(client, farm["id"]).json()
    assert row["observed_at"].startswith("2026-07-19T06:00")
    assert row["recorded_at"] is not None
    assert row["recorded_at"] != row["observed_at"]


def test_humidity_outside_0_100_is_refused(client):
    farm = _farm(client)
    assert _weather(client, farm["id"], relative_humidity_pct=140).status_code == 422


# ------------------------------------------------------------- append-only
def test_correction_supersedes_and_never_destroys_the_original(client):
    farm = _farm(client)
    block = _block(client, farm["id"])
    original = _sample(client, farm["id"], block["id"], units_affected=7).json()

    corrected = _sample(
        client, farm["id"], block["id"], units_affected=9, supersedes_id=original["id"]
    ).json()
    assert corrected["supersedes_id"] == original["id"]

    rows = client.get(f"/farms/{farm['id']}/scouting-samples").json()
    ids = {r["id"] for r in rows}
    assert original["id"] in ids, "the superseded row must remain on file"
    assert corrected["id"] in ids


def test_one_original_reading_per_station_hour_but_corrections_still_allowed(client):
    """A duplicated hour would double-count wetness inside a risk window.

    Enforced by a PARTIAL unique index rather than trusted to the import's dedupe —
    partial so that a correction may deliberately repeat the station+timestamp of the
    row it supersedes.
    """
    farm = _farm(client)
    first = _weather(client, farm["id"]).json()

    dup = _weather(client, farm["id"])  # same station, same hour, not a correction
    assert dup.status_code == 409
    assert "supersedes_id" in dup.json()["detail"], "the 409 must say how to correct it"

    # A correction repeating that exact station+hour is still permitted.
    corrected = _weather(
        client, farm["id"], temperature_c=19.5, supersedes_id=first["id"]
    )
    assert corrected.status_code == 201
    assert corrected.json()["supersedes_id"] == first["id"]


def test_two_farms_may_each_hold_the_same_public_station_hour(client):
    """A public station serves many farms; the uniqueness is per farm.

    CIMIS stations are shared infrastructure. Without `farm_id` in the key the second
    grower to receive an hour simply cannot store it, and the failure looks like a
    duplicate the operator caused. It is also the right key on the merits:
    `station_distance_km` is measured to THIS farm's field, so the same station-hour is
    different evidence for a farm 2 km away than for one 14 km away.
    """
    farm = _farm(client, "Farm A")
    neighbour = _farm(client, "Farm B")

    first = _weather(client, farm["id"])
    second = _weather(client, neighbour["id"])  # same station_id, same observed_at

    assert first.status_code == 201
    assert second.status_code == 201, second.text
    assert first.json()["id"] != second.json()["id"]

    # And the per-farm constraint still bites within each farm.
    assert _weather(client, farm["id"]).status_code == 409


def test_the_duplicate_station_hour_409_still_explains_the_correction_path(client):
    """The handler matches on SQLite's column list, which the widened key changed.

    `main._integrity_handler` keys off the substring `weather_observations.station_id`
    because SQLite names the violated COLUMNS, not the index. Adding `farm_id` to the
    index changed that message. If the match ever stops firing the API silently
    degrades to the generic "conflicts with one that already exists", which does not
    tell anyone that a correction is posted with `supersedes_id`.
    """
    farm = _farm(client)
    _weather(client, farm["id"])
    conflict = _weather(client, farm["id"])

    assert conflict.status_code == 409
    detail = conflict.json()["detail"]
    assert "supersedes_id" in detail
    assert "double-count" in detail
    assert detail != "This record conflicts with one that already exists.", (
        "the specific weather message stopped matching — check _integrity_handler "
        "against the current constraint columns"
    )


def test_observations_have_no_update_or_delete_route(client):
    """Append-only is enforced by there being no other way in."""
    farm = _farm(client)
    block = _block(client, farm["id"])
    sample = _sample(client, farm["id"], block["id"]).json()
    weather = _weather(client, farm["id"]).json()

    for path in (
        f"/farms/{farm['id']}/scouting-samples/{sample['id']}",
        f"/farms/{farm['id']}/weather-observations/{weather['id']}",
    ):
        assert client.put(path, json={}).status_code in (404, 405)
        assert client.patch(path, json={}).status_code in (404, 405)
        assert client.delete(path).status_code in (404, 405)


# ------------------------------------------------------------ farm scoping
def test_observation_cannot_reference_another_farms_block(client):
    farm = _farm(client)
    other = _farm(client, "Other Farm")
    foreign_block = _block(client, other["id"], "Their Block")

    assert _sample(client, farm["id"], foreign_block["id"]).status_code == 422
    assert _weather(client, farm["id"], block_id=foreign_block["id"]).status_code == 422


def test_correction_cannot_supersede_another_farms_record(client):
    farm = _farm(client)
    other = _farm(client, "Other Farm")
    theirs = _sample(client, other["id"], _block(client, other["id"])["id"]).json()

    res = _sample(
        client, farm["id"], _block(client, farm["id"])["id"], supersedes_id=theirs["id"]
    )
    assert res.status_code == 422
    assert "another farm" in res.json()["detail"]


def test_demo_observation_cannot_mix_with_real_records(client):
    farm = _farm(client)
    _block(client, farm["id"])  # real, sets the farm's nature
    res = _weather(
        client, farm["id"], data_source="demo", data_confidence="simulated"
    )
    assert res.status_code == 409
    assert "never mix" in res.json()["detail"]
