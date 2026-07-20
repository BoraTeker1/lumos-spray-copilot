# Botrytis Deferral Shadow Pilot — V1

Conventional strawberries, California Central Coast. This document is the pilot's
contract: what it claims, what it refuses to claim, and what has to be true before any
number leaves this repo.

---

## 1. The hypothesis

> A licensed PCA can safely defer a scheduled Botrytis fungicide application by 24–72
> hours when disease pressure is low, and Lumos can identify those occasions well
> enough to be worth paying for.

It is stated so it can fail. The pilot is designed to detect failure, not to
accumulate supporting anecdotes.

**What V1 actually does:** it collects trustworthy prospective evidence about that
question. It does not answer it, and it is not a model.

---

## 2. What Lumos does and does not do here

**Does:**

- Freezes what was knowable at each decision moment (`app/risk_snapshot.py`).
- Runs a versioned, explainable rule over that snapshot, or abstains
  (`app/disease_risk.py`).
- Records the licensed PCA's decision, attributed and with a mandatory reason.
- Records what was actually executed, and per-block outcomes at harvest.

**Does not, and structurally cannot:**

- **Recommend a pesticide.** `RiskAssessment` has no product, rate, tank-mix or action
  field. A recommendation is not forbidden by policy — it is inexpressible.
- **Declare a deferral safe.** The bands are `low | moderate | high | abstain`. `low`
  is a band, not a safety statement. There is no "safe" value anywhere.
- **Decide anything.** The compliance verdict stays with the deterministic engine; the
  spray decision stays with the PCA, whose legal responsibility is unchanged.
- **Use an LLM in this path.** No language model is consulted about disease risk. There
  is no call site for one. (The photo card, document extraction and review brief are
  real AI, and are separate features — see ENGINEERING_GUIDELINES.md §5.)

**AI proposes. Deterministic rules and the licensed PCA decide.**

---

## 3. The state of the rule: it abstains

`botrytis_wetness_v1` is registered, versioned, tested — and returns
`ABSTAIN("thresholds_not_supplied")` on every input. Its coefficients are **absent on
purpose.**

Every test that can be written about a threshold rule checks the arithmetic *against*
the constants, never the constants themselves. So a plausible-looking cut point
recalled from memory or lifted from a search result would pass the entire suite, and
would then sit in a versioned, cited module that a PCA is entitled to trust. The
threshold table gets transcribed from the primary source — author, year, coefficients,
and the source's crop, region and validation conditions recorded verbatim — or the rule
keeps abstaining.

Adding it later is a one-function change. The plumbing and the tests already exist.

**And once supplied, it stays honest.** The known strawberry Botrytis advisory work is
Florida-based. `local_validation_status` therefore reads:

> published rule; NOT validated for California Central Coast strawberries — no local
> outcome data exists yet

and `calibration_status` stays `not_calibrated` until prospective outcomes exist.

---

## 4. Blinded shadow mode

The PCA **never sees a risk assessment** during V1.

This is enforced structurally: `is_shadow` defaults True, and a shadow assessment is
omitted from every PCA-facing serializer — absent from the payload, not hidden in the
UI. The only surface that returns one is `GET /internal/pilot/assessments`, behind the
operator key.

**Why:** a PCA who has seen a model's risk band can no longer provide an independent
baseline. Blinded, their decisions are exactly the comparison the rule must eventually
beat. It also means the pilot deliberately does *not* learn whether a PCA would act on
a brief — that is open question Q2, and it should be asked in conversation rather than
inferred from contaminated data.

Unblinding is a dated, protocol-versioned event (`PilotProtocol.unblinded_at`), never a
config toggle or an environment variable. A farm with no protocol can never drift out
of shadow, a future date does not unblind early, and assessments already written stay
shadow — unblinding does not rewrite history.

---

## 5. Measurement definitions

The distinction the pilot most easily gets wrong, stated plainly:

| Metric | Meaning | Status |
|---|---|---|
| Application count change | Fewer passes on this block in this window | **Countable** |
| Seasonal pesticide use | Season-total change | **NOT calculated** |
| Active-ingredient mass | Kg of AI avoided | **NOT calculated** |

Deferring one spray pass is a change in application count for those decisions. It is
**not** a season-total reduction — the spray may recur later, and a rescue treatment
may exceed what was avoided — and it is **not** a reduction in active-ingredient mass.
These three are never allowed to be read as one another; the reasons live verbatim in
`pilot_evidence.NOT_CALCULATED`.

**Units are data, never assumed.** `treated_acres` is acre-named but not
acre-guaranteed (it predates `Farm.area_unit`), so `treated_area_unit` records what the
number actually is. `pilot_evidence._sum_treated_area` refuses to total a mixed-unit set
and says why; a missing unit stays unspecified and is never assumed to be acres. **No
conversion table exists and none is fabricated.**

**Ground truth is standardized scouting, actual pesticide-use records, rescue
treatments, and harvest/packout outcomes — never PCA agreement.** A PCA agreeing with
the rule is not evidence the rule is right.

**Evidence separation** is structural: demo/simulated inputs are excluded from
snapshots by construction, one farm is wholly demo or wholly real, every
compliance-critical value carries a `source_type`, and the export filters to real
decisions. Mock model output is never presented as model performance.

---

## 6. Data model

| Model | Purpose | Mutability |
|---|---|---|
| `Block` | The comparison unit | Mutable metadata |
| `WeatherObservation`, `ScoutingSample` | Decision-time evidence | Append-only, supersede to correct |
| `RiskInputSnapshot` | What was knowable at `as_of` | **Immutable** |
| `DiseaseRiskAssessment` | A versioned rule's output | **Append-only**, shadow by default |
| `PcaDisposition` | The PCA's judgement | **Append-only**, attributed, anchored |
| `PilotProtocol` | Which rules the result is read under | Versioned |
| `BlockAssignment` | Arm per block | Never edited — new version instead |
| `BlockOutcomeObservation` | Per-block, per-harvest outcomes | **Append-only** |

Four facts about four moments are kept strictly separate, and this is the pilot's
central design commitment:

1. `decision_*` — what the deterministic engine concluded
2. `review_*` — whether a PCA cleared it
3. `PcaDisposition` — what the PCA judged should happen
4. `outcome` — what actually happened

A disposition never writes a `decision_*` or `review_*` column. `defer` does not unlock
an applied outcome and does not satisfy a required review. A pilot that cannot
distinguish "the rule said defer" from "the PCA chose to defer" from "the spray was in
fact deferred" measures nothing.

---

## 7. Operating the pilot

### One-time setup (operator, ~30 min)

```bash
export LUMOS_OPERATOR_KEY=<a real secret>     # required once real data exists
unset LUMOS_DEMO_TODAY                        # confirm /health says clock_mode: real
```

1. Create the pilot farm **fresh**. Never reuse a demo farm — the mixing guard will
   409, and it should. Set `area_unit`.
2. Create blocks with area, `area_unit`, planting and expected-harvest dates.
3. `/internal` → Botrytis shadow pilot → issue the PCA a credential. **Record the raw
   token immediately; it is shown once and is never retrievable.**
4. Authorize that credential for the farm.
5. Record the `PilotProtocol` (version, assignment method, primary metric).
6. Record `BlockAssignment` rows. **Randomization is performed offline** — a
   spreadsheet and a seed — and the seed is stored so it stays reproducible.

### Weekly (farm manager, ~10 min)

Import weather and standardized scouting samples via `PilotImportCard`: dry-run →
review the report → commit. Both are append-only; a correction is a new row with
`supersedes_id`, never an edit.

### Per scheduled Botrytis spray (PCA, ~5 min)

1. Create the planned spray against the block.
2. A snapshot is taken — this freezes the evidence at the decision moment.
3. Open `/decisions/{id}`, read the deterministic verdict.
4. Record a disposition with a mandatory reason.

**The PCA will see no risk score. Explain this upfront**: V1 measures whether the rule
*would have been* right, and a PCA who has seen the score can no longer provide that
baseline.

### After the spray window (farm manager)

Record the outcome (`sprayed_as_planned` / `delayed` / `avoided` / …) with quantities
where known, and complete the required follow-up.

### Per harvest (farm manager)

Record `BlockOutcomeObservation` rows per block: disease incidence, rescue treatments,
packout, cull, cost. A value always needs its unit.

### What the PCA must be told before enrolling

- Lumos does not recommend pesticides and does not declare deferrals safe.
- Their review remains legally mandatory and completely unchanged.
- The rule is not validated for CA Central Coast strawberries and currently abstains
  by design.
- They will not see risk output during the blinded phase, and why.
- No claim will be published from this pilot until the evidence gate below is met.

---

## 8. Before any reduction claim

All of the following, or the number is not published:

- [ ] Threshold table transcribed from the primary source, with citation
- [ ] Prospective outcomes recorded for a pre-agreed minimum n
- [ ] Assignment method is `randomized` or `matched` — `observational` cannot support a
      causal claim, and the reporting module will refuse one
- [ ] Follow-up completion is high enough to state
- [ ] No demo, simulated or mock-sourced record in any aggregate
- [ ] `calibration_status` is no longer `not_calibrated`
- [ ] The claim names the metric precisely: application count, **not** seasonal
      pesticide use, **not** active-ingredient mass

Deferred to a later milestone: `app/pilot_results.py`, the headline-safe gate, the
evidence-export `pilot` block, and calibration metrics (Brier, log loss, calibration
curve, **false-negative rate in the `low` band** — the metric that matters for safety).
Those are needed before the first *claim*, not before the first *decision*.

---

## 9. Open questions

Blocking a real pilot:

- **B1** — the threshold source table (§3).
- **B2** — what weather data the farm actually has: on-site station, CIMIS,
  third-party, or nothing? Is leaf wetness *measured* or derived (which caps evidence
  grade at B/C)? `MAX_STATION_KM` / `MAX_GAP_HOURS` in `disease_risk.py` are
  provisional and cannot be chosen in the abstract.
- **B3** — the PCA's action threshold for Botrytis: incidence %, severity index, or a
  qualitative call? The system must never invent one.
- **B4** — is block-level randomization operationally acceptable, or will the grower
  refuse to leave control blocks unsprayed?

Answerable only by real users:

- Who is the buyer — the independent PCA firm, the grower, or the packer carrying
  residue/audit risk?
- **Would a PCA ever act on a deferral recommendation at all**, given they carry legal
  liability for the written recommendation? Blinded shadow deliberately does not answer
  this. If the answer is no, the hypothesis fails and no model work rescues it — ask
  directly, in parallel with building.
- What packout/cull data exists, at what granularity, and who owns it? Without it the
  pilot measures only spray counts.
- Does an audited deferral record change the PCA's liability posture, and how does this
  interact with CA DPR reporting?
- Minimum n and duration — needs expected incidence and effect size from the PCA or
  extension.

---

## 10. Known limitations

- No pesticide label / PHI / REI / MRL database. Regulatory values are user-entered and
  never guessed. The architectural seam for label data exists (`authoritative_provider`
  source type, `verified_label` authority tier — both defined, both unused); the
  database is not built.
- No tenant isolation. The operator key is a deployment interlock, not auth
  infrastructure: no login, no session, no password, no user table.
- Lumos does not verify PCA licences. It records the identifier an operator enters;
  `pca_authority.attribution()` always reports `license_verified_by_lumos: False`.
- `recorded_at > as_of` is enforced once, in `risk_snapshot.admissible`, and cannot be
  re-verified downstream because `recorded_at` is deliberately not serialized into the
  snapshot payload.
- The pilot is single-target and single-crop by design.
