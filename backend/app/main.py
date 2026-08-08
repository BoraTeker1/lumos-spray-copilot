"""FastAPI application for Lumos Spray Copilot (Milestone 1).

Routes are intentionally thin: they validate input, call `crud`, and shape responses.
No auth in v1, but handlers are kept stateless so an auth dependency can be added later.
"""
import csv
import io

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import (
    ai_brief, clock, crud, csv_import, decision_status, disease_risk, extraction,
    label_extraction, llm, models, operator_key, pca_authority, schemas, vision,
)
# The layers admitted on 2026-08-07. Every one of these ships with an EMPTY transcription
# source, so each entry point below returns a Refusal until someone reads a document —
# see app/transcription.py and TRANSCRIPTION_TASKS.md.
from app import (
    collateral, credit_scoring, farm_profile, fertilization, hedging, insurance,
    irrigation, land_selection, monitoring, pricing, rfq_transport, seed_selection,
    soil, transcription,
)
from app.ingest import domains as ingest_domains
from app.analytics import compute_cost_analytics
# Imported for its side effect: registering the feature specs and their job handlers.
from app import features as _features  # noqa: F401
from app.ingest import base as ingest_base
from app.ingest import registry as ingest_registry
from app.jobs import queue as job_queue
from app.database import SessionLocal, get_db, init_db
from app.pilot_evidence import (
    build_ai_calibration,
    build_decision_evidence,
    build_evidence_export,
    build_instrumentation_summary,
    build_pilot_case_study,
    build_pilot_evidence,
    summarize_decisions_for_report,
)
from app.recommendation_engine import generate_recommendation
from app.reduction import compute_reduction
from app.vision import (
    ALLOWED_MEDIA_TYPES,
    MAX_IMAGE_BYTES,
    build_analysis_result,
    default_vision_service,
)
from app.advisory_weather import default_weather_service

app = FastAPI(
    title="Lumos Spray Copilot API",
    description="AI-assisted, agronomist-in-the-loop spray-decision support for "
    "greenhouse tomato growers. Decision support only — never a prescription.",
    version="0.2.0",
)

@app.middleware("http")
async def _operator_key_middleware(request, call_next):
    """Gate every /internal path behind the deployment's operator key.

    Middleware rather than a per-route dependency ON PURPOSE. These routes mint PCA
    credentials and grant farm authorizations, so the guarantee that matters is "every
    path under /internal", not "every route someone remembered to annotate" — the
    fifteenth internal route added six months from now is covered by construction.

    No-ops when LUMOS_OPERATOR_KEY is unset (demo/local development); `_startup`
    refuses to boot in that state once the database holds real records.

    CORS PREFLIGHT IS EXEMPT, and it has to be. A browser never sends custom headers
    on an `OPTIONS` preflight — the spec forbids it — so a preflight for any
    key-bearing request arrives here with no `X-Lumos-Operator-Key` and used to be
    refused 403. The browser then never sent the real request, and every /internal
    call from the UI failed with an opaque "Failed to fetch". That made the whole
    operator surface unusable from a browser on exactly the deployments where the key
    is mandatory (i.e. any database holding real records).

    Exempting preflight does not weaken the gate: a preflight carries no credentials
    and returns no data, and the ACTUAL request that follows still passes through here
    and still needs a valid key. Verified by
    `test_a_preflight_is_answered_but_the_real_request_still_needs_the_key`.
    """
    if request.method == "OPTIONS":
        return await call_next(request)

    if request.url.path.startswith("/internal"):
        reason = operator_key.denial_reason(
            request.headers.get(operator_key.KEY_HEADER)
        )
        if reason is not None:
            return JSONResponse(
                status_code=403,
                content={"detail": operator_key.DENIAL_MESSAGES.get(reason, reason)},
            )
    return await call_next(request)


# Allow the local Next.js dev server to call the API.
#
# REGISTERED LAST ON PURPOSE, and the order is load-bearing. Starlette runs the
# most-recently-added middleware OUTERMOST, so adding CORS after the operator gate puts
# CORS *outside* it. That matters because the gate short-circuits with a 403: if CORS
# were inner, it would never run on that path, the 403 would carry no
# `access-control-allow-origin`, and a browser would discard it and report an opaque
# "Failed to fetch" instead of the actual message.
#
# The message is the whole point — "this route requires the X-Lumos-Operator-Key
# header" is what tells an operator their key is missing or wrong. Ordering it this way
# is what lets them see it. Pinned by
# `test_a_denied_internal_request_still_carries_cors_headers`.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# Demo/real mixing is rejected wherever a record is created (several crud entry
# points share the guard), so it maps to 409 once here instead of per-route.
@app.exception_handler(crud.DemoMixingError)
def _demo_mixing_handler(request, exc: crud.DemoMixingError):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


# `farm_id` is this system's only isolation boundary (there is no tenant model), so a
# reference that crosses farms is rejected wherever it is attempted — one handler
# rather than a per-route check that a new route could forget.
@app.exception_handler(crud.CrossFarmReferenceError)
def _cross_farm_handler(request, exc: crud.CrossFarmReferenceError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


# A refused PCA-authority claim is 403 everywhere, with the machine-readable reason
# attached: a PCA being denied needs to know whether their token is unknown, expired,
# revoked, or simply not granted this farm.
@app.exception_handler(crud.PcaAuthorityError)
def _pca_authority_handler(request, exc: crud.PcaAuthorityError):
    return JSONResponse(
        status_code=403, content={"detail": str(exc), "reason": exc.reason}
    )


# A database uniqueness violation is a duplicate, not a server fault. The only such
# constraints are the PCA token digest and the one-original-reading-per-station-hour
# partial index, so a clear 409 beats a 500 for both.
@app.exception_handler(IntegrityError)
def _integrity_handler(request, exc: IntegrityError):
    detail = "This record conflicts with one that already exists."
    # SQLite names the COLUMNS in the violation, not the index, so match on those.
    origin = str(getattr(exc, "orig", exc))
    if "weather_observations.station_id" in origin and "observed_at" in origin:
        detail = (
            "A reading already exists for this station at this timestamp. Duplicating "
            "an hour would double-count it in a risk window — to correct the existing "
            "reading, post a new one with `supersedes_id` set to it."
        )
    elif "pca_dispositions.planned_spray_id" in origin:
        detail = (
            "A live PCA disposition already exists for this decision. Dispositions are "
            "append-only — to change it, post a new one with `supersedes_id` set to the "
            "one it replaces, so the original judgement stays on the record."
        )
    elif "block_assignments.pilot_protocol_id" in origin:
        detail = (
            "This block already has an arm under this protocol version. Assignments are "
            "never changed — moving a block mid-pilot invalidates the comparison — so a "
            "genuine change means a new protocol version with its own assignments."
        )
    return JSONResponse(status_code=409, content={"detail": detail})


def optional_pca_credential(
    x_lumos_pca_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Resolve the PCA token when one is presented, without requiring it.

    Routes that MAY be credential-gated (creating a check, recording a review) take
    this and let `crud.ensure_pca_authority` decide whether this farm demands one.
    Routes that ALWAYS require it (recording a disposition) call
    `crud.require_pca_for_farm` directly, so the strict path can never degrade into
    the optional one by accident.

    A token that is PRESENTED but unusable — unknown, revoked, expired, not yet
    active — is always an error, even on a farm that would not otherwise require one.
    Silently ignoring it would let a PCA whose token was mistyped or revoked act
    through the anonymous free-text path while believing they had authority, and
    would attribute the record to a credential that is no longer valid.

    Credential VALIDITY is checked here because it is global; farm SCOPE is checked
    by `crud.ensure_pca_authority` / `crud.require_pca_for_farm`, because only they
    know which farm is being acted on.
    """
    if x_lumos_pca_token is None:
        return None
    credential = crud.resolve_pca_token(db, x_lumos_pca_token)
    reason = pca_authority.credential_denial_reason(credential, clock.current_date())
    if reason is not None:
        raise crud.PcaAuthorityError(reason)
    return credential


@app.on_event("startup")
def _startup() -> None:
    # A pinned demo clock must be an explicit choice (LUMOS_DEMO_MODE=1), never a
    # leftover env var silently corrupting real pilot timestamps and PHI/REI math.
    clock.assert_safe_for_serving()
    init_db()
    # An unprotected operator surface must be impossible once real data exists.
    # Reuses the same conservative "might be real pilot data" test that guards the
    # demo-reset endpoint, rather than inventing a second definition of "real".
    db = SessionLocal()
    try:
        operator_key.assert_safe_for_serving(crud.has_non_demo_data(db))
    finally:
        db.close()


# ------------------------------------------------------------------------ Health
@app.get("/health", tags=["health"])
def health():
    return {
        "status": "ok",
        "service": "lumos-spray-copilot",
        # "pinned" means LUMOS_DEMO_TODAY is anchoring every date — demo server only.
        "clock_mode": clock.mode(),
        "pinned_date": clock.pinned_anchor(),
    }


# ------------------------------------------------------------------------- Farms
@app.get("/farms", response_model=list[schemas.Farm], tags=["farms"])
def get_farms(db: Session = Depends(get_db)):
    return crud.list_farms(db)


@app.post("/farms", response_model=schemas.Farm, status_code=201, tags=["farms"])
def post_farm(payload: schemas.FarmCreate, db: Session = Depends(get_db)):
    return crud.create_farm(db, payload)


def _farm_overview_entry(db: Session, farm) -> dict:
    """One farm's action-oriented status entry — the ONLY derivation of the dashboard
    counts. The farm-detail page consumes the same entry via /farms/{id}/overview so
    the card and the page can never disagree. Predicates come from decision_status.
    """
    today = clock.current_date()
    sprays = crud.list_spray_events(db, farm.id)
    observations = crud.list_scout_observations(db, farm.id)
    planned = crud.list_planned_sprays(db, farm.id)
    signals = generate_recommendation(farm, sprays, observations, today=today).signals

    counts = decision_status.status_counts(planned)
    flag_count = sum(
        1 for k in (
            "phi_risk", "rei_risk", "repeated_active_ingredient_risk",
            "high_severity_scouting",
        ) if signals.get(k)
    )

    if counts["open_conflict_count"]:
        urgency, why = "conflict", (
            f"{counts['open_conflict_count']} planned spray(s) conflict with entered "
            f"harvest/re-entry timing"
        )
        next_action = "Resolve the blocked pre-spray decision with your PCA"
    elif farm.expected_harvest_date and farm.expected_harvest_date < today:
        # A stale harvest date invalidates every PHI calculation made against it —
        # ask for an update before any new pre-spray check is trusted. Only a live
        # blocked decision outranks this.
        urgency, why = "harvest_overdue", (
            f"Expected harvest date ({farm.expected_harvest_date.isoformat()}) has "
            f"passed — PHI checks against it are no longer valid"
        )
        next_action = "Update the expected harvest date before relying on new pre-spray checks"
    elif counts["needs_review_count"]:
        urgency, why = "needs_review", (
            f"{counts['needs_review_count']} pre-spray decision(s) awaiting PCA review"
        )
        next_action = "Review the pending pre-spray decision(s)"
    elif counts["awaiting_outcome_count"]:
        urgency, why = "awaiting_outcome", (
            f"{counts['awaiting_outcome_count']} checked spray(s) without a recorded outcome"
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
    return {
        "id": farm.id,
        "name": farm.name,
        "location": farm.location,
        "country": farm.country,
        "crop_type": farm.crop_type,
        "area": farm.greenhouse_area,
        "expected_harvest_date": _iso(farm.expected_harvest_date),
        # Server-computed so every "in N days" label agrees with the engine's day math
        # (client-side Date parsing is timezone-dependent and can be off by one).
        "days_to_harvest": (
            (farm.expected_harvest_date - today).days
            if farm.expected_harvest_date else None
        ),
        "urgency": urgency,
        "why": why,
        "next_action": next_action,
        **counts,
        "flag_count": flag_count,
        "spray_count": len(sprays),
        "is_demo": bool(records) and all(
            decision_status.is_demo_record(r) for r in records
        ),
    }


# NOTE: declared before /farms/{farm_id} so "overview" isn't parsed as a farm id.
@app.get("/farms-overview", tags=["farms"])
def farms_overview(db: Session = Depends(get_db)):
    """Action-oriented farm list: which farm needs attention, why, and the next action.

    One call for the dashboard (instead of N calls per farm). Urgency ranking:
    conflict (a critical pre-spray decision is unresolved) > needs_review (a decision
    awaits PCA review) > awaiting_outcome > flags (record-level PHI/REI/resistance/
    scouting flags) > ok.
    """
    out = [_farm_overview_entry(db, farm) for farm in crud.list_farms(db)]
    rank = {
        "conflict": 0, "harvest_overdue": 1, "needs_review": 2,
        "awaiting_outcome": 3, "flags": 4, "ok": 5,
    }
    out.sort(key=lambda f: (rank.get(f["urgency"], 9), f["id"]))
    return out


def _require_farm(db: Session, farm_id: int):
    farm = crud.get_farm(db, farm_id)
    if farm is None:
        raise HTTPException(status_code=404, detail="Farm not found")
    return farm


@app.get("/farms/{farm_id}/overview", tags=["farms"])
def farm_overview(farm_id: int, db: Session = Depends(get_db)):
    """The same status entry the dashboard shows for this farm (single derivation)."""
    farm = _require_farm(db, farm_id)
    return _farm_overview_entry(db, farm)


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


# ------------------------------------------------------------------------ Blocks
@app.get("/farms/{farm_id}/blocks", response_model=list[schemas.Block], tags=["blocks"])
def get_blocks(farm_id: int, db: Session = Depends(get_db)):
    _require_farm(db, farm_id)
    return crud.list_blocks(db, farm_id)


@app.post(
    "/farms/{farm_id}/blocks",
    response_model=schemas.Block,
    status_code=201,
    tags=["blocks"],
)
def post_block(farm_id: int, payload: schemas.BlockCreate, db: Session = Depends(get_db)):
    _require_farm(db, farm_id)
    return crud.create_block(db, farm_id, payload)


# --------------------------------------------------------- Pilot observations
# Append-only inputs to a disease-risk assessment. There is no update or delete: a
# correction appends a row that supersedes the one it replaces.
@app.get(
    "/farms/{farm_id}/weather-observations",
    response_model=list[schemas.WeatherObservation],
    tags=["pilot-observations"],
)
def get_weather_observations(
    farm_id: int, block_id: int | None = None, db: Session = Depends(get_db)
):
    _require_farm(db, farm_id)
    return crud.list_weather_observations(db, farm_id, block_id)


@app.post(
    "/farms/{farm_id}/weather-observations",
    response_model=schemas.WeatherObservation,
    status_code=201,
    tags=["pilot-observations"],
)
def post_weather_observation(
    farm_id: int,
    payload: schemas.WeatherObservationCreate,
    db: Session = Depends(get_db),
):
    """Record one weather reading. Manual/CSV entry only — Lumos has no weather
    provider integration, and none should be built before the provider and field
    requirements are known."""
    _require_farm(db, farm_id)
    return crud.create_weather_observation(db, farm_id, payload)


@app.get(
    "/farms/{farm_id}/scouting-samples",
    response_model=list[schemas.ScoutingSample],
    tags=["pilot-observations"],
)
def get_scouting_samples(
    farm_id: int, block_id: int | None = None, db: Session = Depends(get_db)
):
    _require_farm(db, farm_id)
    return crud.list_scouting_samples(db, farm_id, block_id)


@app.post(
    "/farms/{farm_id}/scouting-samples",
    response_model=schemas.ScoutingSample,
    status_code=201,
    tags=["pilot-observations"],
)
def post_scouting_sample(
    farm_id: int, payload: schemas.ScoutingSampleCreate, db: Session = Depends(get_db)
):
    """Record one standardized scouting sample. Incidence is derived from the stated
    denominator, never accepted as input."""
    _require_farm(db, farm_id)
    return crud.create_scouting_sample(db, farm_id, payload)


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

    result = build_analysis_result(finding, today=clock.current_date())
    # Logged like every other AI call. This path was the only unlogged one, and it is
    # the only one whose output can reach the decision engine (a human-confirmed
    # scouting severity feeds the engine's scouting rule) — exactly the path that most
    # needs to be auditable and calibratable later.
    crud.log_ai_judgment(
        db,
        kind="photo_analysis",
        model_id=finding.get("model") or "unknown",
        prompt_version=vision.PROMPT_VERSION,
        input_digest=vision.photo_input_digest(image_bytes, concern),
        output={
            "detected_issue": finding.get("detected_issue"),
            "suggested_severity": finding.get("suggested_severity"),
            "caveats": finding.get("caveats") or [],
        },
        confidence=result["confidence"],
        # The model abstains by declining to name an issue — there is no separate
        # abstention flag on this schema, so absence of a finding IS the abstention.
        abstained=finding.get("detected_issue") is None,
        abstain_reason=(
            "the model did not identify a specific issue in this photo"
            if finding.get("detected_issue") is None else None
        ),
        is_mock=bool(finding.get("is_mock")),
        farm_id=farm.id,
    )
    return result


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
    farm_id: int,
    payload: schemas.PlannedSprayCreate,
    db: Session = Depends(get_db),
    pca=Depends(optional_pca_credential),
):
    """Check an *intended* spray before it happens (the pre-spray decision point).

    Runs the decision engine (PHI/REI vs. harvest, prior re-entry windows, repeated
    active ingredient, scouting evidence, missing data) and returns ONE explainable
    outcome — approve / block / delay / inspect_first / pca_review_required — with the
    triggered rules, inputs, calculations, and confidence snapshotted on the record.
    Decision support only — the real-world outcome is recorded separately by the human.
    """
    farm = _require_farm(db, farm_id)
    return crud.create_planned_spray(db, farm, payload, pca_credential=pca)


@app.post(
    "/planned-sprays/{planned_id}/risk-snapshot",
    response_model=schemas.RiskInputSnapshot,
    status_code=201,
    tags=["pilot-risk"],
)
def post_risk_snapshot(
    planned_id: int,
    payload: schemas.RiskSnapshotCreate,
    db: Session = Depends(get_db),
):
    """Freeze exactly what was knowable at this moment for this decision's block.

    Immutable once written. Observations that were recorded after `as_of` are
    excluded even when they describe an earlier time — knowing something later is not
    knowing it then, and an assessment scored on hindsight would be meaningless.
    """
    planned = _require_planned_spray(db, planned_id)
    return crud.create_risk_snapshot(
        db, planned, as_of=payload.as_of, horizon_hours=payload.horizon_hours
    )


@app.get(
    "/planned-sprays/{planned_id}/risk-snapshots",
    response_model=list[schemas.RiskInputSnapshot],
    tags=["pilot-risk"],
)
def get_risk_snapshots(planned_id: int, db: Session = Depends(get_db)):
    _require_planned_spray(db, planned_id)
    return crud.list_risk_snapshots(db, planned_id)


@app.post(
    "/planned-sprays/{planned_id}/risk-assessment",
    response_model=schemas.DiseaseRiskAssessment,
    status_code=201,
    tags=["pilot-risk"],
)
def post_risk_assessment(
    planned_id: int,
    payload: schemas.DiseaseRiskAssessmentCreate,
    db: Session = Depends(get_db),
):
    """Run a versioned rule over the decision's latest snapshot. Operator tooling.

    Returns the assessment to the OPERATOR who triggered it. This is not a PCA-facing
    route: while the pilot is blinded the PCA's own view of the decision carries no
    risk field at all, so recording a disposition cannot be influenced by it.

    `botrytis_wetness_v1` currently abstains on every input — its published thresholds
    have not been transcribed. That is a visible, reported state, not a silent failure.
    """
    planned = _require_planned_spray(db, planned_id)
    try:
        return crud.create_disease_risk_assessment(
            db, planned,
            model_version=payload.model_version or disease_risk.DEFAULT_MODEL_VERSION,
        )
    except crud.SnapshotRequiredError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post(
    "/planned-sprays/{planned_id}/pca-disposition",
    response_model=schemas.PcaDisposition,
    status_code=201,
    tags=["pilot-risk"],
)
def post_pca_disposition(
    planned_id: int,
    payload: schemas.PcaDispositionCreate,
    x_lumos_pca_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Record the licensed PCA's professional judgement about a scheduled application.

    ALWAYS requires an authorized credential — this calls `crud.require_pca_for_farm`
    directly rather than taking the optional dependency, so the strict path cannot
    degrade into the permissive one on a farm that happens to have no credentials.

    Recording a disposition changes nothing else about the decision. `defer` in
    particular does not unlock applied outcomes and does not satisfy a required PCA
    review — deferring and being cleared to spray are unrelated decisions.
    """
    planned = _require_planned_spray(db, planned_id)
    credential = crud.require_pca_for_farm(db, x_lumos_pca_token, planned.farm_id)
    try:
        return crud.create_pca_disposition(db, planned, payload, credential)
    except crud.SnapshotRequiredError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get(
    "/planned-sprays/{planned_id}/pca-dispositions",
    response_model=list[schemas.PcaDisposition],
    tags=["pilot-risk"],
)
def get_pca_dispositions(planned_id: int, db: Session = Depends(get_db)):
    """The full chain, superseded rows included — a correction never hides what it replaced."""
    _require_planned_spray(db, planned_id)
    return crud.list_pca_dispositions(db, planned_id)


# ------------------------------------------------------------- Pilot protocol
@app.post(
    "/farms/{farm_id}/pilot-protocols",
    response_model=schemas.PilotProtocol,
    status_code=201,
    tags=["pilot-risk"],
)
def post_pilot_protocol(
    farm_id: int, payload: schemas.PilotProtocolCreate, db: Session = Depends(get_db)
):
    """Record which protocol version is in force. The protocol itself is a document."""
    _require_farm(db, farm_id)
    return crud.create_pilot_protocol(db, farm_id, payload)


@app.get(
    "/farms/{farm_id}/pilot-protocols",
    response_model=list[schemas.PilotProtocol],
    tags=["pilot-risk"],
)
def get_pilot_protocols(farm_id: int, db: Session = Depends(get_db)):
    _require_farm(db, farm_id)
    return crud.list_pilot_protocols(db, farm_id)


@app.post(
    "/pilot-protocols/{protocol_id}/assignments",
    response_model=schemas.BlockAssignment,
    status_code=201,
    tags=["pilot-risk"],
)
def post_block_assignment(
    protocol_id: int,
    payload: schemas.BlockAssignmentCreate,
    db: Session = Depends(get_db),
):
    """Record an offline randomization or matching decision, with its seed.

    409 on a repeat: a block belongs to one arm per protocol version, and changing
    arms mid-pilot invalidates the comparison. A genuine change is a new version.
    """
    protocol = crud.get_pilot_protocol(db, protocol_id)
    if protocol is None:
        raise HTTPException(status_code=404, detail="Pilot protocol not found")
    return crud.create_block_assignment(db, protocol, payload)


@app.get(
    "/pilot-protocols/{protocol_id}/assignments",
    response_model=list[schemas.BlockAssignment],
    tags=["pilot-risk"],
)
def get_block_assignments(protocol_id: int, db: Session = Depends(get_db)):
    if crud.get_pilot_protocol(db, protocol_id) is None:
        raise HTTPException(status_code=404, detail="Pilot protocol not found")
    return crud.list_block_assignments(db, protocol_id)


# ------------------------------------------------------------- Block outcomes
@app.post(
    "/farms/{farm_id}/block-outcomes",
    response_model=schemas.BlockOutcomeObservation,
    status_code=201,
    tags=["pilot-risk"],
)
def post_block_outcome(
    farm_id: int,
    payload: schemas.BlockOutcomeObservationCreate,
    db: Session = Depends(get_db),
):
    """Append a measured block outcome (incidence, packout, cull, cost, ...).

    Per block per harvest, NOT per decision — one harvest outcome is evidence for many
    decisions and for none in particular. Append-only: no PATCH, no DELETE.
    """
    _require_farm(db, farm_id)
    return crud.create_block_outcome(db, farm_id, payload)


@app.get(
    "/farms/{farm_id}/block-outcomes",
    response_model=list[schemas.BlockOutcomeObservation],
    tags=["pilot-risk"],
)
def get_block_outcomes(
    farm_id: int, block_id: int | None = None, db: Session = Depends(get_db)
):
    _require_farm(db, farm_id)
    return crud.list_block_outcomes(db, farm_id, block_id)


@app.get(
    "/internal/pilot/assessments",
    response_model=list[schemas.DiseaseRiskAssessment],
    tags=["internal"],
)
def get_shadow_assessments(farm_id: int | None = None, db: Session = Depends(get_db)):
    """The ONLY surface that returns shadow assessments before unblinding."""
    return crud.list_shadow_assessments(db, farm_id)


@app.post(
    "/internal/farms/{farm_id}/opportunity-scans",
    response_model=schemas.OpportunityScan,
    status_code=201,
    tags=["internal"],
)
def post_opportunity_scan(
    farm_id: int,
    payload: schemas.OpportunityScanCreate,
    db: Session = Depends(get_db),
):
    """Replay a past season's scheduled spray dates for one block (pilot ladder Stage 2).

    INTERNAL on purpose, and for a different reason than most `/internal` routes. This
    is not merely operator tooling: a risk histogram reaching a PCA who is enrolled in
    the blinded shadow study would contaminate the baseline their dispositions exist to
    provide. It stays behind the operator key for as long as any farm is in shadow.

    Returns the histogram together with `cannot_conclude` — the scan cannot be received
    without its claim ceiling.
    """
    _require_farm(db, farm_id)
    try:
        return crud.run_opportunity_scan(
            db,
            farm_id,
            payload.block_id,
            payload.decision_dates,
            horizon_hours=payload.horizon_hours,
            lookback_hours=payload.lookback_hours,
            run_by=payload.run_by,
        )
    except crud.CrossFarmReferenceError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get(
    "/internal/opportunity-scans",
    response_model=list[schemas.OpportunityScan],
    tags=["internal"],
)
def get_opportunity_scans(
    farm_id: int | None = None, limit: int = 50, db: Session = Depends(get_db)
):
    return crud.list_opportunity_scans(db, farm_id, limit)


@app.get(
    "/internal/opportunity-scans/{scan_id}",
    response_model=schemas.OpportunityScan,
    tags=["internal"],
)
def get_opportunity_scan(scan_id: int, db: Session = Depends(get_db)):
    scan = crud.get_opportunity_scan(db, scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Opportunity scan not found")
    return scan


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
    planned_id: int,
    payload: schemas.PlannedSprayReviewUpdate,
    db: Session = Depends(get_db),
    pca=Depends(optional_pca_credential),
):
    """PCA / agronomist review of a pre-spray decision (approve / edit / reject + comment).

    An edit must include the PCA's replacement guidance; a rejection must say why.
    On a farm with PCA credentials enrolled, an approve/edit requires an authorized
    token (403 without one); a rejection never does.
    """
    planned = _require_planned_spray(db, planned_id)
    return crud.review_planned_spray(db, planned, payload, pca_credential=pca)


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
    except crud.OutcomeChronologyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get(
    "/planned-sprays/{planned_id}/audit-events",
    response_model=list[schemas.DecisionAuditEvent],
    tags=["planned-sprays"],
)
def get_planned_spray_audit_events(planned_id: int, db: Session = Depends(get_db)):
    """The immutable, append-only audit history of one decision (oldest first).

    Every state change (creation, review, value supersession, outcome, follow-up)
    appends an event with the prior state — nothing here is ever edited or deleted.
    """
    _require_planned_spray(db, planned_id)
    return crud.list_audit_events(db, planned_id)


@app.get(
    "/planned-sprays/{planned_id}/input-values",
    response_model=list[schemas.DecisionInputValue],
    tags=["planned-sprays"],
)
def get_planned_spray_input_values(planned_id: int, db: Session = Depends(get_db)):
    """Field-level provenance for the decision's critical inputs (full supersede chain,
    oldest first). The latest non-superseded row per field drives the engine."""
    _require_planned_spray(db, planned_id)
    return crud.list_input_values(db, planned_id)


@app.get(
    "/planned-sprays/{planned_id}/follow-up-events",
    response_model=list[schemas.FollowUpEvent],
    tags=["planned-sprays"],
)
def get_follow_up_events(planned_id: int, db: Session = Depends(get_db)):
    """The decision's append-only follow-up timeline (oldest first)."""
    _require_planned_spray(db, planned_id)
    return crud.list_follow_up_events(db, planned_id)


@app.post(
    "/planned-sprays/{planned_id}/follow-up-events",
    response_model=schemas.FollowUpEvent,
    status_code=201,
    tags=["planned-sprays"],
)
def post_follow_up_event(
    planned_id: int, payload: schemas.FollowUpEventCreate, db: Session = Depends(get_db)
):
    """Append one follow-up event (scouting / actual application / rescue / harvest /
    yield-quality / note) to a decision whose outcome is recorded.

    Append-only by design: there is no update or delete. A planned avoidance only
    becomes a CONFIRMED result through this timeline; yield/quality stay "unknown"
    until someone records them.
    """
    planned = _require_planned_spray(db, planned_id)
    try:
        return crud.add_follow_up_event(db, planned, payload)
    except crud.FollowUpError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/planned-sprays/{planned_id}/ai-brief", tags=["planned-sprays"])
def post_ai_brief(planned_id: int, db: Session = Depends(get_db)):
    """AI review brief: retrieval-grounded rescue-risk note + next EVIDENCE actions.

    On-demand only. Grounded exclusively in this decision's audit payload and
    comparable real decisions on the same farm (explicit alias/chemistry match) with
    their recorded follow-ups. Enum-locked to evidence-gathering actions — product or
    spray recommendations are structurally inexpressible. Abstains (deterministic
    server-side guard) with fewer than 2 real comparables. NEVER changes the
    decision; both judgments are logged append-only for future calibration.
    """
    planned = _require_planned_spray(db, planned_id)
    comparables = crud.comparable_decisions(db, planned)

    payload = planned.decision_payload or {}
    decision_summary = {
        "id": planned.id,
        "product_name": planned.product_name,
        "active_ingredient": planned.active_ingredient,
        "moa_group": planned.moa_group,
        "target_pest_or_disease": planned.target_pest_or_disease,
        "intended_date": _iso(planned.intended_date),
        "decision_outcome": planned.decision_outcome,
        "decision_severity": planned.decision_severity,
        "decision_authority": planned.decision_authority,
        "triggered_rules": [
            {"rule_id": r.get("rule_id"), "detail": r.get("detail")}
            for r in payload.get("rules", []) if r.get("triggered")
        ],
        "missing_information": payload.get("missing_information", []),
        "unverified_field_sources": (payload.get("inputs_used") or {}).get(
            "field_sources", {}
        ),
        "recorded_outcome": planned.outcome,
        "follow_up_required": planned.follow_up_required,
        "follow_up_event_count": planned.follow_up_event_count,
    }

    service = llm.default_llm_service
    try:
        brief, model_id = service.parse(
            ai_brief.build_system_prompt(),
            ai_brief.build_content_blocks(decision_summary, comparables),
            ai_brief.AiBrief,
        )
    except llm.LlmError as exc:
        raise HTTPException(status_code=502, detail=f"AI brief failed: {exc}") from exc

    brief = ai_brief.apply_post_guards(brief, len(comparables))
    digest = ai_brief.input_digest(decision_summary, comparables)

    risk_judgment = crud.log_ai_judgment(
        db, kind="risk_note", model_id=model_id,
        prompt_version=ai_brief.PROMPT_VERSION, input_digest=digest,
        output={
            "rescue_risk": brief.rescue_risk, "rationale": brief.rationale,
            "comparable_count": len(comparables),
        },
        confidence=brief.confidence, abstained=brief.abstained,
        abstain_reason=brief.abstain_reason, is_mock=service.is_mock,
        farm_id=planned.farm_id, planned_spray_id=planned.id,
    )
    action_judgment = crud.log_ai_judgment(
        db, kind="next_evidence_action", model_id=model_id,
        prompt_version=ai_brief.PROMPT_VERSION, input_digest=digest,
        output={"actions": [a.model_dump() for a in brief.next_evidence_actions]},
        confidence=brief.confidence, abstained=brief.abstained,
        abstain_reason=brief.abstain_reason, is_mock=service.is_mock,
        farm_id=planned.farm_id, planned_spray_id=planned.id,
    )

    return ai_brief.brief_payload(
        brief, model_id, service.is_mock, len(comparables),
        [risk_judgment.id, action_judgment.id], comparables,
    )


@app.get("/farms/{farm_id}/decision-evidence", tags=["planned-sprays"])
def farm_decision_evidence(farm_id: int, db: Session = Depends(get_db)):
    """Pre-spray decision workflow metrics for the pilot/evidence dashboard.

    Demo/simulated decisions are excluded; every figure states whether it is a count,
    an entered estimate, or a stated assumption (see `limitations`).
    """
    farm = _require_farm(db, farm_id)
    planned = crud.list_planned_sprays(db, farm_id)
    return build_decision_evidence(
        planned,
        advisor_label=_advisor_label(farm),
        follow_ups_by_id=crud.list_farm_follow_up_events(db, farm_id),
        # Empty until a label with a transcribed concentration is PCA-verified for
        # this farm, which is what keeps the active-ingredient quantity honestly
        # not-calculated rather than partially totalled.
        ai_concentrations=crud.ai_concentrations_for_farm(db, farm_id),
        is_reference_farm=bool(farm.is_reference),
    )


@app.delete("/planned-sprays/{planned_id}", status_code=204, tags=["planned-sprays"])
def remove_planned_spray(planned_id: int, db: Session = Depends(get_db)):
    """Remove a decision that has accumulated no evidence — e.g. one just mistyped.

    409 once it carries an outcome, a completed review, follow-ups, a snapshot, an
    assessment, a disposition, procurement, or any audit history beyond its creation.
    Pilot evidence is append-only; a corrected decision is recorded, not swapped in.
    """
    planned = _require_planned_spray(db, planned_id)
    try:
        crud.delete_planned_spray(db, planned)
    except crud.DecisionHasEvidenceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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
    return compute_cost_analytics(sprays, today=clock.current_date())


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
    result = generate_recommendation(farm, sprays, observations, today=clock.current_date())
    weather = default_weather_service.get_weather_risk(farm.location)
    recs = crud.list_recommendations(db, farm_id)
    latest = recs[0] if recs else None
    planned = crud.list_planned_sprays(db, farm_id)
    review_states = [decision_status.review_state(p) for p in planned]

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
        # Review status of the latest farm-wide WEEKLY recommendation — NOT the
        # pre-spray decisions. Renamed so the UI can never present it as the decision
        # queue's review state (that lives in `decision_review` below).
        "recommendation_review_status": latest.agronomist_status if latest else "none",
        # Canonical pre-spray decision review summary (decision_status semantics).
        "decision_review": {
            "pending": review_states.count("pending"),
            "approved": review_states.count("approved"),
            "edited": review_states.count("edited"),
            "rejected": review_states.count("rejected"),
            "not_required": review_states.count("not_required"),
            "needs_review_count": sum(
                1 for p in planned if decision_status.needs_review(p)
            ),
        },
        "advisor_label": _advisor_label(farm),
        # Honest framing for the UI: these signals come from user-entered PHI/REI values,
        # not from a verified pesticide-label database.
        "basis": _compliance_basis(db, farm_id),
        # One server-owned sentence for every surface that describes where these
        # signals come from. Previously four components each hardcoded their own
        # wording, so the honest framing could drift apart — and could not become
        # conditional at all. Nothing is deleted: with no verified label coverage
        # this is the exact sentence those components already showed.
        "basis_text": _compliance_basis_text(db, farm_id),
    }


# The pre-label wording, kept verbatim. Every surface showed some version of this
# sentence; now they all show THIS one, and it stays the answer until a licensed PCA
# has verified a label for the farm.
COMPLIANCE_BASIS_UNVERIFIED = "user-entered values, not label-verified"
COMPLIANCE_BASIS_TEXT_UNVERIFIED = (
    "These signals come from PHI/REI values entered by the user, not from verified "
    "label data. Confirm them against the product label and a licensed PCA."
)


def _verified_label_count(db: Session, farm_id: int) -> int:
    """How many products have a label record verified for this farm by a PCA."""
    return sum(
        1
        for product in crud.list_pesticide_products(db)
        if any(
            crud.resolve_label_for_decision(
                db, product.epa_reg_no, record.registered_crop, farm_id
            )[2] is None
            for record in product.label_records
        )
    )


def _compliance_basis(db: Session, farm_id: int) -> str:
    """Short machine-ish label for where the compliance signals came from."""
    return (
        "partially label-verified"
        if _verified_label_count(db, farm_id)
        else COMPLIANCE_BASIS_UNVERIFIED
    )


def _compliance_basis_text(db: Session, farm_id: int) -> str:
    """The sentence every compliance surface renders. Degrades to today's wording.

    "Partially" is not hedging — it is the accurate word. A farm can have one
    verified label and five products without one, and a sentence claiming the
    snapshot is label-verified would be false for most of what it shows.
    """
    verified = _verified_label_count(db, farm_id)
    if not verified:
        return COMPLIANCE_BASIS_TEXT_UNVERIFIED
    return (
        f"PHI/REI values for {verified} product(s) come from a pesticide label "
        f"verified for this farm by a licensed PCA; everything else on this card "
        f"still comes from user-entered values. Confirm those against the product "
        f"label and a licensed PCA."
    )


def _advisor_label(farm) -> str:
    """U.S. specialty-crop growers work with a PCA; elsewhere we just say agronomist."""
    return "PCA / agronomist" if (farm.country or "").upper() in ("US", "USA") else "agronomist"


# ----------------------------------------------------------- Data readiness
# One server-owned sentence, exactly as `_compliance_basis_text` is. The lesson that
# produced that helper was four components each hardcoding their own wording and
# drifting apart; this surface starts on the right side of it, so `DataReadinessCard`
# renders `basis_text` verbatim and contains no sentence of its own.

DATA_READINESS_BASIS_TEXT_NONE = (
    "No outside data source is configured for this farm, so every reading here was "
    "entered by hand. Nothing on this card is a live feed."
)


def _data_readiness_basis_text(runs: list, feature_rows: list) -> str:
    """Where the numbers on the readiness card come from. Never a claim about risk.

    Deliberately says what the data IS, not what it means. This card exists to answer
    "can this farm support a measurement yet", and a sentence that drifted toward
    "conditions look favourable" would turn a data-quality surface into a spray prompt.
    """
    if not runs:
        return DATA_READINESS_BASIS_TEXT_NONE
    succeeded = sum(1 for r in runs if r.status == ingest_base.RUN_SUCCEEDED)
    skipped = sum(1 for r in runs if r.status == ingest_base.RUN_SKIPPED_NO_CREDENTIAL)
    abstained = sum(1 for row in feature_rows if row.abstained)

    if succeeded == 0 and skipped:
        return (
            "A weather source is configured but has no credential, so no data has been "
            "fetched. Every value below is still hand-entered."
        )
    sentence = (
        f"{succeeded} ingestion run(s) have brought in provider-reported weather for "
        f"this farm. Provider readings are machine-fetched and unreviewed — they are "
        f"not PCA-verified."
    )
    if abstained:
        sentence += (
            f" {abstained} measure(s) below could not be calculated; each one says why "
            f"rather than showing a zero."
        )
    return sentence


@app.get("/farms/{farm_id}/data-readiness", tags=["farms"])
def data_readiness(farm_id: int, db: Session = Depends(get_db)):
    """Whether this farm's data can yet support a measurement, per field and block.

    Grower/PCA-facing and deliberately NOT under `/internal`: the answer to "why does
    my risk assessment still say it did not run" belongs to the person whose farm it
    is, not only to an operator.

    Every feature is rendered as EITHER `{value, unit}` OR `{abstained, reasons}` —
    never a number-shaped placeholder, and never a null `value` key, because a null in
    a numeric field is exactly what a template turns into `0` or `--`. The shape comes
    straight from `FeatureResult.as_payload`, whose invariant makes the two states
    mutually exclusive.

    Carries no risk band, no product, no rate and no action. A readiness card that
    drifted into "conditions look favourable" would be a spray prompt wearing a
    data-quality label, and would also break the shadow study's blinding.
    """
    _require_farm(db, farm_id)

    rows = crud.list_feature_values_for_farm(db, farm_id)
    runs = crud.list_ingestion_runs(db, farm_id=farm_id, limit=50)

    def entity_block(entity_type: str) -> list:
        out = []
        for entity_id in sorted({r.entity_id for r in rows if r.entity_type == entity_type}):
            measures = {}
            for row in rows:
                if row.entity_type != entity_type or row.entity_id != entity_id:
                    continue
                measures[row.name] = (
                    {"abstained": True, "reasons": list(row.reasons or [])}
                    if row.abstained
                    else {"value": row.value, "unit": row.unit}
                )
            out.append({"entity_id": entity_id, "measures": measures})
        return out

    return {
        "farm_id": farm_id,
        "fields": entity_block("field"),
        "crop_cycles": entity_block("crop_cycle"),
        "blocks": entity_block("block"),
        "ingestion": {
            "runs": len(runs),
            "last_run_at": runs[0].finished_at if runs else None,
            "last_status": runs[0].status if runs else None,
        },
        # Server-owned. The card renders this string and writes none of its own.
        "basis_text": _data_readiness_basis_text(runs, rows),
    }


@app.get("/internal/ingestion", tags=["internal"])
def internal_ingestion_runs(
    farm_id: int | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """INTERNAL ingestion health: recent runs with their counts and issues.

    The counts are the point. A run that fetched 24 rows and admitted 24 is a different
    event from one that fetched 24 and admitted 3, and a pipeline reporting only
    success/failure would show both as `succeeded`.
    """
    runs = crud.list_ingestion_runs(db, farm_id=farm_id, limit=limit)
    return {
        "runs": [
            {
                "id": run.id,
                "source_key": run.source_key,
                "domain": run.domain,
                "farm_id": run.farm_id,
                "field_id": run.field_id,
                "status": run.status,
                "window_start": run.window_start,
                "window_end": run.window_end,
                "adapter_version": run.adapter_version,
                "counts": {
                    "fetched": run.fetched_count,
                    "parsed": run.parsed_count,
                    "admitted": run.admitted_count,
                    "duplicate": run.duplicate_count,
                    "superseded": run.superseded_count,
                    "issues": run.issue_count,
                },
                "started_at": run.started_at,
                "finished_at": run.finished_at,
                "duration_ms": run.duration_ms,
                "error": run.error,
                "issues": [
                    {
                        "stage": issue.stage,
                        "severity": issue.severity,
                        "code": issue.code,
                        "message": issue.message,
                        "row_index": issue.row_index,
                    }
                    for issue in run.issues[:20]
                ],
            }
            for run in runs
        ],
    }


@app.post("/internal/ingestion/{source_key}/run", tags=["internal"])
def internal_ingestion_run_now(
    source_key: str,
    payload: schemas.IngestionRunRequest,
    db: Session = Depends(get_db),
):
    """INTERNAL: enqueue one ingestion run. Does NOT fetch synchronously.

    Enqueuing rather than running inline is deliberate: the worker is where retries,
    dead-lettering and stall recovery live, and a route that fetched directly would be
    a second execution path with none of them. It also keeps a slow provider from
    holding an HTTP request open.
    """
    if source_key not in ingest_registry.source_keys():
        raise HTTPException(status_code=404, detail=f"unknown source {source_key!r}")
    _require_farm(db, payload.farm_id)

    job = job_queue.enqueue(
        db,
        "ingest.run_source",
        {
            "source_key": source_key,
            "farm_id": payload.farm_id,
            "field_id": payload.field_id,
            "station_id": payload.station_id,
            "lookback_hours": payload.lookback_hours,
        },
        source_key=source_key,
    )
    return {
        "job_id": job.id,
        "status": job.status,
        "source": ingest_registry.describe(source_key).as_payload(),
        "note": (
            "Enqueued. Run the worker to execute it: "
            "python -m app.jobs.worker --once --queues ingest"
        ),
    }


# -------------------------------------------------------------- Weekly report
@app.get("/farms/{farm_id}/weekly-report", tags=["reports"])
def weekly_report(farm_id: int, db: Session = Depends(get_db)):
    """Return a plain-text weekly summary that can be copied into WhatsApp."""
    farm = _require_farm(db, farm_id)
    sprays = crud.list_spray_events(db, farm_id)
    observations = crud.list_scout_observations(db, farm_id)
    recs = crud.list_recommendations(db, farm_id)
    latest_rec = recs[0] if recs else None
    analytics = compute_cost_analytics(sprays, today=clock.current_date())
    weather = default_weather_service.get_weather_risk(farm.location)
    # Current compliance signals (PHI / REI / repeated-AI) for the report's flag block.
    signals = generate_recommendation(
        farm, sprays, observations, today=clock.current_date()
    ).signals

    text = _build_weekly_report_text(
        farm, len(sprays), len(observations), latest_rec, analytics, weather, signals,
        decision_summary=summarize_decisions_for_report(
            crud.list_planned_sprays(db, farm_id), today=clock.current_date()
        ),
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


def _decision_report_lines(summary: dict) -> list[str]:
    """The 'spray decisions' block for the weekly report and the audit packet.

    This block is the product. It was missing from both artifacts entirely — the
    grower's WhatsApp message and the auditor's packet were built only from the legacy
    farm-wide recommendation, so neither mentioned a single pre-spray decision.

    Honesty rules applied here, not left to the caller:
      * a simulated scope is LABELLED, never silently counted as real;
      * a decision still awaiting review is marked, because an unreviewed verdict is
        not guidance — the same rule the recommendation block below already follows;
      * counts describe what was documented, never what was prevented or saved.
    """
    if not summary["checked"]:
        return []

    heading = "This week's spray decisions"
    if summary["is_simulated"]:
        heading += " (SIMULATED demo records — not real usage)"

    lines = ["", f"{heading}: {summary['checked']} checked"]
    for d in summary["decisions"]:
        when = d["intended_date"].isoformat() if d["intended_date"] else "date not set"
        lines.append(f"  • {d['product_name']} ({when}) — {d['verdict_text']}")
        if d["reason"]:
            lines.append(f"      {d['reason']}")
        if d["needs_review"]:
            lines.append("      Awaiting review — not yet guidance.")
        elif d["outcome_text"]:
            lines.append(f"      Recorded outcome: {d['outcome_text']}.")

    tally = [f"{summary['conflicts_caught']} conflict(s) caught before application"]
    if summary["not_applied"]:
        tally.append(f"{summary['not_applied']} application(s) recorded as not applied")
    if summary["awaiting_review"]:
        tally.append(f"{summary['awaiting_review']} awaiting review")
    lines.append(f"  {' · '.join(tally)}.")
    return lines


def _build_weekly_report_text(
    farm, spray_count, observation_count, latest_rec, analytics, weather, signals,
    decision_summary: dict | None = None,
) -> str:
    advisor = _advisor_label(farm)              # "PCA / agronomist" (US) or "agronomist"
    advisor_cap = advisor[:1].upper() + advisor[1:]   # capitalise first letter, keep "PCA"
    cur = _currency_symbol(farm)
    crop_icon = "🍓" if (farm.crop_type or "").lower().startswith("straw") else "🍅"

    lines = [
        f"{crop_icon} Lumos Weekly Report — {farm.name}",
        f"Location: {farm.location} · {clock.current_date().isoformat()}",
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

    # The decision workflow — the thing the product actually does — goes here, before
    # the farm-wide weekly recommendation.
    if decision_summary:
        lines += _decision_report_lines(decision_summary)

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


# ----------------------------------------------------------------- PCA policies
@app.get(
    "/farms/{farm_id}/pca-policies",
    response_model=list[schemas.PcaPolicy],
    tags=["pca-policies"],
)
def get_pca_policies(farm_id: int, db: Session = Depends(get_db)):
    """The farm's current PCA-entered action thresholds (latest per target wins)."""
    _require_farm(db, farm_id)
    return crud.list_pca_policies(db, farm_id)


@app.put(
    "/farms/{farm_id}/pca-policies",
    response_model=schemas.PcaPolicy,
    tags=["pca-policies"],
)
def put_pca_policy(
    farm_id: int, payload: schemas.PcaPolicyCreate, db: Session = Depends(get_db)
):
    """Record a PCA-entered action threshold for one target (attributed, never invented).

    The pre-spray check's scouting rule reads it with source_authority=pca_entered:
    without recent linked scouting at or above the threshold, the check returns
    INSPECT FIRST instead of relying on a rule-of-thumb heuristic.
    """
    _require_farm(db, farm_id)
    return crud.set_pca_policy(db, farm_id, payload)


# ------------------------------------------------------ Reduction measurement
def _farm_reduction(db: Session, farm, sprays) -> dict:
    """Measure spray reduction for a farm against its current baseline (if any)."""
    baseline = crud.get_spray_baseline(db, farm.id)
    return compute_reduction(farm, sprays, baseline, today=clock.current_date())


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
    analytics = compute_cost_analytics(sprays, today=clock.current_date())
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
        today=clock.current_date(),
    )


@app.get("/import/templates/{record_type}.csv", tags=["pilot-import"])
def import_template(record_type: str):
    """Downloadable CSV template (canonical headers + one clearly-marked example row)."""
    if record_type not in csv_import.FIELDS_BY_TYPE:
        raise HTTPException(
            status_code=404,
            detail=f"No template for '{record_type}'. Available: "
            f"{', '.join(sorted(csv_import.FIELDS_BY_TYPE))}.",
        )
    return Response(
        content=csv_import.template_csv(record_type),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="lumos_{record_type}_template.csv"'
        },
    )


@app.post("/farms/{farm_id}/import/csv", tags=["pilot-import"])
def farm_csv_import(
    farm_id: int, payload: schemas.CsvImportRequest, db: Session = Depends(get_db)
):
    """CSV pilot import for planned sprays or scouting observations.

    Dry-run by default: returns the validation report (column mapping, per-row errors
    and warnings, duplicates) without writing anything. Re-post with dry_run=false to
    commit the importable rows. Imported regulatory values are stored as
    imported_unverified field-level provenance — they are flagged by the decision
    check and can never produce an automatic approve.
    """
    farm = _require_farm(db, farm_id)
    return crud.import_csv(db, farm, payload)


@app.post("/farms/{farm_id}/import/document", tags=["pilot-import"])
async def farm_document_extraction(
    farm_id: int,
    record_type: str = Form(...),
    text: str | None = Form(None),
    file: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    """AI extraction of draft rows from a messy document (PDF/photo) or pasted text.

    REAL AI (Claude structured outputs; deterministic mock without an API key), and
    honest about it: values are extracted only as literally written (regulatory
    values are never guessed), every row carries a verbatim source snippet, the model
    abstains when the input isn't a spray/scouting record, and the extraction is
    logged to the append-only AI judgment log. This endpoint NEVER writes records —
    it returns the same dry-run report as the CSV import; a human reviews/corrects
    the rows and commits them via POST /farms/{id}/import/rows.
    """
    farm = _require_farm(db, farm_id)
    # AI extraction supports the record types with an extraction output model —
    # spray_events history is CSV-import only for now.
    if record_type not in extraction.OUTPUT_MODELS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown record_type '{record_type}'. Use one of: "
            f"{', '.join(sorted(extraction.OUTPUT_MODELS))}.",
        )

    file_bytes = None
    media_type = None
    if file is not None:
        media_type = (file.content_type or "").lower()
        allowed = extraction.ALLOWED_DOCUMENT_TYPES + extraction.ALLOWED_IMAGE_TYPES
        if media_type not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type '{media_type}'. Use PDF or an image "
                f"(JPEG/PNG/WebP/GIF), or paste the text instead.",
            )
        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(status_code=400, detail="Empty file upload.")
        if len(file_bytes) > extraction.MAX_DOCUMENT_BYTES:
            raise HTTPException(status_code=400, detail="File too large (max 10 MB).")
    if file_bytes is None and not (text or "").strip():
        raise HTTPException(
            status_code=422, detail="Provide a file or pasted text to extract from."
        )

    output_model = extraction.OUTPUT_MODELS[record_type]
    blocks = extraction.build_content_blocks(text, file_bytes, media_type)
    service = llm.default_llm_service
    try:
        result, model_id = service.parse(
            extraction.build_system_prompt(record_type), blocks, output_model
        )
    except llm.LlmError as exc:  # refusal, truncation, transport — never a 500
        raise HTTPException(status_code=502, detail=f"AI extraction failed: {exc}") from exc

    judgment = crud.log_ai_judgment(
        db,
        kind="extraction",
        model_id=model_id,
        prompt_version=extraction.PROMPT_VERSION,
        input_digest=extraction.input_digest(record_type, text, file_bytes),
        output={"record_type": record_type, "rows": len(result.rows),
                "abstained": result.abstained, "caveats": result.caveats},
        confidence="none" if result.abstained else result.overall_confidence,
        abstained=result.abstained,
        abstain_reason=result.abstain_reason,
        is_mock=service.is_mock,
        farm_id=farm.id,
    )

    report = csv_import.validate_rows(
        record_type,
        extraction.rows_to_raw(result),
        existing_keys=crud.existing_duplicate_keys(db, farm.id, record_type),
    )
    return {
        "judgment_id": judgment.id,
        "record_type": record_type,
        "extraction": extraction.extraction_payload(result, model_id, service.is_mock),
        "report": report.as_payload(),
    }


@app.post("/farms/{farm_id}/import/rows", tags=["pilot-import"])
def farm_row_import(
    farm_id: int, payload: schemas.RowImportRequest, db: Session = Depends(get_db)
):
    """Commit human-reviewed structured rows (the AI-extraction commit path).

    Rows are RE-validated server-side through the exact same path as the CSV import
    before anything is written; committed rows carry `ai_extracted` provenance and
    field-level imported_unverified values — they can never auto-approve.
    """
    farm = _require_farm(db, farm_id)
    return crud.import_rows(db, farm, payload)


# ------------------------------------------------ INTERNAL: PCA credentials
# Operator tooling. Issuing a credential is a deliberate out-of-band act: the operator
# confirms the PCA's licence themselves and hands over the token directly. Lumos
# verifies nothing against any registry and never claims to.
@app.post(
    "/internal/pca-credentials",
    response_model=schemas.PcaCredentialIssued,
    status_code=201,
    tags=["internal"],
)
def post_pca_credential(
    payload: schemas.PcaCredentialCreate, db: Session = Depends(get_db)
):
    """Issue a PCA credential. The plaintext token is returned ONCE and never stored."""
    credential, token = crud.create_pca_credential(db, payload)
    return schemas.PcaCredentialIssued(
        **schemas.PcaCredential.model_validate(credential).model_dump(), token=token
    )


@app.get(
    "/internal/pca-credentials",
    response_model=list[schemas.PcaCredential],
    tags=["internal"],
)
def get_pca_credentials(db: Session = Depends(get_db)):
    return crud.list_pca_credentials(db)


def _require_credential(db: Session, credential_id: int):
    credential = crud.get_pca_credential(db, credential_id)
    if credential is None:
        raise HTTPException(status_code=404, detail="PCA credential not found")
    return credential


@app.post(
    "/internal/pca-credentials/{credential_id}/revoke",
    response_model=schemas.PcaCredential,
    tags=["internal"],
)
def post_revoke_pca_credential(credential_id: int, db: Session = Depends(get_db)):
    """Revoke a credential. Never deleted — the decisions it signed stay attributable."""
    return crud.revoke_pca_credential(db, _require_credential(db, credential_id))


@app.post(
    "/internal/pca-credentials/{credential_id}/farm-authorizations",
    response_model=schemas.PcaFarmAuthorization,
    status_code=201,
    tags=["internal"],
)
def post_pca_farm_authorization(
    credential_id: int,
    payload: schemas.PcaFarmAuthorizationCreate,
    db: Session = Depends(get_db),
):
    """Authorize one credential for one farm.

    Granting the FIRST authorization on a farm turns on credential enforcement there:
    from then on, claiming PCA-entered values or recording an approve/edit review
    requires a token.
    """
    credential = _require_credential(db, credential_id)
    _require_farm(db, payload.farm_id)
    return crud.authorize_pca_for_farm(db, credential, payload)


@app.get(
    "/internal/farms/{farm_id}/pca-authorizations",
    response_model=list[schemas.PcaFarmAuthorization],
    tags=["internal"],
)
def get_farm_pca_authorizations(farm_id: int, db: Session = Depends(get_db)):
    _require_farm(db, farm_id)
    return crud.list_farm_authorizations(db, farm_id)


# ------------------------------------------------ INTERNAL: pesticide labels
# Read + load only. Nothing here writes a decision input value or changes a verdict —
# applying label values to a decision is a separate, gated step. These routes sit under
# /internal so app/operator_key.py's path-prefix middleware covers them by construction.
@app.get(
    "/internal/labels/products",
    response_model=list[schemas.PesticideProduct],
    tags=["internal"],
)
def get_pesticide_products(db: Session = Depends(get_db)):
    """Every product in the label library, with its append-only label records."""
    return crud.list_pesticide_products(db)


@app.get(
    "/internal/labels/products/{product_id}",
    response_model=schemas.PesticideProduct,
    tags=["internal"],
)
def get_pesticide_product(product_id: int, db: Session = Depends(get_db)):
    product = crud.get_pesticide_product(db, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Pesticide product not found")
    return product


@app.post(
    "/internal/labels/sync",
    response_model=schemas.LabelSyncResult,
    tags=["internal"],
)
def post_label_sync(db: Session = Depends(get_db)):
    """Load `app/label_table.TRANSCRIBED_LABEL_USES` into the append-only record table.

    Deliberately an explicit operator act, not something startup or seeding does: seeded
    label data would make demo decisions look label-grounded, which is a fabricated
    regulatory claim. Safe to re-run — unchanged entries are no-ops and a changed
    transcription appends a superseding row rather than overwriting the original.

    Returns `transcribed_entries: 0` until a value has been transcribed from a primary
    label document with its citation. That is the intended state, not a failure.
    """
    return crud.sync_transcribed_labels(db)


@app.get(
    "/internal/labels/resolution",
    response_model=schemas.LabelResolution,
    tags=["internal"],
)
def get_label_resolution(
    epa_reg_no: str | None = None,
    crop: str | None = None,
    farm_id: int | None = None,
    db: Session = Depends(get_db),
):
    """What a (registration number, crop, farm) resolves to today — and why not, if not.

    The diagnostic behind "why does this decision still say the label check did not
    run". It calls the same `crud.resolve_label_for_decision` the decision path uses, so
    the answer here cannot drift from the answer on a decision record.
    """
    if farm_id is not None:
        _require_farm(db, farm_id)
    record, unresolved_reason, blocked = crud.resolve_label_for_decision(
        db, epa_reg_no, crop, farm_id
    )
    product, _ = crud.resolve_product_identity(db, epa_reg_no)
    return schemas.LabelResolution(
        epa_reg_no=epa_reg_no,
        crop=crop,
        farm_id=farm_id,
        product=product,
        label_record=record,
        unresolved_reason=unresolved_reason,
        promotable=record is not None and blocked is None,
        promotion_blocked_reason=blocked,
    )


@app.post("/internal/labels/extract", tags=["internal"])
async def post_label_extraction(
    text: str | None = Form(None),
    file: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    """AI extraction of draft label uses from a label PDF, photo, or pasted text.

    REAL AI (Claude structured outputs; deterministic mock without an API key), and
    the most carefully fenced call in the system because its output is a regulatory
    value: the model copies only what the label literally states, never converts
    units, emits one row per (crop, use) block with a verbatim snippet, and abstains
    when the document is not a label.

    This endpoint NEVER WRITES a label record. It returns draft rows for a human to
    correct and commit via POST /internal/labels/records — where they land as
    `ai_extracted_unverified` and still cannot back any decision until a licensed
    PCA verifies them for a farm.
    """
    file_bytes = None
    media_type = None
    if file is not None:
        media_type = (file.content_type or "").lower()
        allowed = (
            label_extraction.ALLOWED_DOCUMENT_TYPES + label_extraction.ALLOWED_IMAGE_TYPES
        )
        if media_type not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type '{media_type}'. Use a PDF or an image "
                f"(JPEG/PNG/WebP/GIF), or paste the label text instead.",
            )
        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(status_code=400, detail="Empty file upload.")
        if len(file_bytes) > label_extraction.MAX_DOCUMENT_BYTES:
            raise HTTPException(status_code=400, detail="File too large (max 10 MB).")
    if file_bytes is None and not (text or "").strip():
        raise HTTPException(
            status_code=422, detail="Provide a label file or pasted text to extract from."
        )

    blocks = label_extraction.build_content_blocks(text, file_bytes, media_type)
    service = llm.default_llm_service
    try:
        result, model_id = service.parse(
            label_extraction.build_system_prompt(), blocks,
            label_extraction.LabelExtraction,
        )
    except llm.LlmError as exc:  # refusal, truncation, transport — never a 500
        raise HTTPException(
            status_code=502, detail=f"AI label extraction failed: {exc}"
        ) from exc

    judgment = crud.log_ai_judgment(
        db,
        kind="label_extraction",
        model_id=model_id,
        prompt_version=label_extraction.PROMPT_VERSION,
        input_digest=label_extraction.input_digest(text, file_bytes),
        output={"rows": len(result.rows), "abstained": result.abstained,
                "caveats": result.caveats},
        confidence="none" if result.abstained else result.overall_confidence,
        abstained=result.abstained,
        abstain_reason=result.abstain_reason,
        is_mock=service.is_mock,
    )
    return {
        "judgment_id": judgment.id,
        "extraction": label_extraction.extraction_payload(
            result, model_id, service.is_mock
        ),
    }


@app.post(
    "/internal/labels/records",
    response_model=schemas.ProductLabelRecord,
    status_code=201,
    tags=["internal"],
)
def post_label_record(
    payload: schemas.ProductLabelRecordCreate, db: Session = Depends(get_db)
):
    """Commit ONE human-reviewed label use as an `ai_extracted_unverified` record.

    Append-only: a row for a (product, crop) that already has a live record
    supersedes it rather than replacing it. The tier is server-set — no request
    field can declare a row verified, and the record still cannot back a decision
    until a licensed PCA attests to it for a farm.
    """
    return crud.create_label_record(db, payload)


@app.get(
    "/farms/{farm_id}/label-resolution",
    response_model=schemas.LabelResolution,
    tags=["labels"],
)
def get_farm_label_resolution(
    farm_id: int,
    epa_reg_no: str | None = None,
    crop: str | None = None,
    db: Session = Depends(get_db),
):
    """What a (registration number, crop) resolves to for THIS farm — grower-facing.

    The same resolution as `/internal/labels/resolution`, scoped to one farm and
    outside the operator gate, because the person entering a spray needs the answer:
    it tells them whether to type PHI/REI or whether the verified label already
    supplies them. Read-only; it writes nothing and changes no decision.

    Not a data leak in the operator sense — it returns only what a decision on this
    farm would already show on its record, and it cannot be used to promote anything.
    """
    farm = _require_farm(db, farm_id)
    record, unresolved_reason, blocked = crud.resolve_label_for_decision(
        db, epa_reg_no, crop or farm.crop_type, farm.id
    )
    product, _ = crud.resolve_product_identity(db, epa_reg_no)
    return schemas.LabelResolution(
        epa_reg_no=epa_reg_no,
        crop=crop or farm.crop_type,
        farm_id=farm.id,
        product=product,
        label_record=record,
        unresolved_reason=unresolved_reason,
        promotable=record is not None and blocked is None,
        promotion_blocked_reason=blocked,
    )


@app.post(
    "/farms/{farm_id}/label-verifications",
    response_model=schemas.ProductLabelVerification,
    status_code=201,
    tags=["labels"],
)
def post_label_verification(
    farm_id: int,
    payload: schemas.ProductLabelVerificationCreate,
    db: Session = Depends(get_db),
    x_lumos_pca_token: str | None = Header(default=None),
):
    """A licensed PCA attests that a stored label record matches the primary document.

    The act that makes a label value usable, so it goes through
    `crud.require_pca_for_farm` — the strict path, not the optional one — and is
    attributed from the credential rather than any client-supplied name. NOT under
    /internal: this is a professional act by the farm's PCA, not operator tooling.
    """
    farm = _require_farm(db, farm_id)
    credential = crud.require_pca_for_farm(db, x_lumos_pca_token, farm_id)
    try:
        return crud.create_label_verification(db, farm, payload, credential)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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
    analytics = compute_cost_analytics(sprays, today=clock.current_date())
    weather = default_weather_service.get_weather_risk(farm.location)
    advisor = _advisor_label(farm)
    evidence = build_pilot_evidence(
        farm, sprays, observations, recs, analytics, weather["risk_level"],
        advisor_label=advisor, reduction=_farm_reduction(db, farm, sprays),
        today=clock.current_date(),
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
    analytics = compute_cost_analytics(sprays, today=clock.current_date())
    weather = default_weather_service.get_weather_risk(farm.location)
    result = generate_recommendation(farm, sprays, observations, today=clock.current_date())
    batches = crud.list_pilot_import_batches(db, farm_id)
    latest_rec = recs[0] if recs else None
    # The pre-spray decision trail — the audit-relevant part of this product, and
    # absent from this packet until now.
    decisions = summarize_decisions_for_report(
        crud.list_planned_sprays(db, farm_id), today=clock.current_date()
    )
    report_text = _build_weekly_report_text(
        farm, len(sprays), len(observations), latest_rec, analytics, weather,
        result.signals, decision_summary=decisions,
    )

    return {
        "generated_at": clock.current_datetime().isoformat() + "Z",
        "advisor_label": _advisor_label(farm),
        # Structured decision trail. `scope` says whether these are real or simulated
        # records; an auditor must never have to infer that.
        "spray_decisions": {
            **decisions,
            "decisions": [
                {**d, "intended_date": _iso(d["intended_date"])}
                for d in decisions["decisions"]
            ],
        },
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


@app.post("/internal/demo/reset", tags=["internal"])
def reset_demo(db: Session = Depends(get_db)):
    """Drop and re-seed the demo database, anchored to the current app-clock date.

    Refuses (409) when ANYTHING in the DB might be real pilot data — seeding drops
    every table, and real records must never be one accidental click away from
    deletion. The dashboard's "Reset YC demo" button calls this.
    """
    if crud.has_non_demo_data(db):
        raise HTTPException(
            status_code=409,
            detail="Refusing to reset: this database contains data that is not "
            "demo/simulated. The demo reset drops every table and is only allowed "
            "on an all-demo database.",
        )
    # seed.run() drops all tables on its own connection; release this request's
    # session first so SQLite isn't locked by our open transaction.
    db.close()
    from app import seed  # local import: seeding is not part of normal request flow

    summary = seed.run()
    return {"status": "reseeded", **(summary or {})}


@app.get("/internal/ai-calibration", tags=["internal"])
def internal_ai_calibration(db: Session = Depends(get_db)):
    """INTERNAL: predicted AI rescue-risk vs. realized rescues, abstention rate, and
    judgment counts. Rates are gated behind a minimum n — counts only until then."""
    judgments = crud.list_ai_judgments(db)
    decisions_by_id = {p.id: p for p in crud.list_all_planned_sprays(db)}
    return build_ai_calibration(
        judgments, decisions_by_id, crud.list_all_follow_up_events(db)
    )


@app.get("/internal/jobs", tags=["internal"])
def internal_jobs(
    status: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """INTERNAL background-job health: queue counts plus the most recent jobs.

    The question this answers is "is the platform still ingesting and recomputing", and
    the number that matters is `dead` — a dead job is work that silently stopped
    happening, which for a weather feed means every dependent feature quietly goes
    stale rather than visibly failing.
    """
    query = db.query(models.Job)
    if status:
        query = query.filter(models.Job.status == status)
    recent = query.order_by(models.Job.updated_at.desc(), models.Job.id.desc()).limit(
        max(1, min(limit, 500))
    ).all()
    return {
        "stats": job_queue.stats(db),
        "jobs": [
            {
                "id": job.id,
                "queue": job.queue,
                "task_name": job.task_name,
                "status": job.status,
                "priority": job.priority,
                "attempts": job.attempts,
                "max_attempts": job.max_attempts,
                "run_at": job.run_at,
                "source_key": job.source_key,
                "last_error": job.last_error,
                "locked_by": job.locked_by,
                "finished_at": job.finished_at,
                "created_at": job.created_at,
                "runs": [
                    {
                        "attempt": run.attempt,
                        "status": run.status,
                        "started_at": run.started_at,
                        "duration_ms": run.duration_ms,
                        "error": run.error,
                    }
                    for run in job.runs
                ],
            }
            for job in recent
        ],
    }


# ------------------------------------------------------- Finance persistence
# Recording an assessment is an operator act (it is a consequential record about a real
# person's farm), so the POSTs are operator-gated. READING a farm's own assessment
# history is grower-facing — "why was I declined" is their question, and the refusal
# rows are the part they most need to see.
@app.post("/internal/farms/{farm_id}/credit-assessments", status_code=201,
          tags=["internal"])
def internal_record_credit_assessment(
    farm_id: int, assessed_by: str | None = None, db: Session = Depends(get_db)
):
    """INTERNAL: run the transcribed scorecard and STORE the result — or the refusal.

    With no scorecard transcribed this stores a refusal every time, which is the point:
    "could not score, no scorecard supplied, on this date" is a materially different
    history from an empty one, and it is the record that protects both sides.
    """
    _require_farm(db, farm_id)
    row = crud.record_credit_assessment(db, farm_id, assessed_by=assessed_by)
    return schemas.CreditAssessment.model_validate(row)


@app.get("/farms/{farm_id}/credit-assessments", tags=["finance"])
def farm_credit_assessments(farm_id: int, db: Session = Depends(get_db)):
    """A farm's full assessment history, newest first, INCLUDING refusals.

    Append-only: nothing here was ever edited or deleted, so what a lender saw on a
    given date stays recoverable. `inputs_digest` is what makes that checkable rather
    than merely claimed.
    """
    _require_farm(db, farm_id)
    return [
        schemas.CreditAssessment.model_validate(a)
        for a in crud.list_credit_assessments(db, farm_id)
    ]


@app.post("/internal/farms/{farm_id}/underwriting-decisions", status_code=201,
          tags=["internal"])
def internal_record_underwriting_decision(
    farm_id: int, payload: schemas.UnderwritingRequest, db: Session = Depends(get_db)
):
    """INTERNAL: evaluate the transcribed policy and store the outcome.

    The outcome is never "approved" — there is no such value in the vocabulary and no
    column that could hold one. Storing an evaluation does not make it a commitment.
    """
    _require_farm(db, farm_id)
    row = crud.record_underwriting_decision(
        db, farm_id, exposure_amount=payload.exposure_amount,
        evidence_keys=payload.evidence_keys, decided_by=payload.decided_by,
    )
    return schemas.UnderwritingDecision.model_validate(row)


@app.get("/farms/{farm_id}/underwriting-decisions", tags=["finance"])
def farm_underwriting_decisions(farm_id: int, db: Session = Depends(get_db)):
    _require_farm(db, farm_id)
    return [
        schemas.UnderwritingDecision.model_validate(d)
        for d in crud.list_underwriting_decisions(db, farm_id)
    ]


@app.post("/internal/farms/{farm_id}/collateral", status_code=201, tags=["internal"])
def internal_register_collateral(
    farm_id: int, payload: schemas.CollateralAssetCreate, db: Session = Depends(get_db)
):
    """INTERNAL: register or revalue a collateral asset.

    Append-only: pass `supersedes_id` to revalue, which keeps what the asset was
    assessed at when an earlier decision referenced it.
    """
    _require_farm(db, farm_id)
    row = crud.register_collateral_asset(db, farm_id, payload)
    return schemas.CollateralAsset.model_validate(row)


@app.get("/farms/{farm_id}/collateral", tags=["finance"])
def farm_collateral(farm_id: int, db: Session = Depends(get_db)):
    """LIVE assets only — superseded rows are excluded so a revaluation cannot
    double-count the same asset in a total."""
    _require_farm(db, farm_id)
    return [
        schemas.CollateralAsset.model_validate(a)
        for a in crud.list_collateral_assets(db, farm_id)
    ]


@app.post("/internal/farms/{farm_id}/monitoring-snapshots", status_code=201,
          tags=["internal"])
def internal_record_monitoring_snapshot(farm_id: int, db: Session = Depends(get_db)):
    """INTERNAL: evaluate the covenant schedule and store the standing.

    `standing` is three-valued, and `unknown` is the common answer. A farm with an
    unevaluated covenant is NOT in good standing — nobody looked at all of it.
    """
    _require_farm(db, farm_id)
    row = crud.record_monitoring_snapshot(db, farm_id)
    return schemas.MonitoringSnapshot.model_validate(row)


@app.get("/farms/{farm_id}/monitoring-snapshots", tags=["finance"])
def farm_monitoring_snapshots(farm_id: int, db: Session = Depends(get_db)):
    _require_farm(db, farm_id)
    return [
        schemas.MonitoringSnapshot.model_validate(s)
        for s in crud.list_monitoring_snapshots(db, farm_id)
    ]


@app.post("/internal/farms/{farm_id}/coverage-assessments", status_code=201,
          tags=["internal"])
def internal_record_coverage_assessment(
    farm_id: int, payload: schemas.CoverageAssessmentRequest,
    db: Session = Depends(get_db),
):
    """INTERNAL: match transcribed insurance products and store the result. No premium."""
    _require_farm(db, farm_id)
    row = crud.record_coverage_assessment(
        db, farm_id, crop=payload.crop, peril=payload.peril,
        evidence_keys=payload.evidence_keys, assessed_by=payload.assessed_by,
    )
    return schemas.CoverageAssessment.model_validate(row)


@app.get("/farms/{farm_id}/coverage-assessments", tags=["finance"])
def farm_coverage_assessments(farm_id: int, db: Session = Depends(get_db)):
    _require_farm(db, farm_id)
    return [
        schemas.CoverageAssessment.model_validate(c)
        for c in crud.list_coverage_assessments(db, farm_id)
    ]


# ------------------------------------------------------------------- Marketplace
# Supplier and catalogue registration is operator work (concierge, like quote entry),
# so it sits under /internal. Dispersion and transmission history are grower-facing:
# what suppliers quoted, and whether anyone was actually contacted, belong to the
# person whose plan it is.
@app.post("/internal/suppliers", response_model=schemas.Supplier, status_code=201,
          tags=["internal"])
def internal_create_supplier(
    payload: schemas.SupplierCreate, db: Session = Depends(get_db)
):
    """INTERNAL: register a supplier as an entity rather than a string on each quote."""
    return crud.create_supplier(db, payload)


@app.get("/internal/suppliers", tags=["internal"])
def internal_list_suppliers(
    include_inactive: bool = False, db: Session = Depends(get_db)
):
    """INTERNAL: suppliers in registration order.

    NOT ranked and not sorted by any quality or price signal — ordering a supplier list
    is a recommendation, and Lumos does not make one.
    """
    return [
        schemas.Supplier.model_validate(s)
        for s in crud.list_suppliers(db, include_inactive=include_inactive)
    ]


@app.post("/internal/input-products", response_model=schemas.InputProduct,
          status_code=201, tags=["internal"])
def internal_create_input_product(
    payload: schemas.InputProductCreate, db: Session = Depends(get_db)
):
    """INTERNAL: add a product to the catalogue.

    The catalogue is what makes price comparison possible at all — quote lines carry
    free text, and grouping three spellings of one product reports three products with
    no spread each.
    """
    return crud.create_input_product(db, payload)


@app.get("/internal/input-products", tags=["internal"])
def internal_list_input_products(db: Session = Depends(get_db)):
    return [
        schemas.InputProduct.model_validate(p) for p in crud.list_input_products(db)
    ]


@app.post("/internal/suppliers/{supplier_id}/catalog",
          response_model=schemas.SupplierProduct, status_code=201, tags=["internal"])
def internal_link_supplier_product(
    supplier_id: int, payload: schemas.SupplierProductCreate,
    db: Session = Depends(get_db),
):
    """INTERNAL: record that a supplier offers a catalogued product. No price."""
    if db.get(models.Supplier, supplier_id) is None:
        raise HTTPException(status_code=404, detail="supplier not found")
    return crud.link_supplier_product(db, supplier_id, payload)


@app.get("/internal/suppliers/{supplier_id}/catalog", tags=["internal"])
def internal_supplier_catalog(supplier_id: int, db: Session = Depends(get_db)):
    if db.get(models.Supplier, supplier_id) is None:
        raise HTTPException(status_code=404, detail="supplier not found")
    return [
        schemas.SupplierProduct.model_validate(c)
        for c in crud.list_supplier_catalog(db, supplier_id)
    ]


@app.get("/rfq-transport", tags=["procurement"])
def rfq_transport_status():
    """Whether this deployment can transmit an RFQ to anybody.

    Answers "did my request actually go anywhere". Today it always reports `can_send:
    false` with the reason — no transport is configured, so RFQs are recorded as skipped
    and a human sends them. Reported rather than hidden, because a submitted plan that
    silently contacts nobody is the gap this endpoint exists to make visible.
    """
    return rfq_transport.describe().as_payload()


@app.post("/input-plans/{plan_id}/transmit-rfq", status_code=201, tags=["procurement"])
def transmit_rfq(
    plan_id: int, payload: schemas.RfqTransmissionRequest,
    db: Session = Depends(get_db),
):
    """Attempt to send this plan's RFQ to named suppliers, and record the outcome.

    One append-only row per intended recipient, ALWAYS — including when nothing was
    sent. Recipients are named explicitly rather than auto-selected: choosing who gets
    asked to quote, on the grower's behalf, is a form of ranking.
    """
    plan = crud.get_input_plan(db, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="input plan not found")

    rows = crud.record_rfq_transmissions(
        db, plan, supplier_ids=payload.supplier_ids, requested_by=payload.requested_by
    )
    if not rows:
        raise HTTPException(
            status_code=404, detail="none of the supplied supplier_ids exist"
        )
    return [schemas.RfqTransmission.model_validate(r) for r in rows]


@app.get("/input-plans/{plan_id}/transmissions", tags=["procurement"])
def list_transmissions(plan_id: int, db: Session = Depends(get_db)):
    if crud.get_input_plan(db, plan_id) is None:
        raise HTTPException(status_code=404, detail="input plan not found")
    return [
        schemas.RfqTransmission.model_validate(r)
        for r in crud.list_rfq_transmissions(db, plan_id)
    ]


@app.get("/input-plans/{plan_id}/price-dispersion", tags=["procurement"])
def plan_price_dispersion(plan_id: int, db: Session = Depends(get_db)):
    """How much each catalogued product varied in price across the suppliers who quoted.

    This is what "better buying power" means concretely and honestly. It reports a
    spread, not a saving and not a recommended supplier — a grower may have good reasons
    to buy above the lowest quote, and calling the difference a saving assumes they did
    not. Observations stay in entry order; sorting by price would make this a ranking in
    everything but name.
    """
    if crud.get_input_plan(db, plan_id) is None:
        raise HTTPException(status_code=404, detail="input plan not found")
    return crud.price_dispersion_for_plan(db, plan_id).as_payload()


# ------------------------------------------------- Transcription + cross-layer profile
@app.get("/internal/transcription-status", tags=["internal"])
def internal_transcription_status():
    """INTERNAL: every EMPTY transcription source, and the document that would fill it.

    The operator-facing counterpart to the eight admitted domains. Each source module
    ships empty by design (see `app/transcription.py`), so this endpoint is the worklist:
    it answers "what must someone go and read for the finance layer to produce anything",
    which is a procurement-and-reading task, not a build task.

    Generated from `domains.empty_sources()` rather than a hand-kept list, so a domain
    admitted later cannot be forgotten here — the same reason the operator key middleware
    gates on a path prefix rather than a route list.
    """
    statuses = [
        transcription.status_of(module_path, title=ingest_domains.get(key).title)
        for key, module_path in ingest_domains.empty_sources()
    ]
    return {
        "admission": ingest_domains.ADMISSION,
        "sources": [s.as_payload() for s in statuses],
        "populated_count": sum(1 for s in statuses if s.populated),
        "total_count": len(statuses),
        "note": (
            "A source is filled by transcribing a primary document WITH its citation, "
            "never by recalling a plausible value. Every model over an empty source "
            "returns a refusal naming the reason — that is the designed state, not a bug."
        ),
    }


@app.get("/farms/{farm_id}/profile", tags=["farms"])
def farm_cross_layer_profile(farm_id: int, db: Session = Depends(get_db)):
    """Every layer's view of one farm, side by side, each computed or refused.

    Grower-facing and deliberately NOT under `/internal`, for the same reason as
    `/data-readiness`: "why can't this product tell me anything about X" is a question
    that belongs to the person whose farm it is.

    Deliberately NOT added to the PCA-facing decision surface. The Botrytis shadow study
    depends on the reviewing PCA not seeing model output, and a cross-layer card on
    `/decisions/{id}` would break the blinding.

    On today's data nearly every layer refuses, and `blocking_gaps` — grouped by whether
    a grower or an operator can unblock it — is the useful payload. That grouping is the
    one genuinely cross-layer computation here; there is no overall score, because an
    average across layers that mostly abstain is meaningless rather than merely rough.
    """
    farm = _require_farm(db, farm_id)
    crop = farm.crop_type or "unknown"

    # Each layer supplies its own result or its own refusal. Nothing is invented to fill
    # a gap, and a layer that cannot answer says which document or record would let it.
    views = [
        (
            farm_profile.LAYER_OPERATIONS, "Soil",
            soil.interpret(crud.list_soil_readings(db, farm_id), crop=crop),
        ),
        (
            farm_profile.LAYER_ADVISORY, "Nutrient budget",
            fertilization.budget(
                crop=crop,
                expected_yield_tonnes=crud.expected_yield_tonnes(db, farm_id),
                nutrients=("nitrogen", "potassium"),
            ),
        ),
        (
            farm_profile.LAYER_ADVISORY, "Variety traits",
            seed_selection.traits_for(
                variety=crud.primary_variety(db, farm_id) or "unknown", crop=crop
            ),
        ),
        (
            farm_profile.LAYER_FINANCE, "Credit score",
            credit_scoring.score(
                features=crud.feature_results_for_farm(db, farm_id),
                as_of=clock.current_datetime(),
            ),
        ),
        (
            farm_profile.LAYER_FINANCE, "Collateral",
            collateral.value_assets(
                crud.list_collateral_assets(db, farm_id),
                currency="USD" if farm.country == "US" else "TRY",
            ),
        ),
        (
            farm_profile.LAYER_FINANCE, "Covenant standing",
            monitoring.evaluate(
                features=crud.feature_results_for_farm(db, farm_id),
                as_of=clock.current_datetime(),
            ),
        ),
        (
            farm_profile.LAYER_MARKET, "Reported price",
            pricing.latest(
                commodity=crop, market=farm.location or "unknown",
                as_of=clock.current_date(), max_age_days=7,
            ),
        ),
    ]

    return farm_profile.build(farm_id=farm_id, views=views).as_payload()


@app.get("/internal/ingestion/sources", tags=["internal"])
def internal_ingestion_sources():
    """INTERNAL: every declared data source and the domain table governing it.

    This is the artifact that makes "we declared seventeen domains and built one" a
    checkable statement rather than a claim in a document. Each source says whether the
    gap in front of it is a deployment task (`requires_credential`), a build task
    (`not_implemented`), or a governance decision (`deferred_to_finance_phase`) — and
    every deferred domain quotes the ENGINEERING_GUIDELINES.md clause that defers it.

    No database access at all: sources are code, so the answer cannot depend on what
    happens to be in this deployment's tables.
    """
    return ingest_registry.as_payload()


@app.get("/internal/instrumentation", tags=["internal"])
def internal_instrumentation(db: Session = Depends(get_db)):
    """INTERNAL pilot telemetry summary: check funnel, time-to-review, changed decisions,
    entry sources, abandonment. Never customer-facing."""
    return build_instrumentation_summary(
        crud.list_all_planned_sprays(db),
        crud.list_pilot_events(db),
        reference_farm_ids=crud.reference_farm_ids(db),
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


def _farm_evidence_export(db: Session, farm_id: int) -> dict:
    farm = _require_farm(db, farm_id)
    return build_evidence_export(
        farm,
        crud.list_planned_sprays(db, farm_id),
        crud.list_farm_follow_up_events(db, farm_id),
        crud.list_farm_audit_events(db, farm_id),
        crud.list_farm_input_values(db, farm_id),
        advisor_label=_advisor_label(farm),
        today=clock.current_date(),
        ai_concentrations=crud.ai_concentrations_for_farm(db, farm_id),
        input_plans=crud.list_input_plans(db, farm_id),
    )


@app.get("/farms/{farm_id}/evidence-export", tags=["export"])
def farm_evidence_export(farm_id: int, db: Session = Depends(get_db)):
    """Anonymized pilot-evidence export (JSON): every REAL (non-demo) decision with
    its sources and verification state, triggered exceptions, PCA action, immutable
    audit history, follow-up timeline, confirmed vs. estimated outcomes, missing
    evidence, and methodological limitations. Demo records are excluded by
    construction; the farm appears only as pilot-farm-{id}."""
    return _farm_evidence_export(db, farm_id)


@app.get("/farms/{farm_id}/export/evidence.csv", tags=["export"])
def export_evidence_csv(farm_id: int, db: Session = Depends(get_db)):
    """Flat CSV of the anonymized evidence export (one row per real decision)."""
    export = _farm_evidence_export(db, farm_id)
    header = [
        "farm_ref", "decision_id", "external_record_id", "field_block", "crop",
        "treated_acres", "product_name", "active_ingredient", "moa_group",
        "target_pest_or_disease", "intended_date", "rate_amount", "rate_unit",
        "estimated_cost", "decision_outcome", "decision_severity",
        "decision_authority", "triggered_exceptions", "unverified_input_fields",
        "review_status", "reviewed_by", "recorded_outcome", "outcome_date",
        "follow_up_event_count", "severity_before", "severity_after",
        "rescue_required", "confirmed_avoided", "confirmed_delay_days",
        "additional_scouting_cost", "rescue_cost", "yield_impact", "quality_impact",
        "missing_evidence",
    ]
    rows = []
    for d in export["decisions"]:
        summary = d["follow_up_summary"]
        unverified = sorted({
            v["field_name"] for v in d["input_values"]
            if v["source_type"] not in ("pca_verified", "authoritative_provider")
        })
        rows.append([
            export["farm_ref"], d["decision_id"], d["external_record_id"],
            d["field_block"], d["crop"], d["treated_acres"],
            d["planned"]["product_name"], d["planned"]["active_ingredient"],
            d["planned"]["moa_group"], d["planned"]["target_pest_or_disease"],
            d["planned"]["intended_date"], d["planned"]["rate_amount"],
            d["planned"]["rate_unit"], d["planned"]["estimated_cost"],
            d["decision"]["outcome"], d["decision"]["severity"],
            d["decision"]["authority"],
            "; ".join(r["rule_id"] for r in d["decision"]["triggered_exceptions"]),
            "; ".join(unverified),
            d["review"]["status"], d["review"]["reviewed_by"],
            d["recorded_action"]["outcome"], d["recorded_action"]["outcome_date"],
            summary["event_count"], summary["severity_before"],
            summary["severity_after"], summary["rescue_required"],
            summary["confirmed_avoided"], summary["confirmed_delay_days"],
            summary["additional_scouting_cost"], summary["rescue_cost"],
            summary["yield_impact"], summary["quality_impact"],
            "; ".join(d["missing_evidence"]),
        ])
    return _csv_response(f"pilot_farm_{farm_id}_evidence.csv", header, rows)


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


# ---------------------------------------------------------- Inputs & finance
# Phase 1 procurement: RFQ -> concierge-entered quotes -> optional INDICATIVE
# financing -> order -> explicit application link. No auth exists in v1 (same as
# every route above): farm scoping is by URL path and attribution is free-text
# actor strings; the concierge entry points are namespaced /internal and belong
# to the unlinked operator page. No real money moves anywhere in this module.


def _require_input_plan(db: Session, plan_id: int):
    plan = crud.get_input_plan(db, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Input plan not found")
    return plan


def _require_supplier_quote(db: Session, quote_id: int):
    quote = crud.get_supplier_quote(db, quote_id)
    if quote is None:
        raise HTTPException(status_code=404, detail="Supplier quote not found")
    return quote


def _require_financing_offer(db: Session, offer_id: int):
    offer = crud.get_financing_offer(db, offer_id)
    if offer is None:
        raise HTTPException(status_code=404, detail="Financing offer not found")
    return offer


def _require_purchase_order(db: Session, order_id: int):
    order = crud.get_purchase_order(db, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


def _procurement_call(fn, *args, **kwargs):
    """Map the typed procurement exceptions onto the API's 409/422 idiom."""
    try:
        return fn(*args, **kwargs)
    except (crud.ProcurementStateError, crud.ProcurementEligibilityError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except crud.ProcurementValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get(
    "/farms/{farm_id}/input-plans",
    response_model=list[schemas.InputPlan],
    tags=["inputs"],
)
def get_input_plans(farm_id: int, db: Session = Depends(get_db)):
    _require_farm(db, farm_id)
    return crud.list_input_plans(db, farm_id)


@app.post(
    "/farms/{farm_id}/input-plans",
    response_model=schemas.InputPlan,
    status_code=201,
    tags=["inputs"],
)
def post_input_plan(
    farm_id: int, payload: schemas.InputPlanCreate, db: Session = Depends(get_db)
):
    farm = _require_farm(db, farm_id)
    return _procurement_call(crud.create_input_plan, db, farm, payload)


@app.get(
    "/input-plans/{plan_id}",
    response_model=schemas.InputPlanDetail,
    tags=["inputs"],
)
def get_input_plan(plan_id: int, db: Session = Depends(get_db)):
    return _require_input_plan(db, plan_id)


@app.post(
    "/input-plans/{plan_id}/items",
    response_model=schemas.InputPlanItem,
    status_code=201,
    tags=["inputs"],
)
def post_input_plan_item(
    plan_id: int, payload: schemas.InputPlanItemCreate, db: Session = Depends(get_db)
):
    plan = _require_input_plan(db, plan_id)
    return _procurement_call(crud.add_input_plan_item, db, plan, payload)


@app.delete("/input-plan-items/{item_id}", status_code=204, tags=["inputs"])
def delete_input_plan_item(item_id: int, db: Session = Depends(get_db)):
    item = crud.get_input_plan_item(db, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Input plan item not found")
    _procurement_call(crud.delete_input_plan_item, db, item)


@app.post(
    "/input-plans/{plan_id}/submit",
    response_model=schemas.InputPlan,
    tags=["inputs"],
)
def submit_input_plan(
    plan_id: int, payload: schemas.InputPlanSubmit, db: Session = Depends(get_db)
):
    plan = _require_input_plan(db, plan_id)
    return _procurement_call(crud.submit_input_plan, db, plan, payload)


@app.post(
    "/input-plans/{plan_id}/cancel",
    response_model=schemas.InputPlan,
    tags=["inputs"],
)
def cancel_input_plan(
    plan_id: int, payload: schemas.InputPlanCancel, db: Session = Depends(get_db)
):
    plan = _require_input_plan(db, plan_id)
    return _procurement_call(crud.cancel_input_plan, db, plan, payload)


@app.get(
    "/input-plans/{plan_id}/quotes",
    response_model=list[schemas.SupplierQuote],
    tags=["inputs"],
)
def get_supplier_quotes(plan_id: int, db: Session = Depends(get_db)):
    """Quotes in ENTRY ORDER. There is deliberately no ranking: comparison uses
    transparent totals only — Lumos takes no commission and never ranks suppliers."""
    _require_input_plan(db, plan_id)
    return crud.list_supplier_quotes(db, plan_id)


@app.post(
    "/input-plans/{plan_id}/select-quote",
    response_model=schemas.InputPlan,
    tags=["inputs"],
)
def post_select_quote(
    plan_id: int, payload: schemas.SelectQuoteRequest, db: Session = Depends(get_db)
):
    plan = _require_input_plan(db, plan_id)
    return _procurement_call(crud.select_quote, db, plan, payload)


@app.post(
    "/financing-offers/{offer_id}/decision",
    response_model=schemas.FinancingOffer,
    tags=["inputs"],
)
def post_financing_offer_decision(
    offer_id: int, payload: schemas.FinancingOfferDecision, db: Session = Depends(get_db)
):
    """The grower's one-shot select/decline of an INDICATIVE offer. Selecting
    records a preference for indicative terms only — it is never a loan
    approval, never lender confirmation, and moves no money."""
    offer = _require_financing_offer(db, offer_id)
    return _procurement_call(crud.decide_financing_offer, db, offer, payload)


@app.post(
    "/input-plans/{plan_id}/order",
    response_model=schemas.PurchaseOrder,
    status_code=201,
    tags=["inputs"],
)
def post_purchase_order(
    plan_id: int, payload: schemas.PurchaseOrderCreate, db: Session = Depends(get_db)
):
    plan = _require_input_plan(db, plan_id)
    return _procurement_call(crud.create_purchase_order, db, plan, payload)


@app.get(
    "/farms/{farm_id}/orders",
    response_model=list[schemas.PurchaseOrder],
    tags=["inputs"],
)
def get_purchase_orders(farm_id: int, db: Session = Depends(get_db)):
    _require_farm(db, farm_id)
    return crud.list_purchase_orders(db, farm_id)


@app.get(
    "/orders/{order_id}",
    response_model=schemas.PurchaseOrderDetail,
    tags=["inputs"],
)
def get_purchase_order(order_id: int, db: Session = Depends(get_db)):
    return _require_purchase_order(db, order_id)


@app.get(
    "/orders/{order_id}/events",
    response_model=list[schemas.OrderEvent],
    tags=["inputs"],
)
def get_order_events(order_id: int, db: Session = Depends(get_db)):
    """Append-only order timeline (oldest first). There are deliberately NO
    update/delete endpoints for order events."""
    _require_purchase_order(db, order_id)
    return crud.list_order_events(db, order_id)


@app.post(
    "/orders/{order_id}/input-applied",
    response_model=schemas.OrderEvent,
    status_code=201,
    tags=["inputs"],
)
def post_input_applied(
    order_id: int, payload: schemas.InputAppliedRequest, db: Session = Depends(get_db)
):
    """Explicitly link a delivered order to the actual application record.
    Delivery alone NEVER marks an input as applied."""
    order = _require_purchase_order(db, order_id)
    return _procurement_call(crud.record_input_applied, db, order, payload)


# Concierge entry points (INTERNAL: operator tooling for the unlinked /internal
# page, never customer-facing; Phase 1 has no supplier portal by design).
@app.post(
    "/internal/input-plans/{plan_id}/quotes",
    response_model=schemas.SupplierQuote,
    status_code=201,
    tags=["internal"],
)
def internal_post_supplier_quote(
    plan_id: int, payload: schemas.SupplierQuoteCreate, db: Session = Depends(get_db)
):
    plan = _require_input_plan(db, plan_id)
    return _procurement_call(crud.create_supplier_quote, db, plan, payload)


@app.post(
    "/internal/supplier-quotes/{quote_id}/withdraw",
    response_model=schemas.SupplierQuote,
    tags=["internal"],
)
def internal_withdraw_supplier_quote(quote_id: int, db: Session = Depends(get_db)):
    """Quotes are never edited — withdraw and re-enter is the only correction
    path, so what the grower saw stays on record."""
    quote = _require_supplier_quote(db, quote_id)
    return _procurement_call(crud.withdraw_supplier_quote, db, quote)


@app.post(
    "/internal/supplier-quotes/{quote_id}/financing-offers",
    response_model=schemas.FinancingOffer,
    status_code=201,
    tags=["internal"],
)
def internal_post_financing_offer(
    quote_id: int, payload: schemas.FinancingOfferCreate, db: Session = Depends(get_db)
):
    """Enter a manually collected INDICATIVE financing offer. Requires that the
    grower actually requested financing; never a credit decision."""
    quote = _require_supplier_quote(db, quote_id)
    return _procurement_call(crud.create_financing_offer, db, quote, payload)


@app.post(
    "/internal/orders/{order_id}/events",
    response_model=schemas.OrderEvent,
    status_code=201,
    tags=["internal"],
)
def internal_post_order_event(
    order_id: int, payload: schemas.OrderEventCreate, db: Session = Depends(get_db)
):
    """Append one order lifecycle event (transition-guarded, append-only).
    input_applied is NOT postable here — it requires the explicit
    /orders/{id}/input-applied link."""
    order = _require_purchase_order(db, order_id)
    return _procurement_call(crud.add_order_event, db, order, payload)
