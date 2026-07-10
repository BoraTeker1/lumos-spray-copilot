"""FastAPI application for Lumos Spray Copilot (Milestone 1).

Routes are intentionally thin: they validate input, call `crud`, and shape responses.
No auth in v1, but handlers are kept stateless so an auth dependency can be added later.
"""
import csv
import io
from datetime import date, datetime

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app import crud, schemas
from app.analytics import compute_cost_analytics
from app.database import get_db, init_db
from app.pilot_evidence import (
    build_decision_evidence,
    build_instrumentation_summary,
    build_pilot_case_study,
    build_pilot_evidence,
)
from app.recommendation_engine import generate_recommendation
from app.reduction import compute_reduction
from app.vision import (
    ALLOWED_MEDIA_TYPES,
    MAX_IMAGE_BYTES,
    build_analysis_result,
    default_vision_service,
)
from app.weather import default_weather_service

app = FastAPI(
    title="Lumos Spray Copilot API",
    description="AI-assisted, agronomist-in-the-loop spray-decision support for "
    "greenhouse tomato growers. Decision support only — never a prescription.",
    version="0.2.0",
)

# Allow the local Next.js dev server to call the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    init_db()


# ------------------------------------------------------------------------ Health
@app.get("/health", tags=["health"])
def health():
    return {"status": "ok", "service": "lumos-spray-copilot"}


# ------------------------------------------------------------------------- Farms
@app.get("/farms", response_model=list[schemas.Farm], tags=["farms"])
def get_farms(db: Session = Depends(get_db)):
    return crud.list_farms(db)


@app.post("/farms", response_model=schemas.Farm, status_code=201, tags=["farms"])
def post_farm(payload: schemas.FarmCreate, db: Session = Depends(get_db)):
    return crud.create_farm(db, payload)


# NOTE: declared before /farms/{farm_id} so "overview" isn't parsed as a farm id.
@app.get("/farms-overview", tags=["farms"])
def farms_overview(db: Session = Depends(get_db)):
    """Action-oriented farm list: which farm needs attention, why, and the next action.

    One call for the dashboard (instead of N calls per farm). Urgency ranking:
    conflict (a critical pre-spray decision is unresolved) > needs_review (a decision
    awaits PCA review) > awaiting_outcome > flags (record-level PHI/REI/resistance/
    scouting flags) > ok.
    """
    out = []
    for farm in crud.list_farms(db):
        sprays = crud.list_spray_events(db, farm.id)
        observations = crud.list_scout_observations(db, farm.id)
        planned = crud.list_planned_sprays(db, farm.id)
        signals = generate_recommendation(farm, sprays, observations).signals

        open_planned = [p for p in planned if p.outcome == "planned"]
        needs_review = [
            p for p in open_planned
            if p.review_required and p.review_status not in ("approved", "edited", "rejected")
        ]
        open_critical = [p for p in open_planned if p.decision_severity == "critical"]
        flag_count = sum(
            1 for k in (
                "phi_risk", "rei_risk", "repeated_active_ingredient_risk",
                "high_severity_scouting",
            ) if signals.get(k)
        )

        if open_critical:
            urgency, why = "conflict", (
                f"{len(open_critical)} planned spray(s) conflict with entered "
                f"harvest/re-entry timing"
            )
            next_action = "Resolve the blocked pre-spray decision with your PCA"
        elif needs_review:
            urgency, why = "needs_review", (
                f"{len(needs_review)} pre-spray decision(s) awaiting PCA review"
            )
            next_action = "Review the pending pre-spray decision(s)"
        elif open_planned:
            urgency, why = "awaiting_outcome", (
                f"{len(open_planned)} checked spray(s) without a recorded outcome"
            )
            next_action = "Record what actually happened for the checked spray(s)"
        elif flag_count:
            urgency, why = "flags", (
                f"{flag_count} PHI/REI/resistance/scouting flag(s) from current records"
            )
            next_action = "Open the pre-spray risk snapshot and review the flags"
        else:
            urgency, why = "ok", "No open decisions or risk flags from current records"
            next_action = "Run a pre-spray check before the next planned application"

        records = list(sprays) + list(observations)
        out.append({
            "id": farm.id,
            "name": farm.name,
            "location": farm.location,
            "country": farm.country,
            "crop_type": farm.crop_type,
            "area": farm.greenhouse_area,
            "expected_harvest_date": _iso(farm.expected_harvest_date),
            "urgency": urgency,
            "why": why,
            "next_action": next_action,
            "needs_review_count": len(needs_review),
            "awaiting_outcome_count": len(open_planned),
            "open_conflict_count": len(open_critical),
            "flag_count": flag_count,
            "spray_count": len(sprays),
            "is_demo": bool(records) and all(
                (r.data_source == "demo" or r.data_confidence == "simulated")
                for r in records
            ),
        })

    rank = {"conflict": 0, "needs_review": 1, "awaiting_outcome": 2, "flags": 3, "ok": 4}
    out.sort(key=lambda f: (rank.get(f["urgency"], 9), f["id"]))
    return out


def _require_farm(db: Session, farm_id: int):
    farm = crud.get_farm(db, farm_id)
    if farm is None:
        raise HTTPException(status_code=404, detail="Farm not found")
    return farm


@app.get("/farms/{farm_id}", response_model=schemas.Farm, tags=["farms"])
def get_farm(farm_id: int, db: Session = Depends(get_db)):
    return _require_farm(db, farm_id)


@app.put("/farms/{farm_id}", response_model=schemas.Farm, tags=["farms"])
def put_farm(farm_id: int, payload: schemas.FarmUpdate, db: Session = Depends(get_db)):
    farm = _require_farm(db, farm_id)
    return crud.update_farm(db, farm, payload)


@app.delete("/farms/{farm_id}", status_code=204, tags=["farms"])
def remove_farm(farm_id: int, db: Session = Depends(get_db)):
    farm = _require_farm(db, farm_id)
    crud.delete_farm(db, farm)


# ------------------------------------------------------------------- Spray events
@app.get(
    "/farms/{farm_id}/spray-events",
    response_model=list[schemas.SprayEvent],
    tags=["spray-events"],
)
def get_spray_events(farm_id: int, db: Session = Depends(get_db)):
    _require_farm(db, farm_id)
    return crud.list_spray_events(db, farm_id)


@app.post(
    "/farms/{farm_id}/spray-events",
    response_model=schemas.SprayEvent,
    status_code=201,
    tags=["spray-events"],
)
def post_spray_event(
    farm_id: int, payload: schemas.SprayEventCreate, db: Session = Depends(get_db)
):
    _require_farm(db, farm_id)
    return crud.create_spray_event(db, farm_id, payload)


@app.delete("/spray-events/{event_id}", status_code=204, tags=["spray-events"])
def remove_spray_event(event_id: int, db: Session = Depends(get_db)):
    event = crud.get_spray_event(db, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Spray event not found")
    crud.delete_spray_event(db, event)


# ------------------------------------------------------------- Scout observations
@app.get(
    "/farms/{farm_id}/scout-observations",
    response_model=list[schemas.ScoutObservation],
    tags=["scout-observations"],
)
def get_scout_observations(farm_id: int, db: Session = Depends(get_db)):
    _require_farm(db, farm_id)
    return crud.list_scout_observations(db, farm_id)


@app.post(
    "/farms/{farm_id}/scout-observations",
    response_model=schemas.ScoutObservation,
    status_code=201,
    tags=["scout-observations"],
)
def post_scout_observation(
    farm_id: int, payload: schemas.ScoutObservationCreate, db: Session = Depends(get_db)
):
    _require_farm(db, farm_id)
    return crud.create_scout_observation(db, farm_id, payload)


@app.delete("/scout-observations/{obs_id}", status_code=204, tags=["scout-observations"])
def remove_scout_observation(obs_id: int, db: Session = Depends(get_db)):
    obs = crud.get_scout_observation(db, obs_id)
    if obs is None:
        raise HTTPException(status_code=404, detail="Scout observation not found")
    crud.delete_scout_observation(db, obs)


# --------------------------------------------------------------- Photo analysis
@app.post(
    "/farms/{farm_id}/photo-analysis",
    response_model=schemas.PhotoAnalysisResult,
    tags=["scout-observations"],
)
async def analyze_field_photo(
    farm_id: int,
    file: UploadFile = File(...),
    concern: str | None = None,
    db: Session = Depends(get_db),
):
    """Analyse one uploaded field photo with a multimodal model (decision support only).

    The result is NOT saved as a recommendation or a scouting note — it returns a *draft*
    scouting observation a grower/PCA reviews and confirms. CV is an input to the rule
    engine, never the decider, and the model never tells anyone to spray.
    """
    farm = _require_farm(db, farm_id)

    media_type = (file.content_type or "").lower()
    if media_type not in ALLOWED_MEDIA_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported image type '{media_type}'. Use JPEG, PNG, WebP, or GIF.",
        )
    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Empty image upload.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="Image too large (max 8 MB).")

    try:
        finding = default_vision_service.analyze(
            image_bytes, media_type, crop_type=farm.crop_type, context=concern
        )
    except Exception as exc:  # surface model/transport failures cleanly, never 500-crash the demo
        raise HTTPException(status_code=502, detail=f"Photo analysis failed: {exc}") from exc

    return build_analysis_result(finding)


# --------------------------------------------------------------- Planned sprays
@app.get(
    "/farms/{farm_id}/planned-sprays",
    response_model=list[schemas.PlannedSpray],
    tags=["planned-sprays"],
)
def get_planned_sprays(farm_id: int, db: Session = Depends(get_db)):
    _require_farm(db, farm_id)
    return crud.list_planned_sprays(db, farm_id)


@app.post(
    "/farms/{farm_id}/planned-sprays",
    response_model=schemas.PlannedSpray,
    status_code=201,
    tags=["planned-sprays"],
)
def post_planned_spray(
    farm_id: int, payload: schemas.PlannedSprayCreate, db: Session = Depends(get_db)
):
    """Check an *intended* spray before it happens (the pre-spray decision point).

    Runs the decision engine (PHI/REI vs. harvest, prior re-entry windows, repeated
    active ingredient, scouting evidence, missing data) and returns ONE explainable
    outcome — approve / block / delay / inspect_first / pca_review_required — with the
    triggered rules, inputs, calculations, and confidence snapshotted on the record.
    Decision support only — the real-world outcome is recorded separately by the human.
    """
    farm = _require_farm(db, farm_id)
    return crud.create_planned_spray(db, farm, payload)


def _require_planned_spray(db: Session, planned_id: int):
    planned = crud.get_planned_spray(db, planned_id)
    if planned is None:
        raise HTTPException(status_code=404, detail="Planned spray not found")
    return planned


@app.get(
    "/planned-sprays/{planned_id}",
    response_model=schemas.PlannedSpray,
    tags=["planned-sprays"],
)
def get_planned_spray(planned_id: int, db: Session = Depends(get_db)):
    """One planned spray with its full decision snapshot (drives the decision record)."""
    return _require_planned_spray(db, planned_id)


@app.patch(
    "/planned-sprays/{planned_id}/review",
    response_model=schemas.PlannedSpray,
    tags=["planned-sprays"],
)
def patch_planned_spray_review(
    planned_id: int, payload: schemas.PlannedSprayReviewUpdate, db: Session = Depends(get_db)
):
    """PCA / agronomist review of a pre-spray decision (approve / edit / reject + comment).

    An edit must include the PCA's replacement guidance; a rejection must say why.
    """
    planned = _require_planned_spray(db, planned_id)
    return crud.review_planned_spray(db, planned, payload)


@app.patch(
    "/planned-sprays/{planned_id}/outcome",
    response_model=schemas.PlannedSpray,
    tags=["planned-sprays"],
)
def patch_planned_spray_outcome(
    planned_id: int, payload: schemas.PlannedSprayOutcomeUpdate, db: Session = Depends(get_db)
):
    """Record what actually happened (sprayed_as_planned / changed_product / delayed /
    avoided / inspected_first + stated reason).

    Applied outcomes create and link the real spray event; when the decision required
    review, they are rejected with 409 until a PCA has approved or edited the decision.
    """
    planned = _require_planned_spray(db, planned_id)
    try:
        return crud.record_planned_spray_outcome(db, planned, payload)
    except crud.ReviewRequiredError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/farms/{farm_id}/decision-evidence", tags=["planned-sprays"])
def farm_decision_evidence(farm_id: int, db: Session = Depends(get_db)):
    """Pre-spray decision workflow metrics for the pilot/evidence dashboard.

    Demo/simulated decisions are excluded; every figure states whether it is a count,
    an entered estimate, or a stated assumption (see `limitations`).
    """
    farm = _require_farm(db, farm_id)
    planned = crud.list_planned_sprays(db, farm_id)
    return build_decision_evidence(planned, advisor_label=_advisor_label(farm))


@app.delete("/planned-sprays/{planned_id}", status_code=204, tags=["planned-sprays"])
def remove_planned_spray(planned_id: int, db: Session = Depends(get_db)):
    planned = _require_planned_spray(db, planned_id)
    crud.delete_planned_spray(db, planned)


# -------------------------------------------------------------- Recommendations
@app.get(
    "/farms/{farm_id}/recommendations",
    response_model=list[schemas.Recommendation],
    tags=["recommendations"],
)
def get_recommendations(farm_id: int, db: Session = Depends(get_db)):
    _require_farm(db, farm_id)
    return crud.list_recommendations(db, farm_id)


@app.post(
    "/farms/{farm_id}/recommendations",
    response_model=schemas.Recommendation,
    status_code=201,
    tags=["recommendations"],
)
def post_recommendation(farm_id: int, db: Session = Depends(get_db)):
    """Generate (and store) a cautious recommendation from the farm's current records."""
    farm = _require_farm(db, farm_id)
    return crud.generate_and_store_recommendation(db, farm)


@app.patch(
    "/recommendations/{rec_id}",
    response_model=schemas.Recommendation,
    tags=["recommendations"],
)
def patch_recommendation(
    rec_id: int, payload: schemas.RecommendationUpdate, db: Session = Depends(get_db)
):
    """Agronomist review action (approve / reject / edit + comment)."""
    rec = crud.get_recommendation(db, rec_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    return crud.update_recommendation(db, rec, payload)


# ----------------------------------------------------------------- Analytics
@app.get("/farms/{farm_id}/analytics", tags=["analytics"])
def farm_analytics(farm_id: int, db: Session = Depends(get_db)):
    """Pesticide cost analytics for one farm's current crop cycle."""
    _require_farm(db, farm_id)
    sprays = crud.list_spray_events(db, farm_id)
    return compute_cost_analytics(sprays)


# ------------------------------------------------------------------- Weather
@app.get("/farms/{farm_id}/weather-risk", tags=["weather"])
def farm_weather_risk(farm_id: int, db: Session = Depends(get_db)):
    """Lightweight weather-based disease-pressure assessment for the farm location."""
    farm = _require_farm(db, farm_id)
    return default_weather_service.get_weather_risk(farm.location)


# ---------------------------------------------------------------- Compliance
@app.get("/farms/{farm_id}/compliance", tags=["compliance"])
def farm_compliance(farm_id: int, db: Session = Depends(get_db)):
    """Structured compliance snapshot for the farm-detail compliance card.

    Re-runs the rule engine over current records (does not persist) and combines it
    with weather and the latest agronomist/PCA review status.
    """
    farm = _require_farm(db, farm_id)
    sprays = crud.list_spray_events(db, farm_id)
    observations = crud.list_scout_observations(db, farm_id)
    result = generate_recommendation(farm, sprays, observations)
    weather = default_weather_service.get_weather_risk(farm.location)
    recs = crud.list_recommendations(db, farm_id)
    latest = recs[0] if recs else None

    return {
        "risk_level": result.risk_level,
        "next_action": result.next_action,
        "phi_risk": result.signals.get("phi_risk", False),
        "rei_risk": result.signals.get("rei_risk", False),
        "repeated_active_ingredient_risk": result.signals.get(
            "repeated_active_ingredient_risk", False
        ),
        "max_recent_severity": result.signals.get("max_recent_severity", 0),
        "high_severity_scouting": result.signals.get("high_severity_scouting", False),
        "weather_risk_level": weather["risk_level"],
        "review_status": latest.agronomist_status if latest else "none",
        "advisor_label": _advisor_label(farm),
        # Honest framing for the UI: these signals come from user-entered PHI/REI values,
        # not from a verified pesticide-label database.
        "basis": "user-entered values, not label-verified",
    }


def _advisor_label(farm) -> str:
    """U.S. specialty-crop growers work with a PCA; elsewhere we just say agronomist."""
    return "PCA / agronomist" if (farm.country or "").upper() in ("US", "USA") else "agronomist"


# -------------------------------------------------------------- Weekly report
@app.get("/farms/{farm_id}/weekly-report", tags=["reports"])
def weekly_report(farm_id: int, db: Session = Depends(get_db)):
    """Return a plain-text weekly summary that can be copied into WhatsApp."""
    farm = _require_farm(db, farm_id)
    sprays = crud.list_spray_events(db, farm_id)
    observations = crud.list_scout_observations(db, farm_id)
    recs = crud.list_recommendations(db, farm_id)
    latest_rec = recs[0] if recs else None
    analytics = compute_cost_analytics(sprays)
    weather = default_weather_service.get_weather_risk(farm.location)
    # Current compliance signals (PHI / REI / repeated-AI) for the report's flag block.
    signals = generate_recommendation(farm, sprays, observations).signals

    text = _build_weekly_report_text(
        farm, len(sprays), len(observations), latest_rec, analytics, weather, signals
    )
    return {"text": text}


# Statuses that count as advisor-reviewed guidance for the farmer-facing report.
REVIEWED_STATUSES = ("approved", "edited")


def _currency_symbol(farm) -> str:
    return "$" if (farm.country or "").upper() in ("US", "USA") else "₺"


def _report_disclaimer(farm) -> str:
    if (farm.country or "").upper() in ("US", "USA"):
        return (
            "— Decision support only. Confirm pesticide use, label requirements, PHI, and REI "
            "with a licensed PCA/agronomist and the product label."
        )
    return "— Decision support only; confirm with your agronomist before acting."


def _compliance_flag_lines(signals: dict) -> list[str]:
    """Explicit PHI / REI / repeated-ingredient warning lines for the report."""
    out = []
    if signals.get("phi_risk"):
        out.append("⚠️ PHI: a recent spray may not clear before harvest — review harvest timing.")
    if signals.get("rei_risk"):
        out.append("⚠️ REI: worker re-entry interval may still be active — review label/PCA guidance.")
    if signals.get("repeated_active_ingredient_risk"):
        out.append("⚠️ Resistance: same active ingredient repeated — consider rotating chemistry.")
    if signals.get("high_severity_scouting"):
        out.append("⚠️ Scouting: high-severity pest/disease pressure logged.")
    if not out:
        out.append("No PHI / REI / resistance flags from current records.")
    return out


def _build_weekly_report_text(
    farm, spray_count, observation_count, latest_rec, analytics, weather, signals
) -> str:
    advisor = _advisor_label(farm)              # "PCA / agronomist" (US) or "agronomist"
    advisor_cap = advisor[:1].upper() + advisor[1:]   # capitalise first letter, keep "PCA"
    cur = _currency_symbol(farm)
    crop_icon = "🍓" if (farm.crop_type or "").lower().startswith("straw") else "🍅"

    lines = [
        f"{crop_icon} Lumos Weekly Report — {farm.name}",
        f"Location: {farm.location} · {date.today().isoformat()}",
        "",
        f"Weather risk: {weather['risk_level'].upper()} — {weather['summary']}",
        "",
        "Compliance flags:",
        *[f"  {ln}" for ln in _compliance_flag_lines(signals)],
        "",
        f"Pesticide spend (cycle): {cur}{analytics['total_spend']:.2f}  |  "
        f"Sprays this cycle: {spray_count}  |  Last 30 days: {analytics['sprays_last_30_days']}",
        f"Scouting notes on record: {observation_count}",
    ]

    if latest_rec is None:
        lines += [
            "",
            "No recommendation generated yet — open the farm to generate one.",
        ]
    elif latest_rec.agronomist_status in REVIEWED_STATUSES:
        # Advisor-reviewed guidance: safe to share as guidance with the grower.
        lines += [
            "",
            f"Risk level: {latest_rec.risk_level.upper()}",
            f"Next action: {latest_rec.next_action}",
            "",
            f"{advisor_cap}-reviewed guidance ({latest_rec.agronomist_status}):",
            latest_rec.recommendation_text,
        ]
        if latest_rec.agronomist_comment:
            lines += ["", f"{advisor_cap} note: {latest_rec.agronomist_comment}"]
    else:
        # Pending or rejected -> do NOT present as reviewed guidance.
        status_note = {
            "pending": f"A recommendation is awaiting {advisor} review — not yet shareable guidance.",
            "rejected": f"The latest recommendation was rejected by the {advisor}; no action advised right now.",
        }.get(latest_rec.agronomist_status, f"Status: {latest_rec.agronomist_status}.")
        lines += [
            "",
            f"Risk level (draft): {latest_rec.risk_level.upper()}",
            f"Suggested next action (draft): {latest_rec.next_action}",
            status_note,
        ]

    lines += ["", _report_disclaimer(farm)]
    return "\n".join(lines)


# ------------------------------------------------------ Reduction measurement
def _farm_reduction(db: Session, farm, sprays) -> dict:
    """Measure spray reduction for a farm against its current baseline (if any)."""
    baseline = crud.get_spray_baseline(db, farm.id)
    return compute_reduction(farm, sprays, baseline)


@app.get("/farms/{farm_id}/spray-baseline", tags=["reduction"])
def get_spray_baseline(farm_id: int, db: Session = Depends(get_db)):
    """The farm's current declared spray baseline, or null if none is set yet."""
    _require_farm(db, farm_id)
    baseline = crud.get_spray_baseline(db, farm_id)
    if baseline is None:
        return None
    return schemas.SprayBaseline.model_validate(baseline)


@app.put(
    "/farms/{farm_id}/spray-baseline",
    response_model=schemas.SprayBaseline,
    tags=["reduction"],
)
def put_spray_baseline(
    farm_id: int, payload: schemas.SprayBaselineCreate, db: Session = Depends(get_db)
):
    """Declare/update the grower-or-PCA spray baseline used to measure reduction against."""
    _require_farm(db, farm_id)
    return crud.set_spray_baseline(db, farm_id, payload)


@app.get("/farms/{farm_id}/reduction", tags=["reduction"])
def farm_reduction(farm_id: int, db: Session = Depends(get_db)):
    """Measured sprays-vs-baseline reduction for the farm (honest, baseline-gated)."""
    farm = _require_farm(db, farm_id)
    sprays = crud.list_spray_events(db, farm_id)
    return _farm_reduction(db, farm, sprays)


# --------------------------------------------------- Pilot evidence + audit packet
@app.get("/farms/{farm_id}/pilot-evidence", tags=["pilot"])
def farm_pilot_evidence(farm_id: int, db: Session = Depends(get_db)):
    """Descriptive pilot-evidence summary for the farm (metrics + investor talking points).

    Aggregates existing records only — it is decision support evidence, never a claim of
    guaranteed pesticide reduction (see the `limitations` block in the response).
    """
    farm = _require_farm(db, farm_id)
    sprays = crud.list_spray_events(db, farm_id)
    observations = crud.list_scout_observations(db, farm_id)
    recs = crud.list_recommendations(db, farm_id)
    analytics = compute_cost_analytics(sprays)
    weather = default_weather_service.get_weather_risk(farm.location)
    return build_pilot_evidence(
        farm,
        sprays,
        observations,
        recs,
        analytics,
        weather["risk_level"],
        advisor_label=_advisor_label(farm),
        reduction=_farm_reduction(db, farm, sprays),
        planned_sprays=crud.list_planned_sprays(db, farm_id),
    )


@app.post("/internal/farms/{farm_id}/pilot-import", status_code=201, tags=["internal"])
def pilot_import(
    farm_id: int, payload: schemas.PilotImport, db: Session = Depends(get_db)
):
    """INTERNAL concierge tooling — not part of the customer-facing workflow.

    Manual import of pilot data collected from a call/WhatsApp/spreadsheet/email.
    Not an automated integration — a human transcribes the records. Every imported row is
    tagged with the provided data_source + data_confidence for honest downstream metrics.
    """
    farm = _require_farm(db, farm_id)
    batch = crud.import_pilot_data(db, farm, payload)
    return {
        "farm_id": farm.id,
        "batch_id": batch.id,
        "source_label": batch.source_label,
        "data_source": batch.data_source,
        "data_confidence": batch.data_confidence,
        "imported_by": batch.imported_by,
        "notes": batch.notes,
        "imported_spray_events": batch.spray_event_count,
        "imported_scouting_observations": batch.scouting_observation_count,
        "imported_at": _iso(batch.created_at),
    }


def _distinct_provenance(records, attr: str) -> list[str]:
    """Sorted distinct, non-empty provenance values across a record list."""
    return sorted({getattr(r, attr) for r in records if getattr(r, attr, None)})


@app.get("/farms/{farm_id}/pilot-case-study", tags=["pilot"])
def farm_pilot_case_study(farm_id: int, db: Session = Depends(get_db)):
    """One-page concierge-pilot case study (reuses the pilot-evidence aggregation)."""
    farm = _require_farm(db, farm_id)
    sprays = crud.list_spray_events(db, farm_id)
    observations = crud.list_scout_observations(db, farm_id)
    recs = crud.list_recommendations(db, farm_id)
    analytics = compute_cost_analytics(sprays)
    weather = default_weather_service.get_weather_risk(farm.location)
    advisor = _advisor_label(farm)
    evidence = build_pilot_evidence(
        farm, sprays, observations, recs, analytics, weather["risk_level"],
        advisor_label=advisor, reduction=_farm_reduction(db, farm, sprays),
    )
    records = list(sprays) + list(observations)
    data_sources = _distinct_provenance(records, "data_source")
    data_confidences = _distinct_provenance(records, "data_confidence")
    batches = crud.list_pilot_import_batches(db, farm_id)
    return build_pilot_case_study(
        evidence, data_sources, data_confidences, advisor_label=advisor, import_batches=batches
    )


AUDIT_DISCLAIMER = (
    "Decision support only. Final pesticide decisions must be made by the grower/PCA "
    "according to the product label and applicable regulations."
)


@app.get("/farms/{farm_id}/audit-packet", tags=["reports"])
def farm_audit_packet(farm_id: int, db: Session = Depends(get_db)):
    """Consolidated, audit-ready record for one farm (profile + logs + flags + review trail)."""
    farm = _require_farm(db, farm_id)
    sprays = crud.list_spray_events(db, farm_id)
    observations = crud.list_scout_observations(db, farm_id)
    recs = crud.list_recommendations(db, farm_id)
    analytics = compute_cost_analytics(sprays)
    weather = default_weather_service.get_weather_risk(farm.location)
    result = generate_recommendation(farm, sprays, observations)
    batches = crud.list_pilot_import_batches(db, farm_id)
    latest_rec = recs[0] if recs else None
    report_text = _build_weekly_report_text(
        farm, len(sprays), len(observations), latest_rec, analytics, weather, result.signals
    )

    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "advisor_label": _advisor_label(farm),
        "farm_profile": {
            "id": farm.id,
            "name": farm.name,
            "location": farm.location,
            "country": farm.country,
            "crop_type": farm.crop_type,
            "area": farm.greenhouse_area,
            "planting_date": _iso(farm.planting_date),
            "expected_harvest_date": _iso(farm.expected_harvest_date),
            "advisor_involved": farm.advisor_involved,
        },
        "spray_events": [
            {
                "id": s.id,
                "product_name": s.product_name,
                "active_ingredient": s.active_ingredient,
                "pesticide_class": s.pesticide_class,
                "target_pest_or_disease": s.target_pest_or_disease,
                "dose": s.dose,
                "application_date": _iso(s.application_date),
                "cost": s.cost,
                "pre_harvest_interval_days": s.pre_harvest_interval_days,
                "re_entry_interval_hours": s.re_entry_interval_hours,
                "notes": s.notes,
                "data_source": s.data_source,
                "data_confidence": s.data_confidence,
            }
            for s in sprays
        ],
        "scout_observations": [
            {
                "id": o.id,
                "observation_date": _iso(o.observation_date),
                "crop_stage": o.crop_stage,
                "visible_issue": o.visible_issue,
                "severity_1_to_5": o.severity_1_to_5,
                "notes": o.notes,
                "data_source": o.data_source,
                "data_confidence": o.data_confidence,
            }
            for o in observations
        ],
        "recommendations": [
            {
                "id": r.id,
                "created_at": _iso(r.created_at),
                "risk_level": r.risk_level,
                "next_action": r.next_action,
                "agronomist_status": r.agronomist_status,
                "agronomist_comment": r.agronomist_comment,
                "recommendation_text": r.recommendation_text,
            }
            for r in recs
        ],
        "compliance_flags": {
            "risk_level": result.risk_level,
            "next_action": result.next_action,
            "phi_risk": result.signals.get("phi_risk", False),
            "rei_risk": result.signals.get("rei_risk", False),
            "high_severity_scouting": result.signals.get("high_severity_scouting", False),
            "max_recent_severity": result.signals.get("max_recent_severity", 0),
            "weather_risk_level": weather["risk_level"],
        },
        "resistance_flags": {
            "repeated_active_ingredient_risk": result.signals.get(
                "repeated_active_ingredient_risk", False
            ),
            "most_used_active_ingredient": analytics["most_used_active_ingredient"],
            "most_used_count": analytics["most_used_count"],
        },
        "review_status": {
            "latest_status": latest_rec.agronomist_status if latest_rec else "none",
            "latest_comment": latest_rec.agronomist_comment if latest_rec else None,
            "all_statuses": [r.agronomist_status for r in recs],
        },
        "reduction_measurement": _farm_reduction(db, farm, sprays),
        "pilot_import_batches": [
            {
                "id": b.id,
                "source_label": b.source_label,
                "imported_by": b.imported_by,
                "notes": b.notes,
                "data_source": b.data_source,
                "data_confidence": b.data_confidence,
                "spray_event_count": b.spray_event_count,
                "scouting_observation_count": b.scouting_observation_count,
                "imported_at": _iso(b.created_at),
            }
            for b in batches
        ],
        "weekly_report_text": report_text,
        "disclaimer": AUDIT_DISCLAIMER,
    }


def _iso(value):
    """ISO-format a date/datetime, passing through None."""
    return value.isoformat() if value is not None else None


# ---------------------------------------------------------------- Pilot intake
@app.post("/pilot/farms", response_model=schemas.Farm, status_code=201, tags=["pilot"])
def create_pilot_farm(payload: schemas.PilotFarmIntake, db: Session = Depends(get_db)):
    """One-shot intake: create a pilot farm plus its last sprays and a scouting concern."""
    return crud.create_pilot_farm(db, payload)


# ------------------------------------------------------------- Pilot events
@app.post("/pilot-events", response_model=schemas.PilotEvent, status_code=201, tags=["pilot"])
def post_pilot_event(payload: schemas.PilotEventCreate, db: Session = Depends(get_db)):
    """Fire-and-forget workflow telemetry from the UI (check started/abandoned, imports).

    Server-side events (check_completed / review_recorded / outcome_recorded) are logged
    automatically by their own endpoints — clients should not send those.
    """
    return crud.create_pilot_event(db, payload)


@app.get("/internal/instrumentation", tags=["internal"])
def internal_instrumentation(db: Session = Depends(get_db)):
    """INTERNAL pilot telemetry summary: check funnel, time-to-review, changed decisions,
    entry sources, abandonment. Never customer-facing."""
    return build_instrumentation_summary(
        crud.list_all_planned_sprays(db), crud.list_pilot_events(db)
    )


# ------------------------------------------------------------- Pilot feedback
@app.get("/pilot-feedback", response_model=list[schemas.PilotFeedback], tags=["pilot"])
def list_pilot_feedback(db: Session = Depends(get_db)):
    return crud.list_pilot_feedback(db)


@app.post(
    "/pilot-feedback",
    response_model=schemas.PilotFeedback,
    status_code=201,
    tags=["pilot"],
)
def create_pilot_feedback(
    payload: schemas.PilotFeedbackCreate, db: Session = Depends(get_db)
):
    return crud.create_pilot_feedback(db, payload)


# ------------------------------------------------------------------- Exports
def _csv_response(filename: str, header: list[str], rows: list[list]) -> Response:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(rows)
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/farms/{farm_id}/export/spray-events.csv", tags=["export"])
def export_spray_events(farm_id: int, db: Session = Depends(get_db)):
    _require_farm(db, farm_id)
    sprays = crud.list_spray_events(db, farm_id)
    header = [
        "id", "product_name", "active_ingredient", "pesticide_class",
        "target_pest_or_disease", "dose", "application_date", "cost",
        "pre_harvest_interval_days", "re_entry_interval_hours", "notes",
    ]
    rows = [
        [s.id, s.product_name, s.active_ingredient, s.pesticide_class,
         s.target_pest_or_disease, s.dose, s.application_date, s.cost,
         s.pre_harvest_interval_days, s.re_entry_interval_hours, s.notes]
        for s in sprays
    ]
    return _csv_response(f"farm{farm_id}_spray_events.csv", header, rows)


@app.get("/farms/{farm_id}/export/recommendations.csv", tags=["export"])
def export_recommendations(farm_id: int, db: Session = Depends(get_db)):
    _require_farm(db, farm_id)
    recs = crud.list_recommendations(db, farm_id)
    header = [
        "id", "created_at", "risk_level", "next_action",
        "agronomist_status", "agronomist_comment", "recommendation_text",
    ]
    rows = [
        [r.id, r.created_at, r.risk_level, r.next_action,
         r.agronomist_status, r.agronomist_comment, r.recommendation_text]
        for r in recs
    ]
    return _csv_response(f"farm{farm_id}_recommendations.csv", header, rows)


@app.get("/export/pilot-feedback.csv", tags=["export"])
def export_pilot_feedback(db: Session = Depends(get_db)):
    feedback = crud.list_pilot_feedback(db)
    header = [
        "id", "created_at", "person_type", "crop", "region",
        "current_records_method", "biggest_pain", "would_use_real_data",
        "would_pay", "requested_pilot", "notes",
    ]
    rows = [
        [f.id, f.created_at, f.person_type, f.crop, f.region,
         f.current_records_method, f.biggest_pain, f.would_use_real_data,
         f.would_pay, f.requested_pilot, f.notes]
        for f in feedback
    ]
    return _csv_response("pilot_feedback.csv", header, rows)
