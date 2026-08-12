# DATA_PLATFORM.md — the data-intelligence layer

Companion to `ENGINEERING_GUIDELINES.md`. Read `ENGINEERING_GUIDELINES.md` §3/§4 first; this document assumes them.

Seventeen data domains are **declared**. One has a working adapter. Eight are deferred to
a finance phase that does not exist, and each of those names the guardrail that defers it.
This file exists so that "we declared seventeen and built one" is a checkable statement
rather than a claim in a slide.

---

## 1. What this layer did and did not do

It closed a **software** gap and made a **procurement** gap visible. It did not produce a
risk band, and it did not create demand evidence.

```
BEFORE:  assessment abstains — no_weather_in_window, thresholds_not_supplied
AFTER:   assessment abstains — no_leaf_wetness_or_accepted_proxy, thresholds_not_supplied
```

`no_weather_in_window` was a software gap: `WeatherObservation` existed and nothing ever
wrote to it. That is now closed — a registered adapter, a scheduler, and an eight-stage
pipeline write real readings with real provenance.

The remaining two blockers are **not** code:

| Blocker | What it actually is | Who resolves it |
|---|---|---|
| `no_leaf_wetness_or_accepted_proxy` | CIMIS publishes no leaf-wetness item | a sensor purchase |
| `thresholds_not_supplied` | `BotrytisWetnessV1`'s coefficients are deliberately absent | a transcription task (`BOTRYTIS_PILOT.md` §3) |

Two vague blockers became two named, measured, farm-specific facts. That is the honest
claim. **Never write that this layer reduced pesticide use, or that it unblocked the
Botrytis assessment.**

Per `ENGINEERING_GUIDELINES.md` §15: this raised capability and created **no buyer evidence**. §3 and §11
are unchanged — zero confirmed pilots, zero customer decisions.

---

## 2. The CIMIS finding (verified 2026-08-05)

**CIMIS does not report leaf wetness.**

Verified on 2026-08-05 against the published hourly data-item catalog for the CIMIS Web
API (`et.water.ca.gov/Rest/Index`, cross-checked against the `cimir` R package and the
Python-CIMIS client documentation). The complete hourly item list is:

```
hly-air-tmp    hly-soil-tmp   hly-rel-hum    hly-eto      hly-asce-eto
hly-asce-etr   hly-sol-rad    hly-net-rad    hly-wind-spd hly-wind-dir
hly-res-wind   hly-precip     hly-dew-pnt    hly-vap-pres
```

There is no wetness item. This was verified from documentation, **not** from a live API
call — no CIMIS AppKey was available. Re-verify against `/api/data` when one is obtained.

### The derivation we refuse to make

Leaf wetness can be approximated from relative humidity. **This adapter does not, and
must not.** `app/disease_risk.py` accepts no proxy because the derivation would itself
need a cited source, and inventing one here would be the same failure as guessing the
Botrytis coefficients — one layer down, and worse, because a derived number arriving with
`wetness_is_measured` set would look like a measurement.

Enforced by `tests/test_ingest_cimis.py::test_the_recorded_payload_carries_no_leaf_wetness_and_the_adapter_invents_none`
and by `tests/test_features.py::test_no_weather_feature_reads_relative_humidity`.
**Never delete either.**

`leaf_wetness_minutes` is written as `None`. `wetness_is_measured` is written as `None`
too, **not `False`** — `False` asserts "we have a wetness value and it is derived", which
is also untrue.

---

## 3. The seventeen domains

Declared in `app/ingest/domains.py`; served at `GET /internal/ingestion/sources`.

### MVP (9)

| Domain | Adapter | Notes |
|---|---|---|
| `climate` | **`cimis_hourly`** | The only implemented adapter. Gated on `LUMOS_CIMIS_APP_KEY`. |
| `crop_protection` | — | Richest data already held; the work is derived features, not ingestion. |
| `crop` | — | Crop cycles live in the entity spine. |
| `soil` | declared, unbuilt | A lab report is a document; that path already exists. |
| `fertilization` | — | Declared so the operation type has a home. |
| `land_selection` | — | Parcels and tenure are in the spine. |
| `seed_selection` | — | Variety resistance is a real lever; held on the crop cycle. |
| `market` | declared, unbuilt | **MRL data stays out of scope** (`ENGINEERING_GUIDELINES.md` §4, §14). |
| `energy` | — | Declared for completeness; nothing computes it. |

### Deferred to the finance phase (8)

Each cites the clause that defers it. `ENGINEERING_GUIDELINES.md` §4 unless marked.

| Domain | Cited clause |
|---|---|
| `financing` | "real lending" |
| `credit_scoring` | "credit scoring" |
| `underwriting` | "automated underwriting" |
| `insurance` | "automated underwriting" — pricing a policy from yield and weather history is underwriting under another name |
| `collateralization` | "money movement of any kind" |
| `hedging` | "money movement of any kind" |
| `pricing` | "commission-based quote ranking" |
| `monitoring` | §3: "Stop building product unless a validation need directly requires it" |

### Declaring is provably not building

Three mechanisms, none of them prose:

1. **`test_no_future_finance_domain_owns_an_implementable_source`** — a source under a
   deferred domain must have status `deferred_to_finance_phase`, and `build_adapter`
   raises for every one. The failure message quotes §4 back at the author.
2. **`features.base.register()` refuses a non-MVP domain.** `debt_service_capacity` and
   its relatives cannot be *registered*, so they cannot be scheduled, computed, stored or
   rendered. Pinned by `test_a_feature_in_a_deferred_finance_domain_cannot_be_registered`.
3. **`test_every_deferred_domain_cites_the_clause_that_defers_it`** — each citation must
   still appear in the ENGINEERING_GUIDELINES.md section it names, catching drift in *either* direction:
   a guardrail quietly reworded, or a domain quietly un-deferred. The comparison
   normalizes whitespace, because §4 is hard-wrapped and "credit scoring" spans a line
   break.

### A guardrail this work sits against

`ENGINEERING_GUIDELINES.md` §4 lists "drones / IoT / sensors / hardware / **weather-station hookups**",
and notes that "live weather" is a gated Milestone-3 idea. §4's preamble permits these
"unless the user explicitly instructs it in this session" — which is what happened. Noted
here rather than quietly relied on. CIMIS is a public agency API, not hardware and not an
IoT integration; **on-site sensors remain out of scope**, which is precisely why leaf
wetness is still unavailable.

---

## 4. The eight stages

`app/ingest/pipeline.py`. Every stage reuses something rather than reimplementing it.

| # | Stage | Reuses | Refusal behaviour |
|---|---|---|---|
| 1 | fetch | `storage.store_document(KIND_RAW_INGESTION)` + a `Document` row | `describe().can_fetch` is checked FIRST; a credential-less adapter is never asked to fetch |
| 2 | parse | the adapter | unreadable response → issue, empty row list |
| 3 | validate | **`csv_import.validate_rows(RECORD_TYPE_WEATHER)`** | per-row errors → issue, row dropped |
| 4 | normalize | `units.convert` | a `units.Refusal` drops the row and records **no number** |
| 5 | align | `geo.haversine_km` vs the field centroid | **no centroid → row dropped**, never a NULL distance |
| 6 | resolve | the operator-stated `IngestContext` | an unrequested station is an issue, never a silent join |
| 7 | dedupe | `csv_import.duplicate_key_for_weather` + `pit.digest_of` | same digest → duplicate; different → correction with `supersedes_id` |
| 8 | persist | `crud.create_weather_observations_bulk` | `ensure_demo_real_separation` once per batch |

**Stage 3 is the one worth defending.** Handing provider rows to the same validator the
concierge CSV import uses means an ingested reading is held to an identical contract —
same aliases, same required fields, same typed coercion, same per-row errors. There is no
second, weaker path into the weather table. It is called *without* `existing_keys`,
because that flag cannot tell a repeat from a correction; against-DB dedupe is stage 7's
job, where a value digest can.

**Stage 5 is the one that is easy to get wrong.** `disease_risk._weather_problems` treats
`station_distance_km is None` as *in range*, and `evidence_grade` filters `None` out of
the distance list and then reads the empty list as *close*. That is tolerable for a human
leaving one cell blank and dangerous for a machine writing 24 rows a day. So a row we
cannot place is dropped with `no_field_geolocation`, never written with a null.

### Issues are recorded, never raised

A bad hour must not lose a 720-row backfill, and "we dropped this reading and here is
why" is part of the evidence. This mirrors the risk snapshot, which records an exclusion
reason rather than silently filtering.

### Idempotency, two layers

* **Job level** — `queue.enqueue(..., idempotency_key=f"ingest:{source}:{farm}:{station}:{bucket}")`.
  A live job with that key is returned rather than duplicated.
* **Row level** — the partial unique index on `(farm_id, station_id, observed_at) WHERE
  supersedes_id IS NULL`, plus a value digest over the fields that carry meaning.

So `IngestionRun` needs no unique index, and the testable property is stronger than
"enqueue is idempotent": **re-running any window changes nothing**
(`test_rerunning_the_same_window_persists_nothing_new`).

### What an ingested row looks like

| Column | Value | Why not something else |
|---|---|---|
| `source_type` | `station_export` | already in the vocabulary; nothing wrote it before |
| `data_source` | `provider_api` | `manual_entry` would be a false claim about who entered it |
| `data_confidence` | `provider_reported` | `pca_reviewed` would be a lie with legal weight |
| `station_distance_km` | haversine, 2 dp | never null — the row is dropped instead |
| `leaf_wetness_minutes` | `None` | CIMIS has no such item |
| `wetness_is_measured` | `None` | `False` would assert a derived value exists |
| `quality_flag` | the station's QC flag when not a pass | `pit.admissible` then excludes the row |
| `recorded_at` | **ingest time** | see below |
| `ingestion_run_id` | the run | a join, not a string in `source_reference` |

`data_source` and `source_type` are BOTH set because two different guards read different
columns: `pit.is_demo` reads `data_source`/`data_confidence`, while
`disease_risk._weather_problems` reads `source_type`. A writer that set only one would
pass one guard and fail the other.

### `recorded_at` on a backfill is ingest time

Never back-dated to `observed_at`. Stamping a 30-day backfill with the observation time
would assert we knew a month ago what we learned today — the exact hindsight leak
`app/pit.py` exists to prevent.

**The consequence is uncomfortable and correct: backfilled history is admissible only for
`as_of` values after the backfill ran, so a backtest over that window finds no admissible
weather.** Asserted by
`test_recorded_at_is_ingest_time_and_is_never_backdated_to_observed_at`.

### Subscriptions are configuration, not a table

`LUMOS_CIMIS_SUBSCRIPTIONS="farm_id:field_id:station_id,..."` plus the task payload. A
`WeatherStationSubscription` table is the eventual right answer and is a table-per-noun
with one row today. Stated here rather than built, so the decision is visible.

---

## 5. The feature catalog

`app/features/`. Every feature abstains rather than defaulting.

**The invariant** (`FeatureResult.__post_init__`): a result is abstained **if and only
if** it has no value, and an abstention must carry reasons. There is no "abstained but
here is a number anyway" state, so a card can never render an abstention as `0`. An
abstention's payload omits the `value` key entirely rather than nulling it — a null in a
numeric field is exactly what a template turns into `0` or `--`.

| Feature | Entity | Unit | Abstains when |
|---|---|---|---|
| `weather_observation_coverage_pct` | field | pct | no station configured. **Returns a legitimate `0.0`** when a station *is* configured and returned nothing — the one place a zero is not a lie |
| `weather_data_staleness_hours` | field | h | no admissible weather. Never a large number meaning "none" |
| `leaf_wetness_hours` | field | h | no measured wetness; **or** any row carries wetness with `wetness_is_measured=False`. **Abstains permanently on CIMIS-only data — that is the point** |
| `active_ingredient_kg_per_ha` | crop_cycle | kg/ha | **any** application refuses, naming which; no planted area; no applications |
| `moa_rotation_diversity` | crop_cycle | ratio | **any** application has a null `moa_group`; or n < 2 |
| `scouting_recency_days` | block | d | no sample. Reports the number only — no stale/fresh verdict |

### Why two features are all-or-nothing

Both refusals are **bias** arguments, not purity arguments.

`active_ingredient_kg_per_ha`: a total omitting three of eleven applications is not
approximate, it is **smaller**. A reader has no way to know, and the error runs in the
flattering direction on a pesticide-reduction number.

`moa_rotation_diversity`: the applications most likely to be missing a MoA group are the
carelessly logged ones, which are disproportionately repeat sprays of a familiar product
— exactly the ones that would drag diversity down. Scoring the recorded subset reports
*better rotation than reality*, on a resistance-management number.

On today's data `active_ingredient_kg_per_ha` abstains for nearly every farm, because
only two products have a transcribed label concentration. Naming *which* applications
blocked it makes that a work item rather than a dead end.

### The hindsight rule reaches spray records

`pit.admissible` needs `observed_at` and `recorded_at`. `SprayEvent` has neither — it has
`application_date` and `created_at`, which *are* those two timestamps, spelled
differently. `features/pit_view.py` adapts rather than migrating: backfilling a
`recorded_at` column would fabricate a claim about when something was known.

**A spray keyed in on Friday about Tuesday is excluded from a Wednesday `as_of`.** This
will occasionally surprise someone. It is correct: a pesticide-use figure that includes
applications entered after the fact is not one anyone could have acted on.

### `feature_values` is a leak detector

Fully unique on `(entity_type, entity_id, name, version, as_of)` — no supersede chain,
unlike every observation table. Because `pit.admissible` excludes anything recorded after
`as_of`, **recomputing at a fixed `as_of` must reproduce the identical `inputs_digest`
forever**. A differing digest is therefore proof that an input became visible which
should not have been. `compute.persist` leaves the stored row untouched and records the
disagreement, rather than overwriting and destroying the only evidence it happened.

---

## 6. Known issues

### `station_distance_km` grading contradiction (open)

`csv_import.py:697-701` warns a user that leaving station distance blank means "the
evidence grade cannot reach its highest level". `disease_risk.evidence_grade` does not
implement that:

```python
distances = [r["station_distance_km"] for r in rows if r.get("station_distance_km") is not None]
close = not distances or max(distances) <= (MAX_STATION_KM / 3.0)
```

With every distance unstated, `distances` is empty and `close` is **True** via `not
distances`. An all-unstated payload is graded as *close* and can reach GRADE_A. The
importer promises a conservatism the engine does not provide.

**Deliberately not fixed in this slice.** Changing `evidence_grade` alters the pilot's
scoring contract, which is outside this work. Current behaviour is pinned by
`test_all_unstated_distances_are_graded_close` so it cannot drift silently. The ingest
path is unaffected either way, because stage 5 always sets a distance or drops the row —
the exposure is limited to hand-entered CSV weather on a real pilot farm.

Decide it before the first real pilot enters weather by CSV.

### Provisional gates

`disease_risk.MAX_STATION_KM = 15.0` and `MAX_GAP_HOURS = 3` remain **PROVISIONAL**. They
need the pilot farm's actual station configuration and are not calibrated by this work.

---

## 7. Operating it

### Surfaces

| Route | Audience | Notes |
|---|---|---|
| `GET /farms/{id}/data-readiness` | grower / PCA | **Not** operator-gated. Each measure is `{value,unit}` XOR `{abstained,reasons}` — never a null `value`. Carries a server-owned `basis_text`; `DataReadinessCard` renders it verbatim and writes no wording of its own |
| `GET /internal/ingestion/sources` | operator | The 17-domain table + every source's status and blocker → `DomainRegistryTable` |
| `GET /internal/ingestion` | operator | Runs with counts and issues → `IngestionCard` |
| `POST /internal/ingestion/{source}/run` | operator | **Enqueues; never fetches inline.** Retries, dead-lettering and stall recovery live in the worker, and a route that fetched directly would be a second execution path with none of them |

Nothing was added to the PCA-facing decision surface (`PreSpraySheet`, `/decisions/[id]`).
A risk-shaped field there would break the shadow study's blinding.

```bash
# Every declared source and the domain table governing it (operator-key gated)
curl -H "X-Lumos-Operator-Key: $LUMOS_OPERATOR_KEY" localhost:8000/internal/ingestion/sources

# Run the worker once. With no credential this is INERT: no network call, and each run
# is recorded as skipped_no_credential.
python -m app.jobs.worker --once --queues default,ingest,features

# Enable the adapter
export LUMOS_CIMIS_APP_KEY=...                     # free, from et.water.ca.gov
export LUMOS_CIMIS_SUBSCRIPTIONS="4:1:111"         # farm:field:station
```

**A subscription without a field centroid ingests nothing.** Every row will be dropped
with `no_field_geolocation` — set `Field.centroid_lat`/`centroid_lon` first. This is
deliberate (see stage 5) but looks like a broken feed if you have not read this section.

Schema changes go through Alembic. Rehearse on a **copy** of `lumos.db` first; never the
real file — and note the variable name, because getting it wrong silently rehearses on
the real database:

```bash
cp lumos.db /tmp/rehearse.db
LUMOS_DATABASE_URL="sqlite:////tmp/rehearse.db" alembic upgrade head   # NOT DATABASE_URL
```

`alembic/env.py` resolves the URL through `app.database`, so `alembic.ini`'s
`sqlalchemy.url` is ignored and so is a bare `DATABASE_URL`. Two further traps, both hit
on 2026-08-06: SQLite DDL here is **non-transactional**, so a migration that fails
halfway leaves its already-created tables behind and the retry dies with "table X
already exists" — drop them before re-running. And in `batch_alter_table`, the table is
rebuilt on block exit, so a data `UPDATE` touching a newly added column must be issued
**after** the block, not inside it.

---

## 8. Deferred

| Deferred | Why |
|---|---|
| Live CIMIS capture | No AppKey yet. Fixtures are hand-authored and say so in their own `_provenance` block |
| Postgres / PostGIS | SQLite is not the constraint yet |
| `EntityLink` | Resolution here is deterministic — the operator names farm, field and station, so there is no ambiguity to record |
| `WeatherStationSubscription` table | One row today; env-var config is honest about that |
| soil / market / price adapters | Declared, unbuilt, no validated need |
| All 8 finance-phase domains | `ENGINEERING_GUIDELINES.md` §4 |
| MRL data | Destination-market law, not label law, and a different source (§4, §14) |
| Botrytis threshold coefficients | A transcription task from a primary source (`BOTRYTIS_PILOT.md` §3) — never recalled, never searched for |
