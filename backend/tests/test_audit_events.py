"""Immutable decision audit history: append-only, accumulates, never overwritten."""
import pytest


@pytest.fixture(autouse=True)
def pinned_clock(monkeypatch):
    """Pin the app clock so the hard-coded story dates are chronologically valid."""
    monkeypatch.setenv("LUMOS_DEMO_TODAY", "2026-07-09")


def _farm(client):
    return client.post("/farms", json={
        "name": "Audit Farm", "country": "US", "crop_type": "strawberry",
        "expected_harvest_date": "2026-08-20",
    }).json()


def _planned(client, farm_id):
    return client.post(f"/farms/{farm_id}/planned-sprays", json={
        "intended_date": "2026-07-10",
        "product_name": "Switch 62.5 WG",
        "active_ingredient": "cyprodinil + fludioxonil",
        "target_pest_or_disease": "gray mold",
        "pre_harvest_interval_days": 0,
        "re_entry_interval_hours": 12,
    }).json()


def test_creation_appends_created_event(client):
    farm = _farm(client)
    p = _planned(client, farm["id"])
    events = client.get(f"/planned-sprays/{p['id']}/audit-events").json()
    assert [e["event_type"] for e in events] == ["created"]
    assert events[0]["system_recommendation"] == p["decision_outcome"]
    assert events[0]["after"]["review_status"] == "not_reviewed"


def test_history_accumulates_and_prior_events_never_change(client):
    farm = _farm(client)
    p = _planned(client, farm["id"])

    client.patch(f"/planned-sprays/{p['id']}/review", json={
        "action": "approved", "reviewed_by": "Jane PCA",
        "review_comment": "Looks fine.",
    })
    after_first = client.get(f"/planned-sprays/{p['id']}/audit-events").json()
    first_review = next(e for e in after_first if e["event_type"] == "reviewed")

    # A SECOND review overwrites nothing: it appends another event, and the first
    # review event is byte-for-byte unchanged.
    client.patch(f"/planned-sprays/{p['id']}/review", json={
        "action": "rejected", "reviewed_by": "Jane PCA",
        "review_comment": "Changed my mind after the weather shifted.",
    })
    events = client.get(f"/planned-sprays/{p['id']}/audit-events").json()
    reviews = [e for e in events if e["event_type"] == "reviewed"]
    assert len(reviews) == 2
    assert reviews[0] == first_review
    assert reviews[1]["before"]["review_status"] == "approved"
    assert reviews[1]["after"]["review_status"] == "rejected"

    # Outcome recording appends too (full chain: created -> 2 reviews -> outcome).
    client.patch(f"/planned-sprays/{p['id']}/outcome", json={
        "outcome": "avoided", "outcome_reason": "Held after the rejection.",
        "outcome_date": "2026-07-10",
    })
    events = client.get(f"/planned-sprays/{p['id']}/audit-events").json()
    assert [e["event_type"] for e in events] == [
        "created", "reviewed", "reviewed", "outcome_recorded"
    ]
    outcome_event = events[-1]
    assert outcome_event["before"]["outcome"] == "planned"
    assert outcome_event["after"]["outcome"] == "avoided"
    assert outcome_event["after"]["follow_up_required"] is True


def test_no_mutation_endpoints_exist_for_audit_events(client):
    farm = _farm(client)
    p = _planned(client, farm["id"])
    (event,) = client.get(f"/planned-sprays/{p['id']}/audit-events").json()
    # There is deliberately no PATCH/PUT/DELETE surface for audit events.
    for method in ("patch", "put", "delete"):
        resp = getattr(client, method)(
            f"/planned-sprays/{p['id']}/audit-events/{event['id']}"
        )
        assert resp.status_code in (404, 405)
