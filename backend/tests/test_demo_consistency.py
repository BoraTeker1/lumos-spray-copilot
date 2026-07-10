"""Demo-consistency tests: the seeded YC story must be internally coherent every time.

Seeds the test database with a pinned anchor date (LUMOS_DEMO_TODAY) and asserts the
exact invariants a demo viewer would notice if broken: date ordering, planned vs.
applied dates, decision snapshot vs. stored fields, farm-card counts vs. farm-page
counts, and evidence reconciliation.
"""
import os
from datetime import date, timedelta

import pytest

from app import seed

PINNED = "2026-07-10"


@pytest.fixture()
def seeded(client, monkeypatch):
    """Seed the (test) database with the demo pinned to a fixed anchor date."""
    monkeypatch.setenv("LUMOS_DEMO_TODAY", PINNED)
    seed.run()
    return client


def _us_farm(client):
    farms = client.get("/farms").json()
    return next(f for f in farms if f["country"] == "US")


def test_seed_anchor_is_deterministic(seeded):
    farm = _us_farm(seeded)
    anchor = date.fromisoformat(PINNED)
    assert farm["expected_harvest_date"] == (anchor + timedelta(days=2)).isoformat()


def test_demo_planned_spray_story_is_coherent(seeded):
    farm = _us_farm(seeded)
    planned = seeded.get(f"/farms/{farm['id']}/planned-sprays").json()
    assert len(planned) == 1
    p = planned[0]
    anchor = date.fromisoformat(PINNED)

    # The story: checked, blocked, PCA-edited, and resolved on the SAME demo day.
    assert p["intended_date"] == anchor.isoformat()
    assert p["outcome_date"] == anchor.isoformat()
    assert p["decision_outcome"] == "block"
    assert p["decision_severity"] == "critical"
    # PCA-entered values -> the block is definitive under authority gating.
    assert p["values_source"] == "pca_entered"
    assert p["decision_authority"] == "definitive"
    assert p["review_status"] == "edited"
    assert p["outcome"] == "changed_product"
    assert p["outcome_product_name"] == "Switch 62.5 WG"
    # Snapshot agrees with the stored fields (no drift between payload and columns).
    assert p["decision_payload"]["outcome"] == p["decision_outcome"]
    assert p["decision_payload"]["authority_level"] == p["decision_authority"]
    # The named replacement product comes ONLY from the PCA's edited guidance;
    # the engine snapshot must never mention it.
    assert "Switch 62.5 WG" in p["pca_next_action"]
    assert "switch 62.5" not in p["check_text"].lower()
    # No stale weekday names in the guidance; the harvest date is spelled out.
    assert "saturday" not in p["pca_next_action"].lower()
    assert farm["expected_harvest_date"] in p["pca_next_action"]


def test_replacement_spray_matches_recorded_outcome(seeded):
    farm = _us_farm(seeded)
    planned = seeded.get(f"/farms/{farm['id']}/planned-sprays").json()[0]
    sprays = seeded.get(f"/farms/{farm['id']}/spray-events").json()
    switch = [s for s in sprays if s["product_name"] == planned["outcome_product_name"]]
    assert len(switch) == 1
    # Applied on the intended day — never before the planned date.
    assert switch[0]["application_date"] == planned["intended_date"]
    assert switch[0]["active_ingredient"] == planned["outcome_active_ingredient"]


def test_farm_card_flags_match_farm_page_signals(seeded):
    """The overview card's flag count must equal what /compliance shows on the page."""
    farm = _us_farm(seeded)
    overview = seeded.get("/farms-overview").json()
    card = next(f for f in overview if f["id"] == farm["id"])
    compliance = seeded.get(f"/farms/{farm['id']}/compliance").json()
    page_count = sum(
        1 for k in ("phi_risk", "rei_risk", "repeated_active_ingredient_risk",
                    "high_severity_scouting")
        if compliance[k]
    )
    assert card["flag_count"] == page_count


def test_decision_evidence_reconciles_with_visible_demo_outcomes(seeded):
    """Real metrics exclude demo rows, but the demo story is counted separately so the
    evidence card and the visible decision queue never contradict each other."""
    farm = _us_farm(seeded)
    ev = seeded.get(f"/farms/{farm['id']}/decision-evidence").json()
    assert ev["decisions_checked"] == 0            # no real decisions yet
    assert ev["demo_decisions_checked"] == 1       # the seeded story, reconciled
    assert ev["demo_outcomes"]["changed_product"] == 1
    assert ev["compliance_conflicts_caught"] == 0  # demo conflicts never count as real


def test_demo_dates_never_precede_their_own_story(seeded):
    """No record may claim an application before its planned date or a review before
    its check."""
    farm = _us_farm(seeded)
    p = seeded.get(f"/farms/{farm['id']}/planned-sprays").json()[0]
    assert p["outcome_date"] >= p["intended_date"]
    assert p["reviewed_at"][:10] >= p["created_at"][:10]
