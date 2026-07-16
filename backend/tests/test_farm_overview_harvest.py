"""Expired-harvest handling in the farm overview (urgency + calendar-safe day math).

Pins the app clock (LUMOS_DEMO_TODAY) so today/future/past are exact calendar dates —
no timezone-dependent off-by-one is possible because days_to_harvest is derived
server-side from civil dates.
"""
import pytest

TODAY = "2026-07-16"


@pytest.fixture()
def pinned(client, monkeypatch):
    monkeypatch.setenv("LUMOS_DEMO_TODAY", TODAY)
    return client


def _farm_with_harvest(client, harvest_date, name="Harvest Farm"):
    payload = {"name": name, "country": "US", "crop_type": "strawberry"}
    if harvest_date is not None:
        payload["expected_harvest_date"] = harvest_date
    farm = client.post("/farms", json=payload).json()
    return client.get(f"/farms/{farm['id']}/overview").json()


def test_future_harvest_positive_days_and_no_overdue_urgency(pinned):
    ov = _farm_with_harvest(pinned, "2026-07-21")
    assert ov["days_to_harvest"] == 5
    assert ov["urgency"] != "harvest_overdue"


def test_harvest_today_is_zero_days_and_not_overdue(pinned):
    ov = _farm_with_harvest(pinned, "2026-07-16")
    assert ov["days_to_harvest"] == 0
    assert ov["urgency"] != "harvest_overdue"


def test_past_harvest_negative_days_and_overdue_urgency(pinned):
    ov = _farm_with_harvest(pinned, "2026-07-14")
    assert ov["days_to_harvest"] == -2
    assert ov["urgency"] == "harvest_overdue"
    assert "2026-07-14" in ov["why"]
    assert "harvest date" in ov["next_action"].lower()


def test_no_harvest_date_yields_null_days_and_no_overdue(pinned):
    ov = _farm_with_harvest(pinned, None)
    assert ov["days_to_harvest"] is None
    assert ov["urgency"] != "harvest_overdue"


def test_overdue_harvest_outranks_flags_but_not_open_conflict(pinned):
    # Overdue + record-level flags -> harvest_overdue wins over "flags".
    farm = pinned.post("/farms", json={
        "name": "Overdue Flags Farm", "country": "US", "crop_type": "strawberry",
        "expected_harvest_date": "2026-07-10",
    }).json()
    pinned.post(f"/farms/{farm['id']}/scout-observations", json={
        "observation_date": "2026-07-15", "visible_issue": "gray mold",
        "severity_1_to_5": 5,
    })
    ov = pinned.get(f"/farms/{farm['id']}/overview").json()
    assert ov["urgency"] == "harvest_overdue"

    # Add an open critical (blocked) planned spray -> conflict outranks overdue.
    pinned.post(f"/farms/{farm['id']}/planned-sprays", json={
        "intended_date": "2026-07-16", "product_name": "Blocker",
        "pre_harvest_interval_days": 30, "re_entry_interval_hours": 24,
        "values_source": "grower_entered",
    })
    ov = pinned.get(f"/farms/{farm['id']}/overview").json()
    assert ov["open_conflict_count"] >= 1
    assert ov["urgency"] == "conflict"


def test_farms_overview_ranks_overdue_above_needs_review(pinned):
    overdue = pinned.post("/farms", json={
        "name": "A Overdue", "country": "US", "crop_type": "strawberry",
        "expected_harvest_date": "2026-07-01",
    }).json()
    reviewy = pinned.post("/farms", json={
        "name": "B Needs Review", "country": "US", "crop_type": "strawberry",
        "expected_harvest_date": "2026-09-01",
    }).json()
    # A planned spray missing PHI/REI escalates to PCA review (needs_review).
    pinned.post(f"/farms/{reviewy['id']}/planned-sprays", json={
        "intended_date": "2026-07-20", "product_name": "Mystery Product",
        "values_source": "grower_entered",
    })
    out = pinned.get("/farms-overview").json()
    ids = [f["id"] for f in out]
    assert ids.index(overdue["id"]) < ids.index(reviewy["id"])
