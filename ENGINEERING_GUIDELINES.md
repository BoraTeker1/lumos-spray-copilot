# ENGINEERING_GUIDELINES.md — Lumos Spray Copilot

Canonical project memory for `precision_farming`. Read this first; then open only the files
your task needs. Optimized so future Claude/Cursor sessions avoid re-reading the whole repo.

---

## 1. Project Summary

- **What it is:** Lumos Spray Copilot is an AI-assisted, **agronomist/PCA-in-the-loop**
  pesticide **decision + compliance copilot** for specialty-crop growers. It logs sprays and
  scouting, runs a transparent rule engine that flags PHI/REI/resistance/scouting/weather risk,
  routes every recommendation through human review, and produces audit-ready records + a
  copy-pasteable weekly report.
- **Current wedge:** California specialty crops — **strawberries** (primary) and greenhouse
  tomatoes — and their **PCAs/agronomists**. "The decision/compliance layer *before* the spray."
- **Target user / buyer hypothesis:** grower + their PCA/agronomist use it; best economic buyer
  is likely the **PCA/advisory firm or packer/exporter** carrying audit + residue risk across
  many growers (unvalidated — that's the point of the validation sprint).
- **What this is NOT:** not a sprayer/robot/drone/farm-OS; not row-crop hardware (explicitly not
  competing with John Deere See & Spray); not a black-box AI; not autonomous "must spray" advice;
  not a compliance/legal guarantee.

---

## 2. Current Strategic Positioning

- **YC-style one-liner:** "AI pesticide-decision and compliance copilot for specialty-crop
  growers and their PCAs — the decision layer before the spray that helps them spray less, avoid
  PHI/REI mistakes, and keep audit-ready records." (full text in `YC_POSITIONING.md`)
- **CA specialty-crop / strawberry wedge:** specialty crops are sprayed often, hand-harvested,
  heavily regulated (PHI/REI, MRL, PrimusGFS/GlobalG.A.P. audits, CA DPR reporting). Seeded U.S.
  demo farm = `Golden Coast Strawberry Ranch`, Watsonville. See `US_WEDGE.md`.
- **PCA / agronomist-in-the-loop:** in California a licensed PCA must legally sign pesticide
  recommendations — the human-in-the-loop already exists, and our review workflow maps onto it.
- **Human decision-support framing:** the copilot does the tedious flagging; the licensed advisor
  decides. Every recommendation starts `pending` and must be approved/edited to become guidance.
- **Long-term Lumos thesis:** broader precision-farming platform (advisory + IoT + marketplace +
  embedded finance — see `docs/`). **Finance and marketplace are explicitly DEFERRED**, not part
  of this product.

---

## 3. Current Strategic Conclusion

- The prototype is **strong enough** to demo and to run pilot conversations.
- The startup is **NOT validated yet** — no confirmed real-world pilots (see §11).
- **Current priority is real-world validation, not more product building.**
- **Stop building product unless a validation need directly requires it.** Default answer to
  "should I build X?" is no — get buyer evidence first.

---

## 4. Hard Guardrails

Do **NOT** build any of the following unless the user explicitly instructs it in this session:

- authentication / multi-tenant SaaS infra
- payments / billing
- marketplace / supplier integrations
- financing / revenue-sharing / credit
- drones / IoT / sensors / hardware / weather-station hookups
- robotics / autonomous spray equipment
- ~~computer vision / image-based disease diagnosis~~ — **guardrail lifted (2026-06-28)**: a
  photo-analysis copilot is now built (multimodal Claude, see §5). Still NOT allowed: autonomous
  image *diagnosis* or any photo-driven "spray now" output — the model only *suggests* a draft
  scouting note a human must confirm; it never diagnoses or prescribes.
- chatbot / conversational LLM agent
- autonomous pesticide prescriptions ("you must spray")
- guaranteed pesticide-reduction claims
- more crop or geography expansion beyond the current wedge
- unnecessary dashboards / vanity UI
- a pesticide-label / PHI / REI / MRL **database** — only after buyer validation confirms it's needed

LLM weekly summaries, photo upload, and live weather are Milestone-3 ideas — also gated, not default.

---

## 5. Product Features Already Built

Backend + frontend both implement:

- **Farms** (CRUD) — name, location, country (US/TR), crop_type, area, planting/harvest dates,
  `advisor_involved`.
- **Spray events** (CRUD) — product, active ingredient, class, target, dose, date, cost, **PHI
  days**, **REI hours**, notes, provenance tags.
- **Scouting observations** (CRUD) — date, crop stage, visible issue, severity 1–5, notes.
- **Rule-based recommendation engine** — cautious, never "must spray"; risk low/moderate/elevated
  + a single farmer-facing **next action**.
- **PHI risk** check (harvest inside a spray's pre-harvest interval).
- **REI risk** check (worker re-entry interval may still be active).
- **Repeated active-ingredient / resistance** check (same AI > 2× in 30 days).
- **High-severity scouting** check (severity ≥ 4).
- **Weather risk** module (mock disease-pressure from temp/humidity/rain; swappable service).
- **PCA / agronomist review workflow** — approve / edit / reject + comment; only reviewed
  guidance reaches the grower/report.
- **Photo-scouting copilot** (`POST /farms/{id}/photo-analysis`) — the "do I really need to
  spray?" CV feature. A grower/PCA uploads a field photo; a **multimodal model (Claude
  `claude-opus-4-8`)** describes what it *appears* to see + a confidence + caveats, and pre-fills
  a **draft scouting observation the human must review/confirm** (it then feeds the rule engine).
  Real AI, clearly labelled *AI-suggested, not confirmed*; never diagnoses, never says "spray".
  Falls back to a deterministic `MockVisionService` when no `ANTHROPIC_API_KEY` is set (demo/tests
  work offline). Confirmed notes carry `data_source="photo_ai"`. See `app/vision.py`.
- **Compliance snapshot** card/endpoint (PHI/REI/resistance/scouting/weather/review status).
- **Pesticide cost analytics** — total/avg spend, most-used AI, repeated-ingredient cost,
  *potential* avoidable cost.
- **Reduction-measurement engine** — declared spray baseline (`stated_cadence` /
  `prior_period` / `calendar_program`) → measured *sprays-vs-baseline* reduction. Honest by
  design: no baseline → no number; an `is_headline_safe` gate (trusted confidence + ≥21-day
  window + ≥3 sprays + positive reduction) marks weak/early numbers *illustrative*; negative
  reductions reported honestly. Wired into pilot-evidence / case-study / audit-packet. Built
  for the YC low-pesticide RFS (see `RFS_PESTICIDE_REDUCTION.md`).
- **Weekly report** — copy-pasteable (WhatsApp/text), US vs TR wording + disclaimer.
- **Pilot feedback** capture (discovery answers).
- **Pilot farm intake** (`POST /pilot/farms`) — one-shot create farm + sprays + scouting.
- **CSV exports** — spray events, recommendations, pilot feedback.
- **Pilot evidence dashboard** (`/farms/{id}/pilot-evidence`) — descriptive metrics + investor
  talking points + explicit limitations.
- **Audit packet export** (`/farms/{id}/audit-packet`) — consolidated farm record + flags +
  review trail + weekly report text.
- **Concierge pilot import** (`POST /farms/{id}/pilot-import`) — manual transcription of
  call/WhatsApp/spreadsheet/email data, with provenance tags.
- **Persisted pilot import batches / provenance** — `PilotImportBatch` + `data_source` /
  `data_confidence` on every imported row.
- **Pilot case study** output (`/farms/{id}/pilot-case-study`).
- **U.S. strawberry demo** (Golden Coast Strawberry Ranch) — primary YC demo.
- **Türkiye greenhouse-tomato demos** — secondary contrast (Green Valley high-risk, Sunrise low-risk).

---

## 6. Backend Architecture

- **Framework:** FastAPI; **ORM:** SQLAlchemy 2 (typed `Mapped` columns); **DB:** SQLite
  (`backend/lumos.db`); **validation:** Pydantic v2; **tests:** pytest. No auth (v1).
- **Layering rule:** routes (`main.py`) → `crud.py` (all DB access) → `models.py` / `schemas.py`.
  Pure logic modules (engine/analytics/weather/pilot_evidence) take **plain objects, no
  FastAPI/SQLAlchemy imports** so they unit-test in isolation. Keep it this way.
- **Important modules:**
  - `app/main.py` — FastAPI app, all routes, CORS (localhost:3000), weekly-report + audit-packet
    text builders, US/TR currency + advisor-label + disclaimer helpers.
  - `app/database.py` — engine / `SessionLocal` / `Base` / `get_db` / `init_db`.
  - `app/models.py` — ORM models.
  - `app/schemas.py` — Pydantic request/response contracts; provenance `Literal` vocabularies.
  - `app/crud.py` — DB access; also `generate_and_store_recommendation`, pilot import/intake.
  - `app/recommendation_engine.py` — the rule engine (tunable thresholds at top:
    `RECENT_WINDOW_DAYS=30`, `SAME_INGREDIENT_MAX=2`, `HIGH_SEVERITY_THRESHOLD=4`). Returns a
    `RecommendationResult` (risk_level, next_action, flags, recommendation_text, signals dict).
  - `app/analytics.py` — `compute_cost_analytics`.
  - `app/reduction.py` — `compute_reduction` (pure, framework-free). Baseline methods +
    `CALENDAR_PROGRAMS`, `is_headline_safe` gate, honest caveats. Consumed by `pilot_evidence`.
  - `app/vision.py` — photo analysis. `build_observation_suggestion` / `build_analysis_result`
    (pure), `VisionService` ABC, `ClaudeVisionService` (multimodal Claude, lazy-imports
    `anthropic`), `MockVisionService`, `default_vision_service` (real iff `ANTHROPIC_API_KEY` +
    `anthropic` present, else mock). Never imports FastAPI/SQLAlchemy.
  - `app/weather.py` — `compute_disease_pressure`, `WeatherService` ABC, `MockWeatherService`,
    `default_weather_service`.
  - `app/pilot_evidence.py` — `build_pilot_evidence` + `build_pilot_case_study`.
  - `app/seed.py` — `run()` drops+recreates schema and loads the 3 demo farms.
- **Key models:** `Farm`, `SprayEvent`, `ScoutObservation`, `Recommendation`, `PilotFeedback`,
  `PilotImportBatch`, `SprayBaseline`. Sprays/scouting carry `data_source` + `data_confidence` +
  `pilot_import_batch_id`; `SprayBaseline` carries the same provenance (one per farm, latest wins).
- **Key endpoints (selection):**
  - Farms: `GET/POST /farms`, `GET/PUT/DELETE /farms/{id}`
  - Sprays: `GET/POST /farms/{id}/spray-events`, `DELETE /spray-events/{id}`
  - Scouting: `GET/POST /farms/{id}/scout-observations`, `DELETE /scout-observations/{id}`
  - Recs: `GET/POST /farms/{id}/recommendations`, `PATCH /recommendations/{id}` (review action)
  - Photo: `POST /farms/{id}/photo-analysis` (multipart image upload → draft scouting suggestion)
  - `GET /farms/{id}/analytics`, `/weather-risk`, `/compliance`, `/weekly-report`
  - Reduction: `GET/PUT /farms/{id}/spray-baseline`, `GET /farms/{id}/reduction`
  - Pilot: `/pilot-evidence`, `POST /pilot-import`, `/pilot-case-study`, `/audit-packet`,
    `POST /pilot/farms`, `GET/POST /pilot-feedback`
  - Exports: `/farms/{id}/export/spray-events.csv`, `/recommendations.csv`,
    `/export/pilot-feedback.csv`
  - `GET /health`; interactive docs at `/docs`.
- **Disposable SQLite / no migrations:** there is **no Alembic**. `seed.run()` calls
  `Base.metadata.drop_all` then recreates — schema changes are applied by re-seeding
  (`rm -f backend/lumos.db && python -m app.seed`). Treat `lumos.db` as throwaway demo data.

---

## 7. Frontend Architecture

- **Framework:** Next.js 14 (App Router, JavaScript) + Tailwind CSS. `@/` path alias.
- **Routes (`frontend/app/`):**
  - `page.js` — dashboard / farm list (risk badge + spend per card; sorts U.S. strawberry first).
  - `farms/[id]/page.js` — farm detail (analytics, weather, compliance, recommendation, review,
    weekly report, pilot evidence, concierge pilot).
  - `feedback/page.js` — pilot feedback capture.
  - `pilot/new/page.js` — pilot farm intake form.
  - `layout.js`, `globals.css`.
- **Components (`frontend/components/`):** `AnalyticsCard`, `WeatherCard`, `ComplianceCard`,
  `RecommendationPanel`, `AgronomistReview`, `NextActionCard`, `WeeklyReport`,
  `PilotEvidenceCard`, `ReductionCard`, `ConciergePilotCard`, `PhotoScoutCard`, `SprayEventForm`,
  `ScoutObservationForm`, `RiskBadge`, `SeverityBadge`.
- **API client:** `frontend/lib/api.js` — single `api` object wrapping all backend calls; base
  URL from `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`). `lib/format.js` for
  cost/date/area formatting. Keep all fetches here.
- **Demo flow:** dashboard → open Golden Coast Strawberry Ranch → compliance snapshot → generate
  recommendation → PCA approve → weekly report copy. (Türkiye farms are the secondary contrast.)
- **Where key UI copy lives:** demo/disclaimer wording is in the backend report/audit builders
  (`main.py`) and the engine flag strings (`recommendation_engine.py`); per-card UI copy lives in
  the matching component file. Demo scripts/narration: `DEMO_SCRIPT.md`, `DEMO_DATA.md`.

---

## 8. Test / Build Commands

```bash
# Backend tests (from backend/, venv active)
cd backend && source .venv/bin/activate && pytest

# Seed / reset demo data (drops + recreates schema, loads 3 demo farms)
cd backend && source .venv/bin/activate && python -m app.seed
#   nuclear reset: rm -f backend/lumos.db && python -m app.seed

# Run backend:  uvicorn app.main:app --reload   (http://localhost:8000, docs at /docs)

# Frontend build / lint (from frontend/)
cd frontend && npm install
npm run build      # production build = de-facto typecheck/compile check
npm run lint       # next lint
npm run dev        # http://localhost:3000
```

- **No JS typecheck beyond `next build`** (plain JavaScript project, no `tsc`). `npm run lint`
  is the only lint step.
- **Passing test count:** repo currently shows **107 passing** (README's "41" is STALE — ignore
  it). **Always re-run `pytest` to confirm; do not trust this number.** Known harmless
  `datetime.utcnow()` deprecation warnings.

---

## 9. Demo Data and Honesty Rules

- All seeded farms are **demo / simulated** (`data_source="demo"`, `data_confidence="simulated"`).
  Three farms (`backend/app/seed.py`):
  - **Golden Coast Strawberry Ranch** (Watsonville, CA, USD) — **primary U.S./YC demo**; triggers
    PHI + REI + repeated-AI (captan ×3) + high-severity scouting.
  - **Green Valley Greenhouse** (Antalya, TR, ₺) — secondary high-risk tomato demo.
  - **Sunrise Tomato House** (Mersin, TR, ₺) — secondary low-risk/healthy contrast.
- **Never present seed data as traction.** It is illustrative, not real usage.
- **Never imply real pilots** unless a validation doc proves it (none currently do — see §11).
- **Avoid fake AI claims.** The recommendation/compliance **engine is a deterministic rule
  engine, not ML** — say so. The **photo-scouting copilot IS real AI** (multimodal Claude), but
  describe it honestly: it *suggests* what it appears to see for a human to confirm; it does not
  diagnose disease, is not the decider, and never says "spray." Don't blur the two — the spray
  decision is still the rule engine + PCA, not the photo model.
- Always use **"decision support only"** language; never "diagnoses," never "tells you to spray."

---

## 10. Compliance / Liability Copy Rules

Preferred disclaimer (use this exact phrasing for US-facing copy):

> "Decision support only. Always confirm PHI, REI, rates, crop use, and restrictions with the
> product label and a licensed PCA / agronomist."

Also:

- Do **not** say "must spray."
- Do **not** say "guaranteed reduction."
- Do **not** say "prevents all mistakes."
- Use cautious phrasing: "potential avoidable cost," "if one spray is avoided," "risk appears
  elevated," "consider," "inspect first," "review with your PCA/agronomist."
- Existing disclaimers live in `main.py` (`_report_disclaimer`, `AUDIT_DISCLAIMER`) and
  `pilot_evidence.py` (`CASE_STUDY_DISCLAIMER`) — reuse/extend those, don't invent new tone.

---

## 11. Validation Status (Honest)

- **No confirmed real-world pilots** — no evidence in the repo proves any. If you find a doc that
  does, cite it; otherwise assume not validated.
- The **validation sprint is the current priority** (see §3).
- Evidence still needed: **real spray logs, real scouting notes, real PCA recommendations, audit
  artifacts from actual operations, and willingness-to-pay quotes.**

---

## 12. Validation Plan

Who to contact (see `PILOT_VALIDATION_PLAN.md`, `CUSTOMER_DISCOVERY.md`):

- California **PCAs / crop consultants** (licensed advisers who already document recommendations).
- **Packer / exporter** food-safety or compliance managers (carry audit/residue risk at scale).
- **Specialty-crop growers / farm managers** (strawberry, greenhouse tomato).
- **UC Cooperative Extension / ag advisors.**

The ask:

- Run **5–10 redacted historical spray/scouting records** through the prototype (concierge
  import — we transcribe, no integrations).
- Have it identify **PHI/REI, resistance, scouting-gap, and audit/documentation pain**.
- Determine **who the buyer is** and **willingness to pay** (per-acre / per-grower / per-PCA-seat).

---

## 13. Strong vs Weak Signals

**Strong (lean in):**

- They share **real data**.
- They volunteer a **specific painful incident** (e.g. a rejected residue load).
- They **name a price** or push on packaging.
- **Pilot / LOI** interest, or asking to run it on **more of their farms**.
- A **packer/PCA wants it across multiple growers**.

**Weak (keep probing):**

- Generic praise / "interesting idea."
- "Send me info" with no next step.
- Enthusiasm with **no data and no price**.
- Interest only in **out-of-scope** features (financing, marketplace, hardware).

---

## 14. Known Weaknesses (Brutal)

- **No real validation yet.**
- Engine is **rule-based, not real AI** — easy to dismiss as "just a spreadsheet."
- **No pesticide-label / PHI / REI / MRL reference database** — PHI/REI come from user-entered
  per-spray values, not an authoritative source.
- **Incumbents** may already cover parts (FieldView-style platforms, PCA software, ag ERPs).
- **Data-entry burden** — someone has to log sprays/scouting; unclear who, in practice.
- **Unclear buyer** and **low willingness-to-pay** from individual growers.

---

## 15. Recommended Next Work

- **Do not build more product by default.**
- Next work = **validation assets / outreach / real-data import** (concierge pilots, case
  studies, discovery interviews).
- Only build **label-aware compliance** (a real PHI/REI/MRL database) or other deep functionality
  **after buyer validation** confirms it's the thing people will pay for.

---

## 16. How Future Claude Should Behave

- **Read this `ENGINEERING_GUIDELINES.md` first**, then open only the files relevant to the task.
- **Keep changes small** and focused; match the surrounding code style.
- **Ask before expanding scope** — especially anything near the §4 guardrails.
- **Preserve the guardrails and the cautious tone.** Never introduce "must spray," guaranteed
  savings, fake-AI, or out-of-scope features.
- **Prefer tests for logic changes** — engine/analytics/weather/pilot_evidence are pure and
  unit-tested; add/update tests in `backend/tests/`.
- **Run the appropriate commands** (`pytest`; `npm run build`/`lint` for frontend) and report
  real results — if something fails, say so.
- At the end of a task, **summarize files changed, commands run, and limitations.**
- After **major work**, provide a compact **restart prompt** for the next Claude terminal
  (what changed, current state, what's next).
