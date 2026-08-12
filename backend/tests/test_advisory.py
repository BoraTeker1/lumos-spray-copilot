"""The advisory queue: a small ranked set of things worth doing, and nothing else.

The load-bearing tests here are the ones asserting an item does NOT appear. A queue
that surfaces every unentered field is a data-completion checklist, and the whole
claim of this module is that it is selective — so "a single uncosted application is
not an item", "an abstaining weather surface produces no item", and "a resolved
decision leaves the queue" matter more than any positive case.

Pure tests over stub objects: `advisory.py` imports no FastAPI and no SQLAlchemy, and
these tests keep it that way.
"""
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app import advisory, decision_status

TODAY = date(2026, 6, 1)


def _farm(**overrides):
    payload = {
        "id": 1, "name": "Queue Farm", "country": "US", "currency_code": "USD",
        "expected_harvest_date": TODAY + timedelta(days=30),
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def _cycle(**overrides):
    payload = {
        "id": 7, "status": "growing", "crop": "strawberry",
        "expected_harvest_start": TODAY + timedelta(days=30),
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def _planned(**overrides):
    """A decision that is cleared and awaiting an outcome unless overridden."""
    payload = {
        "id": 11, "product_name": "Switch 62.5WG", "field_block": "North 3",
        "intended_date": TODAY + timedelta(days=3),
        "estimated_cost": 940.0,
        "decision_outcome": "approve", "decision_severity": "none",
        "review_required": False, "review_status": None,
        "outcome": "planned", "decision_payload": {},
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def _build(**overrides):
    kwargs = {
        "farm": _farm(), "cycle": _cycle(), "decisions": [],
        "follow_ups_by_decision": {}, "blocks": [], "scout_observations": [],
        "input_plans": [], "orders": [], "financing_requests": [],
        "closeout": None, "weather_risk": None, "today": TODAY,
    }
    kwargs.update(overrides)
    return advisory.build_queue(**kwargs)


def _kinds(queue):
    return [i["kind"] for i in queue["items"]]


def _by_kind(queue, kind):
    return [i for i in queue["items"] if i["kind"] == kind]


# ------------------------------------------------------------------ item shape
def test_an_item_with_no_recommendation_is_rejected():
    """An item that names no action is a notification, not advice."""
    with pytest.raises(ValueError, match="notification"):
        advisory.AdvisoryItem(
            item_key="k", kind="x", subject_type="farm", subject_id=1,
            title="t", recommendation="", why="w",
        )


def test_an_unknown_urgency_is_rejected():
    with pytest.raises(ValueError, match="unknown urgency"):
        advisory.AdvisoryItem(
            item_key="k", kind="x", subject_type="farm", subject_id=1,
            title="t", recommendation="do it", why="w", urgency="whenever",
        )


def test_an_advisory_item_cannot_express_a_prescription():
    """The RiskAssessment technique: a product/rate field must not exist at all.

    An advisory item may say a decision needs review; naming what to spray is the
    PCA's job, and the strongest guarantee is a value that cannot be represented.
    """
    fields = set(advisory.AdvisoryItem.__dataclass_fields__)
    assert not fields & {
        "product", "product_name", "rate", "rate_amount", "active_ingredient",
        "application", "dose",
    }


def test_a_refused_economic_consequence_carries_no_value_key():
    """`season_closeout._refused`'s rule: a template cannot render an absent key as 0."""
    refused = advisory._no_baseline("nothing prices this")
    assert refused["not_calculated"] is True
    assert "value" not in refused and "amount" not in refused


# -------------------------------------------------------------- decision items
def test_a_decision_awaiting_review_becomes_a_critical_item_when_severe():
    planned = _planned(
        review_required=True, review_status=None,
        decision_outcome="block", decision_severity="critical",
    )
    queue = _build(decisions=[planned])
    items = _by_kind(queue, advisory.KIND_AWAIT_PCA_REVIEW)
    assert len(items) == 1
    assert items[0]["urgency"] == advisory.URGENCY_CRITICAL
    assert items[0]["next_action"]["href"] == "/decisions/11"


def test_a_decision_awaiting_review_is_only_soon_when_not_severe():
    planned = _planned(review_required=True, decision_severity="caution")
    queue = _build(decisions=[planned])
    assert _by_kind(queue, advisory.KIND_AWAIT_PCA_REVIEW)[0]["urgency"] == (
        advisory.URGENCY_SOON
    )


def test_a_critical_decision_past_review_is_an_open_conflict():
    planned = _planned(
        review_required=True, review_status="approved",
        decision_outcome="block", decision_severity="critical",
    )
    queue = _build(decisions=[planned])
    assert advisory.KIND_RESOLVE_CONFLICT in _kinds(queue)


def test_an_inspect_first_decision_asks_for_scouting_not_a_spray():
    planned = _planned(decision_outcome="inspect_first")
    queue = _build(decisions=[planned])
    item = _by_kind(queue, advisory.KIND_INSPECT_FIELD)[0]
    assert item["next_action"]["href"].startswith("/scouting")
    assert "spray" not in item["recommendation"].lower()


def test_an_overdue_outcome_outranks_one_still_in_the_future():
    overdue = _planned(id=11, intended_date=TODAY - timedelta(days=4))
    future = _planned(id=12, intended_date=TODAY + timedelta(days=10))
    queue = _build(decisions=[overdue, future])
    items = _by_kind(queue, advisory.KIND_RECORD_OUTCOME)
    assert [i["subject_id"] for i in items] == [11, 12]
    assert items[0]["urgency"] == advisory.URGENCY_SOON
    assert items[1]["urgency"] == advisory.URGENCY_ROUTINE


def test_a_recorded_outcome_needing_follow_up_asks_for_evidence_not_an_outcome():
    planned = _planned(outcome="avoided")
    queue = _build(decisions=[planned], follow_ups_by_decision={11: []})
    assert _kinds(queue).count(advisory.KIND_RECORD_FOLLOW_UP) == 1
    assert advisory.KIND_RECORD_OUTCOME not in _kinds(queue)


def test_a_fully_resolved_decision_leaves_the_queue_entirely():
    """The queue is derived, so an item clears itself — there is nothing to dismiss."""
    planned = _planned(outcome="sprayed_as_planned", decision_severity="none")
    queue = _build(decisions=[planned])
    assert queue["items"] == []
    assert queue["item_count"] == 0


def test_one_decision_never_produces_two_next_step_items():
    """`current_next_action` returns exactly one step; the queue must not double up."""
    planned = _planned(
        review_required=True, decision_outcome="block", decision_severity="critical",
    )
    kinds = _kinds(_build(decisions=[planned]))
    step_kinds = {
        advisory.KIND_AWAIT_PCA_REVIEW, advisory.KIND_RESOLVE_CONFLICT,
        advisory.KIND_INSPECT_FIELD, advisory.KIND_RECORD_OUTCOME,
        advisory.KIND_RECORD_FOLLOW_UP,
    }
    assert len([k for k in kinds if k in step_kinds]) == 1


def test_item_keys_are_stable_across_rebuilds():
    """A client can address an item without anything being persisted."""
    planned = _planned()
    first = _build(decisions=[planned])
    second = _build(decisions=[planned])
    assert [i["item_key"] for i in first["items"]] == [
        i["item_key"] for i in second["items"]
    ]


# --------------------------------------------------------------- the economics
def test_a_decision_carries_its_cost_as_the_economic_consequence():
    queue = _build(decisions=[_planned(estimated_cost=940.0)])
    econ = queue["items"][0]["economic_consequence"]
    assert econ["amount"] == 940.0
    assert econ["currency"] == "USD"
    # The cost of going ahead, explicitly disclaimed as not a saving — the figure is
    # what an avoidance would later be measured against, not value already created.
    assert "not a claimed saving" in econ["basis"].lower()


def test_a_decision_without_an_entered_cost_refuses_rather_than_showing_zero():
    queue = _build(decisions=[_planned(estimated_cost=None)])
    econ = queue["items"][0]["economic_consequence"]
    assert econ["code"] == advisory.NO_COST_ON_DECISION
    assert "amount" not in econ


def test_a_scouting_item_claims_no_money():
    """Inspecting a block has no recorded baseline; pricing it would invent one."""
    block = SimpleNamespace(id=3, name="North 3")
    queue = _build(blocks=[block])
    econ = _by_kind(queue, advisory.KIND_SCOUTING_STALE)[0]["economic_consequence"]
    assert econ["code"] == advisory.NO_BASELINE_FOR_ACTION


# -------------------------------------------------------------------- scouting
def test_a_block_scouted_recently_produces_no_item():
    block = SimpleNamespace(id=3, name="North 3")
    obs = SimpleNamespace(block_id=3, observation_date=TODAY - timedelta(days=2))
    queue = _build(blocks=[block], scout_observations=[obs])
    assert advisory.KIND_SCOUTING_STALE not in _kinds(queue)


def test_a_block_scouted_beyond_the_risk_window_is_flagged():
    block = SimpleNamespace(id=3, name="North 3")
    stale = TODAY - timedelta(days=advisory.SCOUTING_STALE_DAYS + 1)
    obs = SimpleNamespace(block_id=3, observation_date=stale)
    queue = _build(blocks=[block], scout_observations=[obs])
    assert advisory.KIND_SCOUTING_STALE in _kinds(queue)


def test_a_closed_season_stops_asking_for_scouting():
    block = SimpleNamespace(id=3, name="North 3")
    queue = _build(cycle=_cycle(status="closed"), blocks=[block])
    assert advisory.KIND_SCOUTING_STALE not in _kinds(queue)


# --------------------------------------------------------------------- weather
def test_an_abstaining_weather_surface_produces_no_item():
    """"We cannot see the weather" is a coverage fact, not an action."""
    queue = _build(weather_risk={"not_calculated": True, "code": "no_weather_data"})
    assert advisory.KIND_WEATHER_RISK not in _kinds(queue)


def test_low_weather_risk_produces_no_item():
    queue = _build(weather_risk={"risk_level": "low"})
    assert advisory.KIND_WEATHER_RISK not in _kinds(queue)


def test_elevated_weather_risk_produces_one_item():
    queue = _build(weather_risk={"risk_level": "elevated", "summary": "Wet week."})
    items = _by_kind(queue, advisory.KIND_WEATHER_RISK)
    assert len(items) == 1 and items[0]["why"] == "Wet week."


# ------------------------------------------------------------------- economics
def _closeout(*, gaps=(), revenue=None):
    return {
        "completeness": {"gaps": list(gaps)},
        "metrics": {"revenue": revenue or {"value": 100.0}},
    }


def test_a_single_uncosted_application_is_not_worth_a_recommendation():
    """The materiality floor: one missing cost is a chore, not an economics problem."""
    gap = {"code": "applications_without_cost", "count": 1, "detail": "d", "fix": "f"}
    queue = _build(closeout=_closeout(gaps=[gap]))
    assert advisory.KIND_SEASON_ECONOMICS not in _kinds(queue)


def test_several_uncosted_applications_do_reach_the_queue():
    gap = {
        "code": "applications_without_cost",
        "count": advisory.UNCOSTED_APPLICATIONS_FLOOR,
        "detail": "d", "fix": "f",
    }
    queue = _build(closeout=_closeout(gaps=[gap]))
    assert advisory.KIND_SEASON_ECONOMICS in _kinds(queue)


def test_routine_completeness_gaps_stay_out_of_the_queue():
    """These belong in the closeout's own exhaustive list, not a farmer's action list."""
    gaps = [
        {"code": "operations_uncategorised", "count": 9, "detail": "d", "fix": "f"},
        {"code": "costs_in_other_currency", "count": 4, "detail": "d", "fix": "f"},
        {"code": "operations_without_cost", "count": 6, "detail": "d", "fix": "f"},
    ]
    queue = _build(closeout=_closeout(gaps=gaps))
    assert advisory.KIND_SEASON_ECONOMICS not in _kinds(queue)


def test_a_value_blocking_gap_always_reaches_the_queue():
    gap = {
        "code": "avoided_decisions_without_estimated_cost",
        "count": 1, "detail": "d", "fix": "Enter the estimated cost.",
    }
    queue = _build(closeout=_closeout(gaps=[gap]))
    item = _by_kind(queue, advisory.KIND_SEASON_ECONOMICS)[0]
    assert item["recommendation"] == "Enter the estimated cost."


def test_missing_revenue_is_only_asked_for_once_there_is_a_crop_to_have_sold():
    refused = {"not_calculated": True, "code": "no_sales_recorded", "reason": "r"}
    growing = _build(cycle=_cycle(status="growing"), closeout=_closeout(revenue=refused))
    assert advisory.KIND_SEASON_ECONOMICS not in _kinds(growing)

    harvesting = _build(
        cycle=_cycle(status="harvesting"), closeout=_closeout(revenue=refused)
    )
    assert advisory.KIND_SEASON_ECONOMICS in _kinds(harvesting)


# ----------------------------------------------------------------- procurement
def test_a_cleared_decision_with_no_input_plan_is_a_procurement_opportunity():
    queue = _build(decisions=[_planned()])
    items = _by_kind(queue, advisory.KIND_PROCUREMENT_OPPORTUNITY)
    assert len(items) == 1 and items[0]["subject_id"] == 11


def test_a_decision_already_covered_by_a_plan_is_not_an_opportunity():
    plan = SimpleNamespace(
        id=5, status="draft", quote_count=0, needed_by=None,
        items=[SimpleNamespace(planned_spray_id=11)],
    )
    queue = _build(decisions=[_planned()], input_plans=[plan])
    assert advisory.KIND_PROCUREMENT_OPPORTUNITY not in _kinds(queue)


def test_an_avoided_decision_is_never_a_procurement_opportunity():
    """`procurement_eligible` is the gate; an avoidance closes the door on buying."""
    planned = _planned(outcome="avoided")
    queue = _build(decisions=[planned], follow_ups_by_decision={11: []})
    assert advisory.KIND_PROCUREMENT_OPPORTUNITY not in _kinds(queue)


def test_a_decision_far_beyond_the_buying_horizon_is_not_yet_an_opportunity():
    far = _planned(
        intended_date=TODAY + timedelta(days=advisory.PROCUREMENT_HORIZON_DAYS + 5)
    )
    queue = _build(decisions=[far])
    assert advisory.KIND_PROCUREMENT_OPPORTUNITY not in _kinds(queue)


def test_quotes_awaiting_selection_reach_the_queue():
    plan = SimpleNamespace(
        id=5, status="quoted", quote_count=2,
        needed_by=TODAY + timedelta(days=5), items=[],
    )
    queue = _build(input_plans=[plan])
    items = _by_kind(queue, advisory.KIND_PROCUREMENT_ACTION)
    assert len(items) == 1 and items[0]["next_action"]["href"] == "/inputs/plans/5"


def test_a_quote_comparison_item_never_calls_the_spread_a_saving():
    plan = SimpleNamespace(
        id=5, status="quoted", quote_count=2, needed_by=None, items=[]
    )
    item = _by_kind(_build(input_plans=[plan]), advisory.KIND_PROCUREMENT_ACTION)[0]
    assert "saving" not in item["economic_consequence"]["reason"].lower() or (
        "not a saving" in item["economic_consequence"]["reason"].lower()
    )
    assert "amount" not in item["economic_consequence"]


def test_an_overdue_order_reaches_the_queue():
    order = SimpleNamespace(id=9, overdue=True, supplier_name="Valley Farm Inputs")
    queue = _build(orders=[order])
    assert _by_kind(queue, advisory.KIND_PROCUREMENT_ACTION)[0]["subject_id"] == 9


# ------------------------------------------------------------------- financing
def test_an_undecided_indicative_offer_reaches_the_queue():
    offer = SimpleNamespace(
        id=2, status="indicative", expires_on=TODAY + timedelta(days=10)
    )
    req = SimpleNamespace(
        id=4, status="offers_received", offers=[offer], missing_evidence_count=0
    )
    queue = _build(financing_requests=[req])
    items = _by_kind(queue, advisory.KIND_FINANCING_ACTION)
    assert len(items) == 1
    assert items[0]["next_action"]["href"] == "/financing/4"


def test_a_financing_item_never_states_a_computed_rate():
    offer = SimpleNamespace(id=2, status="indicative", expires_on=None)
    req = SimpleNamespace(
        id=4, status="offers_received", offers=[offer], missing_evidence_count=0
    )
    item = _by_kind(_build(financing_requests=[req]), advisory.KIND_FINANCING_ACTION)[0]
    assert "amount" not in item["economic_consequence"]


def test_a_request_with_complete_evidence_produces_no_item():
    req = SimpleNamespace(id=4, status="draft", offers=[], missing_evidence_count=0)
    queue = _build(financing_requests=[req])
    assert advisory.KIND_FINANCING_ACTION not in _kinds(queue)


# --------------------------------------------------------------------- ranking
def test_the_queue_ranks_critical_before_soon_before_routine():
    conflict = _planned(
        id=11, review_required=True, review_status="approved",
        decision_outcome="block", decision_severity="critical",
    )
    routine = _planned(id=12, intended_date=TODAY + timedelta(days=10))
    block = SimpleNamespace(id=3, name="North 3")
    queue = _build(decisions=[conflict, routine], blocks=[block])

    urgencies = [i["urgency"] for i in queue["items"]]
    ranks = [advisory.URGENCY_ORDER.index(u) for u in urgencies]
    assert ranks == sorted(ranks)
    assert queue["counts_by_urgency"]["critical"] >= 1


def test_the_queue_reports_its_own_scope_and_disclaimer():
    queue = _build()
    assert queue["model_version"] == advisory.MODEL_VERSION
    assert queue["farm_id"] == 1 and queue["crop_cycle_id"] == 7
    assert "licensed PCA" in queue["disclaimer"]


def test_an_empty_farm_produces_an_empty_queue_not_an_error():
    queue = _build(farm=_farm(expected_harvest_date=None), cycle=None)
    assert queue["items"] == []
    assert queue["counts_by_urgency"] == {"critical": 0, "soon": 0, "routine": 0}


# ------------------------------------------------------------------- staleness
def test_a_decision_checked_against_a_moved_harvest_date_is_critical():
    planned = _planned(
        outcome="sprayed_as_planned",
        decision_payload={"inputs_used": {"expected_harvest_date": "2026-05-01"}},
    )
    queue = _build(decisions=[planned])
    items = _by_kind(queue, advisory.KIND_HARVEST_WINDOW_CHANGED)
    assert len(items) == 1 and items[0]["urgency"] == advisory.URGENCY_CRITICAL


def test_a_decision_grounded_in_its_own_harvest_date_is_not_stale():
    """A per-record verified input value is not staled by a farm-level edit."""
    planned = _planned(
        outcome="sprayed_as_planned",
        decision_payload={"inputs_used": {
            "expected_harvest_date": "2026-05-01",
            "field_sources": {"expected_harvest_date": "input_value"},
        }},
    )
    queue = _build(decisions=[planned])
    assert advisory.KIND_HARVEST_WINDOW_CHANGED not in _kinds(queue)
