# ENGINEERING_GUIDELINES.md — Lumos Spray Copilot

Guidance for any AI assistant or developer working in this repo. Read this before writing code.

## Product goal
Help **greenhouse tomato growers and agronomists reduce unnecessary pesticide sprays**, avoid
pre-harvest-interval / residue risk, track pesticide cost, and generate **cautious,
agronomist-reviewable** spray recommendations.

This is a deliberately narrow slice of the broader Lumos precision-farming vision documented in
`docs/`. See `MVP_SPEC.md` for the full product brief.

## What to build
- A FastAPI backend with SQLite storage for **Farms**, **SprayEvents**, **ScoutObservations**,
  and **Recommendations**.
- CRUD endpoints for farms, spray events, and scouting observations.
- A **rule-based recommendation engine** that flags spray-related risks cautiously.
- An endpoint that generates and stores a recommendation for a farm.
- Seed data for two greenhouse tomato farms.
- Unit tests for the recommendation engine.
- A simple Next.js + Tailwind frontend: dashboard, farm list, farm detail, add-spray form,
  add-scouting form, recommendation panel, and a copy-able weekly report.

## What NOT to build
- ❌ No financing / revenue-sharing / credit features.
- ❌ No marketplace / supplier integrations.
- ❌ No IoT / sensors / drones / hardware / external weather integrations.
- ❌ No autonomous "you must spray" recommendations.
- ❌ No claims of perfect or definitive disease diagnosis.
- ❌ No authentication in v1 (but keep code structured so it can be added later).
- ❌ Do not over-engineer. Prefer the simplest thing that works and demos well.

## Tone & safety rules for recommendations
Recommendations are **decision support, not prescriptions**. Always:
- Use cautious language: *"consider," "inspect first," "review with your agronomist,"
  "risk appears elevated."*
- Keep an agronomist in the loop — every recommendation starts as `pending`.
- Never instruct a farmer to spray, and never claim a definitive diagnosis.

## Tech stack
- **Backend:** FastAPI, SQLAlchemy, SQLite, Pydantic, pytest.
- **Frontend:** Next.js (App Router, JavaScript), Tailwind CSS.
- **AI layer (v1):** deterministic rule engine in `backend/app/recommendation_engine.py`.
  LLM summaries are a later milestone.

## Coding standards
- **Python:** PEP 8, 4-space indent, type hints on function signatures, snake_case. Keep
  business logic (the rule engine) free of FastAPI/SQLAlchemy imports so it is easy to unit
  test in isolation. Pydantic schemas (`schemas.py`) are separate from ORM models (`models.py`).
- **Layering:** routes (`main.py`) → `crud.py` (DB access) → `models.py` / `schemas.py`. The
  recommendation engine takes plain Python objects and returns a plain result; the route layer
  persists it.
- **JS/React:** functional components, hooks, Tailwind utility classes, small focused files.
  Keep API calls in a single `lib/api.js` helper.
- **Config:** API base URL configurable via `NEXT_PUBLIC_API_URL` (default
  `http://localhost:8000`).
- **Future auth:** keep request handlers thin and avoid global mutable state so an auth
  dependency can be injected later.

## Milestone plan
- **Milestone 1 (done):** models, CRUD, recommendation engine + endpoint, seed data, engine
  unit tests, and the basic frontend listed above.
- **Milestone 2 (done):** agronomist review workflow (approve/edit/reject + comment, report
  gated to approved/edited), farmer-facing next-action card, pesticide cost analytics
  (`app/analytics.py`), lightweight weather-risk module (`app/weather.py` with a swappable
  `WeatherService` + mock demo data), and an upgraded WhatsApp weekly report.
- **Milestone 3 (later):** LLM weekly summaries, photo upload, basic auth, live weather API.

## How to run (quick reference)
- Backend: `cd backend && python -m venv .venv && source .venv/bin/activate &&
  pip install -r requirements.txt && python -m app.seed && uvicorn app.main:app --reload`
- Tests: `cd backend && pytest`
- Frontend: `cd frontend && npm install && npm run dev`
