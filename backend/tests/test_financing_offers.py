"""Financing offers: request != offer != approval, one-shot decisions, expiry,
arithmetic honesty, and the mandatory disclaimer."""
import pytest


@pytest.fixture(autouse=True)
def pinned_clock(monkeypatch):
    monkeypatch.setenv("LUMOS_DEMO_TODAY", "2026-07-16")


def _farm(client):
    return client.post("/farms", json={
        "name": "Financing Farm", "country": "US", "crop_type": "strawberry",
        "expected_harvest_date": "2026-09-01", "greenhouse_area": 20.0,
    }).json()


def _quoted_plan(client, farm_id, financing_requested=True):
    plan = client.post(f"/farms/{farm_id}/input-plans", json={
        "requested_by": "Test grower",
        "financing_requested": financing_requested,
        "items": [{
            "product_name": "Switch 62.5 WG", "category": "fungicide",
            "quantity": 252.0, "unit": "oz", "needed_by_date": "2026-07-20",
        }],
    }).json()
    client.post(f"/input-plans/{plan['id']}/submit", json={})
    quote = client.post(f"/internal/input-plans/{plan['id']}/quotes", json={
        "supplier_name": "Supplier A",
        "items": [{
            "input_plan_item_id": plan["items"][0]["id"],
            "product_name": "Switch 62.5 WG",
            "quantity": 252.0, "unit": "oz", "unit_price": 15.0,
        }],
    }).json()
    return plan, quote


def _offer_payload(**overrides):
    payload = {
        "provider_name": "AgCredit Test",
        "requested_amount": 3700.0,
        "down_payment": 700.0,
        "financed_amount": 3000.0,
        "total_repayment": 3150.0,
        "fees_total": 45.0,
        "schedule_summary": "3 monthly payments of $1,050",
        "entered_by": "Concierge",
    }
    payload.update(overrides)
    return payload


def _enter_offer(client, quote_id, expect=201, **overrides):
    resp = client.post(
        f"/internal/supplier-quotes/{quote_id}/financing-offers",
        json=_offer_payload(**overrides),
    )
    assert resp.status_code == expect, resp.text
    return resp.json()


def _financing_state(client, plan_id):
    return client.get(f"/input-plans/{plan_id}").json()["financing_state"]


def test_offer_requires_a_financing_request(client):
    farm = _farm(client)
    plan, quote = _quoted_plan(client, farm["id"], financing_requested=False)
    assert _financing_state(client, plan["id"]) == "cash"
    resp = client.post(
        f"/internal/supplier-quotes/{quote['id']}/financing-offers",
        json=_offer_payload(),
    )
    assert resp.status_code == 409
    assert "not requested" in resp.json()["detail"]


def test_request_is_never_an_approval_state_walk(client):
    farm = _farm(client)
    plan, quote = _quoted_plan(client, farm["id"])
    # Requested, nothing back yet — honestly "awaiting terms", not an offer.
    assert _financing_state(client, plan["id"]) == "financing_requested"
    offer = _enter_offer(client, quote["id"])
    assert offer["status"] == "indicative"
    assert offer["offer_state"] == "indicative"
    assert "not an approval" in offer["disclaimer"]
    assert _financing_state(client, plan["id"]) == "offer_received"
    resp = client.post(f"/financing-offers/{offer['id']}/decision", json={
        "action": "selected", "actor": "Test grower",
    })
    assert resp.status_code == 200
    # "selected", never "accepted": choosing indicative terms is not an
    # approval, not funding, not a binding agreement.
    assert resp.json()["status"] == "selected"
    assert "not an approval" in resp.json()["disclaimer"]
    assert _financing_state(client, plan["id"]) == "offer_selected"
    # The legacy "accepted" vocabulary is gone from the API entirely.
    resp = client.post(f"/financing-offers/{offer['id']}/decision", json={
        "action": "accepted",
    })
    assert resp.status_code == 422


def test_declining_all_offers_reads_declined_or_expired(client):
    farm = _farm(client)
    plan, quote = _quoted_plan(client, farm["id"])
    offer = _enter_offer(client, quote["id"])
    client.post(f"/financing-offers/{offer['id']}/decision", json={"action": "declined"})
    assert _financing_state(client, plan["id"]) == "offer_declined_or_expired"


def test_offer_arithmetic_must_be_consistent(client):
    farm = _farm(client)
    plan, quote = _quoted_plan(client, farm["id"])
    _enter_offer(client, quote["id"], expect=422, financed_amount=2500.0)
    _enter_offer(client, quote["id"], expect=422, total_repayment=2900.0)


def test_decisions_are_one_shot(client):
    farm = _farm(client)
    plan, quote = _quoted_plan(client, farm["id"])
    offer = _enter_offer(client, quote["id"])
    assert client.post(
        f"/financing-offers/{offer['id']}/decision", json={"action": "selected"}
    ).status_code == 200
    for action in ("selected", "declined"):
        resp = client.post(
            f"/financing-offers/{offer['id']}/decision", json={"action": action}
        )
        assert resp.status_code == 409


def test_only_one_selected_offer_per_plan(client):
    farm = _farm(client)
    plan, quote = _quoted_plan(client, farm["id"])
    first = _enter_offer(client, quote["id"])
    second = _enter_offer(client, quote["id"], provider_name="Other Lender")
    client.post(f"/financing-offers/{first['id']}/decision", json={"action": "selected"})
    resp = client.post(
        f"/financing-offers/{second['id']}/decision", json={"action": "selected"}
    )
    assert resp.status_code == 409
    assert "already selected" in resp.json()["detail"]


def test_expired_offer_cannot_be_selected(client):
    farm = _farm(client)
    plan, quote = _quoted_plan(client, farm["id"])
    offer = _enter_offer(client, quote["id"], expires_on="2026-07-10")
    assert offer["offer_state"] == "expired"
    resp = client.post(
        f"/financing-offers/{offer['id']}/decision", json={"action": "selected"}
    )
    assert resp.status_code == 409
    assert _financing_state(client, plan["id"]) == "offer_declined_or_expired"


def test_disclaimer_ships_with_every_offer_payload(client):
    farm = _farm(client)
    plan, quote = _quoted_plan(client, farm["id"])
    _enter_offer(client, quote["id"])
    detail = client.get(f"/input-plans/{plan['id']}").json()
    offers = [o for q in detail["quotes"] for o in q["financing_offers"]]
    assert offers and all("Not a credit decision" in o["disclaimer"] for o in offers)


def test_offer_decisions_are_audited_on_the_plan_timeline(client):
    farm = _farm(client)
    plan, quote = _quoted_plan(client, farm["id"])
    first = _enter_offer(client, quote["id"])
    second = _enter_offer(client, quote["id"], provider_name="Other Lender")
    client.post(f"/financing-offers/{first['id']}/decision", json={
        "action": "declined", "actor": "Test grower",
    })
    client.post(f"/financing-offers/{second['id']}/decision", json={
        "action": "selected", "actor": "Test grower",
    })
    events = client.get(f"/input-plans/{plan['id']}").json()["events"]
    types = [e["event_type"] for e in events]
    assert "financing_offer_declined" in types
    assert "financing_offer_selected" in types
    selected = next(
        e for e in events if e["event_type"] == "financing_offer_selected"
    )
    assert selected["payload"]["financing_offer_id"] == second["id"]
    assert selected["payload"]["to_offer_status"] == "selected"
    assert selected["actor"] == "Test grower"
