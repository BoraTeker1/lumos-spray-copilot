"""Pilot-evidence aggregation (framework-free, easy to unit test).

This module turns a farm's existing records (sprays, scouting, recommendations,
cost analytics, weather) into a single, descriptive "what did the pilot show?" object
for the farm-detail Pilot Evidence card and a YC/investor talking-point summary.

Design rules (same spirit as `recommendation_engine.py` / `analytics.py`):
* No FastAPI / SQLAlchemy imports — it reads plain objects via duck typing.
* It is **descriptive, not a claim**. It never asserts guaranteed pesticide reduction,
  never prescribes a spray, and always carries explicit `limitations`.
* All counts are deterministic given the same inputs and `today`.
"""
from __future__ import annotations

from datetime import date

from app.recommendation_engine import RECENT_WINDOW_DAYS, generate_recommendation

# Recommendation statuses that represent a recorded advisor decision (an audit trail entry).
_REVIEWED_STATUSES = ("approved", "edited", "rejected")


def _all_record_dates(spray_events, scout_observations) -> list[date]:
    dates: list[date] = []
    for s in spray_events:
        d = getattr(s, "application_date", None)
        if d is not None:
            dates.append(d)
    for o in scout_observations:
        d = getattr(o, "observation_date", None)
        if d is not None:
            dates.append(d)
    return dates


def _scouting_backed(spray, scout_observations) -> bool:
    """True if any scouting note falls within RECENT_WINDOW_DAYS before/at the spray date."""
    applied = getattr(spray, "application_date", None)
    if applied is None:
        return False
    for o in scout_observations:
        obs_date = getattr(o, "observation_date", None)
        if obs_date is None:
            continue
        if 0 <= (applied - obs_date).days <= RECENT_WINDOW_DAYS:
            return True
    return False


def build_pilot_evidence(
    farm,
    spray_events,
    scout_observations,
    recommendations,
    analytics: dict,
    weather_risk_level: str,
    advisor_label: str = "agronomist",
    today: date | None = None,
) -> dict:
    """Aggregate descriptive pilot evidence for one farm.

    `analytics` is the output of `compute_cost_analytics`; `weather_risk_level` is the
    weather module's risk_level string ("low" / "moderate" / "elevated").
    """
    if today is None:
        today = date.today()

    spray_events = list(spray_events or [])
    scout_observations = list(scout_observations or [])
    recommendations = list(recommendations or [])

    # Re-run the rule engine (does not persist) for current PHI / REI / resistance signals.
    signals = generate_recommendation(farm, spray_events, scout_observations, today=today).signals

    total_sprays = len(spray_events)
    total_obs = len(scout_observations)
    total_recs = len(recommendations)

    # Pilot window inferred from the records themselves.
    record_dates = _all_record_dates(spray_events, scout_observations)
    period_start = min(record_dates).isoformat() if record_dates else None
    period_end = max(record_dates).isoformat() if record_dates else None

    # Scouting-backed vs. scouting-light sprays.
    with_scouting = sum(1 for s in spray_events if _scouting_backed(s, scout_observations))
    without_scouting = total_sprays - with_scouting

    # Risk-flag counts (each currently-active aggregate signal counts once).
    phi_rei_flags = int(bool(signals.get("phi_risk"))) + int(bool(signals.get("rei_risk")))
    resistance_flags = int(bool(signals.get("repeated_active_ingredient_risk")))
    weather_flags = 1 if weather_risk_level in ("moderate", "elevated") else 0

    # Advisor review trail (an "audit-ready" count, not a quality claim).
    statuses = [getattr(r, "agronomist_status", "pending") for r in recommendations]
    reviews = sum(1 for s in statuses if s in _REVIEWED_STATUSES)
    pca_pending = sum(1 for s in statuses if s == "pending")
    pca_approved = sum(1 for s in statuses if s == "approved")
    # "Changes requested" = advisor did not approve as-drafted (edited the wording or rejected it).
    pca_changes_requested = sum(1 for s in statuses if s in ("edited", "rejected"))

    # Avoidable cost is only labelled in USD; we surface it for U.S. farms with cost data.
    is_us = (getattr(farm, "country", "") or "").upper() in ("US", "USA")
    avoidable = analytics.get("potential_avoidable_cost") or 0.0
    estimated_avoidable_cost_usd = (
        round(float(avoidable), 2) if (is_us and total_sprays and avoidable) else None
    )

    advisor_cap = advisor_label[:1].upper() + advisor_label[1:]

    evidence_summary = _evidence_summary(
        advisor_cap=advisor_cap,
        total_sprays=total_sprays,
        total_obs=total_obs,
        period_start=period_start,
        period_end=period_end,
        with_scouting=with_scouting,
        without_scouting=without_scouting,
        phi_rei_flags=phi_rei_flags,
        resistance_flags=resistance_flags,
        reviews=reviews,
        total_recs=total_recs,
        estimated_avoidable_cost_usd=estimated_avoidable_cost_usd,
    )
    investor_summary = _investor_summary(
        advisor_label=advisor_label,
        total_sprays=total_sprays,
        phi_rei_flags=phi_rei_flags,
        resistance_flags=resistance_flags,
        reviews=reviews,
        without_scouting=without_scouting,
        estimated_avoidable_cost_usd=estimated_avoidable_cost_usd,
    )
    limitations = _limitations(
        advisor_label=advisor_label,
        total_sprays=total_sprays,
        total_recs=total_recs,
        estimated_avoidable_cost_usd=estimated_avoidable_cost_usd,
    )

    return {
        "farm_id": getattr(farm, "id", None),
        "farm_name": getattr(farm, "name", None),
        "crop": getattr(farm, "crop_type", None),
        "location": getattr(farm, "location", None),
        "pilot_period_start": period_start,
        "pilot_period_end": period_end,
        "total_spray_events": total_sprays,
        "total_scouting_observations": total_obs,
        "total_recommendations": total_recs,
        "total_agronomist_reviews": reviews,
        "sprays_with_recent_scouting_count": with_scouting,
        "sprays_without_recent_scouting_count": without_scouting,
        "phi_rei_risk_flags_count": phi_rei_flags,
        "resistance_or_repeated_active_ingredient_flags_count": resistance_flags,
        "weather_risk_flags_count": weather_flags,
        "pca_pending_count": pca_pending,
        "pca_approved_count": pca_approved,
        "pca_changes_requested_count": pca_changes_requested,
        "estimated_avoidable_cost_usd": estimated_avoidable_cost_usd,
        "evidence_summary": evidence_summary,
        "investor_summary": investor_summary,
        "limitations": limitations,
    }


def _evidence_summary(
    *,
    advisor_cap: str,
    total_sprays: int,
    total_obs: int,
    period_start: str | None,
    period_end: str | None,
    with_scouting: int,
    without_scouting: int,
    phi_rei_flags: int,
    resistance_flags: int,
    reviews: int,
    total_recs: int,
    estimated_avoidable_cost_usd: float | None,
) -> list[str]:
    window = (
        f"{period_start} → {period_end}" if period_start and period_end else "the pilot so far"
    )
    bullets = [
        f"{total_sprays} spray events and {total_obs} scouting observations recorded over {window}.",
        (
            f"{with_scouting} of {total_sprays} sprays had scouting evidence within "
            f"{RECENT_WINDOW_DAYS} days beforehand; {without_scouting} did not — "
            f"this is where avoidable, calendar-habit spraying tends to hide."
        )
        if total_sprays
        else "No sprays logged yet — nothing to assess for scouting-backed spraying.",
        (
            f"{phi_rei_flags} PHI/REI timing risk(s) currently flagged before harvest or "
            f"worker re-entry."
            if phi_rei_flags
            else "No PHI or REI timing risks flagged from current records."
        ),
        (
            "Repeated active-ingredient (resistance) risk is currently flagged — same chemistry "
            "used too often in the window."
            if resistance_flags
            else "No repeated active-ingredient / resistance risk flagged right now."
        ),
        (
            f"{reviews} of {total_recs} recommendations carry a recorded {advisor_cap.lower()} "
            f"review decision (the audit trail)."
            if total_recs
            else f"No recommendations generated yet — generate one and have the {advisor_cap.lower()} "
            f"review it to start the audit trail."
        ),
    ]
    if estimated_avoidable_cost_usd is not None:
        bullets.append(
            f"~${estimated_avoidable_cost_usd:.2f} potential avoidable cost if a single "
            f"unnecessary spray were prevented (illustrative, not a guarantee)."
        )
    return bullets


def _investor_summary(
    *,
    advisor_label: str,
    total_sprays: int,
    phi_rei_flags: int,
    resistance_flags: int,
    reviews: int,
    without_scouting: int,
    estimated_avoidable_cost_usd: float | None,
) -> list[str]:
    bullets = [
        (
            f"Captures the exact spray decisions a {advisor_label} reviews — {total_sprays} sprays, "
            f"{phi_rei_flags + resistance_flags} PHI/REI/resistance flag(s), {reviews} recorded "
            f"review(s) — as structured, exportable evidence rather than notebooks and texts."
        ),
        (
            f"Human-in-the-loop by design: every recommendation is gated behind a {advisor_label} "
            f"sign-off — we never autonomously prescribe a spray."
        ),
        (
            f"{without_scouting} spray(s) had no recent scouting behind them — the kind of "
            f"calendar-habit spraying a pilot is meant to measure and reduce over time."
        ),
    ]
    if estimated_avoidable_cost_usd is not None:
        bullets.append(
            f"Surfaces ~${estimated_avoidable_cost_usd:.2f} in potential avoidable cost per "
            f"prevented spray — a measurable pilot metric, framed as potential, not promised."
        )
    return bullets


def _limitations(
    *,
    advisor_label: str,
    total_sprays: int,
    total_recs: int,
    estimated_avoidable_cost_usd: float | None,
) -> list[str]:
    notes = [
        "This is descriptive pilot evidence, not a controlled study — it does NOT prove "
        "pesticide reduction. Real reduction must be measured against a baseline over a full "
        "crop cycle.",
        "Counts reflect only what was entered. Demo/seed farms use simulated data; real-pilot "
        "numbers depend on the grower/PCA actually logging sprays and scouting.",
        "Risk flags are cautious rule-engine signals, not a compliance or legal guarantee — "
        f"confirm PHI, REI, and label requirements with a licensed {advisor_label} and the label.",
        "Weather is a lightweight demo signal, not a calibrated forecast.",
    ]
    if not total_sprays:
        notes.append("No spray history yet — scouting-backed and avoidable-cost metrics are not meaningful.")
    if not total_recs:
        notes.append("No recommendations reviewed yet — the approval trail is empty.")
    if estimated_avoidable_cost_usd is None:
        notes.append("Avoidable cost not estimated (no USD cost data, or this is a non-USD farm).")
    return notes
