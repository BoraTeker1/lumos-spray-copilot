"""The farm performance profile: the farm's own seasons, compared honestly.

The load-bearing tests are the refusals. A profile that always produces a trend is a
profile that is inventing one — so "one season yields no comparison", "trays and
kilograms are not two data points", and "there is no overall score" carry more weight
than any arithmetic case.

Pure tests over closeout-shaped dicts: `farm_performance.py` imports no FastAPI and no
SQLAlchemy, and these tests keep it that way.
"""
from datetime import date
from types import SimpleNamespace

from app import farm_performance

TODAY = date(2026, 6, 1)


def _farm(**overrides):
    payload = {"id": 1, "country": "US", "currency_code": "USD"}
    payload.update(overrides)
    return SimpleNamespace(**payload)


def _closeout(year=2026, *, cycle_id=None, yield_kg=12000.0, revenue_net=48000.0,
              cost_total=21000.0, crop_protection=6400.0, gaps=0,
              verified=0.0, verified_items=0, yield_unit="kg", closed=True):
    """A closeout payload in the exact shape `season_closeout.build_closeout` emits."""
    return {
        "crop_cycle_id": cycle_id if cycle_id is not None else year,
        "season_year": year,
        "season_label": f"{year} season",
        "crop": "strawberry",
        "status": "closed" if closed else "growing",
        "is_closed": closed,
        "currency": "USD",
        "metrics": {
            "harvested_yield": {
                "value": yield_kg, "unit": yield_unit, "basis_text": "b",
            },
            "yield_per_area": {
                "per_hectare": yield_kg / 7.3, "unit": yield_unit, "basis_text": "b",
            },
            "revenue": {"gross": revenue_net + 2000, "net": revenue_net, "basis_text": "b"},
            "revenue_per_area": {
                "per_hectare": revenue_net / 7.3, "unit": "USD", "basis_text": "b",
            },
            "costs": {
                "total": cost_total,
                "by_cost_category": {"crop_protection": crop_protection},
            },
            "cost_per_area": {
                "per_hectare": cost_total / 7.3, "unit": "USD", "basis_text": "b",
            },
            "cost_per_yield_unit": {
                "value": cost_total / yield_kg, "unit": "USD/kg", "basis_text": "b",
            },
            "realised_price_per_yield_unit": {
                "value": revenue_net / yield_kg, "unit": "USD/kg", "basis_text": "b",
            },
            "revenue_minus_recorded_costs": {
                "value": revenue_net - cost_total, "basis_text": "b",
            },
        },
        "completeness": {"gap_count": gaps, "gaps": []},
        "lumos_value": {
            "verified": {"total": verified, "item_count": verified_items},
            "estimated": {"total": 0.0, "item_count": 0},
            "basis_text": "b",
        },
    }


def _refused_metric(code="no_yield_recorded"):
    return {"not_calculated": True, "code": code, "reason": "nothing recorded"}


def _build(closeouts, **overrides):
    kwargs = {
        "farm": _farm(), "closeouts": closeouts, "decisions_by_cycle": {},
        "follow_ups_by_decision": {}, "block_outcomes_by_cycle": {}, "today": TODAY,
    }
    kwargs.update(overrides)
    return farm_performance.build_performance(**kwargs)


# ---------------------------------------------------------------- no fake score
def test_the_profile_carries_no_overall_score_of_any_kind():
    """A blended figure across seasons is exactly the fake score this replaces."""
    profile = _build([_closeout(2026), _closeout(2025)])
    forbidden = {"overall_score", "score", "grade", "rating", "index", "percentile"}
    assert not forbidden & set(profile)
    for season in profile["seasons"]:
        assert not forbidden & set(season)


def test_the_profile_states_that_there_is_no_cross_farm_benchmark():
    profile = _build([_closeout(2026)])
    assert "no cross-farm benchmark" in profile["comparison_basis"]


# -------------------------------------------------------------------- seasons
def test_seasons_are_returned_newest_first():
    profile = _build([_closeout(2024), _closeout(2026), _closeout(2025)])
    assert [s["season_year"] for s in profile["seasons"]] == [2026, 2025, 2024]
    assert profile["season_count"] == 3


def test_a_per_area_metric_is_read_from_its_per_hectare_key():
    """Rate metrics keep their number under `per_hectare`, not `value`."""
    profile = _build([_closeout(2026, yield_kg=14600.0)])
    metric = profile["seasons"][0]["metrics"]["yield_per_area"]
    assert metric["value"] == 2000.0
    assert metric["unit"] == "kg/ha"


def test_revenue_is_read_from_its_net_key():
    profile = _build([_closeout(2026, revenue_net=48000.0)])
    assert profile["seasons"][0]["metrics"]["revenue"]["value"] == 48000.0


def test_recorded_costs_are_read_from_the_roll_up_total():
    profile = _build([_closeout(2026, cost_total=21000.0)])
    assert profile["seasons"][0]["metrics"]["costs"]["value"] == 21000.0


def test_a_refused_closeout_metric_keeps_its_own_code_and_reason():
    """Restating it generically would send the reader after the wrong records."""
    closeout = _closeout(2026)
    closeout["metrics"]["harvested_yield"] = _refused_metric("incompatible_yield_units")
    profile = _build([closeout])
    metric = profile["seasons"][0]["metrics"]["harvested_yield"]
    assert metric["code"] == "incompatible_yield_units"
    assert "value" not in metric


def test_an_uncategorised_season_refuses_crop_protection_cost():
    closeout = _closeout(2026)
    closeout["metrics"]["costs"]["by_cost_category"] = {}
    profile = _build([closeout])
    metric = profile["seasons"][0]["metrics"]["crop_protection_cost"]
    assert metric["not_calculated"] is True
    assert "value" not in metric


def test_a_season_with_no_attributable_value_refuses_rather_than_showing_zero():
    """0 verified value reads as "Lumos was worthless", not "nothing is attributable"."""
    profile = _build([_closeout(2026, verified=0.0, verified_items=0)])
    metric = profile["seasons"][0]["metrics"]["lumos_value_verified"]
    assert metric["not_calculated"] is True
    assert "value" not in metric


def test_a_season_with_verified_value_reports_it():
    profile = _build([_closeout(2026, verified=3200.0, verified_items=2)])
    assert profile["seasons"][0]["metrics"]["lumos_value_verified"]["value"] == 3200.0


# ------------------------------------------------------------ derived metrics
def _planned(**overrides):
    payload = {
        "id": 1, "review_required": False, "review_status": None,
        "outcome": "sprayed_as_planned", "decision_severity": "none",
        "decision_payload": {},
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def test_decision_follow_through_is_a_ratio_of_two_record_counts():
    decisions = [
        _planned(id=1, outcome="sprayed_as_planned"),
        _planned(id=2, outcome="avoided"),
        _planned(id=3, outcome="planned"),
        _planned(id=4, outcome="planned"),
    ]
    profile = _build([_closeout(2026, cycle_id=99)], decisions_by_cycle={99: decisions})
    metric = profile["seasons"][0]["metrics"]["decision_follow_through"]
    assert metric["value"] == 0.5
    assert metric["numerator"] == 2 and metric["denominator"] == 4


def test_decisions_still_awaiting_review_are_not_counted_against_follow_through():
    decisions = [_planned(id=1, review_required=True, outcome="planned")]
    profile = _build([_closeout(2026, cycle_id=99)], decisions_by_cycle={99: decisions})
    metric = profile["seasons"][0]["metrics"]["decision_follow_through"]
    assert metric["not_calculated"] is True


def test_a_season_with_no_decisions_refuses_rather_than_reporting_zero():
    profile = _build([_closeout(2026, cycle_id=99)], decisions_by_cycle={99: []})
    assert profile["seasons"][0]["metrics"]["decision_follow_through"]["not_calculated"]


def test_conflicts_caught_counts_critical_findings():
    decisions = [
        _planned(id=1, decision_severity="critical", outcome="changed_product"),
        _planned(id=2, decision_severity="critical", outcome="planned"),
        _planned(id=3, decision_severity="none"),
    ]
    profile = _build([_closeout(2026, cycle_id=99)], decisions_by_cycle={99: decisions})
    metrics = profile["seasons"][0]["metrics"]
    assert metrics["conflicts_caught"]["value"] == 2
    assert metrics["open_conflicts"]["value"] == 1
    assert "prevented" not in metrics["conflicts_caught"]["basis_text"].lower() or (
        "not a claim that a mistake was prevented"
        in metrics["conflicts_caught"]["basis_text"]
    )


def test_rescue_applications_are_counted_from_live_block_outcomes():
    outcomes = [
        SimpleNamespace(id=1, outcome_type="rescue_treatment", supersedes_id=None),
        SimpleNamespace(id=2, outcome_type="rescue_treatment", supersedes_id=1),
        SimpleNamespace(id=3, outcome_type="yield", supersedes_id=None),
    ]
    profile = _build(
        [_closeout(2026, cycle_id=99)], block_outcomes_by_cycle={99: outcomes}
    )
    # Row 2 supersedes row 1, so one rescue treatment stands, not two.
    assert profile["seasons"][0]["metrics"]["rescue_applications"]["value"] == 1


def test_no_recorded_rescue_is_not_claimed_as_none_having_happened():
    profile = _build([_closeout(2026, cycle_id=99)], block_outcomes_by_cycle={99: []})
    basis = profile["seasons"][0]["metrics"]["rescue_applications"]["basis_text"]
    assert "not evidence none happened" in basis


# --------------------------------------------------------------------- trends
def test_one_season_produces_no_trend_at_all():
    profile = _build([_closeout(2026)])
    for key, trend in profile["trends"].items():
        assert trend["not_calculated"] is True, key
        assert trend["code"] == farm_performance.INSUFFICIENT_COMPARABLE_SEASONS


def test_no_seasons_produces_an_empty_profile_not_an_error():
    profile = _build([])
    assert profile["seasons"] == []
    assert profile["season_count"] == 0


def test_two_seasons_produce_a_factual_delta_and_direction():
    profile = _build([
        _closeout(2026, yield_kg=14000.0),
        _closeout(2025, yield_kg=10000.0),
    ])
    trend = profile["trends"]["harvested_yield"]
    assert trend["from_value"] == 10000.0 and trend["to_value"] == 14000.0
    assert trend["delta"] == 4000.0
    assert trend["direction"] == "up"
    assert trend["delta_pct"] == 40.0
    assert trend["higher_is_better"] is True


def test_a_falling_cost_per_unit_reports_down_and_is_marked_lower_is_better():
    """The direction is a fact; whether it is good is a declared metric property."""
    profile = _build([
        _closeout(2026, cost_total=18000.0, yield_kg=12000.0),
        _closeout(2025, cost_total=24000.0, yield_kg=12000.0),
    ])
    trend = profile["trends"]["cost_per_yield_unit"]
    assert trend["direction"] == "down"
    assert trend["higher_is_better"] is False


def test_a_trend_refuses_when_the_metric_is_missing_in_either_season():
    older = _closeout(2025)
    older["metrics"]["harvested_yield"] = _refused_metric()
    profile = _build([_closeout(2026), older])
    trend = profile["trends"]["harvested_yield"]
    assert trend["code"] == farm_performance.METRIC_MISSING_IN_A_SEASON


def test_trays_and_kilograms_are_not_two_data_points():
    profile = _build([
        _closeout(2026, yield_unit="kg"),
        _closeout(2025, yield_unit="trays"),
    ])
    trend = profile["trends"]["harvested_yield"]
    assert trend["code"] == farm_performance.INCOMPARABLE_UNITS
    assert "converts between them" in trend["reason"]


def test_a_percentage_is_omitted_rather_than_divided_by_a_zero_baseline():
    profile = _build([
        _closeout(2026, cost_total=5000.0),
        _closeout(2025, cost_total=0.0),
    ])
    trend = profile["trends"]["costs"]
    assert trend["delta"] == 5000.0
    assert "delta_pct" not in trend


def test_the_trend_compares_the_two_most_recent_closed_seasons():
    profile = _build([
        _closeout(2024, yield_kg=1000.0),
        _closeout(2025, yield_kg=2000.0),
        _closeout(2026, yield_kg=3000.0),
    ])
    trend = profile["trends"]["harvested_yield"]
    assert trend["from_value"] == 2000.0 and trend["to_value"] == 3000.0


def test_an_in_progress_season_is_skipped_when_two_closed_ones_exist():
    """A partial season has recorded only part of its costs; comparing it to a
    finished season flatters every cost metric. Two closed seasons win."""
    profile = _build([
        _closeout(2026, yield_kg=500.0, closed=False),
        _closeout(2025, yield_kg=2000.0),
        _closeout(2024, yield_kg=1000.0),
    ])
    trend = profile["trends"]["harvested_yield"]
    assert trend["from_value"] == 1000.0 and trend["to_value"] == 2000.0
    assert trend["compares_a_season_in_progress"] is False
    assert profile["trend_comparison"]["later_season"] == "2025 season"


def test_comparing_against_an_open_season_is_allowed_but_flagged():
    profile = _build([
        _closeout(2026, cost_total=4000.0, closed=False),
        _closeout(2025, cost_total=21000.0),
    ])
    trend = profile["trends"]["costs"]
    assert trend["compares_a_season_in_progress"] is True
    assert "STILL IN PROGRESS" in trend["basis_text"]
    assert profile["trend_comparison"]["compares_a_season_in_progress"] is True


def test_a_trend_never_asserts_a_cause():
    profile = _build([_closeout(2026), _closeout(2025, yield_kg=9000.0)])
    assert "not a demonstrated cause" in profile["trends"]["harvested_yield"]["basis_text"]


def test_the_profile_reports_its_version_and_disclaimer():
    profile = _build([_closeout(2026)])
    assert profile["model_version"] == farm_performance.MODEL_VERSION
    assert "never as zero" in profile["disclaimer"]
    assert profile["closed_season_count"] == 1
