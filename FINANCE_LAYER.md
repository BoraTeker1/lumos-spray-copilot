# Finance, market and agronomy layers — the contract

Companion to `DATA_PLATFORM.md`. Read this before touching anything under the domains
admitted on 2026-08-07. The worklist that makes any of it produce a number is
`TRANSCRIPTION_TASKS.md`.

---

## 1. What was built, and what was deliberately not

An explicit instruction admitted the eight deferred finance/market domains and asked for
the full three-layer business idea, using the **empty-source pattern**. So:

**Built:** the structure, the workflows, the arithmetic, the refusals, the tests, and the
surfaces that reach them.

**Not built, and not an oversight:** the numbers. Every scorecard weight, advance rate,
covenant threshold, removal rate, crop coefficient, price point and settlement is absent.
Each model returns a `Refusal` naming why, and each becomes live when a human transcribes
a primary document with its citation — with no other code change.

**Not permitted, and unchanged by the admission:**

| Still forbidden | Why, and how it is enforced |
|---|---|
| Money movement of any kind | No payment, disbursement, repayment or amortisation. There is no `funded`/`disbursed`/`repaid` state anywhere, and no structured APR — `financing_terms.disclosed_cost_summary` is the lender's verbatim sentence, because a rate invites a schedule and a schedule is money math on a real debt. |
| A Lumos-authored scorecard, policy, advance rate or covenant | Each lives in an empty transcription source. Lumos *executes* a lender's scorecard and *evaluates* their policy; it authors neither. |
| An `approved` underwriting outcome | The enum is `conditions_met \| conditions_not_met \| referred_to_human`. Pinned by `test_underwriting_has_no_approved_outcome`. |
| An estimated insurance premium | `CoverageProduct` carries no rate and `CoverageAssessment` has no field for one. Pricing a policy from yield history is underwriting wearing a different word. |
| Advice to take/close a market position | `HedgeCoverage` has no action field — structurally inexpressible, like `disease_risk.RiskAssessment` and spray prescriptions. |
| Commission-based quote ranking | Unchanged from the procurement module. Quotes stay in entry order. |
| Hardware | Leaf wetness still requires an on-site sensor; the Botrytis assessment still abstains on it. |

---

## 2. The six patterns every module follows

Lifted from what already worked here; consistency is what makes seventeen modules a
system rather than a pile.

1. **Pure and framework-free.** No FastAPI/SQLAlchemy imports. Enforced over all 27
   modules by `test_every_pure_model_module_imports_no_framework`. The reason is not
   tidiness: *these modules decide refusals, and one that can reach a database can fetch
   the thing it should refuse about — turning a refusal into a silent fallback.*
2. **An EMPTY transcription source as a sibling module.** `credit_scoring.py` ↔
   `scorecard_table.py`. Frozen, kw-only, no provenance defaults.
3. **`Result | Refusal`, never a default.** `app/refusal.py`. A `Refusal` has no `value`
   field and cannot grow one without changing that class.
4. **Abstention ≠ zero.** Derived values go through `features/base.py`, whose invariant
   is `abstained ⟺ no value` and whose `as_payload()` omits the `value` key entirely.
5. **Consequential acts are append-only and attributed.** (Applies to the persistence
   layer — see §5 for what is not yet built.)
6. **Forbidden claims are blocked by test.** `test_finance_layer.py` walks every payload
   for `approved`/`funded`/`premium`/`apr`/… — the `backtest.FORBIDDEN_KEY_SUBSTRINGS`
   technique.

---

## 3. The directional rules, and why each points the way it does

Every refusal in this layer is asymmetric. These are the ones where the *direction* of
the error is the whole argument, and where a later "simplification" would be wrong:

| Rule | If you got it backwards |
|---|---|
| **Credit score is all-or-nothing** (`credit_scoring.score`) | A scorecard is a weighted sum. A missing factor contributes zero points, so a partial score reads as a *worse borrower*, not an incomplete assessment. Someone is declined because a soil test was never uploaded. |
| **Nutrient budget is all-or-nothing** (`fertilization.budget`) | A budget missing a nutrient still reads as a complete answer to the question that was asked. |
| **Soil interpretation is per-analyte** (`soil.interpret`) | The deliberate exception. Nothing is summed, so a partial panel understates nothing — each answered analyte is still correct alone. Do not "make it consistent" with the two above. |
| **No advance-rate default** (`collateral`) | 100% understates lender exposure; 0% denies collateral the borrower holds. Both look like arithmetic, and they point opposite ways — there is no conservative fallback. |
| **Unevaluated ≠ passed** (`underwriting`) | A policy where two of five rules could not be checked would read as "3 passed", and an unchecked condition ships. |
| **Nothing-checked ≠ compliant** (`monitoring`) | A two-value status enum has nowhere to put "we could not look", so the unchecked case falls into whichever value is the default — and the one that reads well is `compliant`. Hence three values. |
| **No stale-price fallback** (`pricing`) | A three-week-old price and a fresh one are both just a number with a currency symbol. The grower acts on it and is wrong for a reason the screen never showed. |
| **Undated lease ≠ perpetual** (`land_selection`) | An absent end date means *indefinite* for ownership and *unrecorded* for a lease. Conflating them claims land is held through a horizon nobody has evidence for — and that claim flows into collateral and underwriting. |
| **No irrigation log ≠ zero water** (`features/agronomy`) | Both produce an empty list. Inferring would report every farm without an irrigation log as running entirely on rainfall. Hence the explicit `records_irrigation` argument. |
| **Extraction method is part of a soil threshold** | Bray-P and Olsen-P are different assays. A Bray threshold applied to an Olsen result is wrong in a direction nothing in the output reveals. |

---

## 4. Surfaces

| Route | Audience | Notes |
|---|---|---|
| `GET /farms/{id}/profile` | Grower | Every layer's result or refusal, side by side. `gaps_by_owner` splits what a grower can fix from what needs an operator to read a document. No overall score — an average across layers that mostly abstain is meaningless, not merely rough. |
| `GET /internal/transcription-status` | Operator | The worklist. Generated from `domains.empty_sources()`, so a domain admitted later cannot be forgotten. |

**Nothing was added to the PCA-facing decision surface.** The Botrytis shadow study
depends on the reviewing PCA not seeing model output; a cross-layer card on
`/decisions/{id}` would break the blinding. Pinned by
`test_the_profile_is_absent_from_the_pca_decision_surface`.

---

## 5. What is NOT built — read this before assuming

Being explicit, because the gap between "the model exists" and "a pilot can use it" is
exactly the delivery-gap failure §5 of `ENGINEERING_GUIDELINES.md` records:

- ~~No persistence for the new layers.~~ **Built 2026-08-07 (third pass)** —
  `CreditAssessment`, `UnderwritingDecision`, `CollateralAsset`, `MonitoringSnapshot`
  and `CoverageAssessment`, all append-only. See §8 below.
- ~~No marketplace persistence.~~ **Built 2026-08-07 (second pass)** — `Supplier`,
  `SupplierProduct` (the catalogue, which finally gives `InputProduct` its first
  reference), `RfqTransmission`, plus `supplier_id` on quotes and `input_product_id` on
  quote lines. See §7 below. What remains unbuilt there: no supplier-facing portal, and
  no transport actually sends (`rfq_transport.describe()` reports `can_send: false` on
  every deployment).
- **No frontend for any of it.** `/soil`, `/fertilization`, `/finance`, `/market` do not
  exist. The two routes above are reachable only via the API.
- **No collateral or soil input path.** `crud.list_collateral_assets` and
  `crud.list_soil_readings` return `[]` and say so in their docstrings — no table holds
  either. A soil report arrives as a document today and nothing reads it.
- **`expected_yield_tonnes` returns None.** `CropCycle` has no expected-yield column, and
  `crop_cycles` holds zero rows.

---

## 6. Honest status

Capability rose across three layers. **Buyer evidence did not move at all.** This is the
fifth consecutive cycle of capability-up / evidence-flat that `ENGINEERING_GUIDELINES.md` §15 names as the
pattern to be skeptical of rather than encouraged by.

Verified on today's data: **every layer refuses, and every single gap is operator-owned** —
because each model checks its transcription source before it checks farm data, and all
eight sources are empty. No amount of grower activity unblocks any of this. What unblocks
it is a lending partner, an insurer, and a few afternoons of reading.

Still zero pilots. Still zero customer decisions. `DESIGN_PARTNER_SPRINT.md` remains the
unstarted work that actually matters.

---

## 7. The marketplace layer (added 2026-08-07, second pass)

Procurement existed before this as a concierge workflow: an operator typed a supplier's
name as free text on each quote, and nothing linked one quote's `Switch 62.5WG` to
another's `Switch 62.5 WG`. Three tables turn that into a marketplace.

| Table | What it is |
|---|---|
| `Supplier` | A supplier as an entity. `SupplierQuote.supplier_name` is **kept and still authoritative** for what was entered; `supplier_id` is the structured link beside it — the same discipline as `SprayEvent.treated_acres` + `treated_area_unit`. Nullable, so a quote from an unregistered supplier still goes in rather than being blocked or attached to a guess. |
| `SupplierProduct` | The catalogue. **The first reference `InputProduct` has ever had** — it sat in `models.py` since the entity-spine phase with zero callers. Carries **no price**: a price belongs to a quote, at a moment, for a quantity; on a catalogue row it is a list price nobody quoted that goes stale invisibly. |
| `RfqTransmission` | Append-only record of an RFQ being sent. One row per intended recipient, **always** — including when nothing was sent. |

### Why the catalogue is the point

`procurement_analytics.build_report` groups price observations by **catalogue id, never
by name**. Grouping free text would report three spellings of one product as three
products with no spread each — which reads as *"prices are consistent"* when the truth is
*"we failed to group them"*. Unlinked lines are counted and excluded, and the count is
surfaced in the payload rather than swallowed, so the report never hides its own blind
spot.

`catalog_key` normalises casing and whitespace and **nothing else** — the same
exact-or-nothing rule as `target_aliases` and `crop_aliases`. Fuzzy-matching a fungicide
to a similar trade name is how a grower compares the price of two different chemistries.

### What "better buying power" means here, precisely

Price **dispersion**: how much the same catalogued product varied between the suppliers
who actually quoted it. Three refusals guard the three ways a spread can lie — fewer than
two quotes (zero spread reads as a competitive market), mixed units (needs a per-product
density `label_data.convert_rate` already refuses to invent), and mixed currency (needs an
FX rate with a date this system does not hold).

**Not** a saving, and **not** a recommended supplier. A grower may have good reasons to
buy above the lowest quote, and calling the difference a saving assumes they did not.
Observations stay in entry order; sorting by price would make it a ranking in everything
but name, and the no-ranking policy is a commitment about Lumos's incentives, not a UI
preference.

### RFQ transmission is real, recorded, and inert

`rfq_transport.describe()` copies the `ingest/cimis.py` contract exactly: the caller asks
before acting, so a deployment with no transport configured is inert **by construction**
and cannot email a real supplier by accident. Every row today reads
`skipped_no_transport`, which is the truthful record that an RFQ exists and did not leave
the building — previously that state was invisible, and a grower asking why nobody quoted
had nothing to look at.

Email transport is declared and **deliberately still unimplemented**: a defect there
emails real suppliers on a real grower's behalf, so the client should be written against
live credentials by someone who can test it end to end.

### Reachability

`test_the_catalog_link_is_reachable_from_the_quote_entry_schema` and
`test_a_catalogued_quote_line_enters_the_dispersion_end_to_end` exist because this layer
had the identical failure mode ENGINEERING_GUIDELINES.md §5 records for `epa_reg_no`: without
`input_product_id` on the quote-item schema, no line could ever be catalogued and the
whole layer would be decorative. **That gap was in fact present** on the first pass of
this build and caught by writing the end-to-end test.

---

## 8. Finance persistence (added 2026-08-07, third pass)

The decision models computed on read, so nothing survived the request.
`credit_scoring.Score.inputs_digest` was built to answer *"what did you know when you
declined me"* — a question with legal weight — and had nowhere to live. Five append-only
tables, migration `e5f5523df75d`.

| Table | Kind | Notes |
|---|---|---|
| `CreditAssessment` | output | One executed scorecard, or one recorded refusal. Carries `inputs_digest` and the scorecard identity **per row**. |
| `UnderwritingDecision` | output | `outcome` is never `approved`; `not_evaluated_rule_ids` is its own column. |
| `CollateralAsset` | **input** | Append-only with a supersede chain. Gives `crud.list_collateral_assets` real data — it returned `[]` with an explanatory docstring until now. |
| `MonitoringSnapshot` | output | `standing` is three-valued; `unknown` is reachable and common. |
| `CoverageAssessment` | output | No premium column exists. `missing_evidence` is the valuable field. |

### The invariant: outcome XOR refusal, and refusals are stored

`refusal_code IS NULL` **iff** the assessment produced a result — the same construction
as `FeatureValue` storing an abstention as `value IS NULL` + non-empty `reasons`.
Enforced in one place, `crud._outcome_columns`, which is the only point it could be
violated.

**Storing the refusal is the design, not an accident.** With no scorecard transcribed,
every row today is a refusal. A farm's history reading *"could not score: no scorecard
supplied, on these dates"* is materially different from that history being empty:

- Storing only successes makes the record set a **survivorship-biased** view of a farm —
  "we assessed you three times" when in truth we tried nine and could not answer six.
- A borrower asking why they were declined is entitled to see that no assessment was
  even possible.

### Append-only, by construction

No `PUT`, `PATCH` or `DELETE` route exists on any of the four assessment resources —
pinned by `test_assessments_have_no_update_or_delete_route`, which enumerates the live
route table rather than trusting a convention. A revaluation of a collateral asset
**supersedes** rather than edits, and `list_collateral_assets` excludes superseded rows
so a revaluation cannot double-count the same asset in a total.

### What is recorded per row, and why

The **scorecard identity** (`scorecard_lender`/`name`/`version`) is stored on each
assessment rather than referenced. A scorecard is transcribed from a lender document that
may be re-transcribed later; an assessment must stay readable against the card **as it
was when it ran**. The same reasoning `ProductLabelRecord` uses for append-only label
revisions.

### Gating

`POST` is operator-gated — recording an assessment is a consequential act about a real
person's farm. `GET` is **grower-facing**: "why was I declined" is their question, and
the refusal rows are the part they most need to see.

### A drift the migration tests caught

Adding `CollateralAsset` to `crud._FARM_RECORD_MODELS` (so a demo farm cannot accumulate
assets that look like real security) desynced the P0 backfill migration's table list.
The fix was **not** to edit that migration: it has already run on real databases, and
`collateral_assets` did not exist at its revision, so replaying it would fail on a
missing table. `ADDED_AFTER_BACKFILL` in `tests/test_schema_migrations.py` records the
exemption explicitly, with a reason, and a second test guards the exemption list itself
from going stale.

---

## 9. Frontend surfaces (added 2026-08-08)

| Surface | Where | Audience |
|---|---|---|
| `/finance` — credit, underwriting, collateral, covenants | nav (secondary group) | Grower |
| `FarmProfileCard` | farm detail | Grower |
| `TranscriptionStatusCard` | `/internal` | Operator |
| `PriceDispersionCard` | input-plan detail | Grower |

**Update 2026-08-10: `/finance` is UNLINKED from the nav** — reachable by URL, absent
from the product surface, like `/internal`. It sat in the secondary nav group on the
reasoning that a finance page in the primary group would misrepresent what this product
is; the stronger version of that argument removed it entirely. Three reasons, on the
record so this is not silently reverted:

1. It advances no rung on the `ENGINEERING_GUIDELINES.md` §3 build ladder — there is no finance rung.
2. It serves a **lender**, a party absent from the §1 buyer hypothesis, the §12
   validation plan, and the §13 signal list.
3. Its own write actions are operator-gated (`POST /internal/...`), so every button on
   this grower-facing page 403s unless an operator key was set on `/internal`. To a
   visitor the page reads as unfinished rather than as disciplined refusal.

Backend modules, routes, persistence and tests are **untouched and still passing**. The
standing decision is: re-link when a lender or insurer conversation is real, and delete
the layer outright if none happens.

**Every refusal renders "Not calculated" plus its reason** — never a `0`, never a dash in
a numeric slot, never a blank card. This is `DataReadinessCard`'s rule extended to the
new layers, and it is why the Finance page is *useful* today rather than empty: with no
lender document transcribed, the assessment history is entirely refusals, and a page that
filtered them would be blank and would imply nothing had happened.

### The CORS bug that only a browser could find

Verifying these pages in a real browser exposed a **two-part bug, latent since the
operator key shipped on 2026-07-20**, that the entire backend suite could not catch
because `TestClient` does not perform CORS:

1. **The gate 403'd the preflight.** A browser never sends custom headers on an
   `OPTIONS` preflight — the spec forbids it — so a preflight for any key-bearing
   request arrived with no `X-Lumos-Operator-Key` and was refused. The browser then
   never sent the real request. **Every `/internal` call from the UI failed with an
   opaque "Failed to fetch"**, on exactly the deployments where the key is mandatory
   (i.e. any database holding real records).
2. **The 403 carried no CORS headers.** The gate short-circuited *outside*
   `CORSMiddleware`, so the browser discarded the response — and with it the one message
   that tells an operator their key is missing or wrong.

Fixes: exempt `OPTIONS` from the gate (a preflight carries no credentials and returns no
data; the actual request is still gated), and register `CORSMiddleware` **last so it is
outermost**. **Middleware registration order in `main.py` is now load-bearing** and
commented as such.

Four regression tests in `tests/test_operator_key.py`, verified to fail without the fix.
Worth noting the pattern: this is the *third* delivery-gap-class defect this build
surfaced (missing `operatorHeaders()`, the absent `input_product_id` schema field, and
now CORS), and **all three were invisible to a green test suite**. The method that found
each was running the actual app.
