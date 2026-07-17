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
    assert plan["financing_state"] == "offer_accepted"
    for item in plan["items"]:
        assert item["data_confidence"] == "simulated"
        # The seeded item is backed by the PCA-edited scenario-1 decision.
        assert item["source_decision_review_state"] == "edited"
        assert item["source_decision_procurement_eligible"] is True
    assert {q["data_confidence"] for q in plan["quotes"]} == {"simulated"}
    # Two materially different quotes: one cash-only, one carrying the offer.
    offers = [o for q in plan["quotes"] for o in q["financing_offers"]]
    assert len(plan["quotes"]) == 2 and len(offers) == 1
    assert offers[0]["status"] == "accepted"
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
