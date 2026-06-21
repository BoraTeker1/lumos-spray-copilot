# Lumos Spray Copilot — Demo Script

Pick the script for your audience:
- **⚡ 90-second YC demo** — fast, investor-facing (below).
- **🧑‍🌾 3-minute farmer/PCA demo** — the detailed U.S. walkthrough.
- **🇹🇷 Türkiye greenhouse tomato demo** — second-market contrast (kept at the bottom).
- **🎙️ Tough-question answers** — for "is this replacing the agronomist / how is this different
  from John Deere / does it guarantee reduction?" (at the very bottom).

Setup for all: backend + frontend running, browser at `http://localhost:3000`,
re-run `python -m app.seed` first for a clean state. The homepage hero has the two demo CTAs.

---

# ⚡ 90-SECOND YC DEMO

> Goal: land the wedge, show one screen of real value, and the human-in-the-loop. Don't click everything.

1. **(15s) One-liner + homepage.** *"Lumos is the pesticide decision and compliance copilot for
   specialty-crop growers and their PCAs — the decision layer **before** the spray, not a sprayer
   or a drone."* Point at the homepage hero (who / pain / outcome) and click
   **🇺🇸 View U.S. strawberry demo**.
2. **(30s) Compliance snapshot.** Scroll to **🛡️ Compliance snapshot**: PHI **At risk**, REI
   **May be active**, repeated ingredient **Repeated**, scouting **High**.
   *"In one screen: residue timing, worker re-entry, resistance — the exact things that get a
   load rejected or a crew sent into a treated field too early."*
3. **(25s) Recommendation + PCA approval.** Click **Generate recommendation** → next action
   **"Harvest timing risk — review before picking."** Hit **Approve** in the PCA review box.
   *"It never says 'spray now.' A licensed PCA — already required by law in California — approves
   before anything reaches the grower."*
4. **(20s) Report + close.** **Weekly report → Copy** (PCA wording, $ costs, PHI/REI warnings,
   disclaimer). *"Audit-ready, shareable, exportable to CSV. We help them spray less and stay
   compliant — capital-light software, no hardware."*

---

# 🧑‍🌾 3-MINUTE FARMER / PCA DEMO — "the decision/compliance layer before the spray"

**Positioning line to open with:**
> "Lumos is an AI pesticide **decision and compliance copilot** for U.S. specialty-crop growers
> and their PCAs. We're not a sprayer, a robot, or a drone — we're the **decision layer before
> the spray**. We help growers spray less and stay audit-ready, with a licensed PCA in the loop."

**Setup:** backend + frontend running (see "Before you start" below), browser at
`http://localhost:3000`. Re-run `python -m app.seed` first for a clean state.

### 1. Dashboard — the U.S. farm (15s)
- Point to **🇺🇸 Golden Coast Strawberry Ranch** (Watsonville, CA · strawberry · 18 acres).
- *"California strawberries — hand-harvested, heavily sprayed, strict pesticide reporting. This
  is where PHI and worker re-entry mistakes actually hurt."*

### 2. Open it → cost analytics (30s)
- Stat cards show spend in **USD** ($540), 4 sprays, harvest in 2 days.
- **💰 Cost analytics:** most-used **captan ×3**, repeated-ingredient cost **$240**, and
  *"$135 potential avoidable cost if one unnecessary spray is prevented."*
- *"We don't promise savings — we show where money leaks and what's avoidable."*

### 3. The compliance snapshot (35s) — the U.S. money slide
- **🛡️ Compliance snapshot** shows red/green rows:
  - **PHI — At risk** (a captan spray won't clear before harvest)
  - **REI — May be active** (worker re-entry window on the latest spray)
  - **Repeated active ingredient — Repeated** (captan ×3 → resistance)
  - **Scouting pressure — High** (Botrytis 4/5)
  - **Weather disease pressure — Moderate** (cool, humid coast)
  - **PCA / agronomist review status**
- *"This is the audit-ready view a PCA and a buyer want — PHI, REI, resistance, all in one place,
  before anyone enters the field or picks."*

### 4. Generate recommendation → next action (25s)
- Click **Generate recommendation** → bold next action **🌡️ "Harvest timing risk — review
  before picking."** Red elevated panel lists PHI, REI, resistance, and scouting flags.
- *"Notice the REI line: 'worker re-entry interval may still be active — review label and PCA
  guidance.' It never says 'safe' or 'spray now.'"*

### 5. PCA approves / edits (30s)
- In **Agronomist review**, add a comment (e.g. *"Hold harvest 2 days; rotate off captan; keep
  crew out until REI clears"*) → **Approve** (or **Edit** then save).
- Status flips **pending → approved**.
- *"In California a licensed PCA signs pesticide recommendations. That human-in-the-loop approval
  is already the law — our workflow maps onto it exactly."*

### 6. Copy the report (20s)
- **Weekly report → Build report → Copy for WhatsApp/text.**
- It reads **PCA/agronomist**, shows **PHI/REI/resistance warnings**, the **next action**, the
  approved guidance + comment, costs in **$**, and the disclaimer: *"Confirm pesticide use, label
  requirements, PHI, and REI with a licensed PCA/agronomist and the product label."*

### 7. The one-liner to close
> **"We are not a sprayer. We are the decision and compliance layer before the spray —**
> fewer unnecessary sprays, no PHI/REI surprises, and an audit-ready PCA-approved record."

---

# 🇹🇷 ORIGINAL 3-Minute Demo (Türkiye greenhouse tomatoes)

Kept as a contrast / second market. Same engine, different crop and advisor wording (₺, "agronomist").

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

---

# 🎙️ TOUGH-QUESTION ANSWERS

Keep these short, confident, and honest. Each ends by steering back to the wedge.

### "Is this replacing the agronomist / PCA?"
> "No — the opposite. We make the PCA more effective and keep them in control. In California a
> licensed PCA legally has to sign pesticide recommendations, so we built the workflow around
> their approval: nothing reaches the grower as guidance until the PCA approves or edits it. We
> handle the tedious part — flagging PHI, REI, resistance, and keeping audit-ready records — so
> the advisor spends time on judgment, not paperwork."

### "How is this different from John Deere (See & Spray)?"
> "John Deere sells hardware that changes *how* a spray is physically applied, mostly on row
> crops — cameras, booms, vehicles. We're software that sits *before* the nozzle: should you
> spray at all, is it compliant on PHI and REI, are you overusing one chemistry, and is it
> documented for the audit. We're complementary, not competitive — and capital-light, because we
> ship no hardware. We also focus on specialty crops, which those platforms largely skip."

### "Does this guarantee pesticide reduction?"
> "No, and we're deliberate about not overclaiming — that's a feature in a compliance product.
> We don't tell anyone to spray and we don't promise savings. We surface *potential avoidable
> cost* and flag risk cautiously; the pilot's job is to **measure** real reduction and the PHI/REI
> near-misses we help avoid. If a grower skips one unnecessary spray and dodges one residue scare
> a season, the math already works — but we let the data prove it, not the pitch."
