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
- **As of 2026-07-20** the repo is repointed at ONE falsifiable hypothesis: the Botrytis
  deferral shadow pilot (`BOTRYTIS_PILOT.md`). V1 of the evidence loop is built and the
  remaining blockers are not code — they are the threshold source table, the farm's actual
  weather data, the PCA's action threshold, and whether block randomization is operationally
  acceptable. **Do not build the reporting/calibration layer until real outcomes exist**; its
  shape will be wrong until you have seen one real block outcome.

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
- ~~a pesticide-label / PHI / REI / MRL **database**~~ — **guardrail partially lifted
  (2026-07-27)**: a label **capability layer** is now built (product identity + append-only
  label records + per-farm PCA verification, see §5). Still NOT allowed: **MRL data** (an MRL
  is destination-market law, not label law, and needs a different source — §14's "no MRL
  database" stays true), bulk-importing a third-party label dataset, or any label value that
  is not transcribed from a primary document with its citation

LLM weekly summaries, photo upload, and live weather are Milestone-3 ideas — also gated, not default.

---

## 5. Product Features Already Built

Backend + frontend both implement:

- **Label capability layer, Phases 0–3 (2026-07-27, commit `cba6e2a`)** — product identity
  and verified label records, so the four label-dependent checks can finally run. Plan:
  `~/.claude/plans/snoopy-hugging-pinwheel.md`. **The abstention gates are SATISFIED, never
  deleted** — no structural constraint is weakened, no disclaimer removed, and a pesticide
  recommendation stays inexpressible.
  - **`app/label_data.py` (framework-free)** — three rules govern everything: a label value
    is usable only when **attributable** (`promotable_to_authoritative` returns the REASON a
    record cannot back a decision, not a boolean); product identity is **exact or ambiguous**
    (`100-1234` and `100-1234-5905` are DIFFERENT labels — a base match goes to a human);
    a conversion is **cited or refused** (`RATE_CONVERSIONS` is definitional only, each with
    its citation; mass↔volume is deliberately absent because it needs a per-product density,
    so `convert_rate` returns a `Refusal` naming the unit).
  - **`app/label_table.py` ships EMPTY** (`TRANSCRIBED_LABEL_USES = ()`), exactly as
    `BotrytisWetnessV1.thresholds` does and for the same reason: a plausible PHI is
    indistinguishable from a correct one to every writable test, and it lands in a record a
    PCA is entitled to trust. `TranscribedLabelUse` is frozen/kw-only with no provenance
    defaults, so an uncited row raises at import. **Never loaded by `seed.run()`/`init_db()`**
    — `python -m app.label_sync` or `POST /internal/labels/sync` only.
  - **Three tables:** `PesticideProduct` (identity; unique `epa_reg_no_normalized`, plus
    `epa_reg_base` recorded so a near-miss is RECOGNIZED, never matched),
    `ProductLabelRecord` (**append-only**; a revision and a withdrawal are both just
    superseding rows — a withdrawal has every regulatory value NULL, so resolution yields
    nothing and the checks correctly return to `not_evaluated`; NULL means THE LABEL IS
    SILENT, never "no limit"), `ProductLabelVerification` (**farm-scoped** so
    `require_pca_for_farm` and `ensure_demo_real_separation` both cover it by construction —
    a demo farm can only hold a `simulated` verification, which never promotes, so demo
    decisions can never look label-grounded with zero special cases in the engine).
  - **Five engine rules** (`label_crop_registration`, `label_max_applications`,
    `label_retreatment_interval`, `label_max_seasonal_rate`, `label_value_disagreement`).
    Crop registration blocks ONLY when `registered_crops_transcription_complete` AND a
    verified record backs it — a partial transcription's silence is not evidence a crop is
    unregistered, and a false BLOCK there would end a PCA's trust permanently. Seasonal
    counting reads **`SprayEvent` only** (an applied outcome already materializes one) and
    matches products on EXACT reg no.
  - **`not_evaluated` is computed per decision**, each check carrying a stable `check_id` and
    its OWN reason; a rule that runs retires its entry by id, never by matching prose.
  - **`crud.apply_label_values`** mirrors the PCA-review supersede path and REFUSES once a
    decision is reviewed or applied — a label sync must never rewrite what a PCA signed.
    `_entered_values_behind_label` walks BACK through the supersede chain past label rows, so
    applying a label value cannot erase the disagreement it should have reported. A later
    revision surfaces as `decision_status.label_reference_stale` instead of a silent recompute.
  - **591 tests.** `tests/test_label_authority.py` is the invariant file — including that an
    **APPROVE is still never `verified_label_grounded`**: `repeated_active_ingredient`
    (heuristic) and `prior_rei_overlap` (grower-entered) keep every approve provisional, so
    **merging or deleting either silently creates a no-human-review approve**.

- **Botrytis Deferral Shadow Pilot V1 (2026-07-20)** — the current focus. Full contract in
  **`BOTRYTIS_PILOT.md`**; read that before touching any of it. One falsifiable hypothesis:
  can a licensed PCA defer a scheduled Botrytis application 24–72h, and can we measure it?
  - **Pilot observation layer:** `Block` (the comparison unit, nullable `block_id` links;
    `field_block` free text deliberately untouched), `WeatherObservation` + `ScoutingSample`
    (units in the column names, dual `observed_at`/`recorded_at`, append-only with
    `supersedes_id`, partial unique indexes `WHERE supersedes_id IS NULL`), and two more CSV
    record types.
  - **`app/risk_snapshot.py` + `RiskInputSnapshot` — the leakage boundary.** Framework-free,
    and its signature admits ONLY block + observations, so post-decision data cannot be passed
    in without a visible contract change. Admissibility is checked on BOTH timestamps: the
    load-bearing rule is `recorded_at > as_of`, because filtering on `observed_at` alone looks
    correct and silently leaks hindsight. Content-addressed (sha256 over canonical JSON).
  - **`app/disease_risk.py` — versioned rules that mostly abstain.** No LLM in this path at
    all. `RiskAssessment` has no product/rate/action field, so a pesticide recommendation is
    *inexpressible*, not merely forbidden. Bands are `low|moderate|high|abstain` — there is no
    "safe". Every abstention condition runs BEFORE the rule and ALL reasons are reported.
    **`botrytis_wetness_v1` is registered and abstains with `thresholds_not_supplied`: its
    coefficients are deliberately absent, and must be transcribed from the primary source, not
    recalled or searched for** — see BOTRYTIS_PILOT.md §3 for why a plausible number would pass
    every writable test.
  - **`DiseaseRiskAssessment` + shadow mode:** `is_shadow` defaults True and shadow rows are
    omitted from every PCA-facing serializer (absent from the payload, not hidden in the UI).
    `GET /internal/pilot/assessments` is the only surface that returns them. Unblinding is a
    dated, protocol-versioned event (`PilotProtocol.unblinded_at`), never a config toggle.
  - **`PcaDisposition`** (`follow_baseline|defer|rescout|insufficient_evidence`, mandatory
    rationale, anchored to a snapshot digest, append-only, always credential-gated via
    `crud.require_pca_for_farm`). **Strictly orthogonal:** recording one never writes a
    `decision_*`/`review_*` column, and `defer` neither unlocks an applied outcome nor
    satisfies a required review. Four facts about four moments — engine verdict, review,
    disposition, outcome — stay separate, or the pilot measures nothing.
  - **`PilotProtocol` / `BlockAssignment` / `BlockOutcomeObservation`:** thin versioned
    protocol reference (the protocol is a document), offline randomization with its seed
    recorded, and per-block/per-harvest outcomes. The last is deliberately NOT on
    `DecisionFollowUpEvent` (whose `planned_spray_id` is non-null) — packout is evidence for
    many decisions and for none in particular.
  - **`DELETE /planned-sprays/{id}` now 409s** once a decision carries evidence beyond its
    creation. The cascade on `input_values`/`audit_events`/`follow_up_events` made the
    unguarded route silently destroy the immutable audit trail.
  - **Honest units:** `treated_area_unit` records what the acre-named `treated_acres` actually
    is; `pilot_evidence._sum_treated_area` refuses to total a mixed-unit set rather than
    converting. `NOT_CALCULATED` gains `seasonal_pesticide_use_reduction` — deferring passes is
    not a season-total reduction.
  - Frontend: `PcaDispositionCard` on `/decisions/[id]` (renders nothing about risk, and
    cannot), `PilotOperatorCard` on `/internal`, `disposition`/`riskBand` STATUS kinds.
    `lib/api.js` now merges headers instead of letting `...options` clobber them.

- **Pilot-integrity & measurement-foundation cycle (2026-07-18)** — hardening for the first
  REAL pilot, no new claims:
  - **Clock interlock:** API refuses to start with `LUMOS_DEMO_TODAY` set unless
    `LUMOS_DEMO_MODE=1` (see §8); `/health` reports `clock_mode`/`pinned_date`.
  - **Demo/real mixing guard:** one farm is all-demo or all-real; mismatched record creation
    409s (`crud.ensure_demo_real_separation`, incl. input plans + both import paths). The
    frontend demo-tags rows created interactively on demo farms (`useDemoTag`). Fixed a
    pre-existing bug where API rows with omitted provenance fell to the ORM default
    `"demo"/"simulated"` — create schemas now default `manual_entry`/`user_provided`.
  - **Historical spray import:** `spray_events` is a third CSV import record type (dry-run,
    aliases, dedupe, template; CSV-only — no AI extraction model). This is the
    `prior_period` reduction baseline's denominator.
  - **Explicit import date formats:** `date_format` = `auto|iso|mdy|dmy`; `auto` ERRORS on
    ambiguous m/d-vs-d/m dates instead of guessing.
  - **Quantity capture (capture only, no computed claims):** SprayEvent gains
    `rate_amount/rate_unit/treated_acres` (+ `external_record_id/source_system/
    source_filename`); `Farm.area_unit` ("acres"/"m2") makes the area unit data instead of
    country-implied; applied outcomes copy rate/acres/MoA from the plan (changed product ⇒
    rate/MoA never carry over). `NOT_CALCULATED` in pilot_evidence stays verbatim.
  - **Alembic baseline** (`32a030ba8bc4`) — see §8; the schema can now evolve after real
    data lands.
  - **IA consolidation:** primary nav = the decision loop only; Inputs & finance demoted to
    the bottom nav group; `/compliance` merged into `/evidence` as a tab (route redirects;
    `CompliancePanel`); ReductionCard + wedge tagline surfaced; WeatherCard renders on demo
    farms ONLY; invariant tests added for missing-data-never-approves + the mixing guard.

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
  - `app/label_data.py` — pesticide-label vocabulary + arithmetic (pure, stdlib only):
    `normalize_epa_reg_no` / `match_product_identity` (match / **ambiguous** / none),
    `RATE_UNIT_ALIASES` + `RATE_CONVERSIONS` (definitional + cited) → `convert_rate` returns
    `Converted | Refusal`, `resolve_label_record`, `promotable_to_authoritative` (returns the
    REASON), `LABEL_TIER_TO_INPUT_SOURCE`. `app/crop_aliases.py` is its curated crop-name
    sibling (same MATCH/AMBIGUOUS/NO_MATCH vocabulary as `target_aliases`, never fuzzy).
    `app/label_table.py` is the EMPTY transcription source; `app/label_sync.py` loads it.
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
  follow-up timeline), `PcaPolicy`. Botrytis pilot (§5, `BOTRYTIS_PILOT.md`): `Block`,
  `WeatherObservation`, `ScoutingSample`, `RiskInputSnapshot` (immutable),
  `DiseaseRiskAssessment` (append-only, shadow), `PcaDisposition` (append-only, attributed),
  `PilotProtocol`, `BlockAssignment`, `BlockOutcomeObservation` (append-only),
  `PcaCredential` + `PcaFarmAuthorization`. Label layer (§5): `PesticideProduct`,
  `ProductLabelRecord` (append-only, supersede chain), `ProductLabelVerification`
  (append-only, farm-scoped, revoked never deleted). Sprays/scouting carry `data_source` +
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
  - Labels: `GET /internal/labels/products[/{id}]`, `POST /internal/labels/sync`,
    `GET /internal/labels/resolution?epa_reg_no=&crop=&farm_id=` (the "why does this decision
    still say the check did not run" diagnostic — calls the same
    `crud.resolve_label_for_decision` the decision path uses, so the two cannot drift)
  - Exports: `/farms/{id}/export/spray-events.csv`, `/recommendations.csv`,
    `/export/pilot-feedback.csv`
  - `GET /health`; interactive docs at `/docs`.
- **Alembic exists (baseline `32a030ba8bc4`); the DB is NO LONGER disposable.** This
  paragraph used to say "no Alembic, re-seed to change the schema". That is now true
  only for a demo-only database. `seed.run()` still calls `Base.metadata.drop_all`, so
  **`rm -f backend/lumos.db && python -m app.seed` DESTROYS REAL PILOT DATA** — see §8
  for the migration workflow. After seeding a fresh demo DB, `alembic stamp head`.

---

## 7. Frontend Architecture

- **Framework:** Next.js 14 (App Router, JavaScript) + Tailwind CSS. `@/` path alias.
- **Routes (`frontend/app/`):**
  - `page.js` — dashboard / farm list (risk badge + spend per card; sorts U.S. strawberry first).
  - `farms/[id]/page.js` — farm detail (analytics, weather, compliance, recommendation, review,
    weekly report, pilot evidence, concierge pilot).
  - `evidence/page.js` — "Evidence & compliance": outer Evidence|Compliance tabs
    (`?tab=compliance` deep-link; `/compliance` redirects here; the compliance view lives
    in `components/CompliancePanel.js`), demo/real scope tabs, ReductionCard, exports.
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
# DEMO-ONLY DATABASES. Both of these DESTROY real pilot data — check first with
#   python -c "from app.database import SessionLocal; from app import crud;
#              print(crud.has_non_demo_data(SessionLocal()))"
cd backend && source .venv/bin/activate && python -m app.seed
#   nuclear reset: rm -f backend/lumos.db && python -m app.seed
#   after seeding a fresh DB, mark it migration-current: alembic stamp head
#   (running create_all — e.g. an ad-hoc script calling init_db() — desyncs the DB
#    from Alembic; symptom is "table X already exists" on upgrade. Reseed + stamp.)

# Schema changes (Alembic exists as of 2026-07-18 — baseline 32a030ba8bc4):
#   demo-only DBs may still drop+reseed; a DB with REAL pilot data must migrate:
#   edit app/models.py -> alembic revision --autogenerate -m "..." -> review the
#   script (env.py enables SQLite batch mode) -> alembic upgrade head

# Load transcribed pesticide labels (app/label_table.py) into the DB. EXPLICIT on
# purpose — never run by seeding or startup, because seeded label data would make demo
# decisions look label-grounded. Safe to re-run; a changed transcription appends a
# superseding row. Reports 0 entries until someone transcribes one with its citation.
cd backend && source .venv/bin/activate && python -m app.label_sync

# Run backend:  uvicorn app.main:app --reload   (http://localhost:8000, docs at /docs)

# Frontend build / lint (from frontend/)
cd frontend && npm install
npm run build      # production build = de-facto typecheck/compile check
npm run lint       # next lint
npm run dev        # http://localhost:3000
```

- **No JS typecheck beyond `next build`** (plain JavaScript project, no `tsc`). `npm run lint`
  is the only lint step.
- **Passing test count:** repo currently shows **591 passing**. **Always re-run `pytest` to
  confirm; do not trust this number.** Known harmless deprecation warnings. AI tests run on
  the deterministic `MockLlmService` — no API key needed; never let tests hit the real API.
- **Deterministic demo:** `LUMOS_DEMO_TODAY=YYYY-MM-DD python -m app.seed` pins every seeded
  date to a fixed anchor (screenshots / demo-consistency tests); unset, the anchor is today and
  re-seeding before a demo keeps the story fresh. `tests/test_demo_consistency.py` asserts the
  seeded story's invariants.
- **Clock interlock (2026-07-18):** the API **refuses to start** with `LUMOS_DEMO_TODAY` set
  unless `LUMOS_DEMO_MODE=1` is also set (a leftover pin would silently corrupt real pilot
  timestamps and PHI/REI math). Seeding is exempt; tests set the mode var in conftest.
  `/health` reports `clock_mode` (`real`/`pinned`) + `pinned_date`.
- **Operator-key interlock (2026-07-20):** the `/internal` surface mints PCA credentials and
  grants farm authorizations, so leaving it open makes every authorization guarantee
  decorative. Set `LUMOS_OPERATOR_KEY` and present it as `X-Lumos-Operator-Key`; enforced by
  **middleware on the path prefix** (`app/operator_key.py`), so a route added later is covered
  by construction. Unset, `/internal` stays open for demo/local use — but the API **refuses to
  start** once `crud.has_non_demo_data` is true. Not auth infrastructure: no login, no session,
  no password, no user table.
- **Demo/real mixing guard (2026-07-18):** one farm's records are either ALL demo/simulated or
  ALL real — creating a mismatched record 409s (`crud.ensure_demo_real_separation`, mirrored on
  input plans). The frontend demo-tags rows created interactively on demo farms
  (`useDemoTag` in `lib/farm-context.js`), so the live demo walkthrough still works and its
  records are honestly simulated. Real pilots always get a fresh farm.
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
- **The label table is EMPTY, so in practice PHI/REI still come from user-entered per-spray
  values.** As of 2026-07-27 the label layer exists (§5) but holds no data: nothing has been
  transcribed from a primary document and no PCA has verified anything, so every
  label-dependent check still reports that it did not run — now with a specific reason
  instead of "no label database exists". **Until a real transcription with a real per-farm
  PCA verification exists, do not claim Lumos checks against label data at all.** Coverage on
  a first pilot is governed by whether the PCA's recommendation sheets carry EPA registration
  numbers — a data-entry question, not a code one.
- **No MRL reference data** — an MRL is destination-market law, not label law; the label layer
  does not and will not supply it.
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
