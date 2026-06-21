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

# Farmer-facing "next action" strings (the canonical set surfaced in the UI/report).
ACTION_HARVEST_TIMING = "Harvest timing risk — review before picking"
ACTION_REVIEW_AGRONOMIST = "Review with agronomist before spraying"
ACTION_INSPECT_FIRST = "Inspect first"
ACTION_CONTINUE_MONITORING = "Low risk — continue monitoring"


@dataclass
class RecommendationResult:
    """Plain result object the route layer can persist to a Recommendation row."""
    risk_level: str = RISK_LOW
    next_action: str = ACTION_CONTINUE_MONITORING
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
    overuse = False
    phi_risk = False

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
            overuse = True
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
                    phi_risk = True
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

    # --- Rule 4: weak / no evidence -> inspect or keep monitoring --------------------
    has_concern = bool(result.flags)
    has_recent_scouting = bool(recent_obs)
    if not has_concern:
        if has_recent_scouting:
            result.flags.append(
                "Recent scouting shows only low-severity issues. Continue monitoring and "
                "inspect again before any spray decision, rather than spraying preventively."
            )
        else:
            result.flags.append(
                "No recent scouting observations on record. Consider scouting the crop "
                "first to gather evidence before any spray decision."
            )

    # --- Map score to a cautious risk level -----------------------------------------
    if score >= 3:
        result.risk_level = RISK_ELEVATED
    elif score >= 1:
        result.risk_level = RISK_MODERATE
    else:
        result.risk_level = RISK_LOW

    # --- Derive the farmer-facing next action from the same rule signals ------------
    result.next_action = _derive_next_action(
        phi_risk=phi_risk,
        overuse=overuse,
        high_sev=bool(high_sev),
        has_recent_scouting=has_recent_scouting,
    )

    result.recommendation_text = _format_text(
        result.risk_level, result.next_action, result.flags
    )
    return result


def _derive_next_action(
    *, phi_risk: bool, overuse: bool, high_sev: bool, has_recent_scouting: bool
) -> str:
    """Map rule signals to one cautious, farmer-friendly next action.

    Priority: harvest/residue safety first, then agronomist review for active concerns,
    then monitoring vs. scouting depending on whether recent scouting data exists.
    """
    if phi_risk:
        return ACTION_HARVEST_TIMING
    if overuse or high_sev:
        return ACTION_REVIEW_AGRONOMIST
    if has_recent_scouting:
        return ACTION_CONTINUE_MONITORING
    return ACTION_INSPECT_FIRST


def _format_text(risk_level: str, next_action: str, flags: list[str]) -> str:
    """Compose the cautious, agronomist-in-the-loop recommendation text."""
    header = {
        RISK_ELEVATED: "Risk appears elevated. Please review the points below with your agronomist.",
        RISK_MODERATE: "Some points are worth attention. Consider reviewing them with your agronomist.",
        RISK_LOW: "No elevated risk detected from current records.",
    }[risk_level]

    lines = [header, f"Suggested next action: {next_action}.", ""]
    for i, flag in enumerate(flags, start=1):
        lines.append(f"{i}. {flag}")
    lines.append("")
    lines.append(
        "Note: This is cautious decision support, not a prescription or a diagnosis. "
        "It does not instruct you to spray. Final decisions should be confirmed with a "
        "qualified agronomist."
    )
    return "\n".join(lines)
