"""Supplier quotes: concierge entry, derived totals, entry-order neutrality,
selection guards, and the withdraw-and-re-enter correction path."""
import pytest


@pytest.fixture(autouse=True)
def pinned_clock(monkeypatch):
    monkeypatch.setenv("LUMOS_DEMO_TODAY", "2026-07-16")


def _farm(client):
    return client.post("/farms", json={
        "name": "Quotes Farm", "country": "US", "crop_type": "strawberry",
        "expected_harvest_date": "2026-09-01", "greenhouse_area": 20.0,
    }).json()


def _submitted_plan(client, farm_id, **plan_overrides):
    payload = {
        "requested_by": "Test grower",
        "items": [{
            "product_name": "Switch 62.5 WG", "category": "fungicide",
            "quantity": 252.0, "unit": "oz", "needed_by_date": "2026-07-20",
        }],
    }
    payload.update(plan_overrides)
    plan = client.post(f"/farms/{farm_id}/input-plans", json=payload).json()
    resp = client.post(f"/input-plans/{plan['id']}/submit", json={"submitted_by": "G"})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _quote_payload(item_id, supplier="Supplier A", unit_price=15.0, **overrides):
    payload = {
        "supplier_name": supplier,
        "delivery_cost": 40.0,
        "fees": 10.0,
        "payment_terms_cash": "Due on delivery",
        "availability": "in_stock",
        "entered_by": "Concierge",
        "items": [{
            "input_plan_item_id": item_id, "product_name": "Switch 62.5 WG",
            "quantity": 252.0, "unit": "oz", "unit_price": unit_price,
        }],
    }
    payload.update(overrides)
    return payload


def _enter_quote(client, plan, expect=201, **overrides):
    item_id = plan["items"][0]["id"]
    resp = client.post(
        f"/internal/input-plans/{plan['id']}/quotes",
        json=_quote_payload(item_id, **overrides),
    )
    assert resp.status_code == expect, resp.text
    return resp.json()


def test_quote_on_draft_plan_is_rejected(client):
    farm = _farm(client)
    draft = client.post(f"/farms/{farm['id']}/input-plans", json={
        "items": [{
            "product_name": "X", "quantity": 1, "unit": "oz",
            "needed_by_date": "2026-07-20",
        }],
    }).json()
    resp = client.post(
        f"/internal/input-plans/{draft['id']}/quotes",
        json=_quote_payload(draft["items"][0]["id"]),
    )
    assert resp.status_code == 409


def test_first_quote_flips_plan_to_quoted_with_derived_totals(client):
    farm = _farm(client)
    plan = _submitted_plan(client, farm["id"])
    quote = _enter_quote(client, plan, unit_price=15.40)
    assert quote["items_subtotal"] == 3880.80
    assert quote["total_cost"] == 3930.80  # + 40 delivery + 10 fees
    assert quote["items"][0]["line_total"] == 3880.80
    assert quote["quote_state"] == "submitted"
    detail = client.get(f"/input-plans/{plan['id']}").json()
    assert detail["status"] == "quoted"
    assert detail["quote_count"] == 1


def test_quotes_are_returned_in_entry_order_never_ranked(client):
    farm = _farm(client)
    plan = _submitted_plan(client, farm["id"])
    # Entered expensive-first: the list must preserve entry order, not price order.
    _enter_quote(client, plan, supplier="Pricey Ag", unit_price=20.0)
    _enter_quote(client, plan, supplier="Cheap Ag", unit_price=10.0)
    quotes = client.get(f"/input-plans/{plan['id']}/quotes").json()
    assert [q["supplier_name"] for q in quotes] == ["Pricey Ag", "Cheap Ag"]


def test_quote_line_for_foreign_item_is_rejected(client):
    farm = _farm(client)
    plan_a = _submitted_plan(client, farm["id"])
    plan_b = _submitted_plan(client, farm["id"])
    foreign_item = plan_b["items"][0]["id"]
    resp = client.post(
        f"/internal/input-plans/{plan_a['id']}/quotes",
        json=_quote_payload(foreign_item),
    )
    assert resp.status_code == 422


def test_substitution_requires_a_reason(client):
    farm = _farm(client)
    plan = _submitted_plan(client, farm["id"])
    item_id = plan["items"][0]["id"]
    payload = _quote_payload(item_id)
    payload["items"][0]["is_substitution"] = True
    resp = client.post(f"/internal/input-plans/{plan['id']}/quotes", json=payload)
    assert resp.status_code == 422
    payload["items"][0]["substitution_reason"] = "Equivalent generic in stock"
    resp = client.post(f"/internal/input-plans/{plan['id']}/quotes", json=payload)
    assert resp.status_code == 201


def test_select_quote_lifecycle_and_guards(client):
    farm = _farm(client)
    plan = _submitted_plan(client, farm["id"])
    quote_a = _enter_quote(client, plan, supplier="A")
    quote_b = _enter_quote(client, plan, supplier="B")
    resp = client.post(f"/input-plans/{plan['id']}/select-quote", json={
        "supplier_quote_id": quote_a["id"], "selected_by": "G",
        "reason": "Lower total quoted cost",
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "quote_selected"
    quotes = client.get(f"/input-plans/{plan['id']}/quotes").json()
    states = {q["supplier_name"]: q["quote_state"] for q in quotes}
    assert states == {"A": "selected", "B": "not_selected"}
    # Re-selecting (same or sibling) is a conflict — one-shot by design.
    for qid in (quote_a["id"], quote_b["id"]):
        resp = client.post(f"/input-plans/{plan['id']}/select-quote", json={
            "supplier_quote_id": qid, "reason": "Changed my mind",
        })
        assert resp.status_code == 409


def test_selecting_an_expired_quote_is_rejected(client):
    farm = _farm(client)
    plan = _submitted_plan(client, farm["id"])
    quote = _enter_quote(client, plan, expires_on="2026-07-10")  # before the pinned today
    assert quote["quote_state"] == "expired"
    resp = client.post(f"/input-plans/{plan['id']}/select-quote", json={
        "supplier_quote_id": quote["id"], "reason": "Only quote available",
    })
    assert resp.status_code == 409


def test_select_requires_a_quote_on_this_plan(client):
    farm = _farm(client)
    plan_a = _submitted_plan(client, farm["id"])
    plan_b = _submitted_plan(client, farm["id"])
    quote_b = _enter_quote(client, plan_b)
    resp = client.post(f"/input-plans/{plan_a['id']}/select-quote", json={
        "supplier_quote_id": quote_b["id"], "reason": "Wrong plan on purpose",
    })
    assert resp.status_code in (409, 422)  # plan_a not quoted AND foreign quote


def test_withdraw_is_the_only_correction_path(client):
    farm = _farm(client)
    plan = _submitted_plan(client, farm["id"])
    quote = _enter_quote(client, plan)
    resp = client.post(f"/internal/supplier-quotes/{quote['id']}/withdraw")
    assert resp.status_code == 200
    assert resp.json()["status"] == "withdrawn"
    assert resp.json()["quote_state"] == "withdrawn"
    # Withdrawn quotes don't count and can't be withdrawn again or selected.
    detail = client.get(f"/input-plans/{plan['id']}").json()
    assert detail["quote_count"] == 0
    assert client.post(
        f"/internal/supplier-quotes/{quote['id']}/withdraw"
    ).status_code == 409
    resp = client.post(f"/input-plans/{plan['id']}/select-quote", json={
        "supplier_quote_id": quote["id"], "reason": "Trying a withdrawn quote",
    })
    assert resp.status_code == 409
    # A selected quote can't be withdrawn out from under the grower.
    replacement = _enter_quote(client, plan, supplier="Replacement")
    client.post(f"/input-plans/{plan['id']}/select-quote", json={
        "supplier_quote_id": replacement["id"], "reason": "Only live quote left",
    })
    assert client.post(
        f"/internal/supplier-quotes/{replacement['id']}/withdraw"
    ).status_code == 409


def test_demo_quote_on_real_plan_is_rejected(client):
    farm = _farm(client)
    plan = _submitted_plan(client, farm["id"])
    resp = client.post(
        f"/internal/input-plans/{plan['id']}/quotes",
        json=_quote_payload(
            plan["items"][0]["id"],
            data_source="demo", data_confidence="simulated",
        ),
    )
    assert resp.status_code == 409


def test_selection_reason_is_required_stored_and_audited(client):
    farm = _farm(client)
    plan = _submitted_plan(client, farm["id"])
    quote = _enter_quote(client, plan)
    # No reason -> validation error; nothing is selected.
    resp = client.post(f"/input-plans/{plan['id']}/select-quote", json={
        "supplier_quote_id": quote["id"],
    })
    assert resp.status_code == 422
    assert client.get(f"/input-plans/{plan['id']}").json()["status"] == "quoted"
    # With a reason: stored on the plan and captured in the audit timeline.
    resp = client.post(f"/input-plans/{plan['id']}/select-quote", json={
        "supplier_quote_id": quote["id"], "selected_by": "G",
        "reason": "Earlier delivery and product availability",
    })
    assert resp.status_code == 200
    detail = client.get(f"/input-plans/{plan['id']}").json()
    assert detail["selection_reason"] == "Earlier delivery and product availability"
    selected = [
        e for e in detail["events"] if e["event_type"] == "quote_selected"
    ]
    assert len(selected) == 1
    assert selected[0]["payload"]["reason"] == (
        "Earlier delivery and product availability"
    )
    assert selected[0]["payload"]["from_status"] == "quoted"
    assert selected[0]["payload"]["to_status"] == "quote_selected"
