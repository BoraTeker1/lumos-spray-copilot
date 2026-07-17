"""Seeded procurement demo: deterministic reseeding, demo/real evidence
separation, the demo-reset guard, and the no-savings-claim rule."""
import json

import pytest

from app import seed


@pytest.fixture()
def pinned_clock(monkeypatch):
    monkeypatch.setenv("LUMOS_DEMO_TODAY", "2026-07-16")


def _procurement_snapshot(client, farm_id):
    plans = client.get(f"/farms/{farm_id}/input-plans").json()
    orders = client.get(f"/farms/{farm_id}/orders").json()
    events = [
        client.get(f"/orders/{o['id']}/events").json() for o in orders
    ]
    details = [client.get(f"/input-plans/{p['id']}").json() for p in plans]
    return json.dumps(
        {"plans": plans, "details": details, "orders": orders, "events": events},
        sort_keys=True,
    )


def _all_keys(node, out):
    if isinstance(node, dict):
        for k, v in node.items():
            out.add(k)
            _all_keys(v, out)
    elif isinstance(node, list):
        for v in node:
            _all_keys(v, out)


def test_reseeding_procurement_under_pinned_clock_is_byte_identical(
    client, pinned_clock
):
    seed.run()
    first = _procurement_snapshot(client, 3)
    seed.run()
    assert _procurement_snapshot(client, 3) == first


def test_seeded_procurement_chain_is_fully_demo_and_consistent(client, pinned_clock):
    seed.run()
    plans = client.get("/farms/3/input-plans").json()
    assert len(plans) == 1
    plan = client.get(f"/input-plans/{plans[0]['id']}").json()
    assert plan["data_source"] == "demo" and plan["data_confidence"] == "simulated"
    assert plan["status"] == "ordered"
    assert plan["financing_state"] == "offer_selected"
    for item in plan["items"]:
        assert item["data_confidence"] == "simulated"
        # The seeded item is backed by the PCA-edited scenario-1 decision.
        assert item["source_decision_review_state"] == "edited"
        assert item["source_decision_procurement_eligible"] is True
    assert {q["data_confidence"] for q in plan["quotes"]} == {"simulated"}
    # Two materially different quotes: one cash-only, one carrying the offer.
    offers = [o for q in plan["quotes"] for o in q["financing_offers"]]
    assert len(plan["quotes"]) == 2 and len(offers) == 1
    assert offers[0]["status"] == "selected"
    orders = client.get("/farms/3/orders").json()
    assert len(orders) == 1 and orders[0]["data_confidence"] == "simulated"
    assert orders[0]["status"] == "delivered"
    # The loop closes: order -> decision -> actual application.
    assert orders[0]["applied_planned_spray_id"] is not None
    assert orders[0]["spray_event_id"] is not None
    events = client.get(f"/orders/{orders[0]['id']}/events").json()
    assert [e["event_type"] for e in events] == [
        "created", "quote_selected", "financing_selected", "supplier_confirmed",
        "shipped", "delivered", "input_applied",
    ]


def test_demo_orders_are_excluded_from_the_evidence_export(client, pinned_clock):
    seed.run()
    export = client.get("/farms/3/evidence-export").json()
    assert export["input_orders"]["plans_exported"] == 0
    assert export["input_orders"]["plans"] == []
    # A real chain on a fresh farm IS exported — with limitations, no savings.
    farm = client.post("/farms", json={
        "name": "Real Farm", "country": "US", "crop_type": "strawberry",
    }).json()
    plan = client.post(f"/farms/{farm['id']}/input-plans", json={
        "items": [{
            "product_name": "Switch 62.5 WG", "quantity": 10, "unit": "oz",
            "needed_by_date": "2026-07-20",
        }],
    }).json()
    client.post(f"/input-plans/{plan['id']}/submit", json={})
    export = client.get(f"/farms/{farm['id']}/evidence-export").json()
    assert export["input_orders"]["plans_exported"] == 1
    exported_plan = export["input_orders"]["plans"][0]
    assert exported_plan["status"] == "submitted_for_quotes"
    assert any("concierge-entered" in l for l in export["input_orders"]["limitations"])
    # The procurement block computes NO savings figure of any kind. (The decision
    # evidence block reports its own honestly-labelled *unconfirmed* estimates —
    # the procurement chain must never grow one.)
    keys = set()
    _all_keys(export["input_orders"], keys)
    assert not any("saving" in k.lower() for k in keys), keys


def test_demo_reset_refuses_once_real_procurement_exists(client, pinned_clock):
    seed.run()
    assert client.post("/internal/demo/reset").status_code == 200
    # A single REAL input plan on the demo farm blocks the reset.
    resp = client.post("/farms/3/input-plans", json={
        "requested_by": "Real grower",
        "items": [{
            "product_name": "Real product", "quantity": 1, "unit": "oz",
            "needed_by_date": "2026-07-20",
        }],
    })
    assert resp.status_code == 201
    assert client.post("/internal/demo/reset").status_code == 409


def _dt(value):
    from datetime import datetime
    return datetime.fromisoformat(value)


def _d(value):
    from datetime import date
    return date.fromisoformat(value)


def test_seeded_chain_has_no_impossible_chronology(client, pinned_clock):
    """Every arrow in the demo story points forward: check -> review -> plan ->
    submit -> quotes -> selection -> offer -> order -> confirmed -> shipped ->
    delivered -> application -> input_applied. Seed drift that breaks any of
    these fails here loudly."""
    seed.run()
    plan = client.get("/input-plans/1").json()
    decision = client.get(
        f"/planned-sprays/{plan['items'][0]['planned_spray_id']}"
    ).json()
    order = client.get(f"/orders/{plan['order_id']}").json()
    events = client.get(f"/orders/{order['id']}/events").json()
    by_type = {e["event_type"]: e for e in events}
    application = next(
        s for s in client.get("/farms/3/spray-events").json()
        if s["id"] == order["spray_event_id"]
    )
    selected_quote = next(
        q for q in plan["quotes"] if q["id"] == plan["selected_quote_id"]
    )

    # Decision precedes procurement.
    assert _dt(decision["created_at"]) <= _dt(decision["reviewed_at"])
    assert _dt(decision["reviewed_at"]) <= _dt(plan["created_at"])
    # Draft precedes submission; quotes come after submission.
    assert _dt(plan["created_at"]) < _dt(plan["submitted_at"])
    for quote in plan["quotes"]:
        assert _dt(plan["submitted_at"]) <= _dt(quote["created_at"])
        # Every quote carries an expiration and was live when entered.
        assert quote["expires_on"] is not None
    # Selection follows the quotes; the offer decision follows its entry.
    plan_events = {e["event_type"]: e for e in plan["events"]}
    assert [e["event_type"] for e in plan["events"]] == [
        "submitted", "quote_selected", "financing_offer_selected", "ordered",
    ]
    assert plan["selection_reason"]
    assert plan_events["quote_selected"]["payload"]["reason"] == (
        plan["selection_reason"]
    )
    assert _dt(selected_quote["created_at"]) <= _dt(
        plan_events["quote_selected"]["created_at"]
    )
    offer = next(
        o for q in plan["quotes"] for o in q["financing_offers"]
    )
    assert _dt(offer["created_at"]) <= _dt(offer["decided_at"])
    assert _dt(offer["decided_at"]) <= _dt(order["created_at"])
    # Order events strictly ordered; delivery precedes the application.
    created_ats = [_dt(e["created_at"]) for e in events]
    assert created_ats == sorted(created_ats)
    assert _d(by_type["delivered"]["occurred_on"]) <= _d(
        application["application_date"]
    )
    assert _d(application["application_date"]) <= _d(
        by_type["input_applied"]["occurred_on"]
    )
    # The selected quote's promise agrees with reality: delivery on-or-before
    # the needed-by date, and the recorded delivery never precedes... the quote
    # never claims a delivery LATER than what actually happened.
    needed_by = _d(plan["items"][0]["needed_by_date"])
    assert _d(selected_quote["expected_delivery_date"]) <= needed_by
    assert _d(selected_quote["expected_delivery_date"]) <= _d(
        by_type["delivered"]["occurred_on"]
    )
    # Nothing in the chain is overdue — the goods arrived.
    assert plan["overdue"] is False
    assert order["overdue"] is False


def test_seeded_item_is_the_replacement_product_never_the_blocked_one(
    client, pinned_clock
):
    seed.run()
    plan = client.get("/input-plans/1").json()
    decision = client.get(
        f"/planned-sprays/{plan['items'][0]['planned_spray_id']}"
    ).json()
    assert decision["decision_outcome"] == "block"
    assert decision["product_name"] == "Captan 80 WDG"  # what was blocked
    for item in plan["items"]:
        assert item["product_name"] == decision["outcome_product_name"]
        assert item["product_name"] == "Switch 62.5 WG"
        assert item["product_name"] != decision["product_name"]
    # And the decision links back to this plan and its order.
    links = decision["procurement_links"]
    assert links and links[0]["input_plan_id"] == plan["id"]
    assert links[0]["order_id"] == plan["order_id"]
    # The applied spray event exposes the source order.
    order = client.get(f"/orders/{plan['order_id']}").json()
    sprays = {s["id"]: s for s in client.get("/farms/3/spray-events").json()}
    assert sprays[order["spray_event_id"]]["source_order_id"] == order["id"]
