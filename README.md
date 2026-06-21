# Lumos Spray Copilot

AI-assisted, **agronomist-in-the-loop** spray-decision support for greenhouse tomato growers.
It helps growers reduce unnecessary pesticide sprays, avoid pre-harvest-interval / residue
risk, track pesticide cost, and produce a cautious, reviewable recommendation plus a
copy-pasteable weekly report.

This is a narrowed MVP of the broader Lumos precision-farming vision (see `docs/`).
See **[MVP_SPEC.md](MVP_SPEC.md)** for the product brief and **[ENGINEERING_GUIDELINES.md](ENGINEERING_GUIDELINES.md)** for
build guidance, scope boundaries, and the milestone plan.

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
├── docs/                    # original startup background material
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
**[DEMO_DATA.md](DEMO_DATA.md)**. Interviewing growers: **[CUSTOMER_DISCOVERY.md](CUSTOMER_DISCOVERY.md)**.

## Scope (MVP)
**In:** spray & scouting logging, rule-based cautious recommendations, next-action guidance,
agronomist review workflow, pesticide cost analytics, lightweight weather-risk, weekly report.
**Out (deliberately):** financing, marketplace, payments, IoT/drones, computer vision,
complex AI, autonomous "must spray" advice, definitive disease diagnosis, authentication.
See `ENGINEERING_GUIDELINES.md`.

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
Tests (run before any demo): `cd backend && source .venv/bin/activate && pytest` → expect **41 passing**.

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
