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
- ~~marketplace / supplier integrations~~ / ~~financing~~ — **guardrail partially lifted
  (2026-07-16)**: an "Inputs & finance" Phase 1 module is now built (RFQ + concierge-entered
  quotes + INDICATIVE financing offers + orders, see §5). Still NOT allowed: a public supplier
  marketplace/portal/catalog, real payments, real lending, automated underwriting, credit
  scoring, money movement of any kind, revenue-sharing, commission-based quote ranking.
- revenue-sharing / credit / money movement
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

- **Inputs & finance V1 (Phase 1 procurement, 2026-07-16)** — RFQ model, concierge-operated,
  NO real money. Chain: PCA-cleared decision → `InputPlan` (plan == RFQ; status
  draft→submitted_for_quotes→quoted→quote_selected→ordered/cancelled; items snapshot product
  data, mutable only in draft) → concierge-entered `SupplierQuote`+items (never edited —
  withdraw+re-enter; entry order, NEVER ranked; derived totals server-side) → optional
  `FinancingOffer` (indicative only, attached to a quote, one-shot **select/decline** — the
  stored/derived vocabulary is `selected`/`offer_selected`, NEVER "accepted" (hardening pass
  2026-07-17): selecting indicative terms is not an approval/funding/binding; derived
  expiry, disclaimer on every payload; "financing requested" is a plan flag, never an offer)
  → `PurchaseOrder` (one per plan; lines = selected quote's items) + append-only `OrderEvent`
  timeline (transition-map-guarded, 409 on invalid/duplicate; delivery NEVER marks applied —
  explicit `input-applied` link to a SprayEvent/applied decision required). Eligibility gate:
  `decision_status.procurement_eligible` (== the applied-outcome gate, minus `avoided`);
  enforced at item-create AND plan-submit. Demo/real records can never mix in one chain (409).
  Evidence export gains an `input_orders` block (demo-excluded, NO savings key by design;
  includes `selection_reason` + `plan_events`).
  **Transaction-integrity hardening (2026-07-17):** quote selection requires a mandatory
  `reason` (stored on the plan, audited, exported — never inferred); every user decision on a
  plan (submit/select/offer decision/order/cancel) appends to the **append-only
  `InputPlanEvent`** audit table (mirror of OrderEvent, payload carries from/to state —
  DecisionAuditEvent couldn't host these: its planned_spray_id is non-null and a plan may
  have no/many decision links); derived `overdue` (`procurement_status.procurement_overdue`:
  needed_by passed ∧ not delivered ∧ not cancelled — never stored); chain navigable both ways
  via derived `PlannedSpray.procurement_links` and `SprayEvent.source_order_id`. There is NO
  quote re-selection/reopen and NO offer-withdraw endpoint (explicitly deferred); after an
  order exists the selected quote is immutable. **Deferred debt:** the
  `PurchaseOrder.accepted_financing_offer_id` column/API field keeps its legacy name (statuses
  and all user-visible copy already say "selected"); rename later if ever worth the diff.
  Modules: `app/procurement_status.py` (pure vocab/transitions/derived states),
  crud/main sections, demo scenario on Golden Coast (Switch 62.5 WG from scenario 1 → 2
  simulated quotes → selected indicative offer → delivered order → input_applied). The seeded
  chain is chronologically real: checked/reviewed/planned/quoted/selected/ordered/
  confirmed/shipped on anchor−1, delivered 07:30 and applied 09:00 on the anchor day; the
  seed asserts the captan check still BLOCKS, and `test_procurement_demo.py` asserts the
  full chain chronology (no date may contradict another). Frontend: "Inputs & finance" nav →
  `/inputs` (plans|orders tabs; value-first headline, next-action + overdue chips),
  `/inputs/plans/[id]` (items, quote comparison with "$X above the lowest quoted total"
  entered-totals note + reason-capture on select, financing, append-only plan history),
  `/inputs/orders/[id]` (lines, timeline, link-application dialog, "Financing — indicative
  offer selected" card); decision records show existing plan/order links instead of a
  duplicate "Request supplier quotes" CTA; applications show "Source order: Order #N";
  concierge quote/offer/event entry on `/internal`. STATUS kinds planStatus/quoteState/
  financing/offerState/orderStatus + PLAN_EVENT_LABELS/PLAN_NEXT_STEP in `lib/status.js`.
  No auth (attribution strings, same as everything else); tenant isolation documented as a
  known limitation.

- **Pre-spray decision workflow (THE core product since 2026-07-10)** — a grower/PCA enters a
  *planned* spray; `app/decision_engine.py` checks it against harvest timing, entered PHI/REI,
  prior applications' re-entry windows, repeated active ingredients, linked scouting evidence,
  and missing data, and returns ONE explainable outcome: **approve / block / delay /
  inspect_first / pca_review_required** — with triggered rules, exact calculations, inputs used,
  missing information, and an input-completeness confidence. Missing inputs can NEVER yield
  approve (they escalate to PCA review). **Authority gating (2026-07-10):** every rule carries a
  `source_authority` (verified_label / pca_entered / grower_entered / heuristic), verification
  status, and who entered the values; only verified-label or PCA-entered sources can back a
  **definitive** approve/block — grower-entered values and heuristics always yield a
  **provisional** result that a PCA must confirm (provisional approve ⇒ review_required). No
  label database exists, so nothing can produce `verified_label` yet — the vocabulary and gate
  are in place for when it does, and approve is currently NEVER definitive (rotation/scouting
  checks are heuristics). The engine never names replacement products — those may only come
  from explicit PCA-entered guidance (`pca_next_action`). A **PCA review** (approve/edit/reject
  + comment) gates
  applied outcomes (409 until approved/edited when review is required); the **real-world
  outcome** is recorded as `sprayed_as_planned / changed_product / delayed / avoided /
  inspected_first` (reason mandatory except as-planned; applied outcomes create the linked
  SprayEvent). `GET /farms/{id}/decision-evidence` aggregates the YC metrics (decisions
  reviewed, sprays changed/delayed/avoided, conflicts caught, PCA acceptance rate, entered-cost
  avoided, assumption-based review minutes) with demo data excluded and caveats attached.
- **AI-Driven Layer V1 (2026-07-12)** — real AI around the deterministic engine.
  **Architecture rule: AI proposes, the deterministic engine + PCA decide.** The
  approve/block/delay/inspect/review outcome stays 100% rule-engine; AI never says
  "spray", never names products, never diagnoses. All AI calls are on-demand
  (buttons), never in the hot decision path; mock service without `ANTHROPIC_API_KEY`.
  - **Shared LLM service** — `app/llm.py` (mirrors vision.py): `LlmService` ABC,
    `ClaudeLlmService` (structured outputs via `client.messages.parse`, model
    `claude-opus-4-8`, override `LUMOS_LLM_MODEL`), `MockLlmService` with per-schema
    registered builders (offline tests/demo), `default_llm_service` gated on the key.
  - **Append-only AI judgment log** — `AiJudgment` (kind extraction/risk_note/
    next_evidence_action, model_id, prompt_version, input_digest, output JSON,
    confidence, abstained, is_mock). NO update/delete; judgments are NEVER seeded or
    fabricated. `GET /internal/ai-calibration` joins risk-note predictions to
    realized rescues from follow-ups — rates gated behind `CALIBRATION_MIN_N=10`
    follow-up-backed predictions per level (counts + "insufficient data" until then).
  - **AI document/message extraction** — `app/extraction.py` +
    `POST /farms/{id}/import/document` (PDF ≤10MB native document block, image, or
    pasted text): Claude extracts ONLY what is literally written (regulatory values
    never guessed), per-row verbatim `source_snippet` + confidence, abstains on
    non-recommendation input. Returns the SAME DryRunReport as the CSV import
    (shared `csv_import.validate_rows`); never writes. Human-corrected rows commit
    via `POST /farms/{id}/import/rows` (server re-validates, `data_source=
    "ai_extracted"`, field-level `imported_unverified` ⇒ can never auto-approve).
  - **AI review brief** — `app/ai_brief.py` + `POST /planned-sprays/{id}/ai-brief`:
    retrieval-grounded (deterministic `crud.comparable_decisions`: same farm,
    non-demo, alias-matched target or same AI/MoA — no embeddings, no fuzzy)
    qualitative rescue-risk note + next actions **enum-locked to evidence gathering
    only** (rescout/verify-label/confirm-threshold/record-follow-up/wait/consult) —
    product recommendations are structurally inexpressible. Deterministic post-guard
    forces ABSTAIN below 2 real comparables regardless of model output; never
    touches decision columns; logs two judgments. UI: `AiBriefCard` on
    `/decisions/[id]` (no-print, never auto-runs).
- **Real Pilot Evidence Loop V1 (2026-07-11)** — the concierge pilot infrastructure:
  - **CSV pilot import** (`POST /farms/{id}/import/csv`; templates at
    `GET /import/templates/{planned_sprays|scout_observations}.csv`): dry-run first
    (header-alias column mapping with per-column overrides, per-row errors/warnings,
    in-file + against-DB duplicate detection), commit only on `dry_run=false`. Pure
    parsing/validation lives in `app/csv_import.py`. Regulatory values are NEVER
    guessed — absent PHI/REI/rate/harvest stay missing and are reported unverified.
  - **Field-level provenance** — `DecisionInputValue`: append-only supersede chain per
    compliance-critical input (product identity, EPA reg no, crop, target, rate, PHI,
    REI, dates, AI, MoA group) with `source_type`
    (demo/user_entered/imported_unverified/pca_verified/authoritative_provider),
    verified_by/at, source_reference. Latest non-superseded value drives the engine.
    Imported values are never silently verified and NEVER auto-approve (they escalate
    to pca_review_required via the `unverified_imported_values` rule).
  - **Immutable audit history** — `DecisionAuditEvent` (created / reviewed /
    input_value_superseded / outcome_recorded / follow_up_added), append-only, prior
    state in `before`. PCA reviews accept structured `proposed_*` field edits that
    supersede input values as `pca_verified` and re-run the decision (prior snapshot
    preserved in the audit event). `GET /planned-sprays/{id}/audit-events`,
    `/input-values`.
  - **Follow-up timeline** — `DecisionFollowUpEvent`, one-to-many append-only
    (scouting_observation / actual_application / rescue_application / harvest_outcome
    / yield_quality_outcome / note); no update/delete endpoints. Required
    (`decision_status.follow_up_required`) for every non-as-planned outcome and for
    "approved despite warning". `GET/POST /planned-sprays/{id}/follow-up-events`
    (409 until an outcome is recorded). Consolidated read-only summary derived in
    `pilot_evidence.derive_follow_up_summary`.
  - **Confirmed vs estimated metrics** — `build_decision_evidence` now returns
    `confirmed` (follow-up-backed only: avoided apps/acres, delay days, replacements,
    rescues, gross avoided, scouting/rescue costs, net result — negatives shown as
    negatives), `estimated` (entered values without follow-up), `not_calculated`
    (AI-quantity + risk-weighted reduction, with reasons), `follow_up` completion.
    Non-demo records only; never combined into one score.
  - **Anonymized evidence export** — `GET /farms/{id}/evidence-export` (JSON) +
    `GET /farms/{id}/export/evidence.csv`: farm as `pilot-farm-{id}` (no name/
    location), per decision: inputs+provenance, triggered exceptions, review, audit
    history, follow-up timeline, confirmed/estimated, missing evidence, methodology,
    correlation≠causality. Demo records excluded by construction (tested).
  - **Target-name matching** — `app/target_aliases.py`: exact normalized names or the
    explicit curated alias dictionary ONLY; partial overlap ⇒ `pca_review_required`
    with the ambiguity recorded (`scouting_target_ambiguity` rule). Never fuzzy.
  - New engine checks: product-identity completeness, incomplete rate/unit pair,
    repeated MoA group (only when structured `moa_group` data exists), stale-scouting
    disclosure, imported-unverified escalation. Label-dependent checks (max seasonal
    rate, max applications, retreatment interval, crop/use registration) are listed
    under `not_evaluated` with reasons — never simulated.
  - Frontend: `PilotImportCard` (dry-run preview + mapping correction),
    `decisions/[id]` shows input provenance + immutable audit timeline + follow-up
    timeline with append-only add-event form; `DecisionEvidenceCard` shows the
    confirmed/estimated/not-calculated split + export links.
- **Farms** (CRUD) — name, location, country (US/TR), crop_type, area, planting/harvest dates,
  `advisor_involved`. `GET /farms-overview` returns the urgency-ranked, action-oriented list
  (why + next action per farm) that drives the dashboard.
- **Spray events** (CRUD) — product, active ingredient, class, target, dose, date, cost, **PHI
  days**, **REI hours**, notes, provenance tags.
- **Scouting observations** (CRUD) — date, crop stage, visible issue, severity 1–5, notes.
- **Rule-based recommendation engine** — cautious, never "must spray"; risk low/moderate/elevated
  + a single farmer-facing **next action**. Now the *secondary* farm-wide surface (feeds the
  weekly report / audit packet); the pre-spray decision check is the primary workflow.
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
- **Pre-spray risk snapshot** (formerly "Compliance snapshot") card/endpoint
  (PHI/REI/resistance/scouting/weather/review status). Renamed in the UI because the signals
  come from user-entered values, not verified label data; the endpoint is still `/compliance`
  and now returns a `basis` field saying exactly that.
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
- **Concierge pilot import** (`POST /internal/farms/{id}/pilot-import`) — manual transcription
  of call/WhatsApp/spreadsheet/email data, with provenance tags. Deliberately INTERNAL: the
  route is namespaced `/internal`, and the raw-JSON UI lives on the unlinked `/internal` page —
  it is operator tooling, not the customer-facing workflow.
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
  - `app/recommendation_engine.py` — the farm-wide rule engine (tunable thresholds at top:
    `RECENT_WINDOW_DAYS=30`, `SAME_INGREDIENT_MAX=2`, `HIGH_SEVERITY_THRESHOLD=4`). Returns a
    `RecommendationResult` (risk_level, next_action, flags, recommendation_text, signals dict).
  - `app/decision_engine.py` — the **pre-spray decision engine** (pure, framework-free).
    `evaluate_planned_spray(...)` → `PlannedSprayDecision` (outcome, severity, confidence,
    per-rule audit trail with calculations, inputs_used, missing_information,
    required_next_action, review_required, narrative, `as_payload()` for the JSON column).
    Outcome precedence: block > delay > pca_review_required > inspect_first > approve.
    `PLANNED_SPRAY_DISCLAIMER` lives here now.
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
- **Key models:** `Farm`, `SprayEvent`, `ScoutObservation`, `PlannedSpray`, `Recommendation`,
  `PilotFeedback`, `PilotImportBatch`, `SprayBaseline`, `PilotEvent` (workflow telemetry),
  `DecisionInputValue` (field-level provenance, append-only supersede chain),
  `DecisionAuditEvent` (immutable audit history), `DecisionFollowUpEvent` (append-only
  follow-up timeline), `PcaPolicy`. Sprays/scouting carry `data_source` +
  `data_confidence` + `pilot_import_batch_id`; `SprayBaseline` carries the same provenance (one
  per farm, latest wins). `PlannedSpray` snapshots the decision (`decision_*`,
  `decision_payload` JSON, legacy `check_*`), the PCA review (`review_*`, `pca_next_action`),
  and the recorded outcome (`outcome*`, linked `spray_event_id`).
- **Key endpoints (selection):**
  - Farms: `GET/POST /farms`, `GET /farms-overview` (urgency-ranked dashboard),
    `GET/PUT/DELETE /farms/{id}`
  - Planned sprays: `GET/POST /farms/{id}/planned-sprays`, `GET /planned-sprays/{id}`,
    `PATCH /planned-sprays/{id}/review`, `PATCH /planned-sprays/{id}/outcome` (409 when a
    required review is missing), `DELETE /planned-sprays/{id}`,
    `GET /farms/{id}/decision-evidence`
  - Instrumentation: `POST /pilot-events` (client-reported check_started / check_abandoned /
    import_used; check_completed / review_recorded / outcome_recorded are logged server-side),
    `GET /internal/instrumentation` (funnel, median time-to-review, decisions changed,
    entry sources, abandonment — internal only)
  - Sprays: `GET/POST /farms/{id}/spray-events`, `DELETE /spray-events/{id}`
  - Scouting: `GET/POST /farms/{id}/scout-observations`, `DELETE /scout-observations/{id}`
  - Recs: `GET/POST /farms/{id}/recommendations`, `PATCH /recommendations/{id}` (review action)
  - Photo: `POST /farms/{id}/photo-analysis` (multipart image upload → draft scouting suggestion)
  - `GET /farms/{id}/analytics`, `/weather-risk`, `/compliance`, `/weekly-report`
  - Reduction: `GET/PUT /farms/{id}/spray-baseline`, `GET /farms/{id}/reduction`
  - Pilot: `/pilot-evidence`, `/pilot-case-study`, `/audit-packet`,
    `POST /pilot/farms`, `GET/POST /pilot-feedback`
  - Internal: `POST /internal/farms/{id}/pilot-import` (concierge import — operator tooling)
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
- **Components (`frontend/components/`):** `DecisionResult` (the explainable
  approve/block/delay/inspect-first/PCA-review verdict, with per-rule source-authority chips
  and PROVISIONAL/definitive banner), `PreSpraySheet` (mobile-first check form — product + date
  required, everything else collapsible — plus PCA review + outcome recorder; the primary CTA;
  fires check_started/check_abandoned telemetry), `SprayImportCard` (customer-facing CSV/paste
  spray-history import, rows tagged `data_source="spreadsheet"` — no JSON exposed),
  `DecisionEvidenceCard` (incl. demo-outcome reconciliation line), `AnalyticsCard`,
  `WeatherCard`, `ComplianceCard`, `RecommendationPanel`, `AgronomistReview`, `NextActionCard`,
  `WeeklyReport`, `PilotEvidenceCard`, `ReductionCard`, `ConciergePilotCard` (on `/internal`
  only), `PhotoScoutCard`, `SprayEventForm`, `ScoutObservationForm`, `RiskBadge`,
  `SeverityBadge`.
- **Page hierarchy:** dashboard (`/`) uses `GET /farms-overview` (urgency-ranked cards with
  why + next action; **Türkiye demo farms are hidden by default** behind a "show secondary-market
  demo farms" toggle — the default demo is the CA strawberry/PCA workflow); farm detail
  Overview = decision queue + pre-spray risk snapshot; `RecommendationPanel` (farm-wide weekly
  review) lives in the Evidence tab; `/decisions/[id]` is the one-page printable decision record
  (inputs, rules + calculations + source authority, missing data, PCA review, outcome,
  disclaimers; print button hides app chrome); `/internal` is the unlinked operator page for
  concierge import + pilot instrumentation.
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
- **Passing test count:** repo currently shows **320 passing**. **Always re-run `pytest` to
  confirm; do not trust this number.** Known harmless deprecation warnings. AI tests run on
  the deterministic `MockLlmService` — no API key needed; never let tests hit the real API.
- **Deterministic demo:** `LUMOS_DEMO_TODAY=YYYY-MM-DD python -m app.seed` pins every seeded
  date to a fixed anchor (screenshots / demo-consistency tests); unset, the anchor is today and
  re-seeding before a demo keeps the story fresh. `tests/test_demo_consistency.py` asserts the
  seeded story's invariants.
- **NEVER run `npm run build` while `npm run dev` is running** — they share `.next` and the
  build corrupts the dev server's cache (dev pages start returning 500 MODULE_NOT_FOUND). Stop
  the dev server first, or restart it afterwards with `rm -rf .next && npm run dev`.
- **`npm run lint` is NOT set up** (it prompts interactively for an ESLint config); the lint
  pass inside `npm run build` is the real frontend check.

---

## 9. Demo Data and Honesty Rules

- All seeded farms are **demo / simulated** (`data_source="demo"`, `data_confidence="simulated"`).
  Three farms (`backend/app/seed.py`):
  - **Golden Coast Strawberry Ranch** (Watsonville, CA, USD) — **primary U.S./YC demo**; triggers
    PHI + REI + repeated-AI (captan ×3) + high-severity scouting, and seeds the end-to-end
    decision story: a 4th captan planned 2 days before harvest → **DEFINITIVE BLOCK** (real
    engine output; values are `pca_entered` by "Demo PCA (simulated)", which is what makes it
    definitive) → demo PCA **edited** guidance (the Switch 62.5 WG recommendation lives ONLY in
    `pca_next_action`, never in engine output) → outcome **changed_product**, applied on the
    intended date. All timestamps anchor to the same demo day. Demo planned sprays are
    demo/simulated: excluded from real decision-evidence counts but reconciled via the
    `demo_outcomes` block so the queue and the evidence card never contradict each other.
    Scenario 2 (PyGanic avoided via the lygus threshold) and scenario 1 both carry
    seeded input-value/audit/follow-up trails. **Scenario 3 (2026-07-11): the honest
    FAILURE story** — an Agri-Mek miticide planned at scouting severity 2 (below the
    PCA threshold of 3) → INSPECT FIRST → PCA held it → severity rose to 4 → **rescue
    application required** (extra scouting + rescue cost, nothing avoided). Spans the
    six days before the anchor; deliberately negative — the product must show failures
    or its evidence is not credible.
  - **Green Valley Greenhouse** (Antalya, TR, ₺) — secondary high-risk tomato demo.
  - **Sunrise Tomato House** (Mersin, TR, ₺) — secondary low-risk/healthy contrast.
- **Never present seed data as traction.** It is illustrative, not real usage.
- **Never imply real pilots** unless a validation doc proves it (none currently do — see §11).
- **Avoid fake AI claims.** The recommendation/compliance **engine is a deterministic rule
  engine, not ML** — say so. The **photo-scouting copilot, document extraction, and AI review
  brief ARE real AI** (Claude), but describe them honestly: they *suggest* (a draft scouting
  note, draft import rows with verbatim snippets, a retrieval-grounded risk note that abstains
  without comparables) for a human to confirm; they do not diagnose, are not the decider, never
  say "spray," and never name products. Every AI output is logged append-only (`AiJudgment`)
  for calibration against real outcomes; AI judgments are NEVER seeded or fabricated, and
  mock-service outputs must never be presented as model performance. Don't blur the layers —
  the spray decision is still the rule engine + PCA.
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
