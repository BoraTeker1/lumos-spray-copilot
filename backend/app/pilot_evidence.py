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

from app import decision_status, procurement_status
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
# Explicit, stated assumption behind the review-minutes-saved estimate. Not a measurement.
ASSUMED_MANUAL_CHECK_MINUTES = 10


def _real_planned(planned_sprays) -> list:
    """Planned sprays excluding demo/simulated records (real pilot decisions only)."""
    return [p for p in (planned_sprays or []) if not decision_status.is_demo_record(p)]


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


def derive_follow_up_summary(planned, events) -> dict:
    """Read-only consolidated view of one decision's append-only follow-up timeline.

    Derived, never stored: earlier observations are never overwritten — this just
    reads the event list. "Confirmed" here means "supported by recorded follow-up
    events", not proof of causation.
    """
    events = sorted(
        list(events or []),
        key=lambda e: (getattr(e, "observed_at", None) or date.min, getattr(e, "id", 0)),
    )
    scouting = [e for e in events if e.event_type == "scouting_observation"]
    applications = [e for e in events if e.event_type == "actual_application"]
    rescues = [e for e in events if e.event_type == "rescue_application"]
    outcome_events = [
        e for e in events
        if e.event_type in ("harvest_outcome", "yield_quality_outcome")
    ]

    def _latest_impact(attr: str) -> str:
        for e in reversed(outcome_events):
            value = getattr(e, attr, None)
            if value:
                return value
        return "unknown"

    severities = [e.severity for e in scouting if e.severity is not None]
    rescue_required = bool(rescues) or any(
        e.rescue_required for e in events if e.rescue_required
    )
    rejected_flags = [
        e.rejected_or_downgraded for e in events if e.rejected_or_downgraded is not None
    ]
    scouting_cost = sum(float(e.cost or 0.0) for e in scouting)
    application_cost = sum(float(e.cost or 0.0) for e in applications)
    rescue_cost = sum(float(e.cost or 0.0) for e in rescues)

    ultimately_applied = bool(applications) or bool(rescues)
    outcome = getattr(planned, "outcome", "planned")

    first_application_date = (
        applications[0].observed_at if applications else None
    )
    confirmed_delay_days = None
    if outcome == "delayed" and first_application_date is not None:
        confirmed_delay_days = max(
            0, (first_application_date - planned.intended_date).days
        )

    return {
        "has_follow_up": bool(events),
        "event_count": len(events),
        "event_types": sorted({e.event_type for e in events}),
        "severity_before": severities[0] if severities else None,
        "severity_after": severities[-1] if len(severities) > 1 else None,
        "spray_ultimately_applied": ultimately_applied if events else None,
        "rescue_required": rescue_required if events else None,
        "confirmed_avoided": (
            outcome == "avoided" and bool(events) and not ultimately_applied
        ),
        "confirmed_replacement": (
            outcome == "changed_product"
            and (bool(applications) or getattr(planned, "spray_event_id", None) is not None)
        ),
        "confirmed_delay_days": confirmed_delay_days,
        "additional_scouting_cost": round(scouting_cost, 2),
        "application_cost": round(application_cost, 2),
        "rescue_cost": round(rescue_cost, 2),
        "yield_impact": _latest_impact("yield_impact") if events else "unknown",
        "quality_impact": _latest_impact("quality_impact") if events else "unknown",
        "rejected_or_downgraded": rejected_flags[-1] if rejected_flags else None,
        "note": (
            "Derived read-only from the append-only follow-up timeline. 'Confirmed' "
            "means supported by recorded follow-up events — correlation, not proof of "
            "causation."
        ),
    }


def _confirmed_and_estimated(real_planned, follow_ups_by_id: dict) -> tuple[dict, dict, dict]:
    """(confirmed, estimated, follow_up_stats) metric blocks from non-demo decisions.

    Confirmed figures come ONLY from follow-up-backed summaries; estimated figures are
    entered values without follow-up support. The two are never mixed or combined
    into a score.
    """
    summaries = {
        p.id: derive_follow_up_summary(p, follow_ups_by_id.get(p.id, []))
        for p in real_planned
    }

    confirmed_avoided = [p for p in real_planned if summaries[p.id]["confirmed_avoided"]]
    confirmed_avoided_acres = sum(
        float(getattr(p, "treated_acres", None) or 0.0) for p in confirmed_avoided
    )
    delays = [
        summaries[p.id]["confirmed_delay_days"]
        for p in real_planned
        if summaries[p.id]["confirmed_delay_days"] is not None
    ]
    replacements = [p for p in real_planned if summaries[p.id]["confirmed_replacement"]]
    rescued = [p for p in real_planned if summaries[p.id]["rescue_required"]]

    gross_avoided = sum(
        float(getattr(p, "estimated_cost", None) or 0.0) for p in confirmed_avoided
    )
    scouting_cost = sum(s["additional_scouting_cost"] for s in summaries.values())
    rescue_cost = sum(s["rescue_cost"] for s in summaries.values())
    replacement_cost = sum(
        summaries[p.id]["application_cost"] for p in replacements
    )
    net = gross_avoided - scouting_cost - rescue_cost

    with_follow_up = [p for p in real_planned if summaries[p.id]["has_follow_up"]]
    yield_counts = {"positive": 0, "neutral": 0, "negative": 0, "unknown": 0}
    quality_counts = {"positive": 0, "neutral": 0, "negative": 0, "unknown": 0}
    rejected = 0
    for p in with_follow_up:
        s = summaries[p.id]
        yield_counts[s["yield_impact"]] = yield_counts.get(s["yield_impact"], 0) + 1
        quality_counts[s["quality_impact"]] = (
            quality_counts.get(s["quality_impact"], 0) + 1
        )
        if s["rejected_or_downgraded"]:
            rejected += 1

    confirmed = {
        "applications_confirmed_avoided": len(confirmed_avoided),
        "treated_acres_confirmed_avoided": round(confirmed_avoided_acres, 2),
        "confirmed_delay_days_total": sum(delays) if delays else 0,
        "confirmed_delayed_decisions": len(delays),
        "confirmed_replacement_applications": len(replacements),
        "confirmed_rescue_treatments": len(rescued),
        "confirmed_gross_spend_avoided": round(gross_avoided, 2),
        "confirmed_additional_scouting_cost": round(scouting_cost, 2),
        "confirmed_replacement_application_cost": round(replacement_cost, 2),
        "confirmed_rescue_cost": round(rescue_cost, 2),
        "confirmed_net_financial_result": round(net, 2),
        "yield_impact_counts": yield_counts,
        "quality_impact_counts": quality_counts,
        "rejected_or_downgraded_count": rejected,
        "basis": (
            "Only decisions with recorded follow-up events count here. 'Gross spend "
            "avoided' sums the entered planned costs of follow-up-confirmed avoided "
            "applications; net = gross avoided - additional scouting - rescue costs. "
            "Replacement application costs are reported separately, not netted. A "
            "negative net is reported as negative."
        ),
    }

    # Estimated: entered values with NO follow-up support (never mixed with confirmed).
    est_avoided_unconfirmed = [
        p for p in real_planned
        if getattr(p, "outcome", None) == "avoided"
        and not summaries[p.id]["confirmed_avoided"]
    ]
    estimated = {
        "planned_application_cost_total": round(
            sum(float(getattr(p, "estimated_cost", None) or 0.0) for p in real_planned), 2
        ),
        "potential_gross_savings_unconfirmed": round(
            sum(
                float(getattr(p, "estimated_cost", None) or 0.0)
                for p in est_avoided_unconfirmed
            ), 2
        ),
        "avoided_outcomes_without_follow_up": len(est_avoided_unconfirmed),
        "basis": (
            "Entered estimates without follow-up support. A planned avoidance is NOT "
            "a confirmed pesticide reduction until follow-up is recorded."
        ),
    }

    required = [p for p in real_planned if decision_status.follow_up_required(p)]
    completed = [p for p in required if summaries[p.id]["has_follow_up"]]
    follow_up_stats = {
        "follow_up_required": len(required),
        "follow_up_with_events": len(completed),
        "follow_up_completion_rate_pct": (
            round(100.0 * len(completed) / len(required), 1) if required else None
        ),
    }
    return confirmed, estimated, follow_up_stats


# Pesticide-quantity and risk-weighted metrics are deliberately NOT calculated —
# stating why beats publishing a wrong number.
NOT_CALCULATED = {
    "active_ingredient_quantity_avoided": (
        "not calculated — requires normalized rate units and active-ingredient "
        "concentration with conversion provenance, which do not exist yet"
    ),
    "risk_weighted_pesticide_reduction": (
        "not calculated — no authoritative risk-weighting methodology/source is "
        "integrated; a home-made weighting would be misleading"
    ),
}


def _scope_metrics(records, follow_ups_by_id: dict, advisor_label: str) -> dict:
    """The decision-workflow metric block for ONE provenance scope (real OR demo).

    Same shape either way so the two scopes are comparable but never combined:
    the caller labels the demo block `is_simulated` and keeps it separate.
    """
    records = list(records or [])
    outcomes = {o: 0 for o in _PLANNED_OUTCOMES}
    for p in records:
        o = getattr(p, "outcome", "planned")
        if o in outcomes:
            outcomes[o] += 1
    pending = len(records) - sum(outcomes.values())

    reviewed = [
        p for p in records
        if decision_status.review_state(p) in decision_status.RESOLVED_REVIEW_STATUSES
    ]
    accepted = sum(
        1 for p in reviewed
        if decision_status.review_state(p)
        in decision_status.APPLIED_OUTCOME_UNLOCK_STATUSES
    )
    acceptance_rate_pct = (
        round(100.0 * accepted / len(reviewed), 1) if reviewed else None
    )

    # Conflicts the check surfaced, resolved or not (unlike the dashboard's open-only
    # count — decision_status names both semantics).
    conflicts_caught = sum(1 for p in records if decision_status.conflict_caught(p))

    # Chemical cost NOT spent on avoided applications (entered estimates only).
    avoided_cost = sum(
        float(getattr(p, "estimated_cost", None) or 0.0)
        for p in records
        if getattr(p, "outcome", None) == "avoided"
    )

    confirmed, estimated, follow_up_stats = _confirmed_and_estimated(
        records, follow_ups_by_id or {}
    )

    return {
        "decisions_checked": len(records),
        "decisions_reviewed": len(reviewed),
        "pca_acceptance_rate_pct": acceptance_rate_pct,
        "outcomes": {**outcomes, "awaiting_outcome": pending},
        "sprays_changed_delayed_or_avoided": (
            outcomes["changed_product"] + outcomes["delayed"] + outcomes["avoided"]
        ),
        "compliance_conflicts_caught": conflicts_caught,
        "estimated_chemical_cost_avoided": round(avoided_cost, 2) if avoided_cost else 0.0,
        "confirmed": confirmed,
        "estimated": estimated,
        "follow_up": follow_up_stats,
    }


def build_decision_evidence(
    planned_sprays, advisor_label: str = "agronomist", follow_ups_by_id: dict | None = None
) -> dict:
    """Aggregate the pre-spray decision workflow into pilot metrics (honest by design).

    Demo/simulated planned sprays are excluded from every top-level metric. The same
    metric shape computed over demo records only is returned under `demo_metrics`
    (flagged `is_simulated`) so a demo farm can show a coherent simulated story instead
    of contradictory zeros — the two scopes are never combined. Every derived number
    states what it is: documented decisions, not caused outcomes; cost *not spent on*
    avoided applications, not net savings; review minutes *estimated from a stated
    assumption*, not measured.
    """
    all_planned = list(planned_sprays or [])
    real = _real_planned(planned_sprays)
    real_metrics = _scope_metrics(real, follow_ups_by_id or {}, advisor_label)
    outcomes = real_metrics["outcomes"]

    # Reconciliation for demo farms: seeded decisions are visible in the queue but
    # excluded from every real metric — compute the same block separately so the two
    # views agree without ever mixing.
    demo = [p for p in all_planned if p not in real]
    demo_metrics = _scope_metrics(demo, follow_ups_by_id or {}, advisor_label)
    demo_outcomes = {
        o: demo_metrics["outcomes"][o] for o in _PLANNED_OUTCOMES
    }

    review_minutes_estimate = len(real) * ASSUMED_MANUAL_CHECK_MINUTES

    limitations = [
        "Outcomes are grower/PCA decisions that the check documented — not outcomes the "
        "check caused. This is workflow evidence, not a controlled study.",
        "Estimated chemical cost avoided sums the user-entered cost estimates of avoided "
        "applications — chemicals not applied, not a net-savings or yield claim.",
        "Yield impact of avoided applications is not yet known or measured — cost "
        "figures are entered application-cost estimates only.",
        (
            f"Review time uses a stated assumption ({ASSUMED_MANUAL_CHECK_MINUTES} min per "
            f"manual PHI/REI/rotation cross-check), not a measurement."
        ),
        "PHI/REI inputs are user-entered, not label-verified.",
    ]
    if not real:
        limitations.insert(0, "No real (non-demo) pre-spray decisions recorded yet.")

    return {
        # Top-level keys are the REAL scope (unchanged contract).
        **real_metrics,
        "not_calculated": dict(NOT_CALCULATED),
        "demo_decisions_checked": len(demo),
        "demo_outcomes": demo_outcomes,
        # Full simulated-scope block for demo farms — same shape as the real
        # metrics, explicitly flagged, never summed with them.
        "demo_metrics": {
            **demo_metrics,
            "is_simulated": True,
            "note": (
                "Simulated demo records — illustrative of the workflow, never "
                "customer evidence."
            ),
        },
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


# ------------------------------------------------------------- AI calibration
# Below this many follow-up-backed predictions per level, no rate is published —
# counts only. Publishing a "rate" off a handful of cases would be misleading.
CALIBRATION_MIN_N = 10


def build_ai_calibration(judgments, decisions_by_id: dict, follow_ups_by_id: dict) -> dict:
    """Predicted rescue risk vs. realized rescues — the honest 'is the AI any good?' view.

    Internal-only. Judgments tied to demo decisions are excluded (there should be
    none — judgments are never seeded — but the guard is cheap). Rates appear only
    at CALIBRATION_MIN_N follow-up-backed predictions per level; until then the
    report shows counts with an explicit insufficient-data note.
    """
    judgments = list(judgments or [])

    def _is_demo_parent(j) -> bool:
        parent = decisions_by_id.get(j.planned_spray_id)
        return parent is not None and decision_status.is_demo_record(parent)

    real = [j for j in judgments if not _is_demo_parent(j)]
    risk = [j for j in real if j.kind == "risk_note"]
    extraction = [j for j in real if j.kind == "extraction"]
    predictions = [j for j in risk if not j.abstained]

    per_level: dict[str, dict] = {}
    for level in ("low", "medium", "high"):
        level_js = [
            j for j in predictions if (j.output or {}).get("rescue_risk") == level
        ]
        with_follow_up = 0
        realized_rescues = 0
        for j in level_js:
            parent = decisions_by_id.get(j.planned_spray_id)
            if parent is None:
                continue
            summary = derive_follow_up_summary(
                parent, follow_ups_by_id.get(parent.id, [])
            )
            if summary["has_follow_up"]:
                with_follow_up += 1
                if summary["rescue_required"]:
                    realized_rescues += 1
        enough = with_follow_up >= CALIBRATION_MIN_N
        per_level[level] = {
            "predictions": len(level_js),
            "with_follow_up": with_follow_up,
            "realized_rescues": realized_rescues,
            "realized_rescue_rate_pct": (
                round(100.0 * realized_rescues / with_follow_up, 1) if enough else None
            ),
            "note": None if enough else (
                f"insufficient data for a rate (need {CALIBRATION_MIN_N} follow-up-"
                f"backed predictions at this level) — counts only"
            ),
        }

    return {
        "risk_notes_total": len(risk),
        "risk_notes_abstained": sum(1 for j in risk if j.abstained),
        "abstention_rate_pct": (
            round(100.0 * sum(1 for j in risk if j.abstained) / len(risk), 1)
            if risk else None
        ),
        "predictions_by_level": per_level,
        "extraction_judgments": len(extraction),
        "extraction_abstained": sum(1 for j in extraction if j.abstained),
        "mock_judgments": sum(1 for j in real if j.is_mock),
        "real_model_judgments": sum(1 for j in real if not j.is_mock),
        "calibration_min_n": CALIBRATION_MIN_N,
        "notes": [
            "Every AI output is logged append-only with model, prompt version, and "
            "input digest; nothing here is ever edited, deleted, or fabricated.",
            "Predicted rescue risk is qualitative and retrieval-grounded — rates are "
            "published only once enough follow-up-backed predictions exist.",
            "Mock judgments come from the offline demo service and must never be "
            "presented as model performance.",
            "Internal telemetry — never customer-facing.",
        ],
    }


# ---------------------------------------------------------------- Evidence export
EVIDENCE_EXPORT_METHODOLOGY = (
    "Each row is one planned spray decision: the recommendation as imported/entered, "
    "the deterministic rule checks it triggered (with per-value source provenance), "
    "the PCA/agronomist review, the recorded real-world action, and the append-only "
    "follow-up timeline. 'Confirmed' figures require recorded follow-up events; "
    "'estimated' figures are entered values without follow-up support; quantities "
    "that cannot be computed honestly are reported as 'not calculated'. The rule "
    "engine is deterministic — no machine-learning model decides anything here."
)

EVIDENCE_EXPORT_LIMITATIONS = [
    "Correlation, not causality: outcomes are decisions humans made that Lumos "
    "documented — this export does not prove Lumos caused them.",
    "This is operational pilot evidence, not a controlled study; no statistical "
    "claim of pesticide reduction or savings is made.",
    "PHI/REI and cost inputs are user-entered or imported and not verified against "
    "an authoritative pesticide label database unless marked pca_verified.",
    "Yield and quality outcomes remain 'unknown' unless explicitly recorded in "
    "follow-up; unknown is reported as unknown, never assumed neutral or positive.",
    "Demo/simulated records are excluded from this export by construction.",
    "Label-dependent checks (seasonal rate caps, application counts, retreatment "
    "intervals, crop/use registration) were not evaluated — they require "
    "authoritative label data.",
]


def _export_decision_row(planned, follow_ups, audit_events, input_values) -> dict:
    """One anonymized decision record for the evidence export (JSON form)."""
    payload = getattr(planned, "decision_payload", None) or {}
    triggered = [
        {
            "rule_id": r.get("rule_id"),
            "severity": r.get("severity"),
            "detail": r.get("detail"),
            "calculation": r.get("calculation"),
            "source_authority": r.get("source_authority"),
        }
        for r in payload.get("rules", [])
        if r.get("triggered")
    ]
    summary = derive_follow_up_summary(planned, follow_ups)
    return {
        "decision_id": planned.id,
        "external_record_id": planned.external_record_id,
        "field_block": planned.field_block,
        "crop": planned.crop,
        "treated_acres": planned.treated_acres,
        "planned": {
            "product_name": planned.product_name,
            "epa_reg_no": planned.epa_reg_no,
            "active_ingredient": planned.active_ingredient,
            "moa_group": planned.moa_group,
            "target_pest_or_disease": planned.target_pest_or_disease,
            "intended_date": _iso_dt(planned.intended_date),
            "rate_amount": planned.rate_amount,
            "rate_unit": planned.rate_unit,
            "estimated_cost": planned.estimated_cost,
            "pre_harvest_interval_days": planned.pre_harvest_interval_days,
            "re_entry_interval_hours": planned.re_entry_interval_hours,
            "recommendation_author": planned.recommendation_author,
            "source_system": planned.source_system,
            "source_filename": planned.source_filename,
        },
        "decision": {
            "outcome": planned.decision_outcome,
            "severity": planned.decision_severity,
            "authority": planned.decision_authority,
            "confidence": planned.decision_confidence,
            "review_required": planned.review_required,
            "triggered_exceptions": triggered,
            "missing_information": payload.get("missing_information", []),
            "not_evaluated": payload.get("not_evaluated", []),
        },
        "input_values": [
            {
                "field_name": v.field_name,
                "raw_value": v.raw_value,
                "normalized_value": v.normalized_value,
                "unit": v.unit,
                "source_type": v.source_type,
                "source_reference": v.source_reference,
                "verified_by": v.verified_by,
                "verified_at": _iso_dt(v.verified_at),
                "supersedes_input_value_id": v.supersedes_input_value_id,
            }
            for v in input_values
        ],
        "review": {
            "status": planned.review_status,
            "reviewed_by": planned.reviewed_by,
            "reviewed_at": _iso_dt(planned.reviewed_at),
            "comment": planned.review_comment,
            "pca_next_action": planned.pca_next_action,
        },
        "recorded_action": {
            "outcome": planned.outcome,
            "outcome_reason": planned.outcome_reason,
            "outcome_date": _iso_dt(planned.outcome_date),
            "outcome_product_name": planned.outcome_product_name,
        },
        "audit_history": [
            {
                "event_type": e.event_type,
                "actor": e.actor,
                "rationale": e.rationale,
                "system_recommendation": e.system_recommendation,
                "before": e.before,
                "after": e.after,
                "created_at": _iso_dt(e.created_at),
            }
            for e in audit_events
        ],
        "follow_up_timeline": [
            {
                "event_type": e.event_type,
                "observed_at": _iso_dt(e.observed_at),
                "severity": e.severity,
                "severity_scale": e.severity_scale,
                "actual_product": e.actual_product,
                "actual_rate_amount": e.actual_rate_amount,
                "actual_rate_unit": e.actual_rate_unit,
                "actual_treated_acres": e.actual_treated_acres,
                "cost": e.cost,
                "rescue_required": e.rescue_required,
                "yield_impact": e.yield_impact,
                "quality_impact": e.quality_impact,
                "rejected_or_downgraded": e.rejected_or_downgraded,
                "evidence_notes": e.evidence_notes,
                "entered_by": e.entered_by,
                "source_type": e.source_type,
                "confidence": e.confidence,
            }
            for e in follow_ups
        ],
        "follow_up_summary": summary,
        "missing_evidence": _missing_evidence_notes(planned, summary),
    }


def _missing_evidence_notes(planned, summary: dict) -> list[str]:
    out = []
    if decision_status.needs_review(planned):
        out.append("PCA review still outstanding.")
    if decision_status.is_open(planned):
        out.append("No real-world outcome recorded yet.")
    elif decision_status.follow_up_required(planned) and not summary["has_follow_up"]:
        out.append(
            "Follow-up required but no follow-up events recorded — nothing about this "
            "decision is confirmed."
        )
    if summary["has_follow_up"] and summary["yield_impact"] == "unknown":
        out.append("Yield impact not recorded — remains unknown.")
    return out


# Fixed limitations attached to the procurement (input_orders) evidence block.
# There is deliberately NO savings key anywhere: amounts are recorded, not compared.
PROCUREMENT_EXPORT_LIMITATIONS = [
    "Supplier quotes are concierge-entered for comparison, not supplier-system data.",
    "Financing terms are indicative only; no credit decision occurred and no money "
    "moved through Lumos.",
    "No cost-savings figure is computed — amounts are recorded, not compared.",
]


def _export_quote(quote, plan, today) -> dict:
    return {
        "supplier_quote_id": quote.id,
        "supplier_name": quote.supplier_name,
        "state": procurement_status.quote_state(quote, plan, today),
        "verification": quote.verification,
        "availability": quote.availability,
        "expected_delivery_date": _iso_dt(quote.expected_delivery_date),
        "expires_on": _iso_dt(quote.expires_on),
        "payment_terms_cash": quote.payment_terms_cash,
        "items_subtotal": quote.items_subtotal,
        "delivery_cost": quote.delivery_cost,
        "fees": quote.fees,
        "total_cost": quote.total_cost,
        "lines": [
            {
                "input_plan_item_id": line.input_plan_item_id,
                "product_name": line.product_name,
                "is_substitution": line.is_substitution,
                "substitution_reason": line.substitution_reason,
                "quantity": line.quantity,
                "unit": line.unit,
                "unit_price": line.unit_price,
                "line_total": line.line_total,
            }
            for line in quote.items
        ],
        "financing_offers": [
            {
                "financing_offer_id": o.id,
                "provider_name": o.provider_name,
                "state": procurement_status.offer_state(o, today),
                "requested_amount": o.requested_amount,
                "down_payment": o.down_payment,
                "financed_amount": o.financed_amount,
                "total_repayment": o.total_repayment,
                "fees_total": o.fees_total,
                "schedule_summary": o.schedule_summary,
                "expires_on": _iso_dt(o.expires_on),
                "decided_by": o.decided_by,
                "disclaimer": procurement_status.FINANCING_OFFER_DISCLAIMER,
            }
            for o in quote.financing_offers
        ],
    }


def build_procurement_export(input_plans, today: date | None = None) -> dict:
    """The input_orders evidence block: every REAL (non-demo) procurement chain.

    Records the plan (with decision links and provenance), the quotes as entered,
    the financing history (indicative only, disclaimer verbatim), the order and
    its append-only event timeline. No savings/impact figure exists here by
    design — the export records amounts, it never compares them.
    """
    today = today or date.today()
    real_plans = [
        p for p in (input_plans or []) if not decision_status.is_demo_record(p)
    ]
    plans_out = []
    for plan in real_plans:
        offers = [o for q in plan.quotes for o in q.financing_offers]
        order = plan.order
        plans_out.append({
            "input_plan_id": plan.id,
            "status": plan.status,
            "requested_by": plan.requested_by,
            "financing_requested": plan.financing_requested,
            "financing_state": procurement_status.financing_state(plan, offers, today),
            "data_source": plan.data_source,
            "data_confidence": plan.data_confidence,
            "items": [
                {
                    "input_plan_item_id": item.id,
                    "planned_spray_id": item.planned_spray_id,
                    "field_block": item.field_block,
                    "crop": item.crop,
                    "category": item.category,
                    "product_name": item.product_name,
                    "active_ingredient": item.active_ingredient,
                    "quantity": item.quantity,
                    "unit": item.unit,
                    "acres": item.acres,
                    "needed_by_date": _iso_dt(item.needed_by_date),
                    "intended_use": item.intended_use,
                    "estimated_cost": item.estimated_cost,
                    "data_source": item.data_source,
                }
                for item in plan.items
            ],
            "quotes_received": sum(
                1 for q in plan.quotes
                if q.status != procurement_status.QUOTE_WITHDRAWN
            ),
            "quotes": [_export_quote(q, plan, today) for q in plan.quotes],
            "selected_quote_id": plan.selected_quote_id,
            "order": None if order is None else {
                "order_id": order.id,
                "status": order.status,
                "placed_by": order.placed_by,
                "selected_quote_id": order.selected_quote_id,
                "accepted_financing_offer_id": order.accepted_financing_offer_id,
                "spray_event_id": order.spray_event_id,
                "applied_planned_spray_id": order.applied_planned_spray_id,
                "events": [
                    {
                        "event_type": e.event_type,
                        "occurred_on": _iso_dt(e.occurred_on),
                        "actor": e.actor,
                        "notes": e.notes,
                        "payload": e.payload,
                    }
                    for e in sorted(
                        order.events, key=lambda e: (e.created_at, e.id)
                    )
                ],
            },
        })
    return {
        "plans_exported": len(plans_out),
        "plans": plans_out,
        "limitations": list(PROCUREMENT_EXPORT_LIMITATIONS),
    }


def build_evidence_export(
    farm,
    planned_sprays,
    follow_ups_by_id: dict,
    audit_events_by_id: dict,
    input_values_by_id: dict,
    advisor_label: str = "agronomist",
    today: date | None = None,
    input_plans=None,
) -> dict:
    """Anonymized evidence export for one farm's REAL (non-demo) decisions.

    The farm is identified only as pilot-farm-{id} plus crop/area — never by name or
    location. Demo/simulated decisions are excluded by construction.
    """
    real = _real_planned(planned_sprays)
    rows = [
        _export_decision_row(
            p,
            follow_ups_by_id.get(p.id, []),
            audit_events_by_id.get(p.id, []),
            input_values_by_id.get(p.id, []),
        )
        for p in real
    ]

    confirmed, estimated, follow_up_stats = _confirmed_and_estimated(
        real, follow_ups_by_id
    )

    # Data-completeness statement (computed, not asserted).
    reviewed = sum(
        1 for p in real
        if decision_status.review_state(p) in decision_status.RESOLVED_REVIEW_STATUSES
    )
    all_active_values = []
    for p in real:
        chain = input_values_by_id.get(p.id, [])
        superseded = {v.supersedes_input_value_id for v in chain if v.supersedes_input_value_id}
        all_active_values.extend(v for v in chain if v.id not in superseded)
    verified_values = sum(
        1 for v in all_active_values
        if v.source_type in ("pca_verified", "authoritative_provider")
    )
    dates = [p.intended_date for p in real if p.intended_date]

    return {
        "farm_ref": f"pilot-farm-{getattr(farm, 'id', 'x')}",
        "anonymization": (
            "Farm name and location are excluded. Operators must anonymize records "
            "before upload; reviewer names appear only as entered."
        ),
        "crop_type": getattr(farm, "crop_type", None),
        "area": getattr(farm, "greenhouse_area", None),
        "advisor_label": advisor_label,
        "generated_on": (today or date.today()).isoformat(),
        "pilot_period_start": min(dates).isoformat() if dates else None,
        "pilot_period_end": max(dates).isoformat() if dates else None,
        "decisions_exported": len(rows),
        "data_completeness": {
            "decisions_reviewed_pct": (
                round(100.0 * reviewed / len(real), 1) if real else None
            ),
            "critical_values_verified_pct": (
                round(100.0 * verified_values / len(all_active_values), 1)
                if all_active_values else None
            ),
            "follow_up_completion_rate_pct": follow_up_stats[
                "follow_up_completion_rate_pct"
            ],
        },
        "methodology": EVIDENCE_EXPORT_METHODOLOGY,
        "confirmed": confirmed,
        "estimated": estimated,
        "not_calculated": dict(NOT_CALCULATED),
        "decisions": rows,
        "input_orders": build_procurement_export(input_plans, today),
        "limitations": list(EVIDENCE_EXPORT_LIMITATIONS),
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
