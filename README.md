# Lumos Spray Copilot

AI-assisted, **agronomist-in-the-loop** spray-decision support for greenhouse tomato growers.
It helps growers reduce unnecessary pesticide sprays, avoid pre-harvest-interval / residue
risk, track pesticide cost, and produce a cautious, reviewable recommendation plus a
copy-pasteable weekly report.

This is a narrowed MVP of a broader precision-farming vision.
See **[MVP_SPEC.md](MVP_SPEC.md)** for the product brief and **[ENGINEERING_GUIDELINES.md](ENGINEERING_GUIDELINES.md)** for
build guidance, scope boundaries, and the milestone plan.

> This is the public engineering repository. Commercial and go-to-market material
> (positioning, customer-discovery notes, pilot outreach) is kept in a separate private
> repo, so a few documents referenced in passing below are not present here.

## U.S. pilot positioning
**Lumos starts as an AI-assisted pesticide decision and compliance copilot for specialty crops,
with agronomist/PCA-in-the-loop approval.** First U.S. wedge: **California specialty-crop growers
(strawberries, greenhouse tomatoes) + their PCAs/agronomists** — fewer unnecessary sprays, fewer
PHI/REI mistakes, cleaner audit-ready records. We are the **decision/compliance layer before the
spray** — not a sprayer, robot, drone, or farm OS, and explicitly **not** competing with John
Deere See & Spray or row-crop hardware.

> ⚠️ The recommendation engine is **decision support, not a prescription**. It never tells a
> farmer to spray and never claims a definitive diagnosis.

## Project structure
```
precision_farming/
├── backend/                 # FastAPI + SQLAlchemy + SQLite
│   ├── app/
│   │   ├── main.py                  # FastAPI app & routes
│   │   ├── database.py              # engine / session / Base
│   │   ├── models.py                # ORM models
│   │   ├── schemas.py               # Pydantic schemas
│   │   ├── crud.py                  # DB access layer
│   │   ├── recommendation_engine.py # rule-based engine (no framework deps)
│   │   └── seed.py                  # seed 2 greenhouse tomato farms
│   ├── tests/test_recommendation_engine.py
│   └── requirements.txt
├── frontend/                # Next.js (App Router) + Tailwind
│   ├── app/                 # dashboard + farm detail pages
│   ├── components/          # forms, recommendation panel, weekly report
│   └── lib/api.js           # single API client
├── MVP_SPEC.md
└── ENGINEERING_GUIDELINES.md
```

## Run the backend
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m app.seed                 # load 2 demo greenhouse tomato farms
uvicorn app.main:app --reload      # http://localhost:8000  (docs at /docs)
```

Run the engine unit tests:
```bash
cd backend
source .venv/bin/activate
pytest
```

## Run the frontend
In a second terminal (keep the backend running):
```bash
cd frontend
npm install
npm run dev                        # http://localhost:3000
```

The frontend talks to `http://localhost:8000` by default. To point elsewhere, copy
`.env.local.example` to `.env.local` and set `NEXT_PUBLIC_API_URL`.

## What you can do in the demo
1. See the two seeded farms on the dashboard (risk badge + pesticide spend per farm).
2. Open **Green Valley Greenhouse** → see **cost analytics** and **weather risk** → generate a
   recommendation → **Elevated** risk with next action *"Harvest timing risk — review before
   picking"* (PHI risk + repeated active ingredient + high-severity scouting).
3. As an agronomist, **Approve / Edit / Reject** the recommendation and add a comment.
4. Build the **weekly report** and **Copy for WhatsApp** (only approved/edited guidance is shared).
5. Open **Sunrise Tomato House** → **Low risk — continue monitoring** (the healthy contrast).

Full timed walkthrough: see **[DEMO_SCRIPT.md](DEMO_SCRIPT.md)**. What the seed data means:
**[DEMO_DATA.md](DEMO_DATA.md)**.

## Real Pilot Evidence Loop (V1)

Lumos can now ingest **real PCA spray-decision records** and produce defensible,
confirmed-vs-estimated pilot evidence:

1. **CSV import** (`POST /farms/{id}/import/csv`, templates at
   `GET /import/templates/{planned_sprays|scout_observations}.csv`) — dry-run
   validation first (column mapping with correctable aliases, per-row errors/warnings,
   in-file + against-DB duplicate detection). Nothing is written until committed.
2. **Field-level provenance** — every compliance-critical value (product identity, EPA
   reg. no., rate, PHI, REI, dates, AI, MoA group) is stored as an append-only
   `DecisionInputValue` chain with a source type (`demo / user_entered /
   imported_unverified / pca_verified / authoritative_provider`). Imported values are
   **never silently verified** and can **never produce an automatic APPROVE** — they
   escalate to PCA review.
3. **Immutable audit history** — creation, reviews (including structured field edits
   that supersede values and re-run the decision), outcomes, and follow-ups each
   append a `DecisionAuditEvent`. History is never overwritten.
4. **Mandatory follow-up timeline** — non-as-planned outcomes require append-only
   `DecisionFollowUpEvent`s (scouting, actual/rescue applications, harvest and
   yield/quality outcomes). *A planned avoidance is not a confirmed reduction until
   follow-up is recorded*; yield/quality stay **unknown** until someone records them.
5. **Confirmed vs. estimated metrics** (`GET /farms/{id}/decision-evidence`) — strictly
   separated, non-demo records only, failures (rescues, negative net results) reported
   plainly; pesticide-mass and risk-weighted reductions are shown as **"not
   calculated"** rather than guessed.
6. **Anonymized evidence export** — `GET /farms/{id}/evidence-export` (JSON) and
   `GET /farms/{id}/export/evidence.csv`. The farm appears only as `pilot-farm-{id}`;
   demo records are excluded by construction; a correlation-not-causality statement
   and methodology travel with every export.

**Operating mode (V1 = concierge pilot):** the founder/operator runs the import;
records should be anonymized *before* upload; there is no customer login.
**Customer-facing production use would additionally require:** authentication, tenant
isolation, backups, and a data-security review — none of which exist in this build.

Target-name matching uses exact normalized names or an explicit alias dictionary
(`backend/app/target_aliases.py`) only — ambiguous overlaps escalate to PCA review and
are recorded; equivalence is never fuzzily inferred.

## AI-Driven Layer (V1)

Real AI (Claude) now works **around** the deterministic engine — **AI proposes, the
engine + PCA decide**. The compliance verdict stays 100% deterministic; AI never says
"spray" and never names products. Without `ANTHROPIC_API_KEY` everything falls back to
a deterministic mock (demo/tests work offline); calls are on-demand only.

- **Document/message extraction** (`POST /farms/{id}/import/document`): a PDF, photo,
  or pasted PCA email/WhatsApp becomes draft import rows — extracted only as literally
  written (regulatory values are never guessed), each row with a verbatim source
  snippet, abstaining on non-recommendation input. Rows flow through the **same**
  dry-run validation as the CSV import, get human-corrected, and commit via
  `POST /farms/{id}/import/rows` as `ai_extracted` + `imported_unverified` — so they
  can never auto-approve.
- **AI review brief** (`POST /planned-sprays/{id}/ai-brief`): a qualitative
  rescue-risk note grounded ONLY in comparable real decisions on the same farm (alias/
  chemistry matched, demo excluded) plus next actions enum-locked to **evidence
  gathering only**. Below 2 real comparables a server-side guard forces abstention —
  no fabricated probabilities.
- **Append-only AI judgment log + calibration** (`GET /internal/ai-calibration`):
  every AI output is logged with model, prompt version, input digest, confidence, and
  abstention; predictions are joined to realized rescue outcomes from follow-ups, with
  rates gated behind a minimum-n (counts + "insufficient data" until then). Judgments
  are never seeded or fabricated.

## Scope (MVP)
**In:** spray & scouting logging, rule-based cautious recommendations, next-action guidance,
agronomist review workflow, pesticide cost analytics, lightweight weather-risk, weekly report.
**Out (deliberately):** financing, marketplace, payments, IoT/drones, chatbots,
autonomous AI decisions or "must spray" advice, definitive disease diagnosis,
authentication. (AI exists only as suggest-and-confirm layers around the deterministic
engine — photo scouting, document extraction, review briefs.) See `ENGINEERING_GUIDELINES.md`.

---

## 🚜 Pilot Mode checklist

A short operational checklist for running Lumos in front of, or with, a real grower.

### Run it locally
```bash
# Terminal 1 — backend
cd backend && source .venv/bin/activate
python -m app.seed                 # only the first time / when you want demo data
uvicorn app.main:app --reload      # http://localhost:8000

# Terminal 2 — frontend
cd frontend && npm run dev          # http://localhost:3000
```
Tests (run before any demo): `cd backend && source .venv/bin/activate && pytest` → expect **212 passing**.

### Reset demo data (clean slate)
```bash
cd backend && source .venv/bin/activate
python -m app.seed                 # wipes farms/sprays/scouting/recommendations, reloads the 2 demo farms
```
If the schema ever looks stale, delete the DB and re-seed: `rm -f backend/lumos.db && python -m app.seed`.
Tip: re-seed **right before** a live demo so your "Generate" and "Approve" clicks look fresh.

### Add a REAL farm (during a pilot)
1. Dashboard is read-only for creation in the UI; create the farm via the API (or `/docs`):
   ```bash
   curl -X POST localhost:8000/farms -H 'Content-Type: application/json' \
     -d '{"name":"<grower name>","location":"Antalya, Türkiye",
          "greenhouse_area":3000,"expected_harvest_date":"2026-08-15"}'
   ```
   (Interactive form: open **http://localhost:8000/docs** → `POST /farms`.)
2. Open the farm in the UI and log their **real sprays** ("Log spray event") and
   **scouting notes** — enter active ingredient, cost, and pre-harvest interval honestly.
3. Click **Generate recommendation**, then have the **agronomist approve/edit** it.
4. ⚠️ This is a **local single-user demo build** — no auth, SQLite only. Don't store data you
   wouldn't want on that laptop; treat real grower data as confidential.

### Export / copy the weekly report
- In the farm page: **Weekly report → Build report → Copy for WhatsApp**, then paste into chat.
- Or fetch the text directly:
  ```bash
  curl -s localhost:8000/farms/1/weekly-report | python3 -c "import sys,json;print(json.load(sys.stdin)['text'])"
  ```

### What NOT to claim during demos
- ❌ It does **not** diagnose disease — it flags pressure cautiously.
- ❌ It does **not** tell anyone to spray — it never says "must spray."
- ❌ No **guaranteed savings** — only *"potential avoidable cost if one unnecessary spray is prevented."*
- ❌ No financing, marketplace, payments, drones, IoT, sensors, or AI vision — none of that exists here.
- ✅ Always frame it as **cautious decision support with an agronomist in the loop.**
