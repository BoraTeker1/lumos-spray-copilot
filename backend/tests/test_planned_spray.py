"""API tests for the planned-spray workflow: decision check -> PCA review -> outcome.

Engine behaviour is covered in test_decision_engine.py; these tests exercise the
HTTP workflow, the human review gate, and the evidence aggregation.
"""
from datetime import date, timedelta

from app.decision_engine import PLANNED_SPRAY_DISCLAIMER


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
    # Intended today: recording an outcome "today" then satisfies the chronology
    # invariant (outcome/application date must never precede the intended date).
    payload = {
        "intended_date": date.today().isoformat(),
        "product_name": "Captan 80WDG",
        "active_ingredient": "captan",
        "target_pest_or_disease": "botrytis",
        "pre_harvest_interval_days": 7,
        "re_entry_interval_hours": 24,
        "estimated_cost": 120.0,
    }
    payload.update(overrides)
    res = client.post(f"/farms/{farm_id}/planned-sprays", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def _approve(client, planned_id, **overrides):
    payload = {"action": "approved", "reviewed_by": "Test PCA"}
    payload.update(overrides)
    res = client.patch(f"/planned-sprays/{planned_id}/review", json=payload)
    assert res.status_code == 200, res.text
    return res.json()


# ------------------------------------------------------------------ decision check
def test_create_planned_spray_returns_explainable_decision(client):
    farm_row = _create_farm(client)
    planned_row = _create_planned(client, farm_row["id"])
    # PHI 7d from today clears after the day-3 harvest -> block.
    assert planned_row["decision_outcome"] == "block"
    assert planned_row["decision_severity"] == "critical"
    assert planned_row["review_required"] is True
    assert planned_row["outcome"] == "planned"
    assert planned_row["review_status"] == "not_reviewed"
    assert PLANNED_SPRAY_DISCLAIMER in planned_row["check_text"]

    payload = planned_row["decision_payload"]
    assert payload["outcome"] == "block"
    triggered = [r for r in payload["rules"] if r["triggered"]]
    assert any(r["rule_id"] == "phi_harvest_conflict" for r in triggered)
    assert any(r["calculation"] for r in triggered)
    assert payload["inputs_used"]["pre_harvest_interval_days"] == 7
    assert payload["disclaimer"] == PLANNED_SPRAY_DISCLAIMER

    listed = client.get(f"/farms/{farm_row['id']}/planned-sprays").json()
    assert [p["id"] for p in listed] == [planned_row["id"]]


def test_clean_planned_spray_is_provisional_approve(client):
    farm_row = _create_farm(
        client, expected_harvest_date=(date.today() + timedelta(days=40)).isoformat()
    )
    client.post(
        f"/farms/{farm_row['id']}/scout-observations",
        json={"observation_date": date.today().isoformat(), "visible_issue": "botrytis",
              "severity_1_to_5": 3},
    )
    planned_row = _create_planned(client, farm_row["id"], pre_harvest_interval_days=2)
    assert planned_row["decision_outcome"] == "approve"
    assert planned_row["decision_confidence"] == "high"
    # Authority gating: grower-entered values + heuristic checks can never yield a
    # definitive green light — the approve is provisional and needs PCA confirmation.
    assert planned_row["decision_authority"] == "provisional"
    assert planned_row["review_required"] is True
    assert planned_row["values_source"] == "grower_entered"


def test_values_source_flows_through_and_gates_authority(client):
    farm_row = _create_farm(client)
    planned_row = _create_planned(
        client, farm_row["id"],
        values_source="pca_entered", values_entered_by="Jane Doe, PCA",
    )
    assert planned_row["decision_outcome"] == "block"
    assert planned_row["decision_authority"] == "pca_authorized"
    assert planned_row["values_entered_by"] == "Jane Doe, PCA"
    phi_rule = next(
        r for r in planned_row["decision_payload"]["rules"]
        if r["rule_id"] == "phi_harvest_conflict"
    )
    assert phi_rule["source_authority"] == "pca_entered"
    assert phi_rule["entered_by"] == "Jane Doe, PCA"

    # verified_label cannot be claimed by clients — there is no label database.
    res = client.post(
        f"/farms/{farm_row['id']}/planned-sprays",
        json={"intended_date": date.today().isoformat(), "product_name": "X",
              "values_source": "verified_label"},
    )
    assert res.status_code == 422


def test_get_planned_spray_by_id(client):
    farm_row = _create_farm(client)
    planned_row = _create_planned(client, farm_row["id"])
    res = client.get(f"/planned-sprays/{planned_row['id']}")
    assert res.status_code == 200
    assert res.json()["decision_payload"]["outcome"] == "block"
    assert client.get("/planned-sprays/99999").status_code == 404


# ---------------------------------------------------------------------- PCA review
def test_review_approve_edit_reject(client):
    farm_row = _create_farm(client)
    planned_row = _create_planned(client, farm_row["id"])

    reviewed = _approve(client, planned_row["id"], review_comment="Agree with the block.")
    assert reviewed["review_status"] == "approved"
    assert reviewed["reviewed_by"] == "Test PCA"
    assert reviewed["reviewed_at"] is not None

    edited = client.patch(
        f"/planned-sprays/{planned_row['id']}/review",
        json={"action": "edited", "pca_next_action": "Use a PHI-0 product instead.",
              "reviewed_by": "Test PCA"},
    ).json()
    assert edited["review_status"] == "edited"
    assert edited["pca_next_action"] == "Use a PHI-0 product instead."


def test_edit_without_guidance_and_reject_without_comment_are_rejected(client):
    farm_row = _create_farm(client)
    planned_row = _create_planned(client, farm_row["id"])
    res = client.patch(
        f"/planned-sprays/{planned_row['id']}/review", json={"action": "edited"}
    )
    assert res.status_code == 422
    res = client.patch(
        f"/planned-sprays/{planned_row['id']}/review", json={"action": "rejected"}
    )
    assert res.status_code == 422


# ------------------------------------------------------------------ the human gate
def test_applied_outcome_requires_review_when_decision_demanded_it(client):
    farm_row = _create_farm(client)
    planned_row = _create_planned(client, farm_row["id"])  # block -> review required
    res = client.patch(
        f"/planned-sprays/{planned_row['id']}/outcome",
        json={"outcome": "sprayed_as_planned"},
    )
    assert res.status_code == 409
    assert "review" in res.json()["detail"].lower()

    # Non-applied outcomes stay recordable without review (honest documentation).
    res = client.patch(
        f"/planned-sprays/{planned_row['id']}/outcome",
        json={"outcome": "avoided", "outcome_reason": "Held off after the block."},
    )
    assert res.status_code == 200


def test_applied_outcome_allowed_after_review(client):
    farm_row = _create_farm(client)
    planned_row = _create_planned(client, farm_row["id"])
    _approve(client, planned_row["id"])
    res = client.patch(
        f"/planned-sprays/{planned_row['id']}/outcome",
        json={"outcome": "sprayed_as_planned"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["outcome"] == "sprayed_as_planned"
    assert body["spray_event_id"] is not None

    events = client.get(f"/farms/{farm_row['id']}/spray-events").json()
    linked = [e for e in events if e["id"] == body["spray_event_id"]]
    assert len(linked) == 1
    assert linked[0]["product_name"] == "Captan 80WDG"
    assert linked[0]["application_date"] == planned_row["intended_date"]


# --------------------------------------------------------------- recorded outcomes
def test_non_as_planned_outcomes_require_a_reason(client):
    farm_row = _create_farm(client)
    planned_row = _create_planned(client, farm_row["id"])
    for outcome in ("avoided", "delayed", "inspected_first", "changed_product"):
        res = client.patch(
            f"/planned-sprays/{planned_row['id']}/outcome", json={"outcome": outcome}
        )
        assert res.status_code == 422, outcome


def test_changed_product_requires_product_and_creates_linked_event(client):
    farm_row = _create_farm(client)
    planned_row = _create_planned(client, farm_row["id"])
    _approve(client, planned_row["id"])

    # Missing the replacement product -> 422.
    res = client.patch(
        f"/planned-sprays/{planned_row['id']}/outcome",
        json={"outcome": "changed_product", "outcome_reason": "Too close to harvest."},
    )
    assert res.status_code == 422

    res = client.patch(
        f"/planned-sprays/{planned_row['id']}/outcome",
        json={
            "outcome": "changed_product",
            "outcome_reason": "Too close to harvest — used a PHI-0 product.",
            "outcome_product_name": "Switch 62.5 WG",
            "outcome_active_ingredient": "cyprodinil + fludioxonil",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["spray_event_id"] is not None

    events = client.get(f"/farms/{farm_row['id']}/spray-events").json()
    linked = next(e for e in events if e["id"] == body["spray_event_id"])
    assert linked["product_name"] == "Switch 62.5 WG"
    assert linked["active_ingredient"] == "cyprodinil + fludioxonil"
    # PHI/REI never carry over from a different planned product.
    assert linked["pre_harvest_interval_days"] is None
    assert linked["re_entry_interval_hours"] is None


def test_avoided_with_reason_is_recorded(client):
    farm_row = _create_farm(client)
    planned_row = _create_planned(client, farm_row["id"])
    res = client.patch(
        f"/planned-sprays/{planned_row['id']}/outcome",
        json={"outcome": "avoided", "outcome_reason": "No botrytis found on inspection."},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["outcome"] == "avoided"
    assert body["spray_event_id"] is None


def test_delete_planned_spray(client):
    farm_row = _create_farm(client)
    planned_row = _create_planned(client, farm_row["id"])
    res = client.delete(f"/planned-sprays/{planned_row['id']}")
    assert res.status_code == 204
    assert client.get(f"/farms/{farm_row['id']}/planned-sprays").json() == []


# ------------------------------------------------------------- evidence aggregation
def test_decision_evidence_metrics(client):
    farm_row = _create_farm(client)
    # Demo/simulated decision: excluded everywhere.
    _create_planned(client, farm_row["id"], data_source="demo", data_confidence="simulated")

    # Real decision 1: blocked, reviewed, avoided (cost 120 -> counted as avoided).
    p1 = _create_planned(client, farm_row["id"])
    _approve(client, p1["id"])
    client.patch(
        f"/planned-sprays/{p1['id']}/outcome",
        json={"outcome": "avoided", "outcome_reason": "Held off — PHI conflict."},
    )
    # Real decision 2: blocked, rejected review, still awaiting outcome.
    p2 = _create_planned(client, farm_row["id"])
    client.patch(
        f"/planned-sprays/{p2['id']}/review",
        json={"action": "rejected", "review_comment": "Data looks wrong — re-enter PHI."},
    )

    ev = client.get(f"/farms/{farm_row['id']}/decision-evidence").json()
    assert ev["decisions_checked"] == 2
    assert ev["decisions_reviewed"] == 2
    assert ev["pca_acceptance_rate_pct"] == 50.0
    assert ev["outcomes"]["avoided"] == 1
    assert ev["outcomes"]["awaiting_outcome"] == 1
    assert ev["sprays_changed_delayed_or_avoided"] == 1
    assert ev["compliance_conflicts_caught"] == 2
    assert ev["estimated_chemical_cost_avoided"] == 120.0
    assert ev["estimated_review_minutes_saved"] == 20
    assert "assumption" in ev["review_minutes_assumption"].lower()
    assert ev["limitations"]


def test_demo_planned_sprays_excluded_from_pilot_evidence(client):
    farm_row = _create_farm(client)
    _create_planned(client, farm_row["id"], data_source="demo", data_confidence="simulated")
    real = _create_planned(client, farm_row["id"])
    client.patch(
        f"/planned-sprays/{real['id']}/outcome",
        json={"outcome": "avoided", "outcome_reason": "Scouting showed no pressure."},
    )

    evidence = client.get(f"/farms/{farm_row['id']}/pilot-evidence").json()
    block = evidence["pre_spray_decisions"]
    assert block["checked"] == 1
    assert block["avoided"] == 1
    assert block["sprayed_as_planned"] == 0
    assert block["outcome_reasons"] == [
        {"outcome": "avoided", "reason": "Scouting showed no pressure."}
    ]
    assert "not" in block["note"].lower()  # explicitly non-causal framing


# --------------------------------------------------------------- farms overview
def test_farms_overview_ranks_urgency_and_explains_why(client):
    quiet = _create_farm(
        client, name="Quiet Farm",
        expected_harvest_date=(date.today() + timedelta(days=60)).isoformat(),
    )
    risky = _create_farm(client, name="Risky Farm")
    _create_planned(client, risky["id"])  # block -> unresolved conflict

    overview = client.get("/farms-overview").json()
    assert [f["name"] for f in overview] == ["Risky Farm", "Quiet Farm"]
    top = overview[0]
    assert top["urgency"] == "conflict"
    assert top["why"]
    assert top["next_action"]
    assert top["needs_review_count"] == 1
    quiet_row = overview[1]
    assert quiet_row["urgency"] == "ok"
