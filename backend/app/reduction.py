"""Reduction-measurement engine (framework-free, easy to unit test).

Turns "potential avoidable cost" (a per-spray illustration) into a *measured* comparison:
how many sprays a farm actually made vs. a stated baseline over an observed window.

Design rules (same spirit as `analytics.py` / `pilot_evidence.py`):
* No FastAPI / SQLAlchemy imports — reads plain objects via duck typing.
* A reduction figure is only as honest as its baseline, so every result carries the baseline
  `method` + `confidence`, an `is_headline_safe` gate, and explicit `confidence_caveats`.
* No baseline → no number. The engine never invents a denominator.
* Negative reduction (they sprayed *more*) is reported honestly, not floored to zero.
* Deterministic given the same inputs and `today`.

Baseline methods (ranked by rigor):
  prior_period     — the grower's own pre-Lumos sprays from a baseline window, scaled to the
                     observed window. Highest rigor (real before/after on their own data).
  stated_cadence   — grower/PCA declares their normal program ("every N days" or "M sprays/season").
  calendar_program — a named schedule (weekly / biweekly / ...) → an implied cadence. Lowest rigor.
"""
from __future__ import annotations

from datetime import date

# Named calendar programs → cadence in days (kept tiny and explicit on purpose).
CALENDAR_PROGRAMS: dict[str, int] = {
    "weekly": 7,
    "every_10_days": 10,
    "biweekly": 14,
    "every_3_weeks": 21,
    "monthly": 30,
}

# Default season length (days) when a farm has no planting/harvest dates to bound it.
DEFAULT_SEASON_DAYS = 180

# Confidence levels rigorous enough to headline a percentage prominently.
_TRUSTED_CONFIDENCE = ("user_provided", "pca_reviewed")

# is_headline_safe thresholds (the anti-overclaim valve).
_MIN_OBSERVED_DAYS = 21
_MIN_ACTUAL_SPRAYS = 3


def _season_days(farm) -> int:
    start = getattr(farm, "planting_date", None)
    end = getattr(farm, "expected_harvest_date", None)
    if start and end:
        days = (end - start).days
        if days > 0:
            return days
    return DEFAULT_SEASON_DAYS


def _baseline_expected(baseline, farm, observed_days: int) -> float | None:
    """Expected number of sprays over `observed_days` implied by the baseline, or None."""
    if observed_days <= 0:
        return None
    method = getattr(baseline, "method", None)

    cadence = getattr(baseline, "cadence_days", None)
    if method == "calendar_program" and cadence is None:
        program = (getattr(baseline, "calendar_program", None) or "").strip().lower()
        cadence = CALENDAR_PROGRAMS.get(program)

    if method in ("stated_cadence", "calendar_program"):
        if cadence and cadence > 0:
            return observed_days / cadence
        season_count = getattr(baseline, "season_spray_count", None)
        if season_count and season_count > 0:
            return season_count * (observed_days / _season_days(farm))
        return None

    if method == "prior_period":
        # Handled by the caller (needs prior-window spray counts), not here.
        return None
    return None


def compute_reduction(
    farm,
    spray_events,
    baseline,
    observed_period_start: date | None = None,
    observed_period_end: date | None = None,
    today: date | None = None,
) -> dict:
    """Measure spray reduction for one farm against its baseline.

    `spray_events` is the farm's full spray list; for `prior_period` baselines the engine
    itself splits them at `baseline_period_end`. For other methods every spray counts as
    "observed". Returns a dict the API/UI/case-study consume directly.
    """
    if today is None:
        today = date.today()
    sprays = list(spray_events or [])
    spray_dates = sorted(s.application_date for s in sprays if getattr(s, "application_date", None))

    empty = _empty_result()
    if baseline is None:
        empty["actual_sprays"] = len(sprays)
        empty["confidence_caveats"] = [
            "No baseline captured yet — set the grower's normal spray cadence or a pre-Lumos "
            "period to measure reduction. Until then this is a starting picture, not a result."
        ]
        return empty

    method = getattr(baseline, "method", None)
    confidence = getattr(baseline, "data_confidence", None)
    source = getattr(baseline, "data_source", None)
    declared_by = getattr(baseline, "declared_by", None)

    if method == "prior_period":
        result = _prior_period(baseline, sprays, observed_period_end, today)
    else:
        # stated_cadence / calendar_program: every logged spray is "observed".
        start = observed_period_start or (spray_dates[0] if spray_dates else None)
        end = observed_period_end or today
        observed_days = (end - start).days if (start and end) else 0
        actual = len(sprays)
        expected = _baseline_expected(baseline, farm, observed_days)
        result = _assemble(actual, expected, start, end, observed_days)

    result.update(
        {
            "has_baseline": True,
            "baseline_method": method,
            "baseline_source": source,
            "baseline_confidence": confidence,
            "declared_by": declared_by,
        }
    )
    result["is_headline_safe"] = _is_headline_safe(result, confidence)
    result["reduction_statement"] = _statement(result, baseline, farm)
    result["confidence_caveats"] = _caveats(result, baseline)
    return result


def _prior_period(baseline, sprays, observed_period_end: date | None, today: date) -> dict:
    """Compare a pre-Lumos baseline window against the observed window on the same farm."""
    b_start = getattr(baseline, "baseline_period_start", None)
    b_end = getattr(baseline, "baseline_period_end", None)
    if not b_end:
        return _assemble(len(sprays), None, None, None, 0)

    prior = [
        s for s in sprays
        if getattr(s, "application_date", None)
        and s.application_date <= b_end
        and (b_start is None or s.application_date >= b_start)
    ]
    observed = [
        s for s in sprays
        if getattr(s, "application_date", None) and s.application_date > b_end
    ]
    obs_end = observed_period_end or today
    observed_days = (obs_end - b_end).days
    actual = len(observed)

    expected = None
    if b_start and observed_days > 0:
        prior_days = (b_end - b_start).days
        if prior_days > 0:
            # Scale the prior spray *rate* onto the observed window length.
            expected = len(prior) * (observed_days / prior_days)
    return _assemble(actual, expected, b_end, obs_end, observed_days)


def _assemble(
    actual: int,
    expected: float | None,
    start: date | None,
    end: date | None,
    observed_days: int,
) -> dict:
    avoided = None
    pct = None
    if expected is not None:
        avoided = round(expected - actual, 2)
        if expected > 0:
            pct = round((expected - actual) / expected * 100, 1)
    return {
        "observed_period_start": start.isoformat() if start else None,
        "observed_period_end": end.isoformat() if end else None,
        "observed_window_days": observed_days if observed_days > 0 else None,
        "baseline_expected_sprays": round(expected, 2) if expected is not None else None,
        "actual_sprays": actual,
        "sprays_avoided": avoided,
        "reduction_pct": pct,
    }


def _is_headline_safe(result: dict, confidence: str | None) -> bool:
    pct = result.get("reduction_pct")
    return (
        confidence in _TRUSTED_CONFIDENCE
        and (result.get("observed_window_days") or 0) >= _MIN_OBSERVED_DAYS
        and result.get("actual_sprays", 0) >= _MIN_ACTUAL_SPRAYS
        and (result.get("baseline_expected_sprays") or 0) >= 1
        # Only an actual reduction is safe to headline — a negative figure (sprayed more) is not.
        and pct is not None
        and pct > 0
    )


def _statement(result: dict, baseline, farm) -> str | None:
    expected = result.get("baseline_expected_sprays")
    pct = result.get("reduction_pct")
    if expected is None or pct is None:
        return None
    method = (getattr(baseline, "method", "") or "").replace("_", " ")
    confidence = (getattr(baseline, "data_confidence", "") or "").replace("_", " ")
    actual = result["actual_sprays"]
    window = result.get("observed_window_days")
    window_txt = f"over ~{window} days" if window else "over the observed window"

    if pct >= 0:
        change = f"about {pct:.0f}% fewer sprays"
    else:
        change = f"about {abs(pct):.0f}% MORE sprays"
    lead = "" if result.get("is_headline_safe") else "Illustrative (early/low-confidence): "
    return (
        f"{lead}{actual} sprays logged {window_txt} vs. a {expected:.0f}-spray baseline "
        f"({method}, {confidence}) — {change}. Measured against a stated baseline, "
        f"not a controlled trial."
    )


def _caveats(result: dict, baseline) -> list[str]:
    out: list[str] = []
    confidence = getattr(baseline, "data_confidence", None)
    method = getattr(baseline, "method", None)

    if result.get("baseline_expected_sprays") is None:
        out.append(
            "Baseline is incomplete (needs a cadence, a season spray count, or a dated prior "
            "period) — reduction cannot be computed yet."
        )
    if confidence not in _TRUSTED_CONFIDENCE:
        out.append(
            f"Baseline confidence is '{confidence}' — treat the figure as illustrative until "
            "the grower/PCA confirms it."
        )
    if (result.get("observed_window_days") or 0) < _MIN_OBSERVED_DAYS:
        out.append(
            f"Observed window is short (<{_MIN_OBSERVED_DAYS} days) — too early for a headline "
            "reduction number."
        )
    if result.get("actual_sprays", 0) < _MIN_ACTUAL_SPRAYS:
        out.append(
            f"Fewer than {_MIN_ACTUAL_SPRAYS} sprays observed — a single spray swings the percentage."
        )
    if method == "calendar_program":
        out.append(
            "Calendar-program baselines assume a fixed schedule the grower may not actually follow "
            "— the lowest-rigor baseline."
        )
    if (result.get("reduction_pct") or 0) < 0:
        out.append("Sprays INCREASED vs. baseline over this window — not a reduction.")
    out.append(
        "Reduction is measured against a stated baseline, not a controlled study, and is not a "
        "guarantee of future reduction."
    )
    return out


def _empty_result() -> dict:
    return {
        "has_baseline": False,
        "baseline_method": None,
        "baseline_source": None,
        "baseline_confidence": None,
        "declared_by": None,
        "observed_period_start": None,
        "observed_period_end": None,
        "observed_window_days": None,
        "baseline_expected_sprays": None,
        "actual_sprays": 0,
        "sprays_avoided": None,
        "reduction_pct": None,
        "reduction_statement": None,
        "is_headline_safe": False,
        "confidence_caveats": [],
    }
