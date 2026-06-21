# Lumos Spray Copilot — 3-Minute Demo Script (Milestone 2)

A tight, repeatable script for demoing the MVP to a farmer, agronomist, or investor.
Milestone 2 adds: **next-action card, agronomist review workflow, pesticide cost analytics,
weather-risk card, and an upgraded WhatsApp report.**

---

## 0. Before you start (off-camera)

Open two terminals.

**Terminal 1 — backend:**
```bash
cd backend
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m app.seed                 # IMPORTANT: resets to a clean demo state
uvicorn app.main:app --reload      # http://localhost:8000
```

**Terminal 2 — frontend:**
```bash
cd frontend
npm run dev                        # http://localhost:3000
```

Open **http://localhost:3000**. Re-run `python -m app.seed` any time for a fresh demo (it
clears generated recommendations so the "Generate" + "Approve" clicks look live).

**One-line pitch:**
> "Lumos Spray Copilot helps greenhouse tomato growers spray less, avoid residue problems at
> harvest, and keep an agronomist in control — it never tells a farmer they *must* spray."

---

## The 3-minute flow

### 1. Dashboard — two greenhouses (15s)
- Two farm cards, each with a **risk badge** and **pesticide spend**.
- *"Green Valley is the problem farm; Sunrise is healthy. Let's open the problem farm."*

### 2. Green Valley → cost analytics (30s)
- Top **stat cards**: ₺205 spend, 4 sprays, harvest in 3 days.
- Scroll to **💰 Pesticide cost analytics**:
  - Total spend ₺205, avg ₺51.25/spray, most-used **mancozeb ×3**, 4 sprays in 30 days.
  - **Cost of repeated-ingredient sprays: ₺90.**
  - Amber line: *"₺51.25 — potential avoidable cost if one unnecessary spray is prevented."*
- *"We're not promising savings — we're showing where money is leaking and what's avoidable."*

### 3. Weather risk (20s)
- **🌦️ Weather risk** card: Antalya is **elevated** — *warm + humid → fungal disease pressure; inspect leaves before spraying.*
- *"Greenhouse disease tracks weather. Warm and humid is exactly when growers over-spray out of fear — we flag it cautiously instead."*

### 4. Generate recommendation → next action (30s)
- Click **"Generate recommendation."**
- A bold **Suggested next action** banner appears: **🌡️ "Harvest timing risk — review before picking."**
- Below it, a red **Elevated risk** panel with three cautious flags: repeated ingredient, PHI/residue, high-severity scouting.
- *"One glance tells the farmer the single next step. And notice — it never says 'spray now.'"*

### 5. Agronomist review (35s)
- In the **Agronomist review** box: type a comment like *"Agree — hold harvest 3 days, rotate chemistry."*
- Click **Approve** (or **Edit recommendation** to tweak the wording, then save → status becomes *edited*).
- Status badge flips **pending → approved**.
- *"Nothing reaches the grower as guidance until a human agronomist signs off. That's the trust layer."*

### 6. Build the WhatsApp report (30s)
- Scroll to **Weekly report** → **Build report** → **Copy for WhatsApp.**
- Point out it now bundles: weather risk, spend, sprays this cycle, risk level, **next action**,
  the **agronomist-approved** guidance + comment, and the safety disclaimer.
- *"Only approved or edited guidance shows up here — pending drafts never leak to the farmer."*

### 7. Contrast with the healthy farm (20s)
- **Back to farms → Sunrise Tomato House → Generate recommendation.**
- Green **Low risk** panel, next action **✅ "Low risk — continue monitoring."** Weather is calmer too.
- *"Same engine, opposite advice — it actively discourages unnecessary spraying. That's the whole point."*

---

## Closing line
> "So in three minutes: less pesticide, no residue surprises at harvest, full cost visibility,
> weather-aware caution, and an agronomist who stays in control — delivered straight to WhatsApp.
> No hardware, no black-box AI."

---

## What to emphasise / avoid
- ✅ Emphasise: **next action**, **agronomist-in-the-loop approval**, **cost analytics + avoidable cost**, **weather disease-pressure**, **WhatsApp-native report**, **cautious language**.
- 🚫 Avoid promising: financing, marketplace, IoT/drones/sensors, payments, auth, or "automatic" disease diagnosis — none of that is in this MVP, by design.

## If something looks off
- Cards show "Not yet assessed" → expected until you click **Generate recommendation**.
- Report shows "awaiting agronomist review" → expected until you **Approve/Edit** the recommendation.
- Red "is the backend running?" banner → start the backend (Terminal 1) and refresh.
- Weather is demo data (Antalya hot/humid, Mersin milder) — a live API can be added behind the same `WeatherService`.
- Totally clean slate → re-run `python -m app.seed` and refresh the browser.
