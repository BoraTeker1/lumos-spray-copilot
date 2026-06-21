"""FastAPI application for Lumos Spray Copilot (Milestone 1).

Routes are intentionally thin: they validate input, call `crud`, and shape responses.
No auth in v1, but handlers are kept stateless so an auth dependency can be added later.
"""
from datetime import date

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app import crud, schemas
from app.analytics import compute_cost_analytics
from app.database import get_db, init_db
from app.recommendation_engine import generate_recommendation
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
