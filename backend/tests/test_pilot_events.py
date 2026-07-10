"""Tests for pilot instrumentation: server-logged workflow events, client-reported
events, and the internal summary."""
from datetime import date, timedelta


def _create_farm(client):
    return client.post("/farms", json={
        "name": "Instrumented Farm",
        "country": "US",
        "crop_type": "strawberry",
        "expected_harvest_date": (date.today() + timedelta(days=3)).isoformat(),
    }).json()


def _create_planned(client, farm_id, **overrides):
    payload = {
        "intended_date": (date.today() + timedelta(days=1)).isoformat(),
        "product_name": "Captan 80WDG",
        "active_ingredient": "captan",
        "target_pest_or_disease": "botrytis",
        "pre_harvest_interval_days": 7,
        "re_entry_interval_hours": 24,
        "estimated_cost": 120.0,
    }
    payload.update(overrides)
    res = client.post(f"/farms/{farm_id}/planned-sprays", json=payload)
    assert res.status_code == 201
    return res.json()


def _summary(client):
    res = client.get("/internal/instrumentation")
    assert res.status_code == 200
    return res.json()


def test_server_side_events_are_logged_automatically(client):
    farm = _create_farm(client)
    p = _create_planned(client, farm["id"])
    client.patch(f"/planned-sprays/{p['id']}/review",
                 json={"action": "approved", "reviewed_by": "Test PCA"})
    client.patch(f"/planned-sprays/{p['id']}/outcome",
                 json={"outcome": "avoided", "outcome_reason": "Held off."})

    s = _summary(client)
    assert s["event_counts"]["check_completed"] == 1
    assert s["event_counts"]["review_recorded"] == 1
    assert s["event_counts"]["outcome_recorded"] == 1
    assert s["median_seconds_to_pca_review"] is not None
    assert s["outcomes_recorded"] == 1
    assert s["decisions_changed"] == 1  # avoided != sprayed_as_planned
    assert s["entry_source_breakdown"] == {"manual_entry": 1}


def test_client_reported_events_and_abandonment(client):
    farm = _create_farm(client)
    for _ in range(2):
        client.post("/pilot-events", json={
            "event_type": "check_started", "farm_id": farm["id"],
            "entry_source": "manual_form",
        })
    client.post("/pilot-events", json={
        "event_type": "check_abandoned", "farm_id": farm["id"],
        "entry_source": "manual_form", "meta": {"fields_touched": 2},
    })
    _create_planned(client, farm["id"])

    s = _summary(client)
    assert s["checks_started"] == 2
    assert s["checks_completed"] == 1
    assert s["checks_abandoned"] == 1
    assert s["abandonment_rate_pct"] == 50.0


def test_unknown_event_type_rejected(client):
    res = client.post("/pilot-events", json={"event_type": "made_up"})
    assert res.status_code == 422


def test_summary_excludes_demo_planned_sprays_from_workflow_stats(client):
    farm = _create_farm(client)
    p = _create_planned(client, farm["id"], data_source="demo",
                        data_confidence="simulated")
    client.patch(f"/planned-sprays/{p['id']}/review",
                 json={"action": "approved"})
    s = _summary(client)
    # The demo row's review timing and outcome are excluded from workflow stats...
    assert s["median_seconds_to_pca_review"] is None
    assert s["entry_source_breakdown"] == {}
    # ...but raw event counts still include everything (and say so in the notes).
    assert s["event_counts"]["check_completed"] == 1
    assert any("demo" in n.lower() for n in s["notes"])
