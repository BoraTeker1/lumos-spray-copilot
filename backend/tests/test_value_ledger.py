"""The value ledger: recommendation → action → outcome → attributable value.

The tests that matter most here are the ones asserting a number does NOT appear.
A ledger that finds value everywhere is worthless — the whole claim is that Lumos
attributes money only where a documented baseline exists, so "a deferral is worth
nothing yet" and "an avoidance with no entered cost is not calculated" are the load-
bearing behaviours.
"""
from datetime import date, timedelta

import pytest

from app import value_ledger


def _farm(client, name="Ledger Farm"):
    res = client.post("/farms", json={
        "name": name, "country": "US", "crop_type": "strawberry", "area_unit": "acres",
        "expected_harvest_date": (date.today() + timedelta(days=60)).isoformat(),
        "planting_date": (date.today() - timedelta(days=60)).isoformat(),
    })
    assert res.status_code == 201, res.text
    return res.json()


def _cycle(client, farm_id, **overrides):
    """A season. `field_id` is omitted on purpose — the farm has no field entities,
    and resolving a whole-farm one is what lets a grower start a season in one step."""
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
        "intended_date": (date.today() + timedelta(days=2)).isoformat(),
        "product_name": "PyGanic EC 5.0",
        "active_ingredient": "pyrethrins",
        "target_pest_or_disease": "lygus_bug",
        "estimated_cost": 95.0,
    }
    payload.update(overrides)
    res = client.post(f"/farms/{farm_id}/planned-sprays", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def _review(client, planned_id, action="approved", **extra):
    payload = {"action": action, "reviewed_by": "Dana PCA"}
    payload.update(extra)
    res = client.patch(f"/planned-sprays/{planned_id}/review", json=payload)
    assert res.status_code == 200, res.text
    return res.json()


def _outcome(client, planned_id, outcome, reason="recorded by the test", **extra):
    payload = {"outcome": outcome, "outcome_reason": reason}
    if outcome in ("sprayed_as_planned", "changed_product"):
        # An applied outcome cannot predate the plan it records.
        payload.setdefault("outcome_date", (date.today() + timedelta(days=3)).isoformat())
    if outcome == "changed_product":
        payload.setdefault("outcome_product_name", "Entrust SC")
    payload.update(extra)
    res = client.patch(f"/planned-sprays/{planned_id}/outcome", json=payload)
    assert res.status_code == 200, res.text
    return res.json()


def _follow_up(client, planned_id, event_type="scouting_observation", **overrides):
    payload = {
        "event_type": event_type,
        "observed_at": date.today().isoformat(),
        "entered_by": "Grower",
    }
    # The follow-up schema requires the fields that make each event type meaningful.
    if event_type == "scouting_observation":
        payload.setdefault("severity", 1)
        payload.setdefault("severity_scale", "lygus_per_20_sweeps")
    if event_type in ("actual_application", "rescue_application"):
        payload.setdefault("actual_product", "Entrust SC")
    payload.update(overrides)
    res = client.post(f"/planned-sprays/{planned_id}/follow-up-events", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def _ledger(client, farm_id, crop_cycle_id=None):
    url = f"/farms/{farm_id}/value-ledger"
    if crop_cycle_id is not None:
        url += f"?crop_cycle_id={crop_cycle_id}"
    res = client.get(url)
    assert res.status_code == 200, res.text
    return res.json()


def _item(ledger, kind, reference_id):
    for item in ledger["items"]:
        if item["kind"] == kind and item["reference_id"] == reference_id:
            return item
    raise AssertionError(f"no {kind} item #{reference_id} in {ledger['items']}")


# ------------------------------------------------------------------ crop cycles
def test_a_crop_cycle_is_creatable_and_closeable(client):
    farm = _farm(client)
    cycle = _cycle(client, farm["id"])
    assert cycle["status"] == "growing"
    # Area is converted to the canonical unit rather than stored only as typed.
    assert cycle["planted_area_m2"] == pytest.approx(18.0 * 4046.8564224)

    closed = client.patch(f"/crop-cycles/{cycle['id']}", json={
        "status": "closed", "actual_harvest_end": date.today().isoformat(),
    })
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "closed"


def test_a_new_decision_is_stamped_with_the_open_cycle(client):
    farm = _farm(client)
    cycle = _cycle(client, farm["id"])
    planned = _planned(client, farm["id"])

    ledger = _ledger(client, farm["id"], cycle["id"])
    assert any(i["reference_id"] == planned["id"] for i in ledger["items"])


def test_records_created_before_the_cycle_are_backfilled_into_it(client):
    """A grower who starts a season mid-flight must not see an empty ledger."""
    farm = _farm(client)
    planned = _planned(client, farm["id"])  # exists BEFORE any cycle

    cycle = _cycle(client, farm["id"])
    ledger = _ledger(client, farm["id"], cycle["id"])
    assert any(i["reference_id"] == planned["id"] for i in ledger["items"])


def test_the_backfill_never_moves_a_record_between_seasons(client):
    farm = _farm(client)
    first = _cycle(client, farm["id"])
    planned = _planned(client, farm["id"])
    assert any(
        i["reference_id"] == planned["id"]
        for i in _ledger(client, farm["id"], first["id"])["items"]
    )

    # A second cycle over the same window must not steal the already-attributed row.
    second = _cycle(client, farm["id"], season_year=date.today().year + 1)
    relinked = client.post(f"/crop-cycles/{second['id']}/link-records")
    assert relinked.status_code == 200, relinked.text
    assert relinked.json()["linked"].get("planned_sprays", 0) == 0
    assert any(
        i["reference_id"] == planned["id"]
        for i in _ledger(client, farm["id"], first["id"])["items"]
    )


def test_a_cycle_from_another_farm_is_a_404_on_the_ledger(client):
    farm_a = _farm(client, "Farm A")
    farm_b = _farm(client, "Farm B")
    cycle = _cycle(client, farm_a["id"])
    res = client.get(f"/farms/{farm_b['id']}/value-ledger?crop_cycle_id={cycle['id']}")
    assert res.status_code == 404


# ----------------------------------------------------------- avoided application
def test_an_avoidance_with_follow_up_evidence_is_verified_value(client):
    farm = _farm(client)
    planned = _planned(client, farm["id"])
    _review(client, planned["id"])
    _outcome(client, planned["id"], "avoided", "threshold not met on re-scout")
    _follow_up(client, planned["id"], severity=1, severity_scale="lygus_per_20_sweeps")

    ledger = _ledger(client, farm["id"])
    item = _item(ledger, "decision", planned["id"])
    assert item["tier"] == value_ledger.TIER_VERIFIED
    assert item["amount"] == 95.0
    assert item["source"] == value_ledger.SOURCE_AVOIDED_APPLICATION
    assert ledger["verified"]["total"] == 95.0
    # The arithmetic is legible from the payload alone.
    assert "95.00 planned application cost" in item["basis"]
    assert any("follow_up_event" in ref for ref in item["evidence"])


def test_an_avoidance_without_follow_up_is_estimated_not_verified(client):
    farm = _farm(client)
    planned = _planned(client, farm["id"])
    _review(client, planned["id"])
    _outcome(client, planned["id"], "avoided")

    ledger = _ledger(client, farm["id"])
    item = _item(ledger, "decision", planned["id"])
    assert item["tier"] == value_ledger.TIER_ESTIMATED
    assert item["amount"] == 95.0
    assert ledger["estimated"]["total"] == 95.0
    assert ledger["verified"]["total"] == 0


def test_verified_and_estimated_totals_are_never_summed_together(client):
    farm = _farm(client)
    confirmed = _planned(client, farm["id"])
    _review(client, confirmed["id"])
    _outcome(client, confirmed["id"], "avoided")
    _follow_up(client, confirmed["id"])

    unconfirmed = _planned(client, farm["id"], product_name="Entrust SC",
                           estimated_cost=140.0)
    _review(client, unconfirmed["id"])
    _outcome(client, unconfirmed["id"], "avoided")

    ledger = _ledger(client, farm["id"])
    assert ledger["verified"]["total"] == 95.0
    assert ledger["estimated"]["total"] == 140.0
    assert "total" not in ledger  # there is deliberately no combined figure


def test_follow_up_scouting_cost_is_netted_off_the_avoidance(client):
    """An avoidance that needed three extra scouting passes did not save the sticker price."""
    farm = _farm(client)
    planned = _planned(client, farm["id"])
    _review(client, planned["id"])
    _outcome(client, planned["id"], "avoided")
    _follow_up(client, planned["id"], cost=35.0)

    item = _item(_ledger(client, farm["id"]), "decision", planned["id"])
    assert item["amount"] == 60.0
    assert "less 35.00" in item["basis"]


def test_an_avoidance_with_no_entered_cost_is_not_calculated(client):
    farm = _farm(client)
    planned = _planned(client, farm["id"], estimated_cost=None)
    _review(client, planned["id"])
    _outcome(client, planned["id"], "avoided")

    item = _item(_ledger(client, farm["id"]), "decision", planned["id"])
    assert item["tier"] == value_ledger.TIER_NOT_CALCULATED
    # The key is OMITTED, not nulled — a null in a numeric slot becomes 0 in a template.
    assert "amount" not in item
    assert "no documented baseline" in item["not_calculated_reason"]


def test_an_application_recorded_after_an_avoidance_withdraws_the_value(client):
    farm = _farm(client)
    planned = _planned(client, farm["id"])
    _review(client, planned["id"])
    _outcome(client, planned["id"], "avoided")
    _follow_up(client, planned["id"], event_type="rescue_application", cost=180.0)

    item = _item(_ledger(client, farm["id"]), "decision", planned["id"])
    assert item["tier"] == value_ledger.TIER_NOT_CALCULATED
    assert "not in fact avoided" in item["not_calculated_reason"]
    assert _ledger(client, farm["id"])["verified"]["total"] == 0


# ------------------------------------------------------- deferrals are not money
@pytest.mark.parametrize("outcome", ["delayed", "inspected_first"])
def test_a_deferral_is_recorded_and_never_valued(client, outcome):
    """The rule that keeps the ledger honest: no rescue is not a saving."""
    farm = _farm(client)
    planned = _planned(client, farm["id"])
    _review(client, planned["id"])
    _outcome(client, planned["id"], outcome)
    _follow_up(client, planned["id"])

    item = _item(_ledger(client, farm["id"]), "decision", planned["id"])
    assert item["tier"] == value_ledger.TIER_NOT_CALCULATED
    assert item["action"] == outcome
    assert "not valued" in item["not_calculated_reason"]
    ledger = _ledger(client, farm["id"])
    assert ledger["verified"]["total"] == 0
    assert ledger["estimated"]["total"] == 0


def test_a_spray_that_went_ahead_carries_no_value(client):
    farm = _farm(client)
    planned = _planned(client, farm["id"])
    _review(client, planned["id"])
    _outcome(client, planned["id"], "sprayed_as_planned")

    item = _item(_ledger(client, farm["id"]), "decision", planned["id"])
    assert item["tier"] == value_ledger.TIER_NOT_CALCULATED
    assert "went ahead as planned" in item["not_calculated_reason"]


def test_a_changed_product_shows_its_delta_but_counts_no_value(client):
    farm = _farm(client)
    planned = _planned(client, farm["id"])
    _review(client, planned["id"], action="edited",
            pca_next_action="Use a different chemistry this week.")
    _outcome(client, planned["id"], "changed_product",
             reason="PCA recommended a different chemistry")
    _follow_up(client, planned["id"], event_type="actual_application", cost=70.0)

    item = _item(_ledger(client, farm["id"]), "decision", planned["id"])
    assert item["tier"] == value_ledger.TIER_NOT_CALCULATED
    assert item["informational"]["delta"] == 25.0
    assert _ledger(client, farm["id"])["verified"]["total"] == 0


# --------------------------------------------------------------- season roll-up
def test_season_costs_exclude_records_with_no_cost_rather_than_zeroing_them(client):
    farm = _farm(client)
    cycle = _cycle(client, farm["id"])

    for cost in (120.0, None):
        res = client.post(f"/farms/{farm['id']}/spray-events", json={
            "product_name": "Captan 80 WDG", "active_ingredient": "captan",
            "application_date": date.today().isoformat(), "cost": cost,
        })
        assert res.status_code == 201, res.text

    op = client.post(f"/crop-cycles/{cycle['id']}/operations", json={
        "operation_type": "fertilization", "cost_amount": 1450.0,
        "performed_on": date.today().isoformat(),
    })
    assert op.status_code == 201, op.text

    costs = _ledger(client, farm["id"], cycle["id"])["season_costs"]
    assert costs["total"] == 1570.0
    assert costs["applications_without_cost"] == 1
    assert costs["operations_by_type"] == {"fertilization": 1450.0}


def test_harvest_outcomes_are_grouped_by_unit_and_never_converted(client):
    farm = _farm(client)
    cycle = _cycle(client, farm["id"])
    block = client.post(f"/farms/{farm['id']}/blocks", json={
        "name": "North 1", "crop": "strawberry",
    }).json()

    res = client.post(f"/farms/{farm['id']}/block-outcomes", json={
        "block_id": block["id"], "observed_on": date.today().isoformat(),
        "outcome_type": "marketable_packout", "value": 87.5, "unit": "pct",
    })
    assert res.status_code == 201, res.text

    outcomes = _ledger(client, farm["id"], cycle["id"])["season_outcomes"]
    assert outcomes == [{
        "outcome_type": "marketable_packout", "unit": "pct", "total": 87.5,
        "observations": 1, "without_value": 0,
    }]


# ------------------------------------------------------------ decision economics
def test_decision_economics_costs_each_choice_from_recorded_figures(client):
    farm = _farm(client)
    planned = _planned(client, farm["id"])

    res = client.get(f"/planned-sprays/{planned['id']}/economics")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["available"] is True
    by_choice = {s["choice"]: s for s in body["scenarios"]}
    assert by_choice["apply"]["direct_cost"] == 95.0
    assert by_choice["avoid"]["direct_cost"] == 0.0
    # A delay is explicitly NOT a saving.
    assert "deferred rather than avoided" in by_choice["delay"]["note"]
    # No probability, no expected value, anywhere in the payload.
    assert not any(
        key in body for key in ("probability", "expected_value", "rescue_rate")
    )


def test_decision_economics_abstains_without_a_recorded_cost(client):
    farm = _farm(client)
    planned = _planned(client, farm["id"], estimated_cost=None)
    body = client.get(f"/planned-sprays/{planned['id']}/economics").json()
    assert body["available"] is False
    assert "scenarios" not in body


def test_economics_is_a_separate_route_and_the_decision_payload_is_untouched(client):
    """Blinding: the shadow study depends on the PCA-facing payload not growing."""
    farm = _farm(client)
    planned = _planned(client, farm["id"])
    detail = client.get(f"/planned-sprays/{planned['id']}").json()
    for key in ("economics", "scenarios", "value", "direct_cost"):
        assert key not in detail


# ------------------------------------------------------------------- invariants
def test_a_tiered_item_must_carry_an_amount():
    with pytest.raises(ValueError, match="must appear together"):
        value_ledger.ValueItem(
            kind="decision", reference_id=1, label="x",
            tier=value_ledger.TIER_VERIFIED, amount=None,
        )


def test_a_not_calculated_item_must_say_why():
    with pytest.raises(ValueError, match="must carry a"):
        value_ledger.ValueItem(kind="decision", reference_id=1, label="x")
