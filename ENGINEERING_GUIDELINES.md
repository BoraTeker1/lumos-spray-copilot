# ENGINEERING_GUIDELINES.md — Lumos Spray Copilot

Canonical project memory for `precision_farming`. Read this first, then open only the files your
task needs.

This document is a **map, not a brake**. It exists so a session can build confidently and
correctly on the first try: what the product is, what is already built, which patterns to reuse,
and the small number of constraints that are genuinely load-bearing.

> **Section numbers are an API.** ~30 source comments and one test cite `ENGINEERING_GUIDELINES.md §4/§5/§6/§9/§10`,
> and `backend/tests/test_ingest_registry.py` reads the headings **§3 "Current Strategic
> Conclusion"** and **§4 "Hard Guardrails"** from this file at import time. Rewrite contents
> freely; do not renumber or rename those two headings.

---

## 1. Project Summary

- **What it is:** Lumos Spray Copilot is the **decision-and-proof layer for low-pesticide
  agriculture**. It logs sprays and scouting, runs a transparent rule engine that flags
  PHI/REI/resistance/scouting/weather risk, routes every recommendation through a licensed human,
  and produces audit-ready records that make a reduction claim *checkable* rather than asserted.
- **The thesis in one line:** most excess spraying is decided *before* any nozzle is involved —
  calendar habit, fear, and resistance ratchets. Robots and biologicals change *how* and *what*
  you spray; something still has to decide **whether**, and prove it afterwards. That layer is
  capital-light, and it is the one we win first.
- **Current wedge:** California specialty crops — **strawberries** (primary) and greenhouse
  tomatoes — and their **PCAs/agronomists**. The wedge is where we start, not a ceiling.
- **Target user / buyer hypothesis:** grower + their PCA/agronomist use it; the likeliest economic
  buyer is the **PCA/advisory firm or packer/exporter** carrying audit and residue risk across
  many growers. Unvalidated — see §11.
- **What this is NOT:** not a hardware manufacturer, not a farm-OS/ERP, not a black-box AI, not an
  autonomous "must spray" prescriber, not a compliance or legal guarantee.

---

## 2. Strategic Positioning

- **YC-style one-liner:** "AI pesticide-decision and compliance copilot for specialty-crop growers
  and their PCAs — the decision layer before the spray that helps them spray less, avoid PHI/REI
  mistakes, and keep audit-ready records." Full text in `YC_POSITIONING.md`.
- **Against the low-pesticide RFS.** The RFS names four unlocks: AI that can see, cheap sensors,
  precise robotic action, and biology (microbes/peptides/RNA). Each one produces or consumes a
  *decision*, and none of them can prove a reduction on its own. Lumos is the layer that decides
  and proves — complementary to the companies building the other four, and the natural place the
  evidence lands. `RFS_PESTICIDE_REDUCTION.md` holds the long-form answer; its framing notes are
  still right, but its "we are not CV/sensors/robotics" concession is now a **roadmap, not a
  permanent boundary** (see §3).
- **Why the CA specialty-crop wedge:** sprayed often, hand-harvested, heavily regulated
  (PHI/REI, MRL, PrimusGFS/GlobalG.A.P., CA DPR reporting). Seeded U.S. demo farm =
  `Golden Coast Strawberry Ranch`, Watsonville. See `US_WEDGE.md`.
- **PCA / agronomist-in-the-loop is an advantage, not a tax.** In California a licensed PCA must
  legally sign pesticide recommendations — the human-in-the-loop already exists and our review
  workflow maps onto it. It is also what lets us ship aggressive capability safely.
- **Why not John Deere / FieldView:** they are row-crop hardware and data plumbing. We are
  software upstream of the nozzle, deep on one painful recurring decision in a segment they do
  not serve.

---

## 3. Current Strategic Conclusion

**Build the thesis. Validate in parallel.**

The prototype is strong enough to demo and to run pilot conversations, and the startup is not yet
validated (§11). Those are both true, and neither is a reason to stop building. This section used
to say "stop building product unless a validation need directly requires it"; that stance
produced a repo full of capability with the ceiling always one purchase or one transcription
away. The correct response is to **close those gaps**, not to freeze.

### The Build Ladder

The organising spine for all engineering work. Every rung names what it unlocks.

| Rung | What it is | Status |
| --- | --- | --- |
| **L0 — Decision layer** | Rule engine, PCA review, audit record, field-level provenance, evidence export | **Built** (§5) |
| **L1 — Measurement substrate** | The feeds and instruments that make a reduction claim checkable: weather ingestion, leaf-wetness sensing, transcribed thresholds and labels | **Next.** Partially built; the binding gaps are named below |
| **L2 — Seeing** | Vision beyond a single suggested scouting note: pressure over time, per block, as engine-admissible evidence | Open |
| **L3 — Targeted application** | Variable-rate / spot-treatment **prescriptions** exported to equipment the grower already owns | Open |
| **L4 — Non-chemical alternatives** | Biologicals and microbials as first-class options, so "don't spray this" can become "spray this instead" | Open |

L1 is the highest-leverage rung, because **every claim the product wants to make is currently
gated on it.** Two of its blockers are not code and are now permitted (§4): buy a leaf-wetness
sensor, and transcribe `app/botrytis_thresholds.py`. Do those.

### The build test

Replaces the old "default answer is no." Ship it when all three hold:

1. **It advances a named rung** (or fixes something on a built one).
2. **It ships with its honesty mechanism** — a refusal path for missing data, provenance on
   anything a human will act on, and a test that pins the behaviour.
3. **It does not cross §4.**

If a request fails one of these, say which one and what would fix it. Do not refuse on vibes, and
do not refuse because the work is ambitious.

### The pattern that makes ambition safe

**Build the structure; ship the coefficients empty; refuse rather than default.** Generalised in
`app/transcription.py`, proven by `label_table.py` and `botrytis_thresholds.py`. It is why this
codebase could add eight decision domains in a day without inventing a single number, and it is
the first tool to reach for whenever the data does not exist yet. A model that cannot compute
returns a `Refusal` with a stable `code` (`app/refusal.py`) — never a plausible number, never a
zero.

### Honest standing

Zero confirmed pilots, zero customer decisions. `DESIGN_PARTNER_SPRINT.md` (secure one Central
Coast strawberry PCA) is still the right *commercial* motion and contains no engineering — run it
alongside the build, not as a gate in front of it. Capability and evidence are two tracks; the
mistake is letting either one stop the other.

---

## 4. Hard Guardrails

Not a list of features someone once felt nervous about. These are the things that would make the
product **dishonest, unsafe, or illegal** — the reasons a compliance-sensitive buyer can trust it.
Everything not listed here is buildable under the §3 build test.

### Genuinely hard — do not cross without an explicit instruction in-session

- **No autonomous spray action.** A licensed human authorises every recommendation. This is legally
  required in California and is the product's entire trust model. It is enforced *structurally*,
  not by prose: `disease_risk.RiskAssessment` has no product, rate, or action field, so a
  prescription is **inexpressible**. Preserve that technique when adding surfaces — the strongest
  guarantee is a value that cannot be represented.
- **No fabricated regulatory or coefficient values.** A PHI, REI, rate limit, threshold, scorecard
  weight, or advance rate arrives by a human transcribing a primary document *with its citation*,
  or the model returns a `Refusal`. `None` means **the source is silent**, never "no limit."
  See `app/transcription.py`, `TRANSCRIPTION_TASKS.md`.
- **No money movement of any kind.** No payments, disbursement, repayment collection, or computed
  amortisation — hence no structured APR anywhere, only a lender's verbatim cost sentence. Also
  no revenue-sharing, no Lumos-authored credit policy or covenant threshold, no `approved`
  underwriting outcome (the strongest affirmative is `conditions_met`), no estimated insurance
  premium, and no recommendation to take/increase/close a market position. Real licensing
  exposure; the last two are structural (there is no field to put them in).
- **No guaranteed-reduction claims**, and no metric that reads as one. "Potential avoidable cost,"
  never "savings." `backtest.FORBIDDEN_KEY_SUBSTRINGS` makes adding an "avoided" key fail CI —
  reuse that technique.
- **No manufacturing our own hardware.** Integrate with instruments, buy them, read their feeds.
  Do not become a hardware company; that is the capital trap the wedge exists to avoid.
- **No presenting simulated output as real.** Demo data is never traction, mock-service output is
  never model performance, a fabricated fixture is never a live capture. See §9.

### Open — build these when a rung calls for them

Previously forbidden, now in scope. The §3 build test still applies (each needs its honesty
mechanism), but none of these requires a special dispensation:

- **Computer vision and image-based diagnosis** — including diagnosis, multi-image and
  time-series pressure, and vision output that reaches the engine as evidence. The human gate
  above still holds: vision can establish *what is there*, never *what to spray*.
- **Sensors, IoT, weather stations, and instrument purchases** — explicitly including the
  on-site leaf-wetness sensor that L1 needs. Ingest via `app/ingest/` and its adapter contract.
- **Targeted-application and spot-spray prescriptions** — variable-rate maps and per-zone
  treatment plans exported to third-party equipment, under the human gate.
- **Biologicals and non-chemical alternatives** — as decision options with the same label,
  provenance, and refusal discipline as conventional chemistry.
- **Crop and geography expansion** — the CA strawberry wedge stays **first**, not **only**. New
  crops need their alias and label work done properly (`app/crop_aliases.py`), not assumed.
- **Conversational interfaces** — a chat surface may explain, retrieve, and draft. It may never
  be the decider; the outcome stays the deterministic engine plus the PCA.
- **Auth, tenant isolation, and multi-grower access control** — reclassified from forbidden to
  buildable. A PCA firm serving many growers needs it, the primitives already exist
  (`PcaCredential`, `PcaFarmAuthorization`, `app/operator_key.py`), and the Strix pentest's
  cross-farm attribution finding (commit `b195713`) is the evidence it is now a liability rather
  than a discipline. Build it when a real multi-grower engagement requires it.
- **Marketplace and procurement depth** — supplier catalogue, RFQ transport, quote dispersion.
  Already partially built (§5). Still excluded by the money-movement rule: real payments, real
  lending, automated underwriting, and commission-based quote ranking.

---

## 5. Product Features Already Built

A capability map, not a changelog. Depth lives in the linked docs — read those before touching
the corresponding area.

### The decision loop (the core product)

- **Pre-spray decision workflow** — a grower/PCA enters a *planned* spray; `app/decision_engine.py`
  checks harvest timing, entered PHI/REI, prior re-entry windows, repeated active ingredients,
  linked scouting evidence, and missing data, returning ONE explainable outcome:
  **approve / block / delay / inspect_first / pca_review_required** with triggered rules, exact
  calculations, inputs used, missing information, and a completeness confidence. Precedence:
  block > delay > pca_review_required > inspect_first > approve.
  **Missing inputs can never yield approve** — they escalate to PCA review.
- **Authority gating** — every rule carries a `source_authority`
  (`verified_label` / `pca_entered` / `grower_entered` / `heuristic`). Only verified-label or
  PCA-entered sources back a **definitive** verdict; everything else is **provisional** and a
  provisional approve becomes review-required. The engine never names replacement products —
  those come only from PCA-entered `pca_next_action`.
- **PCA review** (approve / edit / reject + comment) gates applied outcomes (409 until approved or
  edited when review is required). **Real-world outcome** recorded as
  `sprayed_as_planned / changed_product / delayed / avoided / inspected_first`, reason mandatory
  except as-planned.
- **Field-level provenance** — `DecisionInputValue`, an append-only supersede chain per
  compliance-critical input with `source_type` and verification attribution. Latest non-superseded
  value drives the engine; imported values never auto-approve.
- **Immutable audit history** — `DecisionAuditEvent` (created / reviewed / input_value_superseded /
  outcome_recorded / follow_up_added), prior state in `before`. Plus an append-only
  `DecisionFollowUpEvent` timeline, required for every non-as-planned outcome.
- **Evidence** — `GET /farms/{id}/decision-evidence` splits **confirmed** (follow-up-backed only)
  from **estimated** from **not_calculated** (with reasons). Never combined into one score.
  Anonymized `evidence-export` excludes demo records by construction.

### Label capability layer

Product identity plus verified label records, so label-dependent checks can actually run.
Detail: `TRANSCRIPTION_TASKS.md`; invariants: `tests/test_label_authority.py`.

- Three rules govern everything: a label value is usable only when **attributable**
  (`promotable_to_authoritative` returns the *reason* it cannot back a decision); product identity
  is **exact or ambiguous** (`100-1234` and `100-1234-5905` are different labels — a base match
  goes to a human); a conversion is **cited or refused**.
- `PesticideProduct` (identity) / `ProductLabelRecord` (append-only; a revision and a withdrawal
  are both just superseding rows) / `ProductLabelVerification` (**farm-scoped**, so a demo farm can
  only hold a `simulated` verification, which never promotes — demo decisions can never look
  label-grounded, with zero special cases in the engine).
- Five engine rules: crop registration, max applications, retreatment interval, max seasonal rate,
  value disagreement. Crop registration blocks only when the crop transcription is *complete* — a
  partial transcription's silence is not evidence a crop is unregistered, and a false block there
  would end a PCA's trust permanently.
- **Three routes are three trust levels and must stay separate:** extract (never writes) → commit
  as `ai_extracted_unverified` (tier is server-set, never client-supplied) → PCA verification for
  a farm (a professional act, not under `/internal`).
- `app/label_table.py` holds **two real transcriptions** (Captan 80 WDG `34704-1075`, Switch 62.5WG
  `100-953`, strawberry use, from EPA PPLS PDFs). Loaded only by `python -m app.label_sync` —
  never by seeding or startup.

### Botrytis deferral shadow pilot

The falsifiable measurement study. **Full contract in `BOTRYTIS_PILOT.md` — read it first.**

- **`app/risk_snapshot.py` is the leakage boundary.** Its signature admits only block +
  observations, so post-decision data cannot enter without a visible contract change.
  Admissibility checks **both** timestamps: the load-bearing rule is `recorded_at > as_of`, because
  filtering on `observed_at` alone looks correct and silently leaks hindsight. Content-addressed.
- **`app/disease_risk.py`** — versioned rules, no LLM in this path. Bands are
  `low|moderate|high|abstain`; there is no "safe". Every abstention condition runs before the rule
  and all reasons are reported. `botrytis_wetness_v1` abstains with `thresholds_not_supplied`; the
  arithmetic is implemented and tested against synthetic tables, so transcribing the primary
  source is the only remaining step.
- **Shadow mode** — `is_shadow` defaults True; shadow rows are *absent* from every PCA-facing
  payload, not merely hidden in the UI. Unblinding is a dated protocol event, never a config
  toggle. **Adding anything to the PCA-facing decision surface breaks the blinding** — check this
  before extending a decision payload.
- **`PcaDisposition`** is strictly orthogonal to review: recording one never writes a
  `decision_*`/`review_*` column, and `defer` neither unlocks an applied outcome nor satisfies a
  required review. Four facts about four moments stay separate, or the pilot measures nothing.

### Data platform and features

Outside data reaching a decision auditably. **Full contract in `DATA_PLATFORM.md`.**

- **17 domains declared** (`app/ingest/domains.py`), all 17 now computable (9 MVP + 8 admitted).
  The deferral machinery is kept though currently unused — it is how the next domain gets deferred.
- **Eight-stage pipeline**, each stage reusing something. `validate` reuses
  `csv_import.validate_rows`, so an ingested reading meets the same contract as a concierge-entered
  one. **Issues are recorded, never raised.** A row with no station-to-field distance is
  **dropped, not written with a NULL** (`disease_risk` reads NULL as both *in range* and *close*).
  `recorded_at` is stamped at persist time, **never back-dated**.
- **Features abstain rather than default.** `FeatureResult` is abstained **iff** it has no value,
  so `0` can never stand in for "no data" — and `0 kg/ha of active ingredient` would be a
  pesticide-reduction *claim*, not a gap.
- **`feature_values` is a leak detector**: fully unique, no supersede chain, because at a fixed
  `as_of` the inputs digest must reproduce forever. A digest that moves is proof an input became
  visible that should not have.
- **CIMIS adapter** — the only outbound HTTP in the codebase, confined to one `_http_get` with an
  injectable transport and a key-stripping `_redact`. The pipeline asks `describe()` before
  `fetch`, so a deployment without a credential is **inert by construction**. CIMIS publishes no
  leaf-wetness item; that measurement needs the on-site sensor now permitted by §4.

### Advisory, procurement, finance, market layers

Built 2026-08-07 on the empty-source pattern. **Full contract in `FINANCE_LAYER.md`.**

- Agronomy: `soil`, `fertilization`, `seed_selection`, `irrigation`, `land_selection`.
- Finance: `credit_scoring` (all-or-nothing on inputs — a scorecard is a weighted sum, so a missing
  factor scores zero and reads as a *worse borrower*, not an incomplete one), `underwriting` (no
  `approved`; an unevaluated rule yields `referred_to_human`), `collateral` (refuses an unrated
  asset — 100% understates lender exposure, 0% denies held collateral), `insurance`, `monitoring`
  (`standing` has three values because "nothing checked" must never render as "compliant").
- Market: `pricing` refuses outside a freshness window with **no last-known-value fallback**;
  `hedging` reports coverage with advice *inexpressible*.
- **Persistence is append-only and the invariant is outcome XOR refusal — a refusal IS stored**
  (`crud._outcome_columns`). Storing only successes would make the record set survivorship-biased.
- **Marketplace:** `Supplier` / `SupplierProduct` / `RfqTransmission`.
  `procurement_analytics.build_report` groups by **catalogue id, never by name** — grouping free
  text reports three spellings of one product as three products with no spread, which reads as
  "prices are consistent." Reports a **spread, never a saving or a recommended supplier**;
  observations stay in entry order, because sorting by price is a ranking in everything but name.
- **Cross-layer:** `farm_profile.py` + `GET /farms/{id}/profile` (grower-facing) and
  `GET /internal/transcription-status` (operator worklist, generated from the domain registry so it
  cannot drift). The profile abstains **per field** and computes no overall score.

### Other built surfaces

- **Historical opportunity scan** (`app/backtest.py`) — replays a past season's scheduled spray
  dates against the versioned rule. Uses `BASIS_RETROSPECTIVE`, a second explicitly-named
  admissibility basis, **never a back-dated timestamp**; prospective digests are pinned so a
  reconstruction can never masquerade as the prospective record of that moment. Output is a
  histogram with **no avoided count and no reduction figure**. It is *sizing*, not proof: every
  historical outcome followed the actual spray, so no date can be called avoidable.
- **Operator reference farm** (`app/reference_farm.py`) — the one configuration where label checks
  actually run end to end, because a demo farm is *structurally incapable* of showing a
  label-grounded decision. `Farm.is_reference` excludes it from the usage funnel and stamps a
  disclosure on every evidence surface. Read-only in the API on purpose.
- **AI layer** — `app/llm.py` (shared service, structured outputs via `messages.parse`),
  `app/vision.py` (photo scouting → a *draft* observation a human confirms),
  `app/extraction.py` + `app/label_extraction.py` (document extraction, verbatim
  `source_snippet` per row), `app/ai_brief.py` (retrieval-grounded risk note, next actions
  enum-locked to evidence gathering, forced to abstain below 2 real comparables). Every call logs
  an append-only `AiJudgment`. **AI proposes; the deterministic engine and the PCA decide.**
- **Recommendation engine, analytics, reduction, weather, weekly report, audit packet, CSV
  import/export, pilot intake and feedback, concierge import** — the original MVP surfaces, still
  live. The farm-wide `recommendation_engine` is now *secondary* to the pre-spray decision check.
- **Security fixes (`b195713`, Strix pentest):** CSV formula injection in all four export
  endpoints (`_sanitise_csv_cell`, OWASP tab-prefix for cells starting `= + - @`), and cross-farm
  audit attribution on review rejection (scope-check a presented credential before attributing;
  anonymous rejection still works). `strix-instructions.md` holds the rules of engagement.
- **CORS + operator key** — the middleware gate exempts `OPTIONS` (a browser never sends custom
  headers on a preflight) and `CORSMiddleware` is registered **last so it is outermost** (a 403
  raised outside it carries no CORS headers, so the browser discards the one message explaining
  the key is missing). **Middleware order is load-bearing.** No backend test could catch this —
  TestClient does not speak CORS.

---

## 6. Backend Architecture

- **Framework:** FastAPI; **ORM:** SQLAlchemy 2 (typed `Mapped`); **DB:** SQLite
  (`backend/lumos.db`); **validation:** Pydantic v2; **tests:** pytest. ~145 routes, 62 models.
- **Layering rule:** routes (`main.py`) → `crud.py` (all DB access) → `models.py` / `schemas.py`.
  Pure logic modules take **plain objects, no FastAPI/SQLAlchemy imports**, so they unit-test in
  isolation. Pinned by `tests/test_platform_invariants.py`. Keep it this way.
- **Core modules**
  - `app/main.py` — routes, CORS, middleware order, report/audit text builders.
  - `app/decision_engine.py` — the pre-spray engine (pure). `PLANNED_SPRAY_DISCLAIMER` lives here.
  - `app/crud.py` — all DB access; also recommendation storage, pilot import/intake, and the
    authority helpers `require_pca_for_farm` / `ensure_demo_real_separation`.
  - `app/decision_status.py`, `app/procurement_status.py` — pure derived-state vocabularies.
  - `app/recommendation_engine.py` — the farm-wide rule engine (tunable thresholds at top).
- **Honesty infrastructure** (reach for these first)
  - `app/transcription.py` — the empty-source contract; `Citation` is frozen/kw-only with **no
    defaults**, so an uncited row raises at import.
  - `app/refusal.py` — `Refusal` with a stable `code`. Prose cannot be matched on by a test, a
    payload consumer, or a readiness surface; the code can.
  - `app/units.py`, `app/label_data.py` (`convert_rate` → `Converted | Refusal`),
    `app/target_aliases.py` / `app/crop_aliases.py` (**never fuzzy** — exact or curated alias or
    ambiguous-to-a-human).
  - Empty sources awaiting transcription: `label_table.py` (2 rows), `botrytis_thresholds.py`,
    `soil_thresholds.py`, `nutrient_tables.py`, `variety_table.py`, `irrigation_coefficients.py`,
    `scorecard_table.py`, `underwriting_rules.py`, `collateral_valuation.py`,
    `insurance_products.py`, `monitoring_covenants.py`, `price_series.py`, `futures_curve.py`,
    `financing_terms.py`.
- **Domain modules:** `disease_risk.py`, `risk_snapshot.py`, `backtest.py`, `pit.py`,
  `analytics.py`, `reduction.py`, `weather.py` / `advisory_weather.py`, `pilot_evidence.py`,
  `farm_profile.py`, `procurement_analytics.py`, `rfq_transport.py`, plus the agronomy/finance/
  market set named in §5.
- **`app/ingest/`** — `base`/`domains`/`registry`/`geo` are PURE (pinned by test); `pipeline.py` is
  the only DB-touching module and `cimis.py` the only one with a network call.
- **`app/features/`** — derived values that abstain. `base.py`'s invariant: a `FeatureResult` is
  abstained **iff** it has no value. `pit_view.py` gives `SprayEvent` its two timestamps without a
  migration (a backfilled `recorded_at` would fabricate a claim about when something was known).
- **`app/jobs/`** — queue, schedule, worker. Ingestion enqueues; the worker owns retries and
  dead-lettering. Inert without a provider credential.
- **Key endpoint groups:** farms + `GET /farms-overview` (urgency-ranked dashboard) · planned
  sprays + review/outcome/audit/input-values/follow-ups · spray events · scouting · recommendations
  · photo analysis · analytics / weather-risk / compliance / weekly-report · reduction ·
  pilot evidence / case study / audit packet / evidence export · labels (extract → commit →
  verify) · data readiness (grower-facing) · ingestion (operator) · opportunity scans (operator) ·
  finance and market reads · inputs & finance procurement chain · `/internal/*` operator tooling ·
  `GET /health`. Interactive docs at `/docs`.
- **Alembic exists (baseline `32a030ba8bc4`); the DB is NOT disposable.** `seed.run()` still calls
  `drop_all`, so `rm -f backend/lumos.db && python -m app.seed` **destroys real pilot data** —
  see §8.

---

## 7. Frontend Architecture

- **Framework:** Next.js 14 (App Router, JavaScript) + Tailwind. `@/` path alias. No TypeScript,
  so `npm run build` is the de-facto typecheck.
- **16 routes (`frontend/app/`):** `page.js` (dashboard) · `farms/` + `farms/[id]` ·
  `decisions/` + `decisions/[id]` (the printable one-page decision record) · `applications/` ·
  `scouting/` · `evidence/` (Evidence|Compliance tabs) · `compliance/` (redirects into it) ·
  `finance/` · `inputs/` + `inputs/plans/[id]` + `inputs/orders/[id]` · `feedback/` ·
  `pilot/new/` · `internal/` (unlinked operator page).
- **Design system — use it; do not add ad-hoc styling.**
  - `components/ui/` — 10 primitives: `badge`, `button`, `card`, `dialog`, `field`, `input`,
    `select`, `sheet`, `tabs`, `textarea`.
  - `lib/tones.js` — the single source of visual tone recipes. Components look up a tone by
    **domain value** (decision outcome, review state, risk band) instead of declaring their own
    palette maps. Colors resolve through semantic token pairs in `tailwind.config.js`
    (`ok`/`risk`/`warn`/`inspect`/`review`/`info`/`draft`). **Badge variant keys keep their
    historical color names** (`"green"`, `"amber"`, …) so ~45 call sites re-skin without edits —
    re-point a key, don't add a palette.
  - `lib/labels.js` — shared user-facing label vocabularies, mirroring `app/decision_engine.py`
    and `app/decision_status.py`. Import from here so two surfaces cannot disagree.
  - `lib/status.js`, `lib/format.js`, `lib/utils.js`, `lib/farm-context.js` (`useDemoTag`).
- **Responsive tiers are offset one step from the viewport.** A ~250px sidebar always renders, so a
  table's container is ~250px narrower than the window and viewport-keyed rules fire early.
  `DataTable` collapses secondary columns below `xl` (not `lg`), `PageHeader` stacks below `lg`,
  and narrow rails take explicitly compact columns from the caller rather than guessing.
- **58 components.** Layout: `AppShell`, `PageHeader`, `Breadcrumbs`, `SectionCard`, `DetailPanel`,
  `DataTable`, `FilterBar`, `EmptyState`, `MetricCard`, `StatTile`, `Callout`, `ProgressBar`,
  `StatusBadge`, `RiskBadge`, `SeverityBadge`, `SystemState`, `ActivityTimeline`.
  Decision loop: `PreSpraySheet` (the primary CTA — mobile-first, product + date required,
  everything else collapsible), `DecisionResult`, `DecisionQueue`, `DecisionEvidenceCard`,
  `AgronomistReview`, `NextActionCard`/`NextActionBanner`, `PcaDispositionCard`, `AiBriefCard`.
  Data: `DataReadinessCard` (renders the server-owned `basis_text` **verbatim**, contains no
  wording of its own), `IngestionCard`, `DomainRegistryTable`, `TranscriptionStatusCard`,
  `FarmProfileCard`, `OpportunityScanCard`, `LabelLibraryCard`. Procurement/finance:
  `InputPlanForm`, `QuoteComparisonTable`, `FinancingOfferCard`, `OrderTimeline`,
  `PriceDispersionCard`, `LinkApplicationDialog`, `ConciergeQuoteCard`. Plus `PhotoScoutCard`,
  `SprayEventForm`, `ScoutObservationForm`, `SprayImportCard`, `PilotImportCard`,
  `WeeklyReport`, `ReductionCard`, `AnalyticsCard`, `WeatherCard`, `CompliancePanel`.
- **API client:** `frontend/lib/api.js` — one `api` object wrapping every backend call; base URL
  from `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`). Keep all fetches here. It merges
  headers rather than letting `...options` clobber them, and holds the operator key / PCA token in
  `sessionStorage`.
- **UI rule that matters:** an abstention renders **"Not calculated" plus its reason** — never a
  `0`, never a blank card. This is the `DataReadinessCard` rule and it applies everywhere.

---

## 8. Test / Build Commands

```bash
# Backend tests (from backend/, venv active)
cd backend && source .venv/bin/activate && pytest

# Seed / reset demo data (drops + recreates schema, loads 3 demo farms)
# DEMO-ONLY DATABASES. Both DESTROY real pilot data — check first with
#   python -c "from app.database import SessionLocal; from app import crud;
#              print(crud.has_non_demo_data(SessionLocal()))"
cd backend && source .venv/bin/activate && python -m app.seed
#   nuclear reset: rm -f backend/lumos.db && python -m app.seed
#   after seeding a fresh DB: alembic stamp head
#   (running create_all — e.g. an ad-hoc script calling init_db() — desyncs the DB from
#    Alembic; symptom is "table X already exists" on upgrade. Reseed + stamp.)

# Schema changes: edit app/models.py -> alembic revision --autogenerate -m "..."
#   -> review the script (env.py enables SQLite batch mode) -> alembic upgrade head
#   SQLite batch mode cannot create an unnamed FK constraint — name them explicitly.

# Load transcribed labels. EXPLICIT on purpose — never run by seeding or startup,
# because seeded label data would make demo decisions look label-grounded.
python -m app.label_sync

# FULL REBUILD ORDER. seed.run() drops EVERY table.
python -m app.seed           # demo farms only
alembic stamp head           # seeding uses create_all and desyncs Alembic
python -m app.label_sync     # 2 transcribed labels
python -m app.reference_farm # prints the PCA token ONCE — copy it

# Background worker (ingestion + feature recomputation). Inert without a credential.
python -m app.jobs.worker --once --queues default,ingest,features
#   export LUMOS_CIMIS_APP_KEY=...            (free from et.water.ca.gov)
#   export LUMOS_CIMIS_SUBSCRIPTIONS="4:1:111"  # farm:field:station
#   A subscription whose FIELD HAS NO CENTROID ingests nothing (every row drops with
#   `no_field_geolocation`). Set Field.centroid_lat/lon first.

# Run backend
LUMOS_OPERATOR_KEY=<secret> uvicorn app.main:app --reload   # :8000, docs at /docs
#   Nothing loads .env — export ANTHROPIC_API_KEY too, or every AI path runs on the mock.

# Frontend (from frontend/)
npm install
npm run dev        # http://localhost:3000
npm run build      # production build = the real compile/lint check
```

- **Test count: 1059 passing** as of 2026-08-09. **Always re-run `pytest` and report the real
  number** — this line goes stale, and a remembered count is not evidence. AI tests run on
  `MockLlmService`; never let tests hit the real API.
- **Interlocks that will look like a broken build if you forget them:**
  - **Operator key** — `/internal` mints PCA credentials, so the API **refuses to start** once
    `crud.has_non_demo_data` is true unless `LUMOS_OPERATOR_KEY` is set. With a reference farm
    present that is always true. Symptom: *"Application startup failed. Exiting."*
  - **Clock** — the API refuses to start with `LUMOS_DEMO_TODAY` set unless `LUMOS_DEMO_MODE=1`
    (a leftover pin would corrupt real PHI/REI math). Seeding is exempt; `/health` reports
    `clock_mode` and `pinned_date`.
  - **Demo/real mixing** — one farm's records are all demo or all real; a mismatch 409s. Real
    pilots always get a fresh farm.
- **Never run `npm run build` while `npm run dev` is running** — they share `.next` and the build
  corrupts the dev server's cache (500 MODULE_NOT_FOUND). Stop dev first, or afterwards
  `rm -rf .next && npm run dev`.
- **`npm run lint` is not configured** (it prompts interactively); the lint pass inside
  `npm run build` is the real frontend check.
- **Deterministic demo:** `LUMOS_DEMO_TODAY=YYYY-MM-DD python -m app.seed` pins every seeded date
  to a fixed anchor. `tests/test_demo_consistency.py` asserts the seeded story's invariants.

---

## 9. Demo Data and Honesty Rules

These rules are why the product can build fast and still be trusted by a compliance buyer. They
are not negotiable, and they are cheap to keep if you attach them as you go.

- All seeded farms are **demo / simulated** (`data_source="demo"`,
  `data_confidence="simulated"`). Three farms in `backend/app/seed.py`:
  - **Golden Coast Strawberry Ranch** (Watsonville, CA, USD) — primary demo. Triggers PHI + REI +
    repeated-AI + high-severity scouting, and seeds the end-to-end decision story: a 4th captan
    planned 2 days before harvest → **definitive block** → PCA **edited** guidance (the Switch
    recommendation lives ONLY in `pca_next_action`, never in engine output) → outcome
    **changed_product**. Scenario 2: PyGanic avoided via the lygus threshold. **Scenario 3 is the
    honest FAILURE story** — inspect-first, PCA held it, severity rose, rescue application
    required, nothing avoided. Deliberately negative: a product that shows no failures is not
    credible.
  - **Green Valley Greenhouse** (Antalya, TR, ₺) — secondary high-risk contrast.
  - **Sunrise Tomato House** (Mersin, TR, ₺) — secondary low-risk contrast.
- **Never present seed data as traction.** It is illustrative, not usage.
- **Never imply real pilots** unless a validation doc proves it (none currently do — §11).
- **Be precise about which layer is AI.** The recommendation/compliance **engine is a
  deterministic rule engine, not ML** — say so. The **photo-scouting copilot, document extraction,
  and AI review brief ARE real AI** (Claude), and they *suggest* for a human to confirm: they do
  not diagnose, are not the decider, never say "spray," and never name products. Every AI output
  is logged append-only (`AiJudgment`); judgments are **never seeded or fabricated**, and
  mock-service output must never be presented as model performance.
- **An ingested reading is REAL, not demo, and not reviewed.** A provider-fetched row carries
  `data_source="provider_api"` / `data_confidence="provider_reported"` /
  `source_type="station_export"`. Describe it as machine-fetched and unreviewed — never as
  PCA-verified, which would be a claim with legal weight about a number nobody looked at.
- **An abstention is never rendered as `0`.** The API omits the `value` key entirely rather than
  nulling it. "0 leaf-wetness hours" reads as *no wetness occurred*, the opposite of *we cannot
  see wetness* — and errs toward skipping a needed spray.
- **`recorded_at` on a backfill is ingest time, not observation time.** A backtest over that
  window honestly finds nothing. Never back-date to make a replay work.
- **A fabricated fixture is never presented as a live capture** (see
  `tests/fixtures/cimis/hourly_metric.json`, which says so in the file).
- Always use **"decision support only"** language; never "diagnoses," never "tells you to spray."

---

## 10. Compliance / Liability Copy Rules

Preferred disclaimer — use this exact phrasing for US-facing copy:

> "Decision support only. Always confirm PHI, REI, rates, crop use, and restrictions with the
> product label and a licensed PCA / agronomist."

Also:

- Do **not** say "must spray."
- Do **not** say "guaranteed reduction."
- Do **not** say "prevents all mistakes."
- Use cautious phrasing: "potential avoidable cost," "if one spray is avoided," "risk appears
  elevated," "consider," "inspect first," "review with your PCA/agronomist."
- Prefer "conflict caught" over "spray saved"; "documented, not prevented."
- Existing disclaimers live in `main.py` (`_report_disclaimer`, `AUDIT_DISCLAIMER`),
  `decision_engine.py` (`PLANNED_SPRAY_DISCLAIMER`), and `pilot_evidence.py`
  (`CASE_STUDY_DISCLAIMER`). **Reuse or extend those — do not invent new tone.** When new copy is
  needed, put it server-side (`basis_text`) so a card renders it verbatim and the wording has one
  home.

---

## 11. Validation Status (Honest)

- **No confirmed real-world pilots.** No evidence in the repo proves any. If you find a doc that
  does, cite it; otherwise assume not validated.
- Zero customer decisions, zero willingness-to-pay quotes.
- Evidence still needed: **real spray logs, real scouting notes, real PCA recommendations, audit
  artifacts from actual operations, and a price someone will name.**
- **State this plainly whenever the product's maturity comes up — and do not let it become a
  reason to stop building (§3).** Both tracks run at once.

---

## 12. Validation Plan

Who to contact (see `DESIGN_PARTNER_SPRINT.md`, `PILOT_VALIDATION_PLAN.md`,
`CUSTOMER_DISCOVERY.md`):

- California **PCAs / crop consultants** (licensed advisers who already document recommendations).
- **Packer / exporter** food-safety or compliance managers (audit and residue risk at scale).
- **Specialty-crop growers / farm managers** (strawberry, greenhouse tomato).
- **UC Cooperative Extension / ag advisors.**

The ask:

- Run **5–10 redacted historical spray/scouting records** through the prototype (concierge
  import — we transcribe, no integrations).
- Have it identify **PHI/REI, resistance, scouting-gap, and audit/documentation pain**.
- Determine **who the buyer is** and **willingness to pay** (per-acre / per-grower / per-PCA-seat).

`DESIGN_PARTNER_SPRINT.md` is the executable version: an exact partner profile, three hypotheses
each with a pass threshold **and a kill criterion**, a 20-minute no-pitch call script, a
data-availability checklist mapped field-by-field to models that already exist, and a five-stage
pilot ladder where a lower stage may never make a higher stage's claim.

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
- Interest only in features they will not pay for.

---

## 14. Known Weaknesses (Brutal)

- **No real validation yet** (§11). This is the big one.
- **The core engine is rule-based, not ML** — easy to dismiss as "just a spreadsheet." The answer
  is the audit trail, the authority gating, and the refusal discipline, not a claim of AI.
- **Label coverage is two products on one operator-run farm.** On demo farms and any real pilot
  farm, PHI/REI still come from user-entered values and every label-dependent check reports it did
  not run. Honest claim: "Lumos can check against verified label data, and does for the products
  transcribed so far" — never "Lumos checks your sprays against the label." Coverage is a
  data-entry and labour question, not a code one.
- **Only the strawberry use of each label is transcribed**, so
  `registered_crops_transcription_complete` is False and crop registration correctly abstains.
  Do not set that flag without transcribing the full crop list — a false block would end a PCA's
  trust permanently.
- **No leaf-wetness measurement yet**, so the Botrytis assessment abstains on
  `no_leaf_wetness_or_accepted_proxy` and grade-A evidence is unreachable. CIMIS publishes no
  wetness item, and deriving one from humidity is refused because the derivation itself needs a
  cited source. **This is now a purchase we are allowed to make (§4) — make it.**
- **Thresholds and coefficients are untranscribed** across fourteen empty sources. Every model
  over them refuses. Honest, but it means most of the platform computes nothing today.
- **No MRL reference data** — destination-market law, a different source from the label layer.
- **Tenant isolation is not implemented.** There is no auth, only attribution strings plus the
  operator key and PCA credentials. The Strix pentest found a cross-farm attribution path (fixed
  in `b195713`), which is the concrete evidence this is now a real gap rather than a deferred
  nicety. §4 permits building it.
- **No CIMIS credential** — the adapter ships inert and the leaf-wetness finding was verified from
  documentation rather than a live call.
- **`disease_risk.evidence_grade` treats an unstated station distance as *close*** and can reach
  GRADE_A, contradicting the CSV importer's warning. Pinned by test, deliberately unfixed
  (`DATA_PLATFORM.md` §6). Only bites hand-entered CSV weather; decide before a real pilot enters
  any.
- **Incumbents** may cover parts (FieldView-style platforms, PCA software, ag ERPs).
- **Data-entry burden** — someone has to log sprays and scouting; unclear who, in practice.
- **Unclear buyer** and low willingness-to-pay from individual growers.

---

## 15. Recommended Next Work

Ordered by leverage. Run the commercial track (§12) in parallel — it is not a prerequisite.

1. **Unblock L1, the measurement substrate.** Everything else is gated on it.
   - **Transcribe `app/botrytis_thresholds.py`** from the primary source. The arithmetic is
     implemented and tested against synthetic tables; this is a reading task, and it turns the
     opportunity scan's reason histogram into real band counts.
   - **Buy and integrate a leaf-wetness sensor.** Now permitted (§4). It is the single measurement
     standing between the product and grade-A Botrytis evidence.
   - **Get a CIMIS AppKey** and re-verify the leaf-wetness catalogue finding against `/api/data`.
   - **Transcribe more labels** — coverage is the difference between "the checks can run" and
     "the checks ran on your farm."
2. **L2 — make vision cumulative.** Today it suggests one scouting note per photo. Pressure over
   time, per block, admissible to the engine as evidence, is the version that changes a decision.
   The `AiJudgment` log and the `ScoutingSample` model already exist to hold it.
3. **L3 — targeted-application prescriptions.** A per-zone treatment plan exported to equipment
   the grower already owns is the most direct line from this codebase to the RFS thesis, and it is
   pure software.
4. **L4 — biologicals as decision options**, with the same label, provenance, and refusal
   discipline as conventional chemistry.
5. **Tenant isolation**, when a multi-grower PCA engagement is real. The primitives exist; the
   pentest finding is the motivation.
6. **Land one design partner** (`DESIGN_PARTNER_SPRINT.md`). Five qualified PCA conversations, one
   real anonymized dataset, one completed scorecard, quoted answers on controlled deferral and on
   who pays. No code.

---

## 16. How Future Claude Should Behave

- **Read this file first**, then open only what the task needs.
- **Default to building** when the §3 build test passes. Say which rung the work advances. If it
  fails the test, say which of the three conditions failed and what would fix it — do not refuse
  on general caution, and do not treat ambition as a red flag.
- **Attach the honesty mechanism as you build, not afterwards.** New value that could be missing?
  Give it a `Refusal` with a code. New number a human will act on? Give it provenance and a
  citation. New surface? Make the wrong thing *inexpressible* rather than merely discouraged —
  that technique (`RiskAssessment` with no action field, `FORBIDDEN_KEY_SUBSTRINGS`) is this
  codebase's best idea.
- **Reach for the empty-source pattern when data does not exist.** Build the structure, ship the
  table empty, refuse until a human transcribes it. That is how to move fast without lying.
- **Verify, do not remember.** Re-run `pytest` and report the real count; check the running app,
  not just the tests. A recurring failure mode here has been *docs describing capabilities the UI
  could not reach* — three real delivery gaps were found by auditing the running app end to end
  (`epa_reg_no` missing from the primary form; the weekly report containing no decision data; a
  CORS bug no backend test could see). Audit the surface, not the description.
- **Match the surrounding code style**, keep changes focused, and prefer a test for logic changes —
  the pure modules (engine / analytics / weather / pilot_evidence / label_data / disease_risk) are
  unit-testable in isolation by design.
- **Preserve the §4 hard guardrails and the §9–§10 tone.** They are the moat, not the friction.
- **Check the blinding before touching a decision payload** — adding anything to the PCA-facing
  surface breaks the shadow study (§5).
- At the end of a task, **summarize files changed, commands run, and real results** — including
  failures. After major work, leave a compact restart prompt for the next session.
