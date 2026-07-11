"""Anonymized evidence export: JSON + CSV, demo exclusion, no unsupported claims."""
import pytest

from app import seed


@pytest.fixture(autouse=True)
def pinned_clock(monkeypatch):
    """Pin the app clock so the hard-coded story dates are chronologically valid."""
    monkeypatch.setenv("LUMOS_DEMO_TODAY", "2026-07-09")


def _real_farm_with_story(client):
    farm = client.post("/farms", json={
        "name": "Secret Berry Co", "location": "Somewhere, CA", "country": "US",
        "crop_type": "strawberry", "greenhouse_area": 15.0,
        "expected_harvest_date": "2026-09-01",
    }).json()
    p = client.post(f"/farms/{farm['id']}/planned-sprays", json={
        "intended_date": "2026-07-10",
        "product_name": "PyGanic EC 5.0",
        "active_ingredient": "pyrethrins",
        "target_pest_or_disease": "lygus bug",
        "pre_harvest_interval_days": 0,
        "re_entry_interval_hours": 12,
        "estimated_cost": 95.0,
    }).json()
    client.patch(f"/planned-sprays/{p['id']}/review", json={
        "action": "edited", "reviewed_by": "Jane PCA",
        "pca_next_action": "Hold and inspect first.",
    })
    client.patch(f"/planned-sprays/{p['id']}/outcome", json={
        "outcome": "avoided", "outcome_reason": "below threshold",
        "outcome_date": "2026-07-10",
    })
    client.post(f"/planned-sprays/{p['id']}/follow-up-events", json={
        "event_type": "scouting_observation", "observed_at": "2026-07-14",
        "severity": 2, "cost": 30.0, "rescue_required": False,
    })
    return farm, p


def test_export_is_anonymized_and_complete(client):
    farm, p = _real_farm_with_story(client)
    export = client.get(f"/farms/{farm['id']}/evidence-export").json()

    # Anonymized: id-based ref only; the farm's name/location appear nowhere.
    assert export["farm_ref"] == f"pilot-farm-{farm['id']}"
    blob = str(export)
    assert "Secret Berry Co" not in blob
    assert "Somewhere" not in blob

    assert export["decisions_exported"] == 1
    (row,) = export["decisions"]
    assert row["decision_id"] == p["id"]
    assert row["decision"]["outcome"] == p["decision_outcome"]
    assert row["decision"]["not_evaluated"], "label-gap checks must be disclosed"
    assert row["input_values"], "source/verification state must be included"
    assert [e["event_type"] for e in row["audit_history"]] == [
        "created", "reviewed", "outcome_recorded", "follow_up_added"
    ]
    assert len(row["follow_up_timeline"]) == 1
    assert row["follow_up_summary"]["confirmed_avoided"] is True

    # Confirmed vs estimated are separated; unsupported claims are impossible.
    assert export["confirmed"]["applications_confirmed_avoided"] == 1
    assert export["estimated"]["avoided_outcomes_without_follow_up"] == 0
    assert "not calculated" in export["not_calculated"][
        "risk_weighted_pesticide_reduction"
    ]
    assert any("Correlation, not causality" in l for l in export["limitations"])
    assert export["data_completeness"]["decisions_reviewed_pct"] == 100.0


def test_demo_records_can_never_enter_the_export(client, monkeypatch):
    monkeypatch.setenv("LUMOS_DEMO_TODAY", "2026-07-10")
    seed.run()
    us = next(f for f in client.get("/farms").json() if f["country"] == "US")
    # The seeded demo farm has three decision stories — ALL demo/simulated.
    assert len(client.get(f"/farms/{us['id']}/planned-sprays").json()) == 3

    export = client.get(f"/farms/{us['id']}/evidence-export").json()
    assert export["decisions_exported"] == 0
    assert export["decisions"] == []
    assert export["confirmed"]["applications_confirmed_avoided"] == 0
    assert export["confirmed"]["confirmed_net_financial_result"] == 0.0
    blob = str(export)
    assert "Golden Coast" not in blob
    assert "Watsonville" not in blob

    csv_resp = client.get(f"/farms/{us['id']}/export/evidence.csv")
    assert csv_resp.status_code == 200
    assert "Golden Coast" not in csv_resp.text
    assert len(csv_resp.text.strip().splitlines()) == 1  # header only, no demo rows


def test_evidence_csv_shape(client):
    farm, p = _real_farm_with_story(client)
    resp = client.get(f"/farms/{farm['id']}/export/evidence.csv")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    lines = resp.text.strip().splitlines()
    assert len(lines) == 2
    header = lines[0].split(",")
    for column in ("farm_ref", "decision_outcome", "confirmed_avoided",
                   "yield_impact", "missing_evidence"):
        assert column in header
    assert f"pilot-farm-{farm['id']}" in lines[1]
    assert "Secret Berry Co" not in resp.text
