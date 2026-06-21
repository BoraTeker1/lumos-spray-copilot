"""Tests for pesticide cost analytics."""
from datetime import date, timedelta
from types import SimpleNamespace

from app.analytics import compute_cost_analytics

TODAY = date(2026, 6, 21)


def spray(ai, days_ago, cost):
    return SimpleNamespace(
        active_ingredient=ai,
        application_date=TODAY - timedelta(days=days_ago),
        cost=cost,
    )


def test_empty_history_is_safe():
    a = compute_cost_analytics([], today=TODAY)
    assert a["total_spend"] == 0
    assert a["spray_count"] == 0
    assert a["average_cost_per_spray"] == 0
    assert a["most_used_active_ingredient"] is None
    assert a["sprays_last_30_days"] == 0


def test_totals_and_average():
    sprays = [spray("mancozeb", 2, 45.0), spray("mancozeb", 12, 45.0), spray("imidacloprid", 8, 70.0)]
    a = compute_cost_analytics(sprays, today=TODAY)
    assert a["total_spend"] == 160.0
    assert a["spray_count"] == 3
    assert a["average_cost_per_spray"] == round(160.0 / 3, 2)


def test_most_used_active_ingredient():
    sprays = [spray("mancozeb", 2, 45.0), spray("mancozeb", 12, 45.0), spray("imidacloprid", 8, 70.0)]
    a = compute_cost_analytics(sprays, today=TODAY)
    assert a["most_used_active_ingredient"] == "mancozeb"
    assert a["most_used_count"] == 2


def test_sprays_last_30_days_excludes_old_sprays():
    sprays = [spray("mancozeb", 2, 45.0), spray("mancozeb", 45, 45.0)]
    a = compute_cost_analytics(sprays, today=TODAY)
    assert a["sprays_last_30_days"] == 1


def test_repeated_ingredient_cost_for_overused_ingredient():
    # mancozeb used 3x at 45 -> 2 repeat applications valued at avg cost 45 = 90.
    sprays = [spray("mancozeb", 2, 45.0), spray("mancozeb", 12, 45.0), spray("mancozeb", 22, 45.0)]
    a = compute_cost_analytics(sprays, today=TODAY)
    assert a["repeated_ingredient_cost"] == 90.0


def test_no_repeated_cost_when_ingredient_used_twice():
    # SAME_INGREDIENT_MAX is 2, so exactly 2 uses is not "over-use".
    sprays = [spray("mancozeb", 2, 45.0), spray("mancozeb", 12, 45.0)]
    a = compute_cost_analytics(sprays, today=TODAY)
    assert a["repeated_ingredient_cost"] == 0


def test_potential_avoidable_cost_equals_average_spray_cost():
    sprays = [spray("mancozeb", 2, 40.0), spray("imidacloprid", 8, 80.0)]
    a = compute_cost_analytics(sprays, today=TODAY)
    assert a["potential_avoidable_cost"] == 60.0
