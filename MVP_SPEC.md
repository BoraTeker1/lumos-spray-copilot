# Lumos Spray Copilot — MVP Spec

## One-line summary
An AI-assisted, agronomist-in-the-loop spray-decision workflow that helps greenhouse
tomato growers reduce unnecessary pesticide sprays, avoid pre-harvest interval / residue
risk, and track pesticide cost — while keeping all recommendations cautious and
human-reviewed.

## Why we narrowed the scope
The original Lumos vision (see `docs/`) is a broad agri-fintech platform: precision farming
advisory + IoT/sensors/drones + a product marketplace + embedded revenue-sharing finance.
That is too large and too capital-intensive to validate now. This MVP isolates the single
slice with the clearest pain, fastest path to a demo, and real commercial relevance:
**spray decisions for greenhouse tomatoes.**

Pesticide use in greenhouse tomato production is frequent, costly, and tightly regulated by
**pre-harvest intervals (PHI)** and **maximum residue limits (MRL)**. Growers often spray on
a calendar/habit basis rather than on evidence, which wastes money, builds resistance, and
risks unsellable (residue-rejected) fruit. A simple tool that flags these risks and produces
an agronomist-reviewable recommendation is immediately useful.

## Target users
- **Greenhouse tomato growers** — log sprays and scouting, get cautious guidance, share a
  weekly summary.
- **Agronomists / advisors** — review, approve, edit, or reject recommendations before they
  reach the grower.

## Core jobs to be done
1. Keep a clean record of pesticide spray events (product, active ingredient, dose, cost, PHI).
2. Keep a record of scouting observations (what was seen, how severe).
3. Get a **cautious, evidence-based recommendation** that flags real risks instead of
   prescribing sprays.
4. Track pesticide spend per farm.
5. Produce a copy-pasteable **weekly report** (e.g. for WhatsApp) to share with the grower.

## What the recommendation engine does (v1 — rule-based)
The engine reviews a farm's recent sprays and scouting and raises cautious flags. It **never**
tells a farmer they "must spray." Rules:

1. **Over-use of an active ingredient** — if the same active ingredient was applied too
   frequently in a recent window, flag possible resistance/over-application risk.
2. **Pre-harvest interval (PHI) risk** — if the expected harvest date falls within any recent
   spray's PHI window, flag residue risk and advise reviewing harvest timing with an agronomist.
3. **High-severity scouting** — if there is a recent high-severity observation, flag elevated
   pest/disease pressure and suggest agronomist review.
4. **Weak evidence → inspect first** — if signals are weak or absent, recommend inspecting/
   scouting first rather than acting.

Output language is always cautious: *"consider," "inspect first," "review with your
agronomist," "risk appears elevated."* Recommendations carry a `risk_level`
(`low` / `moderate` / `elevated`) and start in `agronomist_status = pending`.

## Explicit non-goals (do NOT build in this MVP)
- ❌ Financing / revenue-sharing / credit scoring
- ❌ Product marketplace / supplier integration
- ❌ IoT / sensors / drones / hardware / weather-station integrations
- ❌ Autonomous "you must spray" prescriptions
- ❌ Claims of perfect / definitive disease diagnosis
- ❌ Authentication (v1) — but structure code so it can be added later

## Tech stack
- **Backend:** FastAPI + SQLAlchemy + SQLite
- **Frontend:** Next.js (App Router) + Tailwind CSS
- **AI layer (v1):** deterministic rule-based recommendation engine. LLM-generated natural
  language summaries are a later enhancement, not part of v1.

## Data model (summary)
- **Farm** — name, location, crop_type, greenhouse_area, planting_date, expected_harvest_date
- **SprayEvent** — product_name, active_ingredient, pesticide_class, target_pest_or_disease,
  dose, application_date, cost, pre_harvest_interval_days, notes
- **ScoutObservation** — observation_date, crop_stage, visible_issue, severity_1_to_5,
  image_url_optional, notes
- **Recommendation** — created_at, risk_level, recommendation_text, agronomist_status,
  agronomist_comment

## Milestone plan
- **Milestone 1 (this build):** data models, CRUD for farms / spray events / scouting,
  recommendation generation endpoint, seed data for 2 greenhouse tomato farms, unit tests for
  the engine, and a simple Next.js dashboard (farm list, farm detail, add-spray form,
  add-scouting form, recommendation panel, copy-able weekly report).
- **Milestone 2 (later):** agronomist review workflow UI (approve/edit/reject), pesticide
  cost analytics, MRL/active-ingredient reference data.
- **Milestone 3 (later):** LLM-generated weekly summaries, optional photo upload, basic auth.

## Definition of done for Milestone 1
- Backend runs locally, all CRUD + recommendation endpoints work, tests pass.
- Frontend runs locally and can list farms, open a farm, add a spray, add a scouting note,
  generate a recommendation, and copy a weekly report.
