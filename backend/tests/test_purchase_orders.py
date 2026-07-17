"""Purchase orders: creation gates, the append-only event timeline, the
transition matrix, and the delivery-is-never-application rule."""
import pytest


@pytest.fixture(autouse=True)
def pinned_clock(monkeypatch):
    monkeypatch.setenv("LUMOS_DEMO_TODAY", "2026-07-16")


def _farm(client):
    return client.post("/farms", json={
        "name": "Orders Farm", "country": "US", "crop_type": "strawberry",
        "expected_harvest_date": "2026-09-01", "greenhouse_area": 20.0,
    }).json()


def _selected_plan(client, farm_id, financing=False, select_offer=False, item=None):
    """Farm -> plan -> submit -> quote -> (optional offer) -> select."""
    plan = client.post(f"/farms/{farm_id}/input-plans", json={
        "requested_by": "Test grower",
        "financing_requested": financing,
        "items": [item or {
            "product_name": "Switch 62.5 WG", "category": "fungicide",
            "quantity": 252.0, "unit": "oz", "needed_by_date": "2026-07-20",
        }],
    }).json()
    client.post(f"/input-plans/{plan['id']}/submit", json={})
    quote = client.post(f"/internal/input-plans/{plan['id']}/quotes", json={
        "supplier_name": "Supplier A",
        "delivery_cost": 40.0,
        "items": [{
            "input_plan_item_id": plan["items"][0]["id"],
            "product_name": "Switch 62.5 WG",
            "quantity": 252.0, "unit": "oz", "unit_price": 15.0,
        }],
    }).json()
    if financing and select_offer:
        offer = client.post(
            f"/internal/supplier-quotes/{quote['id']}/financing-offers",
            json={
                "provider_name": "AgCredit Test", "requested_amount": 3000.0,
                "down_payment": 0.0, "financed_amount": 3000.0,
                "total_repayment": 3150.0,
            },
        ).json()
        client.post(f"/financing-offers/{offer['id']}/decision", json={
            "action": "selected", "actor": "Test grower",
        })
    resp = client.post(f"/input-plans/{plan['id']}/select-quote", json={
        "supplier_quote_id": quote["id"], "selected_by": "Test grower",
        "reason": "Only quote received; price acceptable",
    })
    assert resp.status_code == 200, resp.text
    return resp.json(), quote


def _order(client, plan_id, expect=201):
    resp = client.post(f"/input-plans/{plan_id}/order", json={"placed_by": "Test grower"})
    assert resp.status_code == expect, resp.text
    return resp.json()


def _post_event(client, order_id, event_type, expect=201, occurred_on="2026-07-16"):
    resp = client.post(f"/internal/orders/{order_id}/events", json={
        "event_type": event_type, "occurred_on": occurred_on, "actor": "Concierge",
    })
    assert resp.status_code == expect, resp.text
    return resp.json()


def _event_types(client, order_id):
    return [e["event_type"] for e in client.get(f"/orders/{order_id}/events").json()]


def test_order_requires_a_selected_quote(client):
    farm = _farm(client)
    plan = client.post(f"/farms/{farm['id']}/input-plans", json={
        "items": [{
            "product_name": "X", "quantity": 1, "unit": "oz",
            "needed_by_date": "2026-07-20",
        }],
    }).json()
    _order(client, plan["id"], expect=409)
    client.post(f"/input-plans/{plan['id']}/submit", json={})
    _order(client, plan["id"], expect=409)


def test_order_creation_writes_the_provenance_events(client):
    farm = _farm(client)
    plan, quote = _selected_plan(client, farm["id"])
    order = _order(client, plan["id"])
    assert order["status"] == "placed"
    assert order["supplier_name"] == "Supplier A"
    assert order["total_cost"] == 3820.0  # 252 x 15.0 + 40 delivery
    assert order["accepted_financing_offer_id"] is None
    events = client.get(f"/orders/{order['id']}/events").json()
    assert [e["event_type"] for e in events] == ["created", "quote_selected"]
    assert events[1]["payload"]["supplier_quote_id"] == quote["id"]
    assert events[1]["payload"]["reason"] == "Only quote received; price acceptable"
    # Cash plan: no financing_selected event exists (a request or offer that was
    # never selected must leave no trace of "financing chosen").
    assert "financing_selected" not in [e["event_type"] for e in events]
    # The plan is terminal and can't be cancelled out from under the order.
    detail = client.get(f"/input-plans/{plan['id']}").json()
    assert detail["status"] == "ordered"
    resp = client.post(f"/input-plans/{plan['id']}/cancel", json={"reason": "no"})
    assert resp.status_code == 409
    # One order per plan.
    _order(client, plan["id"], expect=409)


def test_selected_offer_is_pinned_with_a_financing_selected_event(client):
    farm = _farm(client)
    plan, quote = _selected_plan(client, farm["id"], financing=True, select_offer=True)
    order = _order(client, plan["id"])
    assert order["accepted_financing_offer_id"] is not None
    events = client.get(f"/orders/{order['id']}/events").json()
    assert [e["event_type"] for e in events] == [
        "created", "quote_selected", "financing_selected",
    ]
    assert events[2]["payload"]["financed_amount"] == 3000.0


def test_order_event_transition_matrix(client):
    farm = _farm(client)
    plan, _ = _selected_plan(client, farm["id"])
    order = _order(client, plan["id"])
    oid = order["id"]
    # created/quote_selected/financing_selected are never postable (422 vocabulary).
    for internal_only in ("created", "quote_selected", "financing_selected",
                          "input_applied"):
        _post_event(client, oid, internal_only, expect=422)
    _post_event(client, oid, "supplier_confirmed")
    _post_event(client, oid, "supplier_confirmed", expect=409)  # duplicate
    _post_event(client, oid, "shipped")
    _post_event(client, oid, "exception_reported")  # never changes status
    assert client.get(f"/orders/{oid}").json()["status"] == "shipped"
    _post_event(client, oid, "partially_delivered")
    _post_event(client, oid, "delivered")  # partial -> full delivery is legal
    _post_event(client, oid, "delivered", expect=409)  # duplicate delivered
    _post_event(client, oid, "shipped", expect=409)  # backwards
    _post_event(client, oid, "cancelled", expect=409)  # cancel after delivery
    assert client.get(f"/orders/{oid}").json()["status"] == "delivered"


def test_order_events_are_append_only(client):
    farm = _farm(client)
    plan, _ = _selected_plan(client, farm["id"])
    order = _order(client, plan["id"])
    before = client.get(f"/orders/{order['id']}/events").json()
    event_id = before[0]["id"]
    for method, url in [
        ("PATCH", f"/orders/{order['id']}/events/{event_id}"),
        ("PUT", f"/orders/{order['id']}/events/{event_id}"),
        ("DELETE", f"/orders/{order['id']}/events/{event_id}"),
        ("PATCH", f"/orders/{order['id']}/events"),
        ("DELETE", f"/orders/{order['id']}/events"),
    ]:
        resp = client.request(method, url, json={})
        assert resp.status_code in (404, 405), f"{method} {url} -> {resp.status_code}"
    assert client.get(f"/orders/{order['id']}/events").json() == before


def test_delivery_never_marks_the_input_as_applied(client):
    farm = _farm(client)
    plan, _ = _selected_plan(client, farm["id"])
    order = _order(client, plan["id"])
    # Before delivery: linking is a conflict.
    resp = client.post(f"/orders/{order['id']}/input-applied", json={
        "spray_event_id": 1,
    })
    assert resp.status_code == 409
    _post_event(client, order["id"], "delivered")
    fetched = client.get(f"/orders/{order['id']}").json()
    assert fetched["status"] == "delivered"
    assert fetched["spray_event_id"] is None
    assert fetched["applied_planned_spray_id"] is None
    assert "input_applied" not in _event_types(client, order["id"])


def test_input_applied_links_the_real_application(client):
    farm = _farm(client)
    # An approved decision applied as planned -> the linked SprayEvent exists.
    planned = client.post(f"/farms/{farm['id']}/planned-sprays", json={
        "intended_date": "2026-07-16", "product_name": "Switch 62.5 WG",
        "pre_harvest_interval_days": 0, "re_entry_interval_hours": 12,
    }).json()
    client.patch(f"/planned-sprays/{planned['id']}/review", json={
        "action": "approved", "reviewed_by": "Test PCA",
    })
    outcome = client.patch(f"/planned-sprays/{planned['id']}/outcome", json={
        "outcome": "sprayed_as_planned",
    })
    assert outcome.status_code == 200, outcome.text
    spray_event_id = outcome.json()["spray_event_id"]
    plan, _ = _selected_plan(client, farm["id"], item={
        "planned_spray_id": planned["id"], "product_name": "Switch 62.5 WG",
        "category": "fungicide", "quantity": 252.0, "unit": "oz",
        "needed_by_date": "2026-07-20",
    })
    order = _order(client, plan["id"])
    _post_event(client, order["id"], "delivered")
    resp = client.post(f"/orders/{order['id']}/input-applied", json={
        "planned_spray_id": planned["id"], "actor": "Test grower",
    })
    assert resp.status_code == 201, resp.text
    fetched = client.get(f"/orders/{order['id']}").json()
    assert fetched["applied_planned_spray_id"] == planned["id"]
    assert fetched["spray_event_id"] == spray_event_id
    assert fetched["status"] == "delivered"  # input_applied never changes status
    assert _event_types(client, order["id"])[-1] == "input_applied"
    # A second link is a conflict, not a silent overwrite.
    resp = client.post(f"/orders/{order['id']}/input-applied", json={
        "spray_event_id": spray_event_id,
    })
    assert resp.status_code == 409


def test_input_applied_reference_validation(client):
    farm = _farm(client)
    other_farm = _farm(client)
    plan, _ = _selected_plan(client, farm["id"])
    order = _order(client, plan["id"])
    _post_event(client, order["id"], "delivered")
    # Exactly one reference (both / neither -> 422 from the schema).
    for body in ({}, {"spray_event_id": 1, "planned_spray_id": 1}):
        resp = client.post(f"/orders/{order['id']}/input-applied", json=body)
        assert resp.status_code == 422
    # Cross-farm spray event.
    other_spray = client.post(f"/farms/{other_farm['id']}/spray-events", json={
        "product_name": "X", "application_date": "2026-07-16",
    }).json()
    resp = client.post(f"/orders/{order['id']}/input-applied", json={
        "spray_event_id": other_spray["id"],
    })
    assert resp.status_code == 422
    # A decision without an applied outcome can't be "what was applied".
    open_decision = client.post(f"/farms/{farm['id']}/planned-sprays", json={
        "intended_date": "2026-07-16", "product_name": "Y",
    }).json()
    resp = client.post(f"/orders/{order['id']}/input-applied", json={
        "planned_spray_id": open_decision["id"],
    })
    assert resp.status_code == 422
