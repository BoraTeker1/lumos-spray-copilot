"""Rule-based spray-decision recommendation engine (Lumos v1).

Design notes
------------
* This module is deliberately free of FastAPI and SQLAlchemy imports so it can be unit
  tested with plain Python objects (it only reads attributes via duck typing).
* It is **decision support, not a prescription**. It never tells a farmer to spray and
  never claims a definitive diagnosis. Language stays cautious ("consider", "inspect first",
  "review with your agronomist", "risk appears elevated").
* Each rule appends a human-readable "flag" line and contributes to an overall risk score.
  The score maps to a risk level: low / moderate / elevated.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

# --- Tunable thresholds (kept here so they are easy to find and adjust) -------------
RECENT_WINDOW_DAYS = 30          # how far back we consider sprays/observations "recent"
SAME_INGREDIENT_MAX = 2          # more than this many uses of one AI in the window = over-use
HIGH_SEVERITY_THRESHOLD = 4      # scouting severity (1-5) at/above this is "high"

RISK_LOW = "low"
RISK_MODERATE = "moderate"
RISK_ELEVATED = "elevated"


@dataclass
class RecommendationResult:
    """Plain result object the route layer can persist to a Recommendation row."""
    risk_level: str = RISK_LOW
    flags: list[str] = field(default_factory=list)
    recommendation_text: str = ""


def _recent(items, date_attr: str, today: date):
    """Return items whose `date_attr` falls within the recent window (and not in future)."""
    cutoff = today - timedelta(days=RECENT_WINDOW_DAYS)
    out = []
    for it in items:
        d = getattr(it, date_attr, None)
        if d is not None and cutoff <= d <= today:
            out.append(it)
    return out


def generate_recommendation(
    farm,
    spray_events,
    scout_observations,
    today: date | None = None,
) -> RecommendationResult:
    """Evaluate cautious spray-decision flags for a farm.

    Parameters
    ----------
    farm: object with `expected_harvest_date` (date or None).
    spray_events: iterable of objects with `active_ingredient`, `application_date`,
        `pre_harvest_interval_days`, `product_name`.
    scout_observations: iterable with `observation_date`, `severity_1_to_5`, `visible_issue`.
    today: injectable "current date" for deterministic testing.
    """
    if today is None:
        today = date.today()

    spray_events = list(spray_events or [])
    scout_observations = list(scout_observations or [])

    result = RecommendationResult()
    score = 0

    # --- Rule 1: over-use of the same active ingredient -----------------------------
    recent_sprays = _recent(spray_events, "application_date", today)
    ingredient_counts: dict[str, int] = {}
    for s in recent_sprays:
        ai = (getattr(s, "active_ingredient", None) or "").strip().lower()
        if ai:
            ingredient_counts[ai] = ingredient_counts.get(ai, 0) + 1
    for ai, count in ingredient_counts.items():
        if count > SAME_INGREDIENT_MAX:
            score += 2
            result.flags.append(
                f"The active ingredient '{ai}' appears {count} times in the last "
                f"{RECENT_WINDOW_DAYS} days. Frequent repeat use can raise resistance and "
                f"residue concerns — consider rotating chemistry and review with your agronomist."
            )

    # --- Rule 2: expected harvest falls within a spray's pre-harvest interval -------
    harvest = getattr(farm, "expected_harvest_date", None)
    if harvest is not None:
        for s in spray_events:
            phi = getattr(s, "pre_harvest_interval_days", None)
            applied = getattr(s, "application_date", None)
            if phi and applied:
                phi_clears_on = applied + timedelta(days=phi)
                if harvest < phi_clears_on:
                    score += 3
                    product = getattr(s, "product_name", "a recent product") or "a recent product"
                    result.flags.append(
                        f"Pre-harvest interval risk: '{product}' (PHI {phi} days, applied "
                        f"{applied.isoformat()}) clears on {phi_clears_on.isoformat()}, which is "
                        f"after the expected harvest on {harvest.isoformat()}. Residue risk appears "
                        f"elevated — review harvest timing with your agronomist before picking."
                    )

    # --- Rule 3: high-severity scouting observation ---------------------------------
    recent_obs = _recent(scout_observations, "observation_date", today)
    high_sev = [
        o for o in recent_obs
        if (getattr(o, "severity_1_to_5", None) or 0) >= HIGH_SEVERITY_THRESHOLD
    ]
    for o in high_sev:
        score += 2
        issue = getattr(o, "visible_issue", None) or "an issue"
        sev = getattr(o, "severity_1_to_5", None)
        result.flags.append(
            f"A high-severity scouting observation ('{issue}', severity {sev}/5) was logged on "
            f"{getattr(o, 'observation_date').isoformat()}. Pest/disease pressure appears elevated "
            f"— consider a close inspection and review options with your agronomist."
        )

    # --- Rule 4: weak / no evidence -> inspect first --------------------------------
    has_any_signal = bool(result.flags)
    weak_only = bool(recent_obs) and not high_sev and not has_any_signal
    if not has_any_signal:
        if weak_only or recent_obs:
            result.flags.append(
                "Evidence is currently weak or low-severity. Consider inspecting/scouting the "
                "crop first before any spray decision, rather than spraying preventively."
            )
        else:
            result.flags.append(
                "No recent sprays or scouting observations on record. Consider scouting the crop "
                "first to gather evidence before any spray decision."
            )

    # --- Map score to a cautious risk level -----------------------------------------
    if score >= 3:
        result.risk_level = RISK_ELEVATED
    elif score >= 1:
        result.risk_level = RISK_MODERATE
    else:
        result.risk_level = RISK_LOW

    result.recommendation_text = _format_text(result.risk_level, result.flags)
    return result


def _format_text(risk_level: str, flags: list[str]) -> str:
    """Compose the cautious, agronomist-in-the-loop recommendation text."""
    header = {
        RISK_ELEVATED: "Risk appears elevated. Please review the points below with your agronomist.",
        RISK_MODERATE: "Some points are worth attention. Consider reviewing them with your agronomist.",
        RISK_LOW: "No elevated risk detected from current records.",
    }[risk_level]

    lines = [header, ""]
    for i, flag in enumerate(flags, start=1):
        lines.append(f"{i}. {flag}")
    lines.append("")
    lines.append(
        "Note: This is cautious decision support, not a prescription or a diagnosis. "
        "It does not instruct you to spray. Final decisions should be confirmed with a "
        "qualified agronomist."
    )
    return "\n".join(lines)
