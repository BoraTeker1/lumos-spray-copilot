# Transcription tasks

**Every one of these is a reading task, not a build task.** The code is finished; the
numbers are absent. Each module below ships EMPTY, every model over it returns a refusal
naming the reason, and each becomes live the moment someone transcribes a primary
document into it — with no other code change.

This is the deliverable that converts the 2026-08-07 build into usable software.

> Generated from `app/ingest/domains.py::empty_sources()`. The live version is
> `GET /internal/transcription-status`, and `tests/test_cross_layer_routes.py` asserts
> this list and that endpoint cannot diverge.

---

## The rule, before anything else

**Transcribe from a primary document, with its citation. Never recall a plausible value,
and never search for one to paste in.**

This is not fussiness. It is the single defence that exists here, because:

- A plausible coefficient **passes every test anyone would think to write.** There is no
  unit test that catches a made-up nitrogen removal rate or a made-up credit weight. The
  arithmetic is correct either way; only the citation distinguishes them.
- The feedback loop is far too slow and too noisy to attribute. A wrong soil threshold
  surfaces as a disappointing yield eight months later, alongside twenty other variables.
- Several of these numbers carry legal weight. A fabricated credit weight is an invented
  assessment of a real person's creditworthiness; a fabricated advance rate misstates a
  lender's exposure; a fabricated nitrate figure generates real regulatory exposure in
  California.

`transcription.Citation` is frozen, keyword-only, and has **no defaults** for `document`,
`publisher`, `section`, `snippet`, `transcribed_by` or `transcribed_on`. A row missing any
of them raises at import. `snippet` must be **verbatim** — a paraphrase is a second
transcription step with no record of the first.

**If you cannot find the document, leave the table empty.** An empty table produces an
honest refusal. A filled one produces a confident wrong answer.

---

## Agronomy (Phase 2)

| Module | What to read | Who has it |
|---|---|---|
| `backend/app/soil_thresholds.py` | The regional extension interpretation guide the farm's own lab or advisor already uses (e.g. a UC ANR publication for CA specialty crops): analyte, **extraction method**, crop, class boundaries. | The grower's agronomist almost certainly names one — transcribe *that* one. |
| `backend/app/nutrient_tables.py` | A published crop nutrient removal guide: nutrient, crop, removal per unit of harvested yield, and the **yield basis** the figure assumes. | UC ANR or the lab that issues their soil reports. |
| `backend/app/variety_table.py` | The breeder's published variety description or a university variety trial report: variety, trait, rating, **rating scale**, and **trial conditions**. | Breeder / extension trial reports. Marketing copy is not a trial. |
| `backend/app/irrigation_coefficients.py` | A published Kc curve: growth stage, days-after-planting range, Kc value. | FAO-56, UC ANR, or the farm's irrigation advisor. |

**Traps specific to these four:**

- **Soil:** Bray-P and Olsen-P are different assays producing different numbers for the
  same soil. A threshold transcribed from a Bray guide and applied to an Olsen result is
  wrong in a direction nothing in the output reveals. `method` is required for this reason.
- **Nutrients:** removal per tonne of *fresh fruit* and per tonne of *dry matter* differ by
  roughly an order of magnitude. `yield_basis` is required.
- **Varieties:** a resistance rating is relative to its trial's conditions. "Resistant" in
  Watsonville under overhead irrigation ≠ "resistant" in Florida under plasticulture.
  `seed_selection.compare()` refuses to call ratings comparable across scales or conditions.
- **Kc:** varies through the season by a factor of two or more. A mid-season value applied
  at establishment substantially overstates water use, so `irrigation.balance()` refuses
  rather than borrowing an adjacent stage's coefficient.

---

## Finance (Phase 4) — all eight require a counterparty, not a search

| Module | What to read | Who has it |
|---|---|---|
| `backend/app/scorecard_table.py` | The lender's published or contractually supplied **credit scorecard**: factor list, per-factor weights, score bands, score range. | A lending partner, in writing. |
| `backend/app/underwriting_rules.py` | The lender's **written credit policy**: eligibility rules, minimum score, exposure limits, required evidence, exclusions — each with its section. | Same lending partner. |
| `backend/app/collateral_valuation.py` | The lender's **collateral schedule**: eligible asset classes, advance rates, and the valuation basis each rate assumes. | Same lending partner. |
| `backend/app/monitoring_covenants.py` | The **covenant schedule** from an executed facility agreement: covenant, measure, threshold, direction, reporting frequency, breach consequence. | Same lending partner, post-signature. |
| `backend/app/financing_terms.py` | The lender's **product sheet**: product, purpose, amount range, term, currency, and the cost disclosure **in the lender's own wording**. | Same lending partner. |
| `backend/app/insurance_products.py` | The insurer's **published product terms**: perils, eligible crops, coverage basis, exclusions, required claim evidence. | A crop insurer. |

**The constraint that makes this layer defensible: Lumos executes a scorecard and evaluates
a policy. It does not author either.** If a lender cannot supply these documents, the
correct outcome is that the finance layer keeps refusing — not that someone designs a
scorecard so the demo has a number in it.

Two things are deliberately **never** transcribed:

- **No premium rates** into `insurance_products.py`. Pricing a policy from yield and
  weather history is underwriting wearing a different word. Coverage is matched, never
  priced.
- **No structured APR** into `financing_terms.py`. `disclosed_cost_summary` is the
  lender's verbatim sentence, because a structured rate invites an amortisation schedule,
  and a schedule computed by Lumos is money math on a real debt.

---

## Market (Phase 5)

| Module | What to read | Who has it |
|---|---|---|
| `backend/app/price_series.py` | A **reported** commodity price series: commodity, market, grade, price, currency, unit, and the date observed. | USDA AMS terminal market reports; a cooperative's settlement sheets. |
| `backend/app/futures_curve.py` | An exchange's **published daily settlements** for the relevant contract months. | CME / ICE settlement files. |

**Traps:** a price a grower mentioned on a call is a data point about that conversation,
not a market price. A broker's indicative quote is not a settlement. And note that
`pricing.latest()` refuses anything outside its freshness window rather than falling back
to the last known value — a stale price and a fresh one look identical on screen, and a
grower deciding whether to sell this week would be wrong for a reason nothing showed them.

---

## Still empty from an earlier cycle

| Module | Status |
|---|---|
| `backend/app/botrytis_thresholds.py` | `TRANSCRIBED_TABLE = None`. **Not filled by this build, deliberately** — `BOTRYTIS_PILOT.md` §3 forbids recalling or searching for these coefficients. The arithmetic (`BotrytisWetnessV1.evaluate`) is implemented and tested against synthetic tables; transcription is the only remaining step. Filling it activates the whole snapshot → assessment → opportunity-scan chain with no other change. |
| `backend/app/label_table.py` | **Partially filled** (2 products, strawberry use only). Not part of this cycle. |

---

## How to verify a transcription landed correctly

```bash
cd backend && source .venv/bin/activate

# The worklist, live
python -c "
from app import transcription
from app.ingest import domains
for key, mod in domains.empty_sources():
    s = transcription.status_of(mod, title=domains.get(key).title)
    print(f'{\"FILLED\" if s.populated else \"empty \"}  {mod}  ({s.row_count})')
"

# The suite will TELL YOU that you filled one — several tests assert emptiness on
# purpose, so that transcribing a source is a deliberate, reviewed event rather than a
# silent change. Update those assertions when the citation checks out.
pytest tests/test_finance_layer.py tests/test_soil.py tests/test_agronomy.py \
       tests/test_market_layer.py tests/test_ingest_registry.py -q
```

A filled source makes its model start returning values instead of refusals — which will
show up immediately at `GET /farms/{id}/profile`, where that layer moves out of
`blocking_gaps` and into `available_layers`.
