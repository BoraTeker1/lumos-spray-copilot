"""The routes that make the farm page one coherent surface.

Covers the advisory queue, the intelligence composition, farm performance, season
financing, and Lumos economic participation, end to end through the API.

The two tests that would be most expensive to lose are the blinding guard (a shadow
disease-risk assessment must never reach a PCA-facing payload) and the operator gate
on commercial terms and lender policies.
"""
from datetime import date, timedelta

import pytest

from app import participation


def _farm(client, name="Intelligence Farm", **overrides):
    payload = {
        "name": name, "country": "US", "crop_type": "strawberry",
        "area_unit": "acres",
        "expected_harvest_date": (date.today() + timedelta(days=45)).isoformat(),
        "planting_date": (date.today() - timedelta(days=60)).isoformat(),
    }
    payload.update(overrides)
    res = client.post("/farms", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def _cycle(client, farm_id, **overrides):
    payload = {
        "crop": "strawberry", "season_year": date.today().year,
        "planting_date": (date.today() - timedelta(days=60)).isoformat(),
        "display_area": 18.0, "display_area_unit": "acres",
    }
    payload.update(overrides)
    res = client.post(f"/farms/{farm_id}/crop-cycles", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def _planned(client, farm_id, **overrides):
    payload = {
        "intended_date": (date.today() + timedelta(days=3)).isoformat(),
        "product_name": "Switch 62.5WG",
        "active_ingredient": "cyprodinil",
        "target_pest_or_disease": "botrytis",
        "estimated_cost": 940.0,
    }
    payload.update(overrides)
    res = client.post(f"/farms/{farm_id}/planned-sprays", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


# ------------------------------------------------------------ advisory queue
def test_the_advisory_queue_surfaces_a_decision_that_needs_an_outcome(client):
    farm = _farm(client)
    _cycle(client, farm["id"])
    _planned(client, farm["id"])

    res = client.get(f"/farms/{farm['id']}/advisory")
    assert res.status_code == 200, res.text
    queue = res.json()
    kinds = {i["kind"] for i in queue["items"]}
    assert kinds & {"await_pca_review", "record_outcome", "procurement_opportunity"}
    assert queue["disclaimer"]


def test_every_advisory_item_carries_a_recommendation_and_a_next_action(client):
    farm = _farm(client)
    _cycle(client, farm["id"])
    _planned(client, farm["id"])

    queue = client.get(f"/farms/{farm['id']}/advisory").json()
    assert queue["items"], "expected at least one item"
    for item in queue["items"]:
        assert item["recommendation"], item["kind"]
        assert item["why"], item["kind"]
        assert item["next_action"]["href"], item["kind"]
        assert item["urgency"] in ("critical", "soon", "routine")


def test_an_advisory_item_never_names_a_product_to_apply(client):
    """The queue may say a decision needs review; prescribing is inexpressible."""
    farm = _farm(client)
    _cycle(client, farm["id"])
    _planned(client, farm["id"])

    queue = client.get(f"/farms/{farm['id']}/advisory").json()
    for item in queue["items"]:
        assert "product" not in item
        assert "rate" not in item
        assert "active_ingredient" not in item


def test_an_empty_farm_has_an_empty_queue(client):
    farm = _farm(client, name="Quiet Farm")
    queue = client.get(f"/farms/{farm['id']}/advisory").json()
    assert queue["items"] == []
    assert queue["item_count"] == 0


def test_the_advisory_queue_404s_for_an_unknown_farm(client):
    assert client.get("/farms/9999/advisory").status_code == 404


# ---------------------------------------------------------- the intelligence
def test_the_intelligence_view_composes_every_block_the_farm_page_needs(client):
    farm = _farm(client)
    _cycle(client, farm["id"])
    _planned(client, farm["id"])

    res = client.get(f"/farms/{farm['id']}/intelligence")
    assert res.status_code == 200, res.text
    payload = res.json()
    for key in (
        "crop_cycle", "cycles", "advisory", "season", "value_ledger",
        "performance", "coverage", "participation", "financing", "procurement",
    ):
        assert key in payload, key


def test_the_intelligence_view_never_carries_a_shadow_assessment(client):
    """The Botrytis study is blinded — a shadow row on a PCA-facing surface ends it."""
    farm = _farm(client)
    _cycle(client, farm["id"])
    _planned(client, farm["id"])

    body = client.get(f"/farms/{farm['id']}/intelligence").text.lower()
    for leak in ("is_shadow", "risk_band", "disease_risk", "abstain_reason"):
        assert leak not in body, f"{leak} reached the intelligence payload"


def test_coverage_distinguishes_connected_data_from_declared_domains(client):
    """Declaring a domain is not building it — coverage must count records."""
    farm = _farm(client)
    _cycle(client, farm["id"])

    coverage = client.get(f"/farms/{farm['id']}/intelligence").json()["coverage"]
    by_key = {row["key"]: row for row in coverage}
    assert by_key["crop"]["connected"] is True and by_key["crop"]["record_count"] >= 1
    assert by_key["climate"]["connected"] is False
    assert by_key["financing"]["connected"] is False


def test_the_intelligence_view_404s_on_a_cross_farm_cycle(client):
    farm_a = _farm(client, name="A")
    farm_b = _farm(client, name="B")
    cycle_b = _cycle(client, farm_b["id"])
    res = client.get(
        f"/farms/{farm_a['id']}/intelligence", params={"crop_cycle_id": cycle_b["id"]}
    )
    assert res.status_code == 404


# ------------------------------------------------------------- performance
def test_performance_reports_no_trend_from_a_single_season(client):
    farm = _farm(client)
    _cycle(client, farm["id"])

    profile = client.get(f"/farms/{farm['id']}/performance").json()
    assert profile["season_count"] == 1
    assert all(t.get("not_calculated") for t in profile["trends"].values())


def test_performance_carries_no_overall_score(client):
    farm = _farm(client)
    _cycle(client, farm["id"])
    profile = client.get(f"/farms/{farm['id']}/performance").json()
    assert "overall_score" not in profile
    assert "no cross-farm benchmark" in profile["comparison_basis"]


# -------------------------------------------------------- season financing
def _request(client, farm_id, **overrides):
    payload = {"purpose": "input_purchase", "requested_amount": 30000.0}
    payload.update(overrides)
    res = client.post(f"/farms/{farm_id}/financing-requests", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def test_a_financing_request_opens_in_draft_with_an_event(client):
    farm = _farm(client)
    request = _request(client, farm["id"])
    assert request["status"] == "draft"
    assert [e["event_type"] for e in request["events"]] == ["created"]


def test_a_financing_request_has_no_approved_status(client):
    farm = _farm(client)
    request = _request(client, farm["id"])
    res = client.patch(
        f"/financing-requests/{request['id']}", json={"status": "approved"}
    )
    assert res.status_code == 422


def test_the_evidence_package_lists_what_is_recorded_and_what_is_not(client):
    farm = _farm(client)
    _cycle(client, farm["id"])
    _planned(client, farm["id"])
    request = _request(client, farm["id"])

    package = client.get(
        f"/financing-requests/{request['id']}/evidence-package"
    ).json()
    assert package["present_count"] + package["missing_count"] == package["total_count"]
    assert package["present_count"] >= 1
    assert all(item["how"] for item in package["missing"])


def test_the_evidence_package_forms_no_credit_opinion(client):
    farm = _farm(client)
    request = _request(client, farm["id"])
    package = client.get(
        f"/financing-requests/{request['id']}/evidence-package"
    ).json()
    for forbidden in (
        "approval_probability", "creditworthiness", "credit_score", "interest_rate"
    ):
        assert forbidden not in package


def test_an_assessment_refuses_without_a_lender_policy(client):
    farm = _farm(client)
    request = _request(client, farm["id"])
    result = client.get(f"/financing-requests/{request['id']}/assessment").json()
    assert result["refused"] is True
    assert result["code"] == "no_lender_policy_attached"
    assert "never authors one" in result["detail"]


def test_monitoring_refuses_without_a_covenant_schedule(client):
    farm = _farm(client)
    request = _request(client, farm["id"])
    result = client.get(f"/financing-requests/{request['id']}/monitoring").json()
    assert result["refused"] is True


def test_a_lender_policy_makes_an_assessment_reachable(client, monkeypatch):
    monkeypatch.setenv("LUMOS_OPERATOR_KEY", "")
    farm = _farm(client)
    _cycle(client, farm["id"])
    _planned(client, farm["id"])

    policy = client.post("/internal/lender-policies", json={
        "lender": "Central Coast Ag Credit (simulated)",
        "policy_version": "2026-A",
        "source_document": "Simulated term sheet, for demonstration only.",
        "rules": [
            {
                "rule_id": "evidence-spray-log", "kind": "required_evidence",
                "description": "Pesticide application log",
                "evidence_key": "spray_log",
            },
            {
                "rule_id": "max-exposure", "kind": "maximum_exposure",
                "description": "Maximum exposure to one borrower",
                "threshold": 250000.0,
            },
        ],
    })
    assert policy.status_code == 201, policy.text

    request = _request(client, farm["id"], lender_policy_id=policy.json()["id"])
    result = client.get(f"/financing-requests/{request['id']}/assessment").json()
    assert result.get("refused") is not True
    assert result["outcome"] in (
        "conditions_met", "conditions_not_met", "referred_to_human"
    )
    assert result["lender"] == "Central Coast Ag Credit (simulated)"


def test_missing_evidence_refers_to_a_human_rather_than_declining(client):
    """Lumos cannot see the grower's filing cabinet; absence is a question, not a no."""
    farm = _farm(client)
    policy = client.post("/internal/lender-policies", json={
        "lender": "Simulated Lender", "policy_version": "1",
        "source_document": "Simulated.",
        "rules": [{
            "rule_id": "needs-collateral", "kind": "required_evidence",
            "description": "Registered collateral", "evidence_key": "collateral_register",
        }],
    })
    request = _request(client, farm["id"], lender_policy_id=policy.json()["id"])
    result = client.get(f"/financing-requests/{request['id']}/assessment").json()
    assert result["outcome"] == "referred_to_human"


def test_a_lender_policy_requires_its_source_document(client):
    res = client.post("/internal/lender-policies", json={
        "lender": "No Paperwork Bank", "policy_version": "1", "source_document": "",
    })
    assert res.status_code == 422


def test_an_indicative_offer_can_be_entered_against_a_request(client):
    farm = _farm(client)
    request = _request(client, farm["id"])
    res = client.post(f"/internal/financing-requests/{request['id']}/offers", json={
        "provider_name": "AgCredit Partners (simulated)",
        "requested_amount": 30000.0, "down_payment": 5000.0,
        "financed_amount": 25000.0, "total_repayment": 26500.0,
        "schedule_summary": "Repaid in full at harvest settlement.",
    })
    assert res.status_code == 201, res.text
    offer = res.json()
    assert offer["status"] == "indicative"
    assert "apr" not in offer and "interest_rate" not in offer

    refreshed = client.get(f"/financing-requests/{request['id']}").json()
    assert refreshed["status"] == "offers_received"
    assert len(refreshed["offers"]) == 1


# --------------------------------------------------- commercial agreements
def _agreement(client, farm_id, **overrides):
    payload = {
        "name": "Pilot terms 2026",
        "model_type": participation.MODEL_VERIFIED_VALUE_SHARE,
        "terms": {"rate_pct": 15.0},
    }
    payload.update(overrides)
    return client.post(
        f"/internal/farms/{farm_id}/commercial-agreements", json=payload
    )


def test_a_commercial_agreement_can_be_recorded_and_read_back(client):
    farm = _farm(client)
    res = _agreement(client, farm["id"])
    assert res.status_code == 201, res.text
    assert res.json()["status"] == "active"

    listed = client.get(f"/farms/{farm['id']}/commercial-agreements").json()
    assert len(listed) == 1


def test_agreement_terms_cannot_carry_a_settlement_field(client):
    """The one place a payment field could enter without a migration to review."""
    farm = _farm(client)
    res = _agreement(client, farm["id"], terms={"rate_pct": 15.0, "due_date": "2026-12-01"})
    assert res.status_code == 422
    assert "moves no money" in res.text


def test_superseding_an_agreement_retires_the_old_one(client):
    farm = _farm(client)
    first = _agreement(client, farm["id"]).json()
    second = _agreement(
        client, farm["id"], name="Renegotiated", supersedes_id=first["id"]
    ).json()

    listed = {a["id"]: a for a in client.get(
        f"/farms/{farm['id']}/commercial-agreements"
    ).json()}
    assert listed[first["id"]]["status"] == "superseded"
    assert listed[second["id"]]["status"] == "active"


def test_participation_refuses_when_no_verified_value_exists(client):
    farm = _farm(client)
    cycle = _cycle(client, farm["id"])
    _agreement(client, farm["id"])

    result = client.get(f"/crop-cycles/{cycle['id']}/participation").json()
    assert result["refused"] is True
    assert result["code"] == participation.NO_VERIFIED_VALUE


def test_participation_refuses_when_no_agreement_exists(client):
    farm = _farm(client)
    cycle = _cycle(client, farm["id"])
    result = client.get(f"/crop-cycles/{cycle['id']}/participation").json()
    assert result["code"] == participation.NO_AGREEMENT


def test_participation_computes_from_a_verified_avoided_application(client):
    """The full loop: decision → review → avoided → follow-up → verified → share."""
    farm = _farm(client)
    cycle = _cycle(client, farm["id"])
    planned = _planned(client, farm["id"], estimated_cost=2000.0)

    client.patch(f"/planned-sprays/{planned['id']}/review", json={
        "action": "approved", "reviewed_by": "Dana PCA",
    })
    res = client.patch(f"/planned-sprays/{planned['id']}/outcome", json={
        "outcome": "avoided",
        "outcome_reason": "Scouting showed pressure below the action threshold.",
    })
    assert res.status_code == 200, res.text
    # A scouting observation and no application on record is what turns an avoided
    # outcome from estimated into verified.
    res = client.post(f"/planned-sprays/{planned['id']}/follow-up-events", json={
        "event_type": "scouting_observation",
        "observed_at": date.today().isoformat(),
        "notes": "No rot found; no rescue treatment needed.",
        "severity": 1,
    })
    assert res.status_code == 201, res.text

    _agreement(client, farm["id"], terms={"rate_pct": 15.0})
    result = client.get(f"/crop-cycles/{cycle['id']}/participation").json()

    assert not result.get("refused"), result
    assert result["basis_amount"] == 2000.0
    assert result["participation_amount"] == 300.0
    assert result["grower_retained_amount"] == 1700.0
    assert "moves no money" in result["disclaimer"]


def test_a_participation_payload_carries_no_payment_fields(client):
    farm = _farm(client)
    cycle = _cycle(client, farm["id"])
    _agreement(client, farm["id"], model_type="platform_fee", terms={"amount": 1200.0})

    result = client.get(f"/crop-cycles/{cycle['id']}/participation").json()
    for forbidden in ("invoice", "due_date", "paid", "settlement_status", "apr"):
        assert forbidden not in result
