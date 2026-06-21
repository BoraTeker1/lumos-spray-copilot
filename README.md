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
1. See the two seeded farms on the dashboard.
2. Open **Green Valley Greenhouse** → generate a recommendation → it flags **elevated** risk
   (PHI risk + repeated active ingredient + high-severity scouting).
3. Open **Sunrise Tomato House** → recommendation suggests **inspect first** (weak evidence).
4. Add a spray event or scouting note and regenerate to see the recommendation change.
5. Build the **weekly report** and copy it for WhatsApp.

## Scope (MVP)
**In:** spray & scouting logging, rule-based cautious recommendations, cost tracking, weekly
report. **Out (deliberately):** financing, marketplace, IoT/drones, autonomous "must spray"
advice, definitive disease diagnosis, authentication. See `ENGINEERING_GUIDELINES.md`.
