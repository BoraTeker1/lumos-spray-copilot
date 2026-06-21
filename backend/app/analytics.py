"""Pesticide cost analytics (framework-free, easy to unit test).

Reads plain objects via duck typing (same approach as the recommendation engine).
All money figures are rounded to 2 decimals. Wording in the UI/report deliberately
avoids overclaiming — we surface *potential avoidable cost*, not guaranteed savings.
"""
from __future__ import annotations

from datetime import date, timedelta

from app.recommendation_engine import RECENT_WINDOW_DAYS, SAME_INGREDIENT_MAX


def _round(value: float) -> float:
    return round(float(value), 2)


def compute_cost_analytics(spray_events, today: date | None = None) -> dict:
    """Summarise pesticide spend for one farm's spray history.

    Returns a dict with: total_spend, spray_count, average_cost_per_spray,
    most_used_active_ingredient (+ count), sprays_last_30_days,
    repeated_ingredient_cost, and potential_avoidable_cost.
    """
    if today is None:
        today = date.today()
    sprays = list(spray_events or [])

    costs = [float(getattr(s, "cost", 0) or 0) for s in sprays]
    spray_count = len(sprays)
    total_spend = sum(costs)
    average_cost_per_spray = total_spend / spray_count if spray_count else 0.0

    # Sprays within the recent window.
    cutoff = today - timedelta(days=RECENT_WINDOW_DAYS)
    recent = [
        s for s in sprays
        if getattr(s, "application_date", None) and cutoff <= s.application_date <= today
    ]

    # Count + total cost per active ingredient (over the recent window).
    counts: dict[str, int] = {}
    ingredient_cost: dict[str, float] = {}
    for s in recent:
        ai = (getattr(s, "active_ingredient", None) or "").strip().lower()
        if not ai:
            continue
        counts[ai] = counts.get(ai, 0) + 1
        ingredient_cost[ai] = ingredient_cost.get(ai, 0.0) + float(getattr(s, "cost", 0) or 0)

    most_used = max(counts.items(), key=lambda kv: kv[1]) if counts else None
    most_used_active_ingredient = most_used[0] if most_used else None
    most_used_count = most_used[1] if most_used else 0

    # Cost attributable to *repeat* applications of over-used ingredients.
    # For each ingredient used more than SAME_INGREDIENT_MAX times, the repeats beyond
    # the first are the "extra" applications. We value them at that ingredient's average cost.
    repeated_ingredient_cost = 0.0
    for ai, count in counts.items():
        if count > SAME_INGREDIENT_MAX:
            avg_for_ai = ingredient_cost[ai] / count if count else 0.0
            repeated_ingredient_cost += avg_for_ai * (count - 1)

    # Potential avoidable cost if a single unnecessary spray were prevented (one avg spray).
    potential_avoidable_cost = average_cost_per_spray

    return {
        "total_spend": _round(total_spend),
        "spray_count": spray_count,
        "average_cost_per_spray": _round(average_cost_per_spray),
        "most_used_active_ingredient": most_used_active_ingredient,
        "most_used_count": most_used_count,
        "sprays_last_30_days": len(recent),
        "repeated_ingredient_cost": _round(repeated_ingredient_cost),
        "potential_avoidable_cost": _round(potential_avoidable_cost),
    }
