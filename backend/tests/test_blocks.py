"""Block entity: farm ownership, cross-farm rejection, and demo/real separation.

`farm_id` is this system's only isolation boundary — there is no tenant model — so a
block reference that crosses farms is a tenancy violation, not a validation nicety.
These tests pin that every record type which can carry a `block_id` refuses one
belonging to another farm.
"""
from datetime import date, timedelta

import pytest


def _farm(client, name="Block Farm", **overrides):
    payload = {
        "name": name,
        "country": "US",
        "crop_type": "strawberry",
        "expected_harvest_date": (date.today() + timedelta(days=30)).isoformat(),
    }
    payload.update(overrides)
    res = client.post("/farms", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def _block(client, farm_id, name="North 1", **overrides):
    payload = {"name": name, "crop": "strawberry", "cultivar": "Monterey"}
    payload.update(overrides)
    res = client.post(f"/farms/{farm_id}/blocks", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


# ------------------------------------------------------------------- ownership
def test_block_is_created_under_its_farm_and_listed_there(client):
    farm = _farm(client)
    other = _farm(client, name="Other Farm")
    block = _block(client, farm["id"])

    assert block["farm_id"] == farm["id"]
    assert [b["id"] for b in client.get(f"/farms/{farm['id']}/blocks").json()] == [block["id"]]
    # A block never leaks into another farm's listing.
    assert client.get(f"/farms/{other['id']}/blocks").json() == []


def test_block_defaults_to_real_provenance_not_demo(client):
    """API-created rows must not fall through to the ORM's legacy demo defaults."""
    block = _block(client, _farm(client)["id"])
    assert block["data_source"] == "manual_entry"
    assert block["data_confidence"] == "user_provided"


# ------------------------------------------------------- phenology is never invented
def test_phenology_stage_without_an_observation_date_is_refused(client):
    farm = _farm(client)
    res = client.post(
        f"/farms/{farm['id']}/blocks",
        json={"name": "North 2", "phenology_stage": "bloom"},
    )
    assert res.status_code == 422
    assert "phenology_observed_on" in res.text


def test_phenology_stage_with_its_observation_date_is_accepted(client):
    farm = _farm(client)
    block = _block(
        client, farm["id"], name="North 3",
        phenology_stage="bloom", phenology_observed_on=date.today().isoformat(),
    )
    assert block["phenology_stage"] == "bloom"
    assert block["phenology_observed_on"] == date.today().isoformat()


# ------------------------------------------------------------ cross-farm rejection
@pytest.mark.parametrize(
    "path,payload",
    [
        (
            "spray-events",
            {
                "product_name": "Switch 62.5 WG",
                "active_ingredient": "cyprodinil",
                "application_date": date.today().isoformat(),
            },
        ),
        (
            "scout-observations",
            {"observation_date": date.today().isoformat(), "visible_issue": "botrytis"},
        ),
        (
            "planned-sprays",
            {
                "intended_date": date.today().isoformat(),
                "product_name": "Switch 62.5 WG",
                "active_ingredient": "cyprodinil",
                "target_pest_or_disease": "botrytis",
                "pre_harvest_interval_days": 1,
                "re_entry_interval_hours": 12,
            },
        ),
    ],
)
def test_record_cannot_reference_another_farms_block(client, path, payload):
    farm = _farm(client)
    other = _farm(client, name="Other Farm")
    foreign_block = _block(client, other["id"], name="Their Block")

    res = client.post(
        f"/farms/{farm['id']}/{path}", json={**payload, "block_id": foreign_block["id"]}
    )
    assert res.status_code == 422, res.text
    assert "another farm's block" in res.json()["detail"]

    # The farm's own block is accepted on the same payload.
    own_block = _block(client, farm["id"], name="Our Block")
    ok = client.post(
        f"/farms/{farm['id']}/{path}", json={**payload, "block_id": own_block["id"]}
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["block_id"] == own_block["id"]


def test_record_cannot_reference_a_block_that_does_not_exist(client):
    farm = _farm(client)
    res = client.post(
        f"/farms/{farm['id']}/spray-events",
        json={
            "product_name": "Switch 62.5 WG",
            "application_date": date.today().isoformat(),
            "block_id": 9999,
        },
    )
    assert res.status_code == 422
    assert "does not exist" in res.json()["detail"]


# --------------------------------------------------- field_block is left untouched
def test_free_text_field_block_is_not_turned_into_a_block(client):
    """`field_block` is grower shorthand, not an entity — nothing infers a Block
    from it, and two records reading the same string create no linkage."""
    farm = _farm(client)
    res = client.post(
        f"/farms/{farm['id']}/spray-events",
        json={
            "product_name": "Switch 62.5 WG",
            "application_date": date.today().isoformat(),
            "field_block": "north 3",
        },
    )
    assert res.status_code == 201
    assert res.json()["field_block"] == "north 3"
    assert res.json()["block_id"] is None
    # No Block was conjured into existence by the string.
    assert client.get(f"/farms/{farm['id']}/blocks").json() == []


# ------------------------------------------------------- demo/real separation
def test_demo_block_cannot_be_added_to_a_farm_with_real_records(client):
    farm = _farm(client)
    _block(client, farm["id"])  # real, sets the farm's nature

    res = client.post(
        f"/farms/{farm['id']}/blocks",
        json={"name": "Demo Block", "data_source": "demo", "data_confidence": "simulated"},
    )
    assert res.status_code == 409
    assert "never mix" in res.json()["detail"]
