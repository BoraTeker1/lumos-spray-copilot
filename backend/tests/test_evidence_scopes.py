"""Demo-scoped evidence metrics: simulated and real are both coherent, never mixed.

The /decision-evidence endpoint's top-level metrics stay real-only (unchanged
contract); `demo_metrics` carries the SAME metric shape computed over demo records so
a demo farm shows a coherent simulated story instead of contradictory zeros.
"""
import pytest

from app import seed

PINNED = "2026-07-10"


@pytest.fixture()
def seeded(client, monkeypatch):
    monkeypatch.setenv("LUMOS_DEMO_TODAY", PINNED)
    seed.run()
    return client


def _us_evidence(client):
    farms = client.get("/farms").json()
    us = next(f for f in farms if f["country"] == "US")
    return us, client.get(f"/farms/{us['id']}/decision-evidence").json()


def test_top_level_metrics_stay_real_only_on_demo_farm(seeded):
    _, ev = _us_evidence(seeded)
    assert ev["decisions_checked"] == 0
    assert ev["decisions_reviewed"] == 0
    assert ev["estimated_chemical_cost_avoided"] == 0.0


def test_demo_metrics_block_tells_the_seeded_story(seeded):
    _, ev = _us_evidence(seeded)
    dm = ev["demo_metrics"]
    assert dm["is_simulated"] is True
    assert "simulated" in dm["note"].lower()
    assert dm["decisions_checked"] == 3
    assert dm["decisions_reviewed"] == 3  # all three scenarios are PCA-edited
    assert dm["outcomes"]["changed_product"] == 1
    assert dm["outcomes"]["avoided"] == 1
    assert dm["outcomes"]["delayed"] == 1
    assert dm["sprays_changed_delayed_or_avoided"] == 3
    # The blocked captan is the caught conflict.
    assert dm["compliance_conflicts_caught"] == 1
    # The avoided PyGanic's entered cost (95.0) — entered estimate, not savings.
    assert dm["estimated_chemical_cost_avoided"] == 95.0
    # Follow-up completion: all three scenarios carry follow-up events.
    assert dm["follow_up"]["follow_up_required"] == 3
    assert dm["follow_up"]["follow_up_with_events"] == 3


def test_demo_and_real_scopes_are_never_summed(seeded):
    _, ev = _us_evidence(seeded)
    # demo_outcomes reconciliation block still present and consistent with demo_metrics.
    assert ev["demo_decisions_checked"] == ev["demo_metrics"]["decisions_checked"]
    for key, value in ev["demo_outcomes"].items():
        assert ev["demo_metrics"]["outcomes"][key] == value
        # The real outcome block must not contain the demo counts.
        assert ev["outcomes"][key] == 0


def test_real_records_populate_top_level_not_demo(client):
    farm = client.post("/farms", json={
        "name": "Real Pilot Farm", "country": "US", "crop_type": "strawberry",
        "expected_harvest_date": "2030-01-01",
    }).json()
    p = client.post(f"/farms/{farm['id']}/planned-sprays", json={
        "intended_date": "2029-11-01", "product_name": "RealProd",
        "pre_harvest_interval_days": 0, "re_entry_interval_hours": 4,
        "estimated_cost": 50.0, "values_source": "grower_entered",
        "data_source": "manual_entry", "data_confidence": "user_provided",
    }).json()
    client.patch(f"/planned-sprays/{p['id']}/outcome", json={
        "outcome": "avoided", "outcome_reason": "held after inspection",
    })
    ev = client.get(f"/farms/{farm['id']}/decision-evidence").json()
    assert ev["decisions_checked"] == 1
    assert ev["outcomes"]["avoided"] == 1
    assert ev["demo_metrics"]["decisions_checked"] == 0
