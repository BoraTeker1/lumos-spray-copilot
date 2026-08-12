"""How this farm has actually performed, season over season.

Pure and framework-free (no FastAPI / SQLAlchemy imports). The caller owns the DB
access and hands in one season closeout per crop cycle, already built by
`season_closeout.build_closeout` — this module never recomputes a season's economics,
because two independently-derived answers to "what did this season cost" would
eventually disagree, and the closeout is the one that already reconciles with the
value ledger.

The boundary against `farm_profile.py`
--------------------------------------
`farm_profile` answers a CAPABILITY question: which advisory and finance layers can
compute anything for this farm right now, and whose job it is to unblock the ones
that cannot. This module answers an OUTCOME question: what did the farm actually
produce, spend, earn, and document, and how has that moved between seasons. They read
different inputs and neither subsumes the other; keep both.

No composite score
------------------
There is no overall number, no grade, and no index. A farm's seasons differ in crop,
area, weather and market, and a single figure blended across them would be a claim
nobody could check — which is exactly the "fake arbitrary AI score" this profile
exists instead of. The story is told by the individual metrics and by the movement
between two seasons that are actually comparable.

What makes two seasons comparable
---------------------------------
A trend is reported only when the same metric has a real value in both seasons AND
the units and currency match. Otherwise the trend refuses with a reason. A season
whose yield is recorded in trays and one recorded in kilograms are not two data
points; a delta across them would be arithmetic on incompatible things.

The direction is factual, the judgement is not
----------------------------------------------
Each trend reports `delta`, `delta_pct` and `direction` (up / down / unchanged) —
all facts. Whether a rise is good is a property of the metric (`higher_is_better`),
declared once here, so the surface can colour it without this module asserting that
a smaller harvest was a failure. It may have been the weather.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app import decision_status
from app.refusal import Refusal
from app.value_ledger import currency_for

MODEL_VERSION = "farm_performance_v1"

# Refusal codes.
NO_SEASONS_RECORDED = "no_seasons_recorded"
INSUFFICIENT_COMPARABLE_SEASONS = "insufficient_comparable_seasons"
METRIC_MISSING_IN_A_SEASON = "metric_not_recorded_in_both_seasons"
INCOMPARABLE_UNITS = "incomparable_units_between_seasons"

PERFORMANCE_DISCLAIMER = (
    "Performance is computed from records this farm entered. Metrics that nobody "
    "recorded are reported as not calculated, never as zero, and a season-over-season "
    "movement is a change in the records — not proof of a cause. Decision support only."
)


@dataclass(frozen=True)
class MetricSpec:
    """How to read one metric out of a closeout, and which way is up.

    `source` is the closeout metric key; `value_key` is where that metric keeps its
    number, which differs by shape — a plain metric uses `value`, a per-area rate uses
    `per_hectare`, revenue uses `net`, and the cost roll-up uses `total`.
    """

    key: str
    label: str
    source: str
    value_key: str
    higher_is_better: bool | None
    unit_key: str | None = "unit"


# The economics half, read straight from the closeout. Order is the display order.
_CLOSEOUT_METRICS = (
    MetricSpec("harvested_yield", "Harvested yield", "harvested_yield", "value", True),
    MetricSpec("yield_per_area", "Yield per area", "yield_per_area", "per_hectare", True),
    MetricSpec("revenue", "Revenue (net)", "revenue", "net", True, unit_key=None),
    MetricSpec("revenue_per_area", "Revenue per area", "revenue_per_area", "per_hectare", True),
    MetricSpec("costs", "Recorded costs", "costs", "total", None, unit_key=None),
    MetricSpec("cost_per_area", "Cost per area", "cost_per_area", "per_hectare", False),
    MetricSpec("cost_per_yield_unit", "Cost per unit of crop", "cost_per_yield_unit", "value", False),
    MetricSpec(
        "realised_price_per_yield_unit", "Realised price per unit",
        "realised_price_per_yield_unit", "value", True,
    ),
    MetricSpec(
        "revenue_minus_recorded_costs", "Revenue minus recorded costs",
        "revenue_minus_recorded_costs", "value", True, unit_key=None,
    ),
)

# Metrics this module derives itself, from decisions and block outcomes.
_DERIVED_METRIC_LABELS = {
    "crop_protection_cost": ("Crop protection cost", False),
    "rescue_applications": ("Rescue applications", False),
    "decision_follow_through": ("Decision follow-through", True),
    "evidence_gaps": ("Open evidence gaps", False),
    "conflicts_caught": ("Conflicts caught before spraying", None),
    "open_conflicts": ("Unresolved conflicts", False),
    "lumos_value_verified": ("Lumos value — verified", True),
    "lumos_value_estimated": ("Lumos value — estimated", None),
}

HIGHER_IS_BETTER = {
    **{spec.key: spec.higher_is_better for spec in _CLOSEOUT_METRICS},
    **{k: v[1] for k, v in _DERIVED_METRIC_LABELS.items()},
}

METRIC_LABELS = {
    **{spec.key: spec.label for spec in _CLOSEOUT_METRICS},
    **{k: v[0] for k, v in _DERIVED_METRIC_LABELS.items()},
}


# ------------------------------------------------------------------- primitives
def _metric(value, *, unit=None, basis: str = "", **extra) -> dict:
    payload = {"value": round(float(value), 2), "basis_text": basis}
    if unit:
        payload["unit"] = unit
    payload.update(extra)
    return payload


def _refused(refusal: Refusal, **extra) -> dict:
    """No `value` key, ever — the `season_closeout._refused` contract."""
    payload = {"not_calculated": True, "code": refusal.code, "reason": refusal.detail}
    if refusal.context:
        payload["context"] = refusal.context
    payload.update(extra)
    return payload


def _read(closeout: dict, spec: MetricSpec) -> dict:
    """Lift one metric out of a closeout into this module's uniform shape."""
    raw = (closeout.get("metrics") or {}).get(spec.source)
    if not raw:
        return _refused(Refusal(
            code=NO_SEASONS_RECORDED,
            detail=f"This season's closeout carries no {spec.label.lower()}.",
        ))
    if raw.get("not_calculated"):
        # Carry the closeout's OWN code and reason through. Restating it as a generic
        # "missing" would send the reader looking for records that already exist but
        # could not be combined — the trays-versus-kilograms case.
        return _refused(Refusal(code=raw["code"], detail=raw["reason"]))
    if spec.value_key not in raw:
        return _refused(Refusal(
            code=NO_SEASONS_RECORDED,
            detail=f"This season's closeout carries no {spec.label.lower()}.",
        ))
    unit = raw.get(spec.unit_key) if spec.unit_key else closeout.get("currency")
    if spec.value_key == "per_hectare":
        unit = f"{raw.get('unit') or closeout.get('currency') or ''}/ha".strip("/")
    return _metric(
        raw[spec.value_key],
        unit=unit,
        basis=raw.get("basis_text", ""),
    )


# --------------------------------------------------------------- derived metrics
def _decision_metrics(decisions, follow_ups_by_decision, currency) -> dict:
    """What the farm did with the decisions Lumos checked."""
    decisions = list(decisions or [])
    metrics: dict = {}

    if not decisions:
        absent = _refused(Refusal(
            code=NO_SEASONS_RECORDED,
            detail="No pre-spray decisions were recorded in this season.",
        ))
        for key in ("decision_follow_through", "conflicts_caught", "open_conflicts"):
            metrics[key] = dict(absent)
        return metrics

    cleared = [d for d in decisions if not decision_status.needs_review(d)]
    recorded = [d for d in cleared if not decision_status.is_open(d)]
    if cleared:
        metrics["decision_follow_through"] = _metric(
            len(recorded) / len(cleared),
            unit="ratio",
            basis=(
                f"{len(recorded)} of {len(cleared)} decision(s) cleared to proceed "
                "have a recorded real-world outcome. Both numbers are record counts."
            ),
            numerator=len(recorded),
            denominator=len(cleared),
        )
    else:
        metrics["decision_follow_through"] = _refused(Refusal(
            code=NO_SEASONS_RECORDED,
            detail=(
                "Every decision this season is still awaiting review, so there is no "
                "follow-through to measure yet."
            ),
        ))

    metrics["conflicts_caught"] = _metric(
        sum(1 for d in decisions if decision_status.conflict_caught(d)),
        unit="decisions",
        basis=(
            "Decisions where the pre-spray check returned a critical finding. Caught "
            "and documented — not a claim that a mistake was prevented."
        ),
    )
    metrics["open_conflicts"] = _metric(
        sum(1 for d in decisions if decision_status.open_conflict(d)),
        unit="decisions",
        basis="Critical findings with no recorded outcome at the end of the season.",
    )
    return metrics


def _outcome_metrics(block_outcomes) -> dict:
    """Rescue treatments, counted from what somebody measured in a block."""
    rows = [
        o for o in (block_outcomes or [])
        if getattr(o, "outcome_type", None) == "rescue_treatment"
    ]
    superseded = {
        getattr(o, "supersedes_id", None) for o in rows
        if getattr(o, "supersedes_id", None) is not None
    }
    live = [o for o in rows if getattr(o, "id", None) not in superseded]
    return {
        "rescue_applications": _metric(
            len(live),
            unit="observations",
            basis=(
                "Rescue treatments recorded as block outcomes this season. A season "
                "with none recorded is not evidence none happened — only that none "
                "was entered."
            ),
        )
    }


def _cost_category_metrics(closeout, currency) -> dict:
    costs = (closeout.get("metrics") or {}).get("costs") or {}
    by_category = costs.get("by_cost_category") or {}
    crop_protection = by_category.get("crop_protection")
    if crop_protection is None:
        return {"crop_protection_cost": _refused(Refusal(
            code="no_crop_protection_cost_recorded",
            detail=(
                "No cost recorded this season is categorised as crop protection, so "
                "the share spent on spraying cannot be reported."
            ),
        ))}
    return {"crop_protection_cost": _metric(
        crop_protection,
        unit=currency,
        basis=(
            "Recorded costs categorised as crop protection. Applications entered "
            "without a cost are absent, so the true figure is higher."
        ),
    )}


def _value_metrics(closeout, currency) -> dict:
    lumos = closeout.get("lumos_value") or {}
    metrics = {}
    for key, tier in (("lumos_value_verified", "verified"),
                      ("lumos_value_estimated", "estimated")):
        block = lumos.get(tier) or {}
        if not block.get("item_count"):
            metrics[key] = _refused(Refusal(
                code=f"no_{tier}_value_this_season",
                detail=(
                    f"No {tier} value was attributable to a Lumos recommendation in "
                    "this season."
                ),
            ))
        else:
            metrics[key] = _metric(
                block.get("total", 0.0),
                unit=currency,
                basis=lumos.get("basis_text", ""),
            )
    return metrics


def _completeness_metric(closeout) -> dict:
    completeness = closeout.get("completeness") or {}
    count = completeness.get("gap_count")
    if count is None:
        return {"evidence_gaps": _refused(Refusal(
            code=NO_SEASONS_RECORDED,
            detail="This season's closeout reports no completeness assessment.",
        ))}
    return {"evidence_gaps": _metric(
        count,
        unit="gaps",
        basis=(
            "Named gaps in this season's records — each one a specific thing somebody "
            "can go and enter. Fewer gaps means the season's economics are more "
            "complete, not that the season went better."
        ),
    )}


# --------------------------------------------------------------------- a season
def _season(closeout, decisions, follow_ups_by_decision, block_outcomes) -> dict:
    currency = closeout.get("currency")
    metrics: dict = {spec.key: _read(closeout, spec) for spec in _CLOSEOUT_METRICS}
    metrics.update(_cost_category_metrics(closeout, currency))
    metrics.update(_outcome_metrics(block_outcomes))
    metrics.update(_decision_metrics(decisions, follow_ups_by_decision, currency))
    metrics.update(_completeness_metric(closeout))
    metrics.update(_value_metrics(closeout, currency))
    return {
        "crop_cycle_id": closeout.get("crop_cycle_id"),
        "season_year": closeout.get("season_year"),
        "season_label": closeout.get("season_label"),
        "crop": closeout.get("crop"),
        "status": closeout.get("status"),
        "is_closed": closeout.get("is_closed", False),
        "currency": currency,
        "is_simulated": closeout.get("is_simulated", False),
        "metrics": metrics,
    }


# ---------------------------------------------------------------------- trends
def _trend(key: str, earlier: dict, later: dict, *, partial: bool = False) -> dict:
    """The movement of one metric between two seasons, or why there isn't one."""
    if "not_calculated" in earlier or "not_calculated" in later:
        return _refused(Refusal(
            code=METRIC_MISSING_IN_A_SEASON,
            detail=(
                f"{METRIC_LABELS.get(key, key)} is not calculated in both seasons, so "
                "there is nothing to compare."
            ),
        ))
    if earlier.get("unit") != later.get("unit"):
        return _refused(Refusal(
            code=INCOMPARABLE_UNITS,
            detail=(
                f"{METRIC_LABELS.get(key, key)} is recorded as "
                f"{earlier.get('unit')!r} in one season and {later.get('unit')!r} in "
                "the other. Nothing here converts between them."
            ),
        ))
    delta = later["value"] - earlier["value"]
    payload = {
        "from_value": earlier["value"],
        "to_value": later["value"],
        "delta": round(delta, 2),
        "direction": "unchanged" if delta == 0 else ("up" if delta > 0 else "down"),
        "unit": later.get("unit"),
        "higher_is_better": HIGHER_IS_BETTER.get(key),
        "compares_a_season_in_progress": partial,
        "basis_text": (
            "The change between the two most recent seasons with a comparable figure. "
            "A movement in the records, not a demonstrated cause."
            + (
                " The later season is STILL IN PROGRESS, so its costs and yield are "
                "only what has been recorded so far — a partial season understates "
                "cost and overstates any per-unit figure derived from it."
                if partial else ""
            )
        ),
    }
    # A percentage against a zero baseline is a division by zero dressed up as growth.
    if earlier["value"] != 0:
        payload["delta_pct"] = round(delta / abs(earlier["value"]) * 100, 1)
    return payload


def _comparison_pair(seasons: list[dict]):
    """(later, earlier, is_partial) — the two seasons a trend compares, or Nones."""
    closed = [s for s in seasons if s.get("is_closed")]
    if len(closed) >= 2:
        return closed[0], closed[1], False
    if len(seasons) >= 2:
        return seasons[0], seasons[1], not seasons[0].get("is_closed")
    return None, None, False


def _trends(seasons: list[dict]) -> dict:
    """Compare two seasons — preferring two CLOSED ones.

    A season still in progress has recorded only part of its costs and part of its
    harvest, so comparing it against a finished season flatters it on every cost
    metric and every per-unit figure derived from one. Two closed seasons are
    therefore always preferred; when only one is closed the comparison still runs
    (it is better than nothing) but every trend carries
    `compares_a_season_in_progress` and says so in its own basis text.
    """
    later, earlier, partial = _comparison_pair(seasons)
    if later is None:
        absent = _refused(Refusal(
            code=INSUFFICIENT_COMPARABLE_SEASONS,
            detail=(
                "A trend needs two seasons of records on this farm. Comparisons "
                "appear as more crop cycles are closed."
            ),
        ))
        return {key: dict(absent) for key in METRIC_LABELS}

    return {
        key: _trend(
            key,
            earlier["metrics"].get(key, {}),
            later["metrics"].get(key, {}),
            partial=partial,
        )
        for key in METRIC_LABELS
    }


def _trend_comparison(seasons: list[dict]) -> dict | None:
    """Which two seasons the trends compare, so a surface can name them."""
    later, earlier, partial = _comparison_pair(seasons)
    if later is None:
        return None
    return {
        "later_season": later.get("season_label") or later.get("season_year"),
        "earlier_season": earlier.get("season_label") or earlier.get("season_year"),
        "later_crop_cycle_id": later.get("crop_cycle_id"),
        "earlier_crop_cycle_id": earlier.get("crop_cycle_id"),
        "compares_a_season_in_progress": partial,
    }


# ----------------------------------------------------------------------- build
def build_performance(
    *,
    farm,
    closeouts: list[dict],
    decisions_by_cycle: dict | None = None,
    follow_ups_by_decision: dict | None = None,
    block_outcomes_by_cycle: dict | None = None,
    today: date,
) -> dict:
    """The farm's own performance history. Newest season first.

    `closeouts` are `season_closeout.build_closeout` payloads, one per crop cycle.
    """
    decisions_by_cycle = decisions_by_cycle or {}
    block_outcomes_by_cycle = block_outcomes_by_cycle or {}

    ordered = sorted(
        closeouts or [],
        key=lambda c: (c.get("season_year") or 0, c.get("crop_cycle_id") or 0),
        reverse=True,
    )
    seasons = [
        _season(
            closeout,
            decisions_by_cycle.get(closeout.get("crop_cycle_id"), []),
            follow_ups_by_decision or {},
            block_outcomes_by_cycle.get(closeout.get("crop_cycle_id"), []),
        )
        for closeout in ordered
    ]

    return {
        "model_version": MODEL_VERSION,
        "farm_id": getattr(farm, "id", None),
        "currency": currency_for(farm),
        "as_of": today.isoformat(),
        "season_count": len(seasons),
        "closed_season_count": sum(1 for s in seasons if s["is_closed"]),
        "seasons": seasons,
        "trends": _trends(seasons),
        "trend_comparison": _trend_comparison(seasons),
        "metric_labels": METRIC_LABELS,
        "higher_is_better": HIGHER_IS_BETTER,
        "comparison_basis": (
            "This farm compared against its own previous seasons. There is no "
            "cross-farm benchmark: Lumos has no comparable population, and a "
            "percentile against one would be invented."
        ),
        "disclaimer": PERFORMANCE_DISCLAIMER,
    }
