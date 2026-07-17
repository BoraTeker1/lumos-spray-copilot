"""Input plans (the RFQ): lifecycle, draft-only mutation, decision eligibility,
and demo/real chain separation."""
import pytest


@pytest.fixture(autouse=True)
def pinned_clock(monkeypatch):
    monkeypatch.setenv("LUMOS_DEMO_TODAY", "2026-07-16")


def _farm(client):
    return client.post("/farms", json={
        "name": "Inputs Farm", "country": "US", "crop_type": "strawberry",
        "expected_harvest_date": "2026-09-01", "greenhouse_area": 20.0,
    }).json()


def _planned(client, farm_id, **overrides):
    # Deliberately missing PHI/REI: missing regulatory inputs escalate the check
    # to pca_review_required, so the decision starts with a PENDING review.
    payload = {
        "intended_date": "2026-07-16",
        "product_name": "Switch 62.5 WG",
        "active_ingredient": "cyprodinil + fludioxonil",
        "target_pest_or_disease": "gray mold",
        "estimated_cost": 210.0,
        "treated_acres": 18.0,
    }
    payload.update(overrides)
    resp = client.post(f"/farms/{farm_id}/planned-sprays", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _review(client, pid, action="approved", **extra):
    payload = {"action": action, "reviewed_by": "Test PCA"}
    payload.update(extra)
    resp = client.patch(f"/planned-sprays/{pid}/review", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _item(**overrides):
    payload = {
        "product_name": "Switch 62.5 WG",
        "category": "fungicide",
        "quantity": 252.0,
        "unit": "oz",
        "needed_by_date": "2026-07-20",
    }
    payload.update(overrides)
    return payload


def _plan(client, farm_id, items=None, expect=201, **overrides):
    payload = {"requested_by": "Test grower", "items": items or []}
    payload.update(overrides)
    resp = client.post(f"/farms/{farm_id}/input-plans", json=payload)
    assert resp.status_code == expect, resp.text
    return resp.json()


def test_create_and_list_draft_plan(client):
    farm = _farm(client)
    plan = _plan(client, farm["id"], items=[_item()])
    assert plan["status"] == "draft"
    assert plan["financing_state"] == "cash"
    assert plan["quote_count"] == 0
    assert plan["order_id"] is None
    assert plan["items"][0]["source_decision_review_state"] == "not_linked"
    assert plan["items"][0]["source_decision_procurement_eligible"] is None
    plans = client.get(f"/farms/{farm['id']}/input-plans").json()
    assert [p["id"] for p in plans] == [plan["id"]]


def test_pending_review_decision_cannot_back_an_item(client):
    farm = _farm(client)
    p = _planned(client, farm["id"])  # missing PHI/REI -> PCA review required
    assert p["review_state"] == "pending"
    assert p["procurement_eligible"] is False
    resp = client.post(f"/farms/{farm['id']}/input-plans", json={
        "items": [_item(planned_spray_id=p["id"])],
    })
    assert resp.status_code == 409
    assert "not eligible" in resp.json()["detail"]


def test_rejected_decision_cannot_back_an_item(client):
    farm = _farm(client)
    p = _planned(client, farm["id"])
    _review(client, p["id"], action="rejected", review_comment="Do not apply.")
    resp = client.post(f"/farms/{farm['id']}/input-plans", json={
        "items": [_item(planned_spray_id=p["id"])],
    })
    assert resp.status_code == 409


def test_avoided_decision_cannot_back_an_item(client):
    farm = _farm(client)
    p = _planned(client, farm["id"])
    _review(client, p["id"])
    resp = client.patch(f"/planned-sprays/{p['id']}/outcome", json={
        "outcome": "avoided", "outcome_reason": "below threshold",
    })
    assert resp.status_code == 200, resp.text
    resp = client.post(f"/farms/{farm['id']}/input-plans", json={
        "items": [_item(planned_spray_id=p["id"])],
    })
    assert resp.status_code == 409


def test_approved_decision_backs_an_item_and_serializes_eligibility(client):
    farm = _farm(client)
    p = _planned(client, farm["id"])
    _review(client, p["id"])
    fetched = client.get(f"/planned-sprays/{p['id']}").json()
    assert fetched["procurement_eligible"] is True
    plan = _plan(client, farm["id"], items=[_item(planned_spray_id=p["id"])])
    item = plan["items"][0]
    assert item["source_decision_review_state"] == "approved"
    assert item["source_decision_procurement_eligible"] is True


def test_cross_farm_decision_link_is_rejected(client):
    farm_a = _farm(client)
    farm_b = _farm(client)
    p = _planned(client, farm_a["id"])
    _review(client, p["id"])
    resp = client.post(f"/farms/{farm_b['id']}/input-plans", json={
        "items": [_item(planned_spray_id=p["id"])],
    })
    assert resp.status_code == 422


def test_items_locked_after_submit(client):
    farm = _farm(client)
    plan = _plan(client, farm["id"], items=[_item()])
    item_id = plan["items"][0]["id"]
    resp = client.post(f"/input-plans/{plan['id']}/submit", json={"submitted_by": "G"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "submitted_for_quotes"
    resp = client.post(f"/input-plans/{plan['id']}/items", json=_item())
    assert resp.status_code == 409
    resp = client.delete(f"/input-plan-items/{item_id}")
    assert resp.status_code == 409
    # Draft plans still allow both.
    draft = _plan(client, farm["id"], items=[_item()])
    resp = client.post(f"/input-plans/{draft['id']}/items", json=_item())
    assert resp.status_code == 201
    resp = client.delete(f"/input-plan-items/{resp.json()['id']}")
    assert resp.status_code == 204


def test_submit_requires_items_and_draft_status(client):
    farm = _farm(client)
    empty = _plan(client, farm["id"])
    resp = client.post(f"/input-plans/{empty['id']}/submit", json={})
    assert resp.status_code == 409
    plan = _plan(client, farm["id"], items=[_item()])
    assert client.post(f"/input-plans/{plan['id']}/submit", json={}).status_code == 200
    resp = client.post(f"/input-plans/{plan['id']}/submit", json={})
    assert resp.status_code == 409  # idempotency guard: not a draft any more


def test_submit_rechecks_decision_eligibility(client):
    farm = _farm(client)
    p = _planned(client, farm["id"])
    _review(client, p["id"])
    plan = _plan(client, farm["id"], items=[_item(planned_spray_id=p["id"])])
    # The decision's situation changes after the item was added: recorded as avoided.
    resp = client.patch(f"/planned-sprays/{p['id']}/outcome", json={
        "outcome": "avoided", "outcome_reason": "inspection found no pressure",
    })
    assert resp.status_code == 200
    resp = client.post(f"/input-plans/{plan['id']}/submit", json={})
    assert resp.status_code == 409
    assert str(p["id"]) in resp.json()["detail"]


def test_cancel_draft_but_not_twice(client):
    farm = _farm(client)
    plan = _plan(client, farm["id"], items=[_item()])
    resp = client.post(f"/input-plans/{plan['id']}/cancel", json={"reason": "changed mind"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"
    resp = client.post(f"/input-plans/{plan['id']}/cancel", json={"reason": "again"})
    assert resp.status_code == 409


def test_demo_and_real_records_never_mix_in_one_plan(client):
    farm = _farm(client)
    # Demo item on a real plan.
    resp = client.post(f"/farms/{farm['id']}/input-plans", json={
        "items": [_item(data_source="demo", data_confidence="simulated")],
    })
    assert resp.status_code == 409
    assert "mix" in resp.json()["detail"]
    # Real (user-provided) decision behind a demo plan/item.
    p = _planned(client, farm["id"])
    _review(client, p["id"])
    resp = client.post(f"/farms/{farm['id']}/input-plans", json={
        "data_source": "demo", "data_confidence": "simulated",
        "items": [_item(
            planned_spray_id=p["id"],
            data_source="demo", data_confidence="simulated",
        )],
    })
    assert resp.status_code == 409
