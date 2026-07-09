"""Tests for the pre-spray decision check (planned sprays).

Engine tests use SimpleNamespace stand-ins with a fixed `today` (same style as
test_recommendation_engine.py); API tests use the shared TestClient fixture.
"""
from datetime import date, timedelta
from types import SimpleNamespace

from app.recommendation_engine import (
    PLANNED_SPRAY_DISCLAIMER,
    RISK_LOW,
    evaluate_planned_spray,
)

TODAY = date(2026, 7, 9)


def farm(harvest_offset_days=None):
    harvest = (
        TODAY + timedelta(days=harvest_offset_days)
        if harvest_offset_days is not None
        else None
    )
    return SimpleNamespace(expected_harvest_date=harvest)


def spray(ai="captan", days_ago=1):
    return SimpleNamespace(
        active_ingredient=ai,
        application_date=TODAY - timedelta(days=days_ago),
        pre_harvest_interval_days=None,
        product_name="Test Product",
    )


def obs(issue, days_ago=1, severity=2):
    return SimpleNamespace(
        observation_date=TODAY - timedelta(days=days_ago),
        severity_1_to_5=severity,
        visible_issue=issue,
    )


def planned(ai="captan", target="botrytis", phi=None, intended_offset_days=1):
    return SimpleNamespace(
        intended_date=TODAY + timedelta(days=intended_offset_days),
        product_name="Captan 80WDG",
        active_ingredient=ai,
        target_pest_or_disease=target,
        pre_harvest_interval_days=phi,
    )


# ------------------------------------------------------ Check 1: repeated ingredient
def test_planned_spray_exceeding_ingredient_window_is_flagged():
    # 2 recent captan uses; the planned one would be the 3rd -> over the limit.
    sprays = [spray(days_ago=5), spray(days_ago=15)]
    result = evaluate_planned_spray(farm(), planned(), sprays, [], today=TODAY)
    assert any("use number 3" in f for f in result.flags)


def test_planned_spray_within_ingredient_limit_not_flagged():
    sprays = [spray(days_ago=5)]  # planned would be only the 2nd use
    result = evaluate_planned_spray(farm(), planned(), sprays, [], today=TODAY)
    assert not any("use number" in f for f in result.flags)


def test_old_sprays_outside_window_do_not_count():
    sprays = [spray(days_ago=40), spray(days_ago=50)]
    result = evaluate_planned_spray(farm(), planned(), sprays, [], today=TODAY)
    assert not any("use number" in f for f in result.flags)


# ------------------------------------------------------------- Check 2: PHI arithmetic
def test_phi_clearing_after_harvest_is_flagged():
    # Intended tomorrow + PHI 7 clears on day 8; harvest on day 3 -> flag.
    result = evaluate_planned_spray(
        farm(harvest_offset_days=3), planned(phi=7), [], [], today=TODAY
    )
    assert any("pre-harvest interval risk" in f.lower() for f in result.flags)


def test_phi_clearing_before_harvest_not_flagged():
    # Intended tomorrow + PHI 2 clears on day 3; harvest on day 10 -> fine.
    result = evaluate_planned_spray(
        farm(harvest_offset_days=10), planned(phi=2), [], [], today=TODAY
    )
    assert not any("pre-harvest interval risk" in f.lower() for f in result.flags)


def test_no_phi_entered_means_no_phi_flag():
    result = evaluate_planned_spray(
        farm(harvest_offset_days=1), planned(phi=None), [], [], today=TODAY
    )
    assert not any("pre-harvest interval risk" in f.lower() for f in result.flags)


# ------------------------------------------- Check 3: explicitly linked scouting evidence
def test_exact_normalized_scouting_match_suppresses_flag():
    observations = [obs("  Botrytis ", days_ago=3)]  # trims + lowercases to "botrytis"
    result = evaluate_planned_spray(
        farm(), planned(ai="azoxystrobin", target="botrytis"), [], observations, today=TODAY
    )
    assert not any("no scouting observation" in f.lower() for f in result.flags)
    assert result.signals["scouting_evidence_linked"] is True
    assert result.risk_level == RISK_LOW


def test_near_miss_scouting_text_still_flags_as_not_explicitly_linked():
    # "botrytis on fruit" is NOT an exact normalized match for "botrytis" — no substring
    # matching is allowed, so this must flag.
    observations = [obs("botrytis on fruit", days_ago=3)]
    result = evaluate_planned_spray(
        farm(), planned(target="botrytis"), [], observations, today=TODAY
    )
    assert any("no scouting observation explicitly referencing" in f.lower() for f in result.flags)
    assert result.signals["scouting_evidence_linked"] is False


def test_no_recent_scouting_flags_missing_evidence():
    result = evaluate_planned_spray(farm(), planned(), [], [], today=TODAY)
    assert any("no scouting observation explicitly referencing" in f.lower() for f in result.flags)


# ------------------------------------------------------------------ Cautious language
def test_disclaimer_and_cautious_language_in_check_text():
    result = evaluate_planned_spray(
        farm(harvest_offset_days=1), planned(phi=7), [spray(days_ago=2), spray(days_ago=4)], [],
        today=TODAY,
    )
    assert PLANNED_SPRAY_DISCLAIMER in result.recommendation_text
    lower = result.recommendation_text.lower()
    assert "must spray" not in lower
    assert "don't spray" not in lower
    assert "do not spray" not in lower


# ------------------------------------------------------------------------- API flow
def _create_farm(client, **overrides):
    payload = {
        "name": "Pilot Berry Farm",
        "country": "US",
        "crop_type": "strawberry",
        "expected_harvest_date": (date.today() + timedelta(days=3)).isoformat(),
    }
    payload.update(overrides)
    return client.post("/farms", json=payload).json()


def _create_planned(client, farm_id, **overrides):
    payload = {
        "intended_date": (date.today() + timedelta(days=1)).isoformat(),
        "product_name": "Captan 80WDG",
        "active_ingredient": "captan",
        "target_pest_or_disease": "botrytis",
        "pre_harvest_interval_days": 7,
        "estimated_cost": 120.0,
    }
    payload.update(overrides)
    res = client.post(f"/farms/{farm_id}/planned-sprays", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def test_create_planned_spray_returns_check_snapshot(client):
    farm_row = _create_farm(client)
    planned_row = _create_planned(client, farm_row["id"])
    assert planned_row["outcome"] == "planned"
    assert planned_row["check_risk_level"] in ("low", "moderate", "elevated")
    assert PLANNED_SPRAY_DISCLAIMER in planned_row["check_text"]
    # PHI 7d from tomorrow clears after the day-3 harvest -> flagged in the snapshot.
    assert "pre-harvest interval risk" in planned_row["check_text"].lower()

    listed = client.get(f"/farms/{farm_row['id']}/planned-sprays").json()
    assert [p["id"] for p in listed] == [planned_row["id"]]


def test_skipped_without_reason_is_rejected(client):
    farm_row = _create_farm(client)
    planned_row = _create_planned(client, farm_row["id"])
    for outcome in ("skipped", "postponed"):
        res = client.patch(
            f"/planned-sprays/{planned_row['id']}/outcome", json={"outcome": outcome}
        )
        assert res.status_code == 422
        res = client.patch(
            f"/planned-sprays/{planned_row['id']}/outcome",
            json={"outcome": outcome, "outcome_reason": "   "},
        )
        assert res.status_code == 422


def test_skipped_with_reason_is_recorded(client):
    farm_row = _create_farm(client)
    planned_row = _create_planned(client, farm_row["id"])
    res = client.patch(
        f"/planned-sprays/{planned_row['id']}/outcome",
        json={"outcome": "skipped", "outcome_reason": "No botrytis found on inspection."},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["outcome"] == "skipped"
    assert body["outcome_reason"] == "No botrytis found on inspection."
    assert body["spray_event_id"] is None


def test_sprayed_outcome_creates_linked_spray_event(client):
    farm_row = _create_farm(client)
    planned_row = _create_planned(client, farm_row["id"])
    res = client.patch(
        f"/planned-sprays/{planned_row['id']}/outcome", json={"outcome": "sprayed"}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["outcome"] == "sprayed"
    assert body["spray_event_id"] is not None

    events = client.get(f"/farms/{farm_row['id']}/spray-events").json()
    linked = [e for e in events if e["id"] == body["spray_event_id"]]
    assert len(linked) == 1
    assert linked[0]["product_name"] == "Captan 80WDG"
    assert linked[0]["application_date"] == planned_row["intended_date"]
    assert linked[0]["data_confidence"] == "user_provided"


def test_delete_planned_spray(client):
    farm_row = _create_farm(client)
    planned_row = _create_planned(client, farm_row["id"])
    res = client.delete(f"/planned-sprays/{planned_row['id']}")
    assert res.status_code == 204
    assert client.get(f"/farms/{farm_row['id']}/planned-sprays").json() == []


def test_demo_planned_sprays_excluded_from_pilot_evidence(client):
    farm_row = _create_farm(client)
    # One demo/simulated record (excluded) and one real user-provided record (counted).
    _create_planned(client, farm_row["id"], data_source="demo", data_confidence="simulated")
    real = _create_planned(client, farm_row["id"])
    client.patch(
        f"/planned-sprays/{real['id']}/outcome",
        json={"outcome": "skipped", "outcome_reason": "Scouting showed no pressure."},
    )

    evidence = client.get(f"/farms/{farm_row['id']}/pilot-evidence").json()
    block = evidence["pre_spray_decisions"]
    assert block["checked"] == 1
    assert block["skipped"] == 1
    assert block["sprayed"] == 0
    assert block["postponed"] == 0
    assert block["outcome_reasons"] == [
        {"outcome": "skipped", "reason": "Scouting showed no pressure."}
    ]
    assert "not" in block["note"].lower()  # explicitly non-causal framing
