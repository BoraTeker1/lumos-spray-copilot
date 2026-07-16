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


def _planned_by_product(client, farm_id, product_name):
    planned = client.get(f"/farms/{farm_id}/planned-sprays").json()
    return next(p for p in planned if p["product_name"] == product_name)


def test_demo_planned_spray_story_is_coherent(seeded):
    farm = _us_farm(seeded)
    planned = seeded.get(f"/farms/{farm['id']}/planned-sprays").json()
    # Three seeded scenarios: the blocked-then-changed captan, the avoided PyGanic,
    # and the failed-delay Agri-Mek rescue story.
    assert len(planned) == 3
    p = _planned_by_product(seeded, farm["id"], "Captan 80 WDG")
    anchor = date.fromisoformat(PINNED)

    # The story: checked, blocked, PCA-edited, and resolved on the SAME demo day.
    assert p["intended_date"] == anchor.isoformat()
    assert p["outcome_date"] == anchor.isoformat()
    assert p["decision_outcome"] == "block"
    assert p["decision_severity"] == "critical"
    # PCA-entered values -> the block is PCA-authorized under authority gating.
    assert p["values_source"] == "pca_entered"
    assert p["decision_authority"] == "pca_authorized"
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


def test_replacement_spray_matches_recorded_outcome_and_is_linked(seeded):
    farm = _us_farm(seeded)
    planned = _planned_by_product(seeded, farm["id"], "Captan 80 WDG")
    sprays = seeded.get(f"/farms/{farm['id']}/spray-events").json()
    switch = [s for s in sprays if s["product_name"] == planned["outcome_product_name"]]
    assert len(switch) == 1
    # Applied on the intended day — never before the planned date.
    assert switch[0]["application_date"] == planned["intended_date"]
    assert switch[0]["active_ingredient"] == planned["outcome_active_ingredient"]
    # The decision links the spray it produced, exactly like a live recorded outcome.
    assert planned["spray_event_id"] == switch[0]["id"]


def test_scenario2_routine_spray_avoided_story(seeded):
    """The pesticide-reduction scenario: routine spray -> INSPECT FIRST via the
    PCA-entered threshold -> inspection below threshold -> AVOIDED. No invented
    thresholds, no spray event, attributed policy, one demo day."""
    farm = _us_farm(seeded)
    p = _planned_by_product(seeded, farm["id"], "PyGanic EC 5.0")
    anchor = date.fromisoformat(PINNED)

    assert p["intended_date"] == anchor.isoformat()
    assert p["outcome_date"] == anchor.isoformat()
    assert p["decision_outcome"] == "inspect_first"
    assert p["decision_authority"] == "provisional"  # a human decision by design
    assert p["outcome"] == "avoided"
    assert p["spray_event_id"] is None               # nothing was applied
    assert p["estimated_cost"] == 95.0               # the entered cost not spent

    # The scouting rule cites the PCA-entered threshold, attributed — never invented.
    rule = next(
        r for r in p["decision_payload"]["rules"] if r["rule_id"] == "scouting_evidence"
    )
    assert rule["triggered"] is True
    assert rule["source_authority"] == "pca_entered"
    assert rule["entered_by"] == "Demo PCA (simulated)"
    assert "PCA-entered action threshold" in rule["detail"]
    assert ">= 3" in rule["detail"]
    # The outcome reason states the below-threshold inspection finding.
    assert "severity 2" in p["outcome_reason"]
    assert "PCA-entered" in p["outcome_reason"]

    # The policy itself is exposed and attributed.
    policies = seeded.get(f"/farms/{farm['id']}/pca-policies").json()
    lygus = next(pol for pol in policies if pol["target_pest_or_disease"] == "lygus bug")
    assert lygus["min_severity_to_treat"] == 3
    assert lygus["entered_by"] == "Demo PCA (simulated)"

    # The follow-up inspection is on record, same demo day, below threshold.
    obs = seeded.get(f"/farms/{farm['id']}/scout-observations").json()
    lygus_obs = [o for o in obs if o["visible_issue"] == "lygus bug"]
    assert len(lygus_obs) == 1
    assert lygus_obs[0]["observation_date"] == anchor.isoformat()
    assert lygus_obs[0]["severity_1_to_5"] == 2


def test_scenario3_failed_delay_is_shown_honestly(seeded):
    """The failure scenario: delayed miticide -> severity rose -> rescue required.
    The product must show this as a failure — negative result, no avoided claim."""
    farm = _us_farm(seeded)
    p = _planned_by_product(seeded, farm["id"], "Agri-Mek SC")
    anchor = date.fromisoformat(PINNED)

    assert p["decision_outcome"] == "inspect_first"
    assert p["outcome"] == "delayed"
    assert p["follow_up_required"] is True
    assert p["follow_up_event_count"] == 3

    events = seeded.get(f"/planned-sprays/{p['id']}/follow-up-events").json()
    assert [e["event_type"] for e in events] == [
        "scouting_observation", "scouting_observation", "rescue_application"
    ]
    # Severity rose after the delay; the rescue is recorded with its cost.
    assert events[0]["severity"] == 3
    assert events[1]["severity"] == 4
    rescue = events[2]
    assert rescue["rescue_required"] is True
    assert rescue["cost"] == 260.0
    assert "FAILED" in rescue["evidence_notes"]
    # Chronology: check -> delay -> re-scouts -> rescue, all before/at the anchor.
    assert p["created_at"][:10] <= p["outcome_date"]
    observed = [e["observed_at"] for e in events]
    assert observed == sorted(observed)
    assert observed[-1] <= anchor.isoformat()
    # No avoided claim anywhere: yield/quality stay unknown, nothing "confirmed".
    assert all(e["yield_impact"] in (None, "unknown") for e in events)


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
    assert ev["demo_decisions_checked"] == 3       # all seeded stories, reconciled
    assert ev["demo_outcomes"]["changed_product"] == 1
    assert ev["demo_outcomes"]["avoided"] == 1
    assert ev["demo_outcomes"]["delayed"] == 1     # the failed-delay rescue story
    assert ev["compliance_conflicts_caught"] == 0  # demo conflicts never count as real
    assert ev["estimated_chemical_cost_avoided"] == 0.0  # demo cost never counts as real
    # Demo follow-up events never leak into the CONFIRMED metrics either.
    assert ev["confirmed"]["applications_confirmed_avoided"] == 0
    assert ev["confirmed"]["confirmed_rescue_treatments"] == 0
    assert ev["confirmed"]["confirmed_net_financial_result"] == 0.0


def test_demo_dates_never_precede_their_own_story(seeded):
    """No record may claim an application before its planned date or a review before
    its check."""
    farm = _us_farm(seeded)
    for p in seeded.get(f"/farms/{farm['id']}/planned-sprays").json():
        assert p["outcome_date"] >= p["intended_date"], p["product_name"]
        assert p["reviewed_at"][:10] >= p["created_at"][:10], p["product_name"]


def test_demo_scenarios_share_scenario_consistent_field_blocks(seeded):
    """Each demo scenario's planned spray, scouting evidence, and applied sprays live
    in one named field block — the Farms/Scouting/Applications field columns must
    tell one coherent story per scenario."""
    farm = _us_farm(seeded)
    planned = seeded.get(f"/farms/{farm['id']}/planned-sprays").json()
    sprays = seeded.get(f"/farms/{farm['id']}/spray-events").json()
    observations = seeded.get(f"/farms/{farm['id']}/scout-observations").json()

    blocks = {p["product_name"]: p["field_block"] for p in planned}
    assert blocks["Captan 80 WDG"] == "Field 7"
    assert blocks["PyGanic EC 5.0"] == "North Block"
    assert blocks["Agri-Mek SC"] == "South Block"

    # Every Golden Coast record carries a field block (no orphan rows in the demo).
    assert all(s["field_block"] for s in sprays)
    assert all(o["field_block"] for o in observations)

    # Scenario coherence: the replacement Switch spray happened where the captan was
    # blocked; mite scouting happened where the miticide was delayed.
    switch = next(s for s in sprays if s["product_name"] == "Switch 62.5 WG")
    assert switch["field_block"] == "Field 7"
    rescue = next(s for s in sprays if s["product_name"] == "Agri-Mek SC")
    assert rescue["field_block"] == "South Block"
    mite_obs = [o for o in observations if "mite" in (o["visible_issue"] or "")]
    assert mite_obs and all(o["field_block"] == "South Block" for o in mite_obs)
