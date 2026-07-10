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

# Shared honest-framing disclaimer for the concierge case study.
CASE_STUDY_DISCLAIMER = (
    "Decision support only — not a guarantee of pesticide reduction and not a compliance or "
    "legal guarantee. Confirm PHI, REI, and label requirements with a licensed advisor and the "
    "product label."
)


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


# Recorded real-world outcomes for a planned spray (mirrors schemas.PlannedSprayOutcome).
_PLANNED_OUTCOMES = (
    "sprayed_as_planned", "changed_product", "delayed", "avoided", "inspected_first"
)
# Review statuses that count as a recorded PCA decision on a pre-spray check.
_DECISION_REVIEWED = ("approved", "edited", "rejected")
# Explicit, stated assumption behind the review-minutes-saved estimate. Not a measurement.
ASSUMED_MANUAL_CHECK_MINUTES = 10


def _real_planned(planned_sprays) -> list:
    """Planned sprays excluding demo/simulated records (real pilot decisions only)."""
    return [
        p for p in (planned_sprays or [])
        if getattr(p, "data_source", None) != "demo"
        and getattr(p, "data_confidence", None) != "simulated"
    ]


def _pre_spray_decisions(planned_sprays) -> dict:
    """Minimal pre-spray decision counts for the evidence block.

    Demo/simulated records are excluded — these counts are meant to reflect real pilot
    decisions only. Outcomes are the grower/PCA's decisions that the check documented;
    no causation is claimed and no cost/savings figure is derived.
    """
    real = _real_planned(planned_sprays)
    outcomes = [getattr(p, "outcome", "planned") for p in real]
    reasons = [
        {"outcome": getattr(p, "outcome", None), "reason": getattr(p, "outcome_reason", None)}
        for p in real
        if getattr(p, "outcome_reason", None)
    ]
    block = {"checked": len(real)}
    block.update({o: sum(1 for x in outcomes if x == o) for o in _PLANNED_OUTCOMES})
    block["outcome_reasons"] = reasons
    block["note"] = (
        "Outcomes are grower/PCA decisions that the pre-spray check documented — not "
        "outcomes the check caused. Demo/simulated planned sprays are excluded."
    )
    return block


def build_decision_evidence(planned_sprays, advisor_label: str = "agronomist") -> dict:
    """Aggregate the pre-spray decision workflow into pilot metrics (honest by design).

    Demo/simulated planned sprays are excluded. Every derived number states what it is:
    documented decisions, not caused outcomes; cost *not spent on* avoided applications,
    not net savings; review minutes *estimated from a stated assumption*, not measured.
    """
    all_planned = list(planned_sprays or [])
    real = _real_planned(planned_sprays)
    outcomes = {o: 0 for o in _PLANNED_OUTCOMES}
    for p in real:
        o = getattr(p, "outcome", "planned")
        if o in outcomes:
            outcomes[o] += 1
    pending = len(real) - sum(outcomes.values())

    # Reconciliation for demo farms: seeded decisions are visible in the queue but
    # excluded from every real metric — count them separately so the two views agree.
    demo = [p for p in all_planned if p not in real]
    demo_outcomes = {o: 0 for o in _PLANNED_OUTCOMES}
    for p in demo:
        o = getattr(p, "outcome", "planned")
        if o in demo_outcomes:
            demo_outcomes[o] += 1

    reviewed = [p for p in real if getattr(p, "review_status", None) in _DECISION_REVIEWED]
    accepted = sum(
        1 for p in reviewed if getattr(p, "review_status", None) in ("approved", "edited")
    )
    acceptance_rate_pct = (
        round(100.0 * accepted / len(reviewed), 1) if reviewed else None
    )

    conflicts_caught = sum(
        1 for p in real if getattr(p, "decision_severity", None) == "critical"
    )

    # Chemical cost NOT spent on avoided applications (entered estimates only).
    avoided_cost = sum(
        float(getattr(p, "estimated_cost", None) or 0.0)
        for p in real
        if getattr(p, "outcome", None) == "avoided"
    )

    review_minutes_estimate = len(real) * ASSUMED_MANUAL_CHECK_MINUTES

    limitations = [
        "Outcomes are grower/PCA decisions that the check documented — not outcomes the "
        "check caused. This is workflow evidence, not a controlled study.",
        "Estimated chemical cost avoided sums the user-entered cost estimates of avoided "
        "applications — chemicals not applied, not a net-savings or yield claim.",
        (
            f"Review time uses a stated assumption ({ASSUMED_MANUAL_CHECK_MINUTES} min per "
            f"manual PHI/REI/rotation cross-check), not a measurement."
        ),
        "PHI/REI inputs are user-entered, not label-verified.",
    ]
    if not real:
        limitations.insert(0, "No real (non-demo) pre-spray decisions recorded yet.")

    return {
        "decisions_checked": len(real),
        "demo_decisions_checked": len(demo),
        "demo_outcomes": demo_outcomes,
        "decisions_reviewed": len(reviewed),
        "pca_acceptance_rate_pct": acceptance_rate_pct,
        "outcomes": {**outcomes, "awaiting_outcome": pending},
        "sprays_changed_delayed_or_avoided": (
            outcomes["changed_product"] + outcomes["delayed"] + outcomes["avoided"]
        ),
        "compliance_conflicts_caught": conflicts_caught,
        "estimated_chemical_cost_avoided": round(avoided_cost, 2) if avoided_cost else 0.0,
        "estimated_review_minutes_saved": review_minutes_estimate,
        "review_minutes_assumption": (
            f"Assumes ~{ASSUMED_MANUAL_CHECK_MINUTES} minutes per manual "
            f"PHI/REI/rotation cross-check a {advisor_label} would otherwise do by hand. "
            f"Stated assumption, not a measurement."
        ),
        "advisor_label": advisor_label,
        "limitations": limitations,
    }


def build_instrumentation_summary(planned_sprays, events) -> dict:
    """Pilot workflow telemetry: how the check→review→outcome loop is actually used.

    Internal-only. Demo/simulated planned sprays are excluded from timing and
    decision-changed stats (their timestamps are seeded); raw event counts include
    everything and say so.
    """
    events = list(events or [])
    real = _real_planned(planned_sprays)

    counts: dict[str, int] = {}
    for e in events:
        t = getattr(e, "event_type", None)
        if t:
            counts[t] = counts.get(t, 0) + 1

    started = counts.get("check_started", 0)
    completed = counts.get("check_completed", 0)
    abandoned = counts.get("check_abandoned", 0)

    reviewed = [
        p for p in real
        if getattr(p, "reviewed_at", None) and getattr(p, "created_at", None)
    ]
    review_seconds = sorted(
        (p.reviewed_at - p.created_at).total_seconds() for p in reviewed
    )
    median_seconds_to_review = (
        round(review_seconds[len(review_seconds) // 2], 1) if review_seconds else None
    )

    recorded = [p for p in real if getattr(p, "outcome", "planned") != "planned"]
    decisions_changed = sum(
        1 for p in recorded if getattr(p, "outcome", None) != "sprayed_as_planned"
    )

    entry_sources: dict[str, int] = {}
    for p in real:
        src = getattr(p, "data_source", None) or "unknown"
        entry_sources[src] = entry_sources.get(src, 0) + 1

    return {
        "event_counts": counts,
        "checks_started": started,
        "checks_completed": completed,
        "checks_abandoned": abandoned,
        "abandonment_rate_pct": (
            round(100.0 * abandoned / started, 1) if started else None
        ),
        "median_seconds_to_pca_review": median_seconds_to_review,
        "outcomes_recorded": len(recorded),
        "decisions_changed": decisions_changed,
        "entry_source_breakdown": entry_sources,
        "notes": [
            "Internal workflow telemetry, not customer-facing metrics.",
            "Timing, decision-changed, and entry-source stats exclude demo/simulated "
            "planned sprays; raw event counts include every logged event.",
            "check_started and check_abandoned are client-reported and best-effort; "
            "check_completed, review_recorded, and outcome_recorded are logged "
            "server-side and complete.",
        ],
    }


def build_pilot_evidence(
    farm,
    spray_events,
    scout_observations,
    recommendations,
    analytics: dict,
    weather_risk_level: str,
    advisor_label: str = "agronomist",
    today: date | None = None,
    reduction: dict | None = None,
    planned_sprays=None,
) -> dict:
    """Aggregate descriptive pilot evidence for one farm.

    `analytics` is the output of `compute_cost_analytics`; `weather_risk_level` is the
    weather module's risk_level string ("low" / "moderate" / "elevated"). `reduction` is the
    optional output of `compute_reduction` — when a baseline exists it adds a measured
    sprays-vs-baseline bullet instead of only the descriptive picture.
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

    has_measured_reduction = bool(
        reduction and reduction.get("has_baseline") and reduction.get("reduction_pct") is not None
    )

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

    if has_measured_reduction:
        evidence_summary.append(reduction["reduction_statement"])
        investor_summary.insert(0, reduction["reduction_statement"])
    else:
        limitations.insert(
            0,
            "No baseline captured yet, so actual spray reduction is not computed — this is a "
            "descriptive picture, not a before/after result.",
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
        "has_measured_reduction": has_measured_reduction,
        "reduction": reduction,
        "pre_spray_decisions": _pre_spray_decisions(planned_sprays),
        "evidence_summary": evidence_summary,
        "investor_summary": investor_summary,
        "limitations": limitations,
    }


def _iso_dt(value):
    """ISO-format a datetime/date, passing through None."""
    return value.isoformat() if value is not None else None


def build_pilot_case_study(
    evidence: dict,
    data_sources: list[str],
    data_confidences: list[str],
    advisor_label: str = "agronomist",
    import_batches=None,
) -> dict:
    """Shape a concise, one-page case study from an already-built pilot-evidence dict.

    `data_sources` / `data_confidences` are the distinct provenance tags found on the
    farm's records (e.g. ["spreadsheet", "whatsapp"]). `import_batches` is an optional
    newest-first list of concierge import batches (duck-typed). Reuses the evidence metrics
    rather than recomputing them.
    """
    pilot_data_source = data_sources or ["demo"]
    surfaced = _what_lumos_surfaced(evidence, advisor_label)
    unknown = _what_is_still_unknown(evidence, data_confidences)

    import_batches = list(import_batches or [])
    latest = import_batches[0] if import_batches else None

    return {
        "farm_name": evidence["farm_name"],
        "crop": evidence["crop"],
        "location": evidence["location"],
        "pilot_data_source": pilot_data_source,
        "data_confidence_levels": data_confidences or ["simulated"],
        "pilot_import_batches_count": len(import_batches),
        "latest_import_source_label": getattr(latest, "source_label", None),
        "latest_imported_by": getattr(latest, "imported_by", None),
        "latest_import_notes": getattr(latest, "notes", None),
        "latest_imported_at": _iso_dt(getattr(latest, "created_at", None)),
        "pilot_period_start": evidence["pilot_period_start"],
        "pilot_period_end": evidence["pilot_period_end"],
        "spray_events_analyzed": evidence["total_spray_events"],
        "scouting_observations_analyzed": evidence["total_scouting_observations"],
        "scouting_backed_sprays": evidence["sprays_with_recent_scouting_count"],
        "sprays_without_recent_scouting": evidence["sprays_without_recent_scouting_count"],
        "phi_rei_flags": evidence["phi_rei_risk_flags_count"],
        "resistance_flags": evidence["resistance_or_repeated_active_ingredient_flags_count"],
        "weather_risk_flags": evidence["weather_risk_flags_count"],
        "pca_review_status_summary": (
            f"{evidence['pca_approved_count']} approved · "
            f"{evidence['pca_pending_count']} pending · "
            f"{evidence['pca_changes_requested_count']} changes requested "
            f"(of {evidence['total_recommendations']} recommendation(s))"
        ),
        "estimated_avoidable_cost_usd": evidence["estimated_avoidable_cost_usd"],
        "measured_reduction": _measured_reduction_block(evidence),
        "what_lumos_helped_surface": surfaced,
        "what_is_still_unknown": unknown,
        "quote_placeholder": (
            "\"<Add a short grower/PCA quote from your pilot call here — e.g. what surprised "
            "them or what they'd want next.>\""
        ),
        "disclaimer": CASE_STUDY_DISCLAIMER,
    }


def _what_lumos_surfaced(evidence: dict, advisor_label: str) -> list[str]:
    out: list[str] = []
    if evidence["phi_rei_risk_flags_count"]:
        out.append(
            f"Surfaced {evidence['phi_rei_risk_flags_count']} PHI/REI timing risk(s) before "
            f"harvest or worker re-entry."
        )
    if evidence["resistance_or_repeated_active_ingredient_flags_count"]:
        out.append("Flagged repeated active-ingredient (resistance) pressure for rotation.")
    if evidence["sprays_without_recent_scouting_count"]:
        out.append(
            f"Identified {evidence['sprays_without_recent_scouting_count']} spray(s) made "
            f"without recent scouting evidence — candidate calendar-habit sprays."
        )
    if evidence["weather_risk_flags_count"]:
        out.append("Flagged weather-driven disease pressure where over-spraying often happens.")
    if evidence["total_agronomist_reviews"]:
        out.append(
            f"Recorded {evidence['total_agronomist_reviews']} {advisor_label} review "
            f"decision(s) as an audit trail."
        )
    if not out:
        out.append(
            f"Captured a clean baseline of {evidence['total_spray_events']} spray(s) and "
            f"{evidence['total_scouting_observations']} scouting note(s) for {advisor_label} review."
        )
    return out


def _measured_reduction_block(evidence: dict) -> dict | None:
    """Compact reduction summary for the one-pager, or None if no baseline is set."""
    reduction = evidence.get("reduction")
    if not reduction or not reduction.get("has_baseline"):
        return None
    return {
        "baseline_method": reduction.get("baseline_method"),
        "baseline_confidence": reduction.get("baseline_confidence"),
        "baseline_expected_sprays": reduction.get("baseline_expected_sprays"),
        "actual_sprays": reduction.get("actual_sprays"),
        "sprays_avoided": reduction.get("sprays_avoided"),
        "reduction_pct": reduction.get("reduction_pct"),
        "is_headline_safe": reduction.get("is_headline_safe"),
        "statement": reduction.get("reduction_statement"),
        "caveats": reduction.get("confidence_caveats", []),
    }


def _what_is_still_unknown(evidence: dict, data_confidences: list[str]) -> list[str]:
    if evidence.get("has_measured_reduction"):
        out = [
            "Reduction is measured against a stated baseline, not a controlled trial — confirm "
            "the baseline with the grower/PCA and re-measure over a full crop cycle.",
        ]
    else:
        out = [
            "Pre-Lumos baseline spray count is not captured yet, so actual reduction cannot be "
            "computed — this is a starting picture, not a before/after result.",
        ]
    if any(c in ("simulated", "incomplete") for c in data_confidences):
        out.append(
            "Some records are simulated or incomplete — treat the numbers as illustrative until "
            "confirmed with the grower/PCA."
        )
    if not evidence["total_recommendations"]:
        out.append("No recommendation has been reviewed yet — the approval trail is empty.")
    if evidence["estimated_avoidable_cost_usd"] is None:
        out.append("Avoidable cost not estimated (no USD cost data, or a non-USD farm).")
    # Carry through the evidence-level limitations so the one-pager stays honest.
    out.extend(evidence.get("limitations", [])[:2])
    return out


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
