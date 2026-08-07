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

- **No persistence for the new layers.** There is no `CreditAssessment`,
  `UnderwritingDecision`, `CollateralRegistration`, `InsurancePolicy` or
  `PortfolioMonitoringSnapshot` table. Results are computed on read and not stored, so
  there is no append-only history of what was assessed when. **This must exist before
  any real assessment is shown to a counterparty** — "what did you know when you declined
  me" is a question with legal weight, and `credit_scoring.Score.inputs_digest` was built
  to answer it but currently has nowhere to live.
- **No marketplace persistence.** `Supplier`, a catalog wired to the orphaned
  `InputProduct` table, and `RfqTransmission` were planned and not built. Procurement
  remains the concierge workflow described in §5 of `ENGINEERING_GUIDELINES.md`: no suppliers, no
  catalog, no transmission.
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
