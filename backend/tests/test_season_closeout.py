"""Season economics: what a crop cycle cost, produced, sold for, and was worth.

The load-bearing tests here are again the ones asserting a number does NOT appear.
A closeout that always produces a figure is worse than none at all, because a
per-acre cost built on half the season's invoices reads exactly like a complete one.
So: a yield in trays refuses rather than totalling, a sale in another currency is
excluded rather than converted, and every metric that cannot be computed omits its
`value` key entirely rather than nulling it.
"""
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app import season_closeout, units, value_ledger


# ---------------------------------------------------------------- pure fixtures
def _cycle(**overrides):
    payload = {
        "id": 1,
        "crop": "strawberry",
        "season_year": 2026,
        "season_label": "2026 spring plant",
        "status": "harvesting",
        "planted_area_m2": 18.0 * 4046.8564224,
        "display_area": 18.0,
        "display_area_unit": "acres",
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def _sale(**overrides):
    payload = {
        "id": 1,
        "quantity": 1000.0,
        "unit": "lb",
        "unit_price": 2.0,
        "gross_amount": 2000.0,
        "deductions_amount": None,
        "currency_code": "USD",
        "supersedes_id": None,
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def _outcome(**overrides):
    payload = {
        "id": 1,
        "outcome_type": "yield",
        "value": 1000.0,
        "unit": "lb",
        "supersedes_id": None,
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def _operation(**overrides):
    payload = {
        "cost_amount": 100.0,
        "currency_code": "USD",
        "operation_type": "irrigation",
        "cost_category": "irrigation",
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def _empty_ledger(**overrides):
    payload = {
        "verified": {"total": 0.0, "by_source": {}, "item_count": 0},
        "estimated": {"total": 0.0, "by_source": {}, "item_count": 0},
        "not_calculated_count": 0,
        "currency": "USD",
        "is_simulated": False,
        "record_scope": "real",
    }
    payload.update(overrides)
    return payload


def _build(*, cycle=None, sales=(), sprays=(), operations=(), outcomes=(), scope=None):
    cycle = cycle or _cycle()
    costs = value_ledger._season_costs(list(sprays), list(operations), "USD")
    return season_closeout.build_closeout(
        cycle=cycle,
        farm=SimpleNamespace(id=7, currency_code="USD"),
        sales=list(sales),
        spray_events=list(sprays),
        operations=list(operations),
        block_outcomes=list(outcomes),
        costs=costs,
        ledger=_empty_ledger(),
        scope=scope or {"crop_cycle_id": 1, "records_outside_cycle": {}},
    )


def _gap_codes(payload):
    return {g["code"] for g in payload["completeness"]["gaps"]}


# --------------------------------------------------------------------- revenue
def test_revenue_reports_gross_deductions_and_net_as_three_numbers():
    payload = _build(sales=[
        _sale(id=1, gross_amount=63270.0, deductions_amount=5061.60),
        _sale(id=2, gross_amount=43416.0, deductions_amount=3473.28),
    ])
    revenue = payload["metrics"]["revenue"]
    assert revenue["gross"] == pytest.approx(106686.0)
    assert revenue["deductions"] == pytest.approx(8534.88)
    assert revenue["net"] == pytest.approx(98151.12)
    # Net is never presented as the only figure: what the crop sold for and what the
    # farm received are different facts.
    assert revenue["gross"] != revenue["net"]


def test_a_cycle_with_no_sales_refuses_and_carries_no_value_key():
    payload = _build()
    revenue = payload["metrics"]["revenue"]
    assert revenue["code"] == season_closeout.NO_SALES_RECORDED
    # The whole point: a template cannot render an absent key as a zero.
    assert "value" not in revenue
    assert "gross" not in revenue and "net" not in revenue


def test_a_sale_in_another_currency_is_excluded_and_counted_never_converted():
    payload = _build(sales=[
        _sale(id=1, gross_amount=1000.0),
        _sale(id=2, gross_amount=5000.0, currency_code="TRY"),
    ])
    revenue = payload["metrics"]["revenue"]
    assert revenue["gross"] == pytest.approx(1000.0)
    assert revenue["sales_in_other_currency"] == 1
    assert "sales_in_other_currency" in _gap_codes(payload)


def test_every_sale_in_another_currency_refuses_rather_than_reporting_zero():
    payload = _build(sales=[_sale(id=1, gross_amount=5000.0, currency_code="TRY")])
    revenue = payload["metrics"]["revenue"]
    assert revenue["code"] == season_closeout.NO_REVENUE_IN_CYCLE_CURRENCY
    assert "gross" not in revenue


def test_a_superseded_settlement_is_not_counted_twice():
    payload = _build(sales=[
        _sale(id=1, gross_amount=1000.0),
        _sale(id=2, gross_amount=1200.0, supersedes_id=1),
    ])
    assert payload["metrics"]["revenue"]["gross"] == pytest.approx(1200.0)
    assert payload["metrics"]["revenue"]["sales_counted"] == 1


def test_gross_is_derived_from_quantity_and_price_when_not_stated():
    payload = _build(sales=[_sale(gross_amount=None, quantity=500.0, unit_price=3.0)])
    revenue = payload["metrics"]["revenue"]
    assert revenue["gross"] == pytest.approx(1500.0)
    # And the payload says so, rather than presenting a derivation as a settlement.
    assert revenue["gross_derived_count"] == 1
    assert "derived" in revenue["basis_text"]


# ----------------------------------------------------------------------- yield
def test_yield_normalises_across_compatible_mass_units():
    payload = _build(outcomes=[
        _outcome(id=1, value=1000.0, unit="lb"),
        _outcome(id=2, value=500.0, unit="kg"),
        _outcome(id=3, value=1.0, unit="t"),
    ])
    harvested = payload["metrics"]["harvested_yield"]
    assert harvested["unit"] == "kg"
    assert harvested["value"] == pytest.approx(1000 * 0.45359237 + 500 + 1000, abs=0.01)
    assert harvested["observations"] == 3


def test_yield_in_packaging_units_refuses_rather_than_inventing_a_weight():
    """A tray is packaging, not a unit. No source states its weight, so no total."""
    payload = _build(outcomes=[
        _outcome(id=1, value=1000.0, unit="lb"),
        _outcome(id=2, value=400.0, unit="tray"),
    ])
    harvested = payload["metrics"]["harvested_yield"]
    assert harvested["code"] == season_closeout.INCOMPATIBLE_YIELD_UNITS
    assert "value" not in harvested
    # It names what it could not combine, so the reader knows which records to fix.
    assert harvested["groups"] == [{"unit": "tray", "total": 400.0, "observations": 1}]
    assert harvested["convertible_observations"] == 1
    assert season_closeout.INCOMPATIBLE_YIELD_UNITS in _gap_codes(payload)


def test_a_percentage_outcome_is_never_summed_into_the_yield():
    payload = _build(outcomes=[
        _outcome(id=1, outcome_type="marketable_packout", value=87.5, unit="pct"),
    ])
    # Only `yield` rows count; a packout percentage and a weight do not add.
    assert payload["metrics"]["harvested_yield"]["code"] == season_closeout.NO_YIELD_RECORDED


def test_a_superseded_yield_observation_is_replaced_not_added():
    payload = _build(outcomes=[
        _outcome(id=1, value=1000.0, unit="kg"),
        _outcome(id=2, value=1200.0, unit="kg", supersedes_id=1),
    ])
    assert payload["metrics"]["harvested_yield"]["value"] == pytest.approx(1200.0)


# ------------------------------------------------- revenue minus recorded costs
def test_revenue_minus_recorded_costs_always_carries_its_cost_coverage():
    payload = _build(
        sales=[_sale(gross_amount=10000.0, deductions_amount=1000.0)],
        operations=[_operation(cost_amount=2000.0), _operation(cost_amount=None)],
    )
    metric = payload["metrics"]["revenue_minus_recorded_costs"]
    assert metric["value"] == pytest.approx(9000.0 - 2000.0)
    coverage = metric["cost_coverage"]
    assert coverage["complete"] is False
    assert coverage["operations_without_cost"] == 1
    # And the sentence says outright that the real cost is higher.
    assert "higher than the figure subtracted" in metric["basis_text"]


def test_revenue_minus_recorded_costs_is_never_called_profit():
    payload = _build(
        sales=[_sale(gross_amount=10000.0)],
        operations=[_operation(cost_amount=2000.0)],
    )
    metric = payload["metrics"]["revenue_minus_recorded_costs"]
    assert "This is not profit" in metric["basis_text"]
    assert metric["cost_coverage"]["complete"] is True


def test_revenue_with_no_recorded_cost_refuses_rather_than_subtracting_nothing():
    """Otherwise the whole settlement renders as though the season had been free."""
    payload = _build(sales=[_sale(gross_amount=10000.0)])
    metric = payload["metrics"]["revenue_minus_recorded_costs"]
    assert metric["code"] == season_closeout.NO_COSTS_RECORDED
    assert "value" not in metric


def test_no_revenue_means_no_contribution_figure():
    payload = _build(operations=[_operation(cost_amount=2000.0)])
    metric = payload["metrics"]["revenue_minus_recorded_costs"]
    assert metric["code"] == season_closeout.NO_REVENUE_RECORDED
    assert "value" not in metric


# ------------------------------------------------------------ cost breakdown
def test_costs_break_down_by_category_and_an_application_is_crop_protection():
    payload = _build(
        sprays=[SimpleNamespace(cost=300.0), SimpleNamespace(cost=200.0)],
        operations=[
            _operation(cost_amount=1450.0, cost_category="fertilizer_nutrition"),
            _operation(cost_amount=380.0, cost_category="irrigation"),
        ],
    )
    by_category = payload["metrics"]["costs"]["by_cost_category"]
    assert by_category["crop_protection"] == pytest.approx(500.0)
    assert by_category["fertilizer_nutrition"] == pytest.approx(1450.0)
    assert by_category["irrigation"] == pytest.approx(380.0)
    assert payload["metrics"]["costs"]["total"] == pytest.approx(2330.0)


def test_an_uncategorised_cost_gets_its_own_bucket_not_other():
    """"Nobody classified this" and "the grower called it other" are different facts."""
    payload = _build(operations=[_operation(cost_amount=500.0, cost_category=None)])
    by_category = payload["metrics"]["costs"]["by_cost_category"]
    assert by_category == {value_ledger.COST_CATEGORY_UNCATEGORISED: 500.0}
    assert "other" not in by_category
    assert "operations_uncategorised" in _gap_codes(payload)


# ------------------------------------------------------------ derived rates
def test_per_area_figures_are_reported_in_the_growers_own_unit_and_per_hectare():
    payload = _build(
        outcomes=[_outcome(value=18000.0, unit="kg")],
        operations=[_operation(cost_amount=9000.0)],
    )
    per_area = payload["metrics"]["yield_per_area"]
    assert per_area["display_unit"] == "acre"
    assert per_area["per_display_unit"] == pytest.approx(1000.0)
    hectares = units.convert(18.0 * 4046.8564224, "m2", "ha").amount
    assert per_area["per_hectare"] == pytest.approx(18000.0 / hectares, abs=0.01)

    cost_per_area = payload["metrics"]["cost_per_area"]
    assert cost_per_area["per_display_unit"] == pytest.approx(500.0)


def test_every_per_area_figure_refuses_when_the_cycle_has_no_area():
    payload = _build(
        cycle=_cycle(planted_area_m2=None, display_area=None, display_area_unit=None),
        outcomes=[_outcome(value=18000.0, unit="kg")],
        operations=[_operation(cost_amount=9000.0)],
        sales=[_sale(gross_amount=1000.0)],
    )
    assert payload["metrics"]["planted_area"]["code"] == season_closeout.NO_PLANTED_AREA
    for key in ("yield_per_area", "cost_per_area", "revenue_per_area"):
        assert payload["metrics"][key]["code"] == season_closeout.NO_PLANTED_AREA
        assert "per_hectare" not in payload["metrics"][key]
    assert season_closeout.NO_PLANTED_AREA in _gap_codes(payload)


def test_cost_per_unit_of_crop_and_realised_price_come_from_records_only():
    payload = _build(
        outcomes=[_outcome(value=10000.0, unit="kg")],
        operations=[_operation(cost_amount=20000.0)],
        sales=[_sale(gross_amount=35000.0, deductions_amount=2000.0)],
    )
    assert payload["metrics"]["cost_per_yield_unit"]["value"] == pytest.approx(2.0)
    assert payload["metrics"]["cost_per_yield_unit"]["unit"] == "USD/kg"
    # Realised price is gross over yield — what the crop fetched, not a market quote.
    assert payload["metrics"]["realised_price_per_yield_unit"]["value"] == pytest.approx(3.5)


def test_cost_per_unit_refuses_when_the_yield_units_could_not_be_combined():
    payload = _build(
        outcomes=[_outcome(value=400.0, unit="tray")],
        operations=[_operation(cost_amount=20000.0)],
    )
    metric = payload["metrics"]["cost_per_yield_unit"]
    assert metric["code"] == season_closeout.INCOMPATIBLE_YIELD_UNITS
    assert "value" not in metric


def test_a_derived_rate_reports_its_numerators_real_reason_not_a_generic_one():
    """"No yield recorded" would send the reader hunting for records that exist."""
    payload = _build(outcomes=[_outcome(value=400.0, unit="tray")])
    rate = payload["metrics"]["yield_per_area"]
    assert rate["code"] == season_closeout.INCOMPATIBLE_YIELD_UNITS
    assert "tray" in rate["reason"]


# ---------------------------------------------------------------- the framing
def test_an_open_cycle_reads_as_season_to_date_and_a_closed_one_as_a_closeout():
    """Same arithmetic, same payload — only the framing differs."""
    open_payload = _build(cycle=_cycle(status="harvesting"))
    closed_payload = _build(cycle=_cycle(status="closed"))
    assert open_payload["view"] == "season_to_date"
    assert open_payload["is_closed"] is False
    assert closed_payload["view"] == "season_closeout"
    assert closed_payload["is_closed"] is True
    assert open_payload["metrics"].keys() == closed_payload["metrics"].keys()


def test_lumos_value_keeps_verified_and_estimated_apart_with_no_total():
    payload = _build()
    lumos = payload["lumos_value"]
    assert set(lumos) == {
        "verified", "estimated", "not_calculated_count", "currency", "basis_text"
    }
    # There is deliberately no combined figure anywhere in this block.
    assert "total" not in lumos
    assert "recommendations" in lumos["basis_text"]


def test_records_outside_the_cycle_are_named_as_a_gap():
    payload = _build(scope={
        "crop_cycle_id": 1,
        "records_outside_cycle": {"spray_events": 3, "planned_sprays": 1},
    })
    gap = next(
        g for g in payload["completeness"]["gaps"]
        if g["code"] == "records_outside_cycle"
    )
    assert gap["count"] == 4
    assert gap["breakdown"] == {"spray_events": 3, "planned_sprays": 1}


def test_completeness_is_a_list_of_gaps_and_never_a_score():
    payload = _build()
    completeness = payload["completeness"]
    assert isinstance(completeness["gaps"], list)
    # A percentage would let a season look nearly finished with the one figure that
    # mattered still missing.
    assert "score" not in completeness
    assert "percent" not in completeness


# ================================================================== route tests
def _farm(client, name="Closeout Farm"):
    res = client.post("/farms", json={
        "name": name, "country": "US", "crop_type": "strawberry", "area_unit": "acres",
        "expected_harvest_date": (date.today() + timedelta(days=60)).isoformat(),
        "planting_date": (date.today() - timedelta(days=60)).isoformat(),
    })
    assert res.status_code == 201, res.text
    return res.json()


def _api_cycle(client, farm_id, **overrides):
    payload = {
        "crop": "strawberry", "season_year": date.today().year,
        "planting_date": (date.today() - timedelta(days=60)).isoformat(),
        "display_area": 18.0, "display_area_unit": "acres",
    }
    payload.update(overrides)
    res = client.post(f"/farms/{farm_id}/crop-cycles", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def _api_sale(client, cycle_id, **overrides):
    payload = {
        "sale_date": date.today().isoformat(),
        "quantity": 1000.0, "unit": "lb", "unit_price": 2.0,
        "gross_amount": 2000.0,
    }
    payload.update(overrides)
    return client.post(f"/crop-cycles/{cycle_id}/sales", json=payload)


def test_a_sale_is_recorded_and_read_back(client):
    farm = _farm(client)
    cycle = _api_cycle(client, farm["id"])
    res = _api_sale(client, cycle["id"], buyer_name="Pajaro Packing", reference="STL-1")
    assert res.status_code == 201, res.text
    sale = res.json()
    assert sale["crop_cycle_id"] == cycle["id"]
    assert sale["farm_id"] == farm["id"]
    # Currency falls back to the farm's rather than being left unlabelled.
    assert sale["currency_code"] == "USD"

    listed = client.get(f"/crop-cycles/{cycle['id']}/sales").json()
    assert [s["id"] for s in listed] == [sale["id"]]


def test_a_contradictory_settlement_is_rejected(client):
    """quantity x unit price must agree with the stated gross, within rounding."""
    farm = _farm(client)
    cycle = _api_cycle(client, farm["id"])
    res = _api_sale(client, cycle["id"], quantity=1000.0, unit_price=2.0, gross_amount=9000.0)
    assert res.status_code == 422, res.text
    assert "contradicts itself" in res.text


def test_settlement_rounding_within_tolerance_is_accepted(client):
    farm = _farm(client)
    cycle = _api_cycle(client, farm["id"])
    res = _api_sale(client, cycle["id"], quantity=1000.0, unit_price=2.0, gross_amount=2000.40)
    assert res.status_code == 201, res.text


def test_a_sale_stating_no_money_is_rejected(client):
    farm = _farm(client)
    cycle = _api_cycle(client, farm["id"])
    res = _api_sale(client, cycle["id"], gross_amount=None, unit_price=None)
    assert res.status_code == 422, res.text


def test_a_quantity_without_a_unit_is_rejected(client):
    farm = _farm(client)
    cycle = _api_cycle(client, farm["id"])
    res = _api_sale(client, cycle["id"], unit=None)
    assert res.status_code == 422, res.text


def test_deductions_may_not_exceed_the_gross(client):
    farm = _farm(client)
    cycle = _api_cycle(client, farm["id"])
    res = _api_sale(client, cycle["id"], deductions_amount=99999.0)
    assert res.status_code == 422, res.text


def test_a_correction_supersedes_rather_than_edits(client):
    farm = _farm(client)
    cycle = _api_cycle(client, farm["id"])
    first = _api_sale(client, cycle["id"]).json()
    corrected = _api_sale(
        client, cycle["id"], gross_amount=2500.0, unit_price=2.5, supersedes_id=first["id"]
    )
    assert corrected.status_code == 201, corrected.text
    # Both rows survive: what the grower saw before the correction is still readable.
    assert len(client.get(f"/crop-cycles/{cycle['id']}/sales").json()) == 2
    closeout = client.get(f"/crop-cycles/{cycle['id']}/closeout").json()
    assert closeout["metrics"]["revenue"]["gross"] == pytest.approx(2500.0)

    # There is no way to edit or delete one.
    assert client.patch(f"/crop-cycles/{cycle['id']}/sales", json={}).status_code in (404, 405)


def test_a_sale_cannot_supersede_another_cycles_record(client):
    farm = _farm(client)
    cycle_a = _api_cycle(client, farm["id"])
    cycle_b = _api_cycle(client, farm["id"], season_year=date.today().year - 1)
    sale_a = _api_sale(client, cycle_a["id"]).json()
    res = _api_sale(client, cycle_b["id"], supersedes_id=sale_a["id"])
    assert res.status_code == 422, res.text
    assert "different crop cycle" in res.text


def test_the_closeout_route_serves_an_open_cycle_and_a_closed_one(client):
    farm = _farm(client)
    cycle = _api_cycle(client, farm["id"])
    _api_sale(client, cycle["id"])
    client.post(f"/crop-cycles/{cycle['id']}/operations", json={
        "operation_type": "irrigation", "cost_amount": 400.0,
        "performed_on": date.today().isoformat(),
    })

    open_view = client.get(f"/crop-cycles/{cycle['id']}/closeout")
    assert open_view.status_code == 200, open_view.text
    assert open_view.json()["view"] == "season_to_date"

    client.patch(f"/crop-cycles/{cycle['id']}", json={
        "status": "closed", "actual_harvest_end": date.today().isoformat(),
    })
    closed_view = client.get(f"/crop-cycles/{cycle['id']}/closeout").json()
    assert closed_view["view"] == "season_closeout"
    assert closed_view["metrics"]["revenue"]["gross"] == pytest.approx(2000.0)
    assert closed_view["metrics"]["costs"]["total"] == pytest.approx(400.0)


def test_the_closeout_404s_for_a_cycle_that_does_not_exist(client):
    assert client.get("/crop-cycles/9999/closeout").status_code == 404


def test_an_operations_cost_category_is_defaulted_from_its_type_but_never_guessed(client):
    farm = _farm(client)
    cycle = _api_cycle(client, farm["id"])
    fert = client.post(f"/crop-cycles/{cycle['id']}/operations", json={
        "operation_type": "fertilization", "cost_amount": 100.0,
    }).json()
    assert fert["cost_category"] == "fertilizer_nutrition"

    # Tillage may be owned equipment or a hired operator. Nobody knows, so nobody guesses.
    tillage = client.post(f"/crop-cycles/{cycle['id']}/operations", json={
        "operation_type": "tillage", "cost_amount": 100.0,
    }).json()
    assert tillage["cost_category"] is None

    # And the caller can always override the default.
    override = client.post(f"/crop-cycles/{cycle['id']}/operations", json={
        "operation_type": "fertilization", "cost_amount": 100.0, "cost_category": "labor",
    }).json()
    assert override["cost_category"] == "labor"


def test_a_harvest_outcome_is_stamped_with_the_open_season(client):
    farm = _farm(client)
    block = client.post(f"/farms/{farm['id']}/blocks", json={
        "name": "Field 7", "crop": "strawberry",
    }).json()
    cycle = _api_cycle(client, farm["id"])

    client.post(f"/farms/{farm['id']}/block-outcomes", json={
        "block_id": block["id"],
        "observed_on": date.today().isoformat(),
        "outcome_type": "yield", "value": 2204.62, "unit": "lb",
    })
    closeout = client.get(f"/crop-cycles/{cycle['id']}/closeout").json()
    assert closeout["metrics"]["harvested_yield"]["value"] == pytest.approx(1000.0, abs=0.01)


def test_an_outcome_recorded_before_the_season_existed_is_linked_by_backfill(client):
    farm = _farm(client)
    block = client.post(f"/farms/{farm['id']}/blocks", json={
        "name": "Field 7", "crop": "strawberry",
    }).json()
    # Recorded first: there is no cycle to stamp it with.
    client.post(f"/farms/{farm['id']}/block-outcomes", json={
        "block_id": block["id"],
        "observed_on": (date.today() - timedelta(days=5)).isoformat(),
        "outcome_type": "yield", "value": 1000.0, "unit": "kg",
    })
    # Creating the season backfills it through the same route a grower would use.
    cycle = _api_cycle(client, farm["id"])
    closeout = client.get(f"/crop-cycles/{cycle['id']}/closeout").json()
    assert closeout["metrics"]["harvested_yield"]["value"] == pytest.approx(1000.0)
    assert closeout["scope"]["records_outside_cycle"]["block_outcomes"] == 0


def test_an_avoided_decision_with_no_estimated_cost_is_named_as_a_gap(client):
    """The one figure the value ledger needs, surfaced rather than silently lost."""
    farm = _farm(client)
    cycle = _api_cycle(client, farm["id"])
    planned = client.post(f"/farms/{farm['id']}/planned-sprays", json={
        "intended_date": (date.today() + timedelta(days=2)).isoformat(),
        "product_name": "PyGanic EC 5.0",
        "target_pest_or_disease": "lygus_bug",
    }).json()
    client.patch(f"/planned-sprays/{planned['id']}/review", json={
        "action": "approved", "reviewed_by": "Dana PCA",
    })
    client.patch(f"/planned-sprays/{planned['id']}/outcome", json={
        "outcome": "avoided", "outcome_reason": "below threshold",
    })

    closeout = client.get(f"/crop-cycles/{cycle['id']}/closeout").json()
    codes = {g["code"] for g in closeout["completeness"]["gaps"]}
    assert "avoided_decisions_without_estimated_cost" in codes
    assert "decisions_awaiting_follow_up" in codes


def test_the_closeout_and_the_value_ledger_report_the_same_season_cost(client):
    """Both read the same roll-up, so the two surfaces cannot drift apart."""
    farm = _farm(client)
    cycle = _api_cycle(client, farm["id"])
    for amount in (1450.0, 380.0):
        client.post(f"/crop-cycles/{cycle['id']}/operations", json={
            "operation_type": "irrigation", "cost_amount": amount,
        })
    closeout = client.get(f"/crop-cycles/{cycle['id']}/closeout").json()
    ledger = client.get(
        f"/farms/{farm['id']}/value-ledger?crop_cycle_id={cycle['id']}"
    ).json()
    assert closeout["metrics"]["costs"]["total"] == ledger["season_costs"]["total"]
