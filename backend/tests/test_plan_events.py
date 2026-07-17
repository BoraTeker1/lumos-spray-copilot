"""Input-plan audit timeline (append-only), procurement eligibility negatives,
derived overdue state, and chain navigability (decision <-> plan <-> order <->
application)."""
import pytest

from datetime import date

from app import procurement_status


@pytest.fixture(autouse=True)
def pinned_clock(monkeypatch):
    monkeypatch.setenv("LUMOS_DEMO_TODAY", "2026-07-16")


def _farm(client, harvest="2026-09-01"):
    return client.post("/farms", json={
        "name": "Plan Events Farm", "country": "US", "crop_type": "strawberry",
        "expected_harvest_date": harvest, "greenhouse_area": 20.0,
    }).json()


def _plan(client, farm_id, needed_by="2026-07-20", **overrides):
    payload = {
        "requested_by": "Test grower",
        "items": [{
            "product_name": "Switch 62.5 WG", "category": "fungicide",
            "quantity": 252.0, "unit": "oz", "needed_by_date": needed_by,
        }],
    }
    payload.update(overrides)
    return client.post(f"/farms/{farm_id}/input-plans", json=payload).json()


def _quote(client, plan, **overrides):
    payload = {
        "supplier_name": "Supplier A",
        "delivery_cost": 40.0,
        "items": [{
            "input_plan_item_id": plan["items"][0]["id"],
            "product_name": "Switch 62.5 WG",
            "quantity": 252.0, "unit": "oz", "unit_price": 15.0,
        }],
    }
    payload.update(overrides)
    resp = client.post(f"/internal/input-plans/{plan['id']}/quotes", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _select(client, plan_id, quote_id, reason="Lower total quoted cost"):
    resp = client.post(f"/input-plans/{plan_id}/select-quote", json={
        "supplier_quote_id": quote_id, "selected_by": "Test grower",
        "reason": reason,
    })
    assert resp.status_code == 200, resp.text
    return resp.json()


# ------------------------------------------------------------ audit timeline
def test_every_user_decision_appends_a_plan_event(client):
    farm = _farm(client)
    plan = _plan(client, farm["id"])
    client.post(f"/input-plans/{plan['id']}/submit", json={"submitted_by": "G"})
    quote = _quote(client, plan)
    _select(client, plan["id"], quote["id"])
    client.post(f"/input-plans/{plan['id']}/order", json={"placed_by": "G"})
    events = client.get(f"/input-plans/{plan['id']}").json()["events"]
    assert [e["event_type"] for e in events] == [
        "submitted", "quote_selected", "ordered",
    ]
    # Every event carries prior and resulting state.
    assert events[0]["payload"]["from_status"] == "draft"
    assert events[0]["payload"]["to_status"] == "submitted_for_quotes"
    assert events[2]["payload"]["from_status"] == "quote_selected"
    assert events[2]["payload"]["to_status"] == "ordered"
    assert events[2]["payload"]["purchase_order_id"] is not None


def test_cancellation_is_audited(client):
    farm = _farm(client)
    plan = _plan(client, farm["id"])
    client.post(f"/input-plans/{plan['id']}/submit", json={})
    resp = client.post(f"/input-plans/{plan['id']}/cancel", json={
        "reason": "Grower changed strategy", "actor": "Test grower",
    })
    assert resp.status_code == 200
    events = client.get(f"/input-plans/{plan['id']}").json()["events"]
    cancelled = [e for e in events if e["event_type"] == "cancelled"]
    assert len(cancelled) == 1
    assert cancelled[0]["payload"]["reason"] == "Grower changed strategy"
    assert cancelled[0]["actor"] == "Test grower"


def test_plan_events_have_no_mutation_surface(client):
    """No route exists to edit or delete a plan event — append-only by construction."""
    farm = _farm(client)
    plan = _plan(client, farm["id"])
    client.post(f"/input-plans/{plan['id']}/submit", json={})
    events = client.get(f"/input-plans/{plan['id']}").json()["events"]
    event_id = events[0]["id"]
    for method, url in [
        ("POST", f"/input-plans/{plan['id']}/events"),
        ("PATCH", f"/input-plans/{plan['id']}/events/{event_id}"),
        ("PUT", f"/input-plans/{plan['id']}/events/{event_id}"),
        ("DELETE", f"/input-plans/{plan['id']}/events/{event_id}"),
    ]:
        resp = client.request(method, url, json={})
        assert resp.status_code in (404, 405), f"{method} {url} -> {resp.status_code}"
    assert client.get(f"/input-plans/{plan['id']}").json()["events"] == events


# ----------------------------------------------- eligibility: blocked product
def test_blocked_original_product_cannot_be_procured(client):
    """The blocked Captan itself must never become purchasable; the PCA-reviewed
    replacement can."""
    farm = _farm(client, harvest="2026-07-18")  # 2 days out
    planned = client.post(f"/farms/{farm['id']}/planned-sprays", json={
        "intended_date": "2026-07-16", "product_name": "Captan 80 WDG",
        "active_ingredient": "captan",
        "pre_harvest_interval_days": 4, "re_entry_interval_hours": 24,
        "values_source": "pca_entered", "values_entered_by": "Test PCA",
    }).json()
    assert planned["decision_outcome"] == "block"
    assert planned["procurement_eligible"] is False
    # Blocked + unreviewed: the decision cannot back a purchasable item.
    resp = client.post(f"/farms/{farm['id']}/input-plans", json={
        "items": [{
            "planned_spray_id": planned["id"],
            "product_name": "Captan 80 WDG", "quantity": 10, "unit": "lb",
            "needed_by_date": "2026-07-20",
        }],
    })
    assert resp.status_code == 409
    # PCA rejection keeps it ineligible.
    client.patch(f"/planned-sprays/{planned['id']}/review", json={
        "action": "rejected", "reviewed_by": "Test PCA",
        "comment": "Do not apply captan this close to harvest.",
    })
    resp = client.post(f"/farms/{farm['id']}/input-plans", json={
        "items": [{
            "planned_spray_id": planned["id"],
            "product_name": "Captan 80 WDG", "quantity": 10, "unit": "lb",
            "needed_by_date": "2026-07-20",
        }],
    })
    assert resp.status_code == 409


def test_pca_edited_replacement_can_be_procured(client):
    """After the PCA edits the guidance and the changed product is recorded,
    procurement for the REPLACEMENT product is eligible."""
    farm = _farm(client, harvest="2026-07-18")
    planned = client.post(f"/farms/{farm['id']}/planned-sprays", json={
        "intended_date": "2026-07-16", "product_name": "Captan 80 WDG",
        "active_ingredient": "captan",
        "pre_harvest_interval_days": 4, "re_entry_interval_hours": 24,
        "values_source": "pca_entered", "values_entered_by": "Test PCA",
    }).json()
    assert planned["decision_outcome"] == "block"
    client.patch(f"/planned-sprays/{planned['id']}/review", json={
        "action": "edited", "reviewed_by": "Test PCA",
        "comment": "Switch to a PHI-0 alternative.",
        "pca_next_action": "Apply Switch 62.5 WG instead.",
    })
    outcome = client.patch(f"/planned-sprays/{planned['id']}/outcome", json={
        "outcome": "changed_product",
        "outcome_reason": "Followed the PCA's edited guidance.",
        "outcome_product_name": "Switch 62.5 WG",
        "outcome_active_ingredient": "cyprodinil + fludioxonil",
    })
    assert outcome.status_code == 200, outcome.text
    resp = client.post(f"/farms/{farm['id']}/input-plans", json={
        "items": [{
            "planned_spray_id": planned["id"],
            "product_name": "Switch 62.5 WG", "category": "fungicide",
            "quantity": 252.0, "unit": "oz", "needed_by_date": "2026-07-20",
        }],
    })
    assert resp.status_code == 201, resp.text
    item = resp.json()["items"][0]
    assert item["product_name"] == "Switch 62.5 WG"
    assert item["source_decision_procurement_eligible"] is True


# ------------------------------------------------------------------- overdue
def test_procurement_overdue_matrix():
    today = date(2026, 7, 16)
    past, future = date(2026, 7, 10), date(2026, 7, 20)
    f = procurement_status.procurement_overdue
    assert f(None, "submitted_for_quotes", None, today) is False  # no date
    assert f(future, "quoted", None, today) is False              # not yet due
    assert f(past, "quoted", None, today) is True                 # due, no order
    assert f(past, "cancelled", None, today) is False             # plan cancelled
    assert f(past, "ordered", "placed", today) is True            # ordered, not there
    assert f(past, "ordered", "shipped", today) is True
    assert f(past, "ordered", "partially_delivered", today) is True  # not fully there
    assert f(past, "ordered", "delivered", today) is False        # goods arrived
    assert f(past, "ordered", "cancelled", today) is False        # order cancelled
    assert f(today, "quoted", None, today) is False               # due today != overdue


def test_overdue_is_serialized_from_canonical_data(client):
    farm = _farm(client)
    plan = _plan(client, farm["id"], needed_by="2026-07-10")  # already past
    client.post(f"/input-plans/{plan['id']}/submit", json={})
    fetched = client.get(f"/input-plans/{plan['id']}").json()
    assert fetched["needed_by"] == "2026-07-10"
    assert fetched["overdue"] is True
    quote = _quote(client, plan)
    _select(client, plan["id"], quote["id"])
    order = client.post(
        f"/input-plans/{plan['id']}/order", json={"placed_by": "G"}
    ).json()
    assert client.get(f"/orders/{order['id']}").json()["overdue"] is True
    client.post(f"/internal/orders/{order['id']}/events", json={
        "event_type": "delivered", "occurred_on": "2026-07-16",
    })
    # Delivered: no urgency is fabricated for a completed chain.
    assert client.get(f"/orders/{order['id']}").json()["overdue"] is False
    assert client.get(f"/input-plans/{plan['id']}").json()["overdue"] is False


# -------------------------------------------------------------- navigability
def test_decision_exposes_its_procurement_links(client):
    farm = _farm(client)
    planned = client.post(f"/farms/{farm['id']}/planned-sprays", json={
        "intended_date": "2026-07-16", "product_name": "Switch 62.5 WG",
        "pre_harvest_interval_days": 0, "re_entry_interval_hours": 12,
    }).json()
    client.patch(f"/planned-sprays/{planned['id']}/review", json={
        "action": "approved", "reviewed_by": "Test PCA",
    })
    client.patch(f"/planned-sprays/{planned['id']}/outcome", json={
        "outcome": "sprayed_as_planned",
    })
    assert client.get(
        f"/planned-sprays/{planned['id']}"
    ).json()["procurement_links"] == []
    plan = _plan(client, farm["id"], items=[{
        "planned_spray_id": planned["id"], "product_name": "Switch 62.5 WG",
        "category": "fungicide", "quantity": 252.0, "unit": "oz",
        "needed_by_date": "2026-07-20",
    }])
    links = client.get(
        f"/planned-sprays/{planned['id']}"
    ).json()["procurement_links"]
    assert links == [{
        "input_plan_id": plan["id"], "plan_status": "draft",
        "order_id": None, "order_status": None,
    }]
    client.post(f"/input-plans/{plan['id']}/submit", json={})
    quote = _quote(client, plan)
    _select(client, plan["id"], quote["id"])
    order = client.post(
        f"/input-plans/{plan['id']}/order", json={"placed_by": "G"}
    ).json()
    links = client.get(
        f"/planned-sprays/{planned['id']}"
    ).json()["procurement_links"]
    assert links[0]["order_id"] == order["id"]
    assert links[0]["order_status"] == "placed"
    assert links[0]["plan_status"] == "ordered"


def test_application_exposes_its_source_order(client):
    farm = _farm(client)
    planned = client.post(f"/farms/{farm['id']}/planned-sprays", json={
        "intended_date": "2026-07-16", "product_name": "Switch 62.5 WG",
        "pre_harvest_interval_days": 0, "re_entry_interval_hours": 12,
    }).json()
    client.patch(f"/planned-sprays/{planned['id']}/review", json={
        "action": "approved", "reviewed_by": "Test PCA",
    })
    outcome = client.patch(f"/planned-sprays/{planned['id']}/outcome", json={
        "outcome": "sprayed_as_planned",
    }).json()
    spray_event_id = outcome["spray_event_id"]
    plan = _plan(client, farm["id"])
    client.post(f"/input-plans/{plan['id']}/submit", json={})
    quote = _quote(client, plan)
    _select(client, plan["id"], quote["id"])
    order = client.post(
        f"/input-plans/{plan['id']}/order", json={"placed_by": "G"}
    ).json()
    client.post(f"/internal/orders/{order['id']}/events", json={
        "event_type": "delivered", "occurred_on": "2026-07-16",
    })
    # Before the explicit link: no application claims a source order.
    sprays = client.get(f"/farms/{farm['id']}/spray-events").json()
    assert all(s["source_order_id"] is None for s in sprays)
    resp = client.post(f"/orders/{order['id']}/input-applied", json={
        "spray_event_id": spray_event_id,
    })
    assert resp.status_code == 201, resp.text
    sprays = {s["id"]: s for s in client.get(f"/farms/{farm['id']}/spray-events").json()}
    assert sprays[spray_event_id]["source_order_id"] == order["id"]
