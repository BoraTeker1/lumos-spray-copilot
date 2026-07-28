# Lumos Spray Copilot — Demo Script

Pick the script for your audience:
- **⚡ 90-second YC demo** — fast, investor-facing (below).
- **🧑‍🌾 3-minute farmer/PCA demo** — the detailed U.S. walkthrough.
- **🇹🇷 Türkiye greenhouse tomato demo** — second-market contrast (kept at the bottom).
- **🎙️ Tough-question answers** — for "is this replacing the agronomist / how is this different
  from John Deere / does it guarantee reduction?" (at the very bottom).

Setup for all: backend + frontend running, browser at `http://localhost:3000`.

**Startup order matters as of 2026-07-28.** `seed.run()` drops every table, so the label
library and the reference farm must be rebuilt after any re-seed:

```bash
cd backend && source .venv/bin/activate
python -m app.seed              # demo farms only; DESTROYS the reference farm
alembic stamp head              # seeding uses create_all and desyncs Alembic
python -m app.label_sync        # loads the transcribed EPA labels
python -m app.reference_farm    # prints the PCA token ONCE — copy it

# The reference farm is REAL (non-demo) data, so the operator-key interlock now
# applies: the API refuses to start without this.
LUMOS_OPERATOR_KEY=<secret> ANTHROPIC_API_KEY=<key> uvicorn app.main:app --reload
```

`ANTHROPIC_API_KEY` is only needed if you intend to show a live AI path (photo scouting,
document extraction, AI brief). **Nothing loads `.env`** — if it is not exported into the
shell that starts uvicorn, every AI feature silently runs on the deterministic mock, and
mock output must never be presented as model performance.

---

# ⚡ 90-SECOND YC DEMO — "the label says four"

> Goal: show a decision grounded in a real, cited pesticide label, and one number in the
> unit the pesticide question is actually asked in — mass of active ingredient.
> Run this on the **Lumos Reference Ranch**, not the demo farm. That is not a
> presentation choice; a demo farm can only hold a *simulated* label verification, which
> never promotes, so the demo farm is structurally incapable of showing this.

1. **(10s) One-liner.** *"Lumos is the pesticide decision copilot for specialty-crop growers
   and their PCAs — the decision layer **before** the spray."*
2. **(30s) The label-verified block.** Open the reference farm's blocked decision. A grower
   plans a fifth Switch 62.5WG application. It comes back **BLOCK**, and the authority chip
   reads **verified_label_grounded** — the first level the engine has that does not depend on
   anyone's typing. Two rules fired, both tagged `verified_label`:
   - *"This would be application 5 of Switch 62.5WG this season; the verified label allows 4."*
   - *"…would total 70.0 oz/acre this season; the verified label allows 56.0 oz/acre."*

   *"Nobody typed '4'. That came off EPA Reg. No. 100-953, transcribed with its section, its
   revision date and a verbatim snippet, and verified for this farm by a licensed PCA. Click
   through — the citation is on the record."*

   Point at the **one** remaining not-evaluated check: the crop-registration check still
   abstains, because only the strawberry use was transcribed and a partial list is not
   evidence a crop is unregistered. *"Three of the four run. The fourth tells you why it
   didn't. It was four out of four saying 'no label data' last week."*
3. **(25s) The number, in the right unit.** Evidence → **Decision evidence**. One
   follow-up-confirmed avoided captan application shows
   **36.0 lb of captan not applied** — from the label's 80% w/w concentration, the entered
   rate and the treated area, with the conversion's citation printed beside it.
   *"That is the unit the pesticide question is asked in. And note what is still refused:
   season-total reduction and risk-weighted reduction are permanently not calculated, and
   Switch contributes nothing to that total because it has two actives and no single
   concentration to convert from. The metric is all-or-nothing on purpose — a partial total
   reads as a smaller number, not an incomplete one."*
4. **(25s) Close honestly — this is the strongest part.** Point at the badge on the page:
   **Operator reference farm — not a customer.**
   *"I'm not going to pretend this is traction. This farm is ours. Real decisions checked for
   real growers is zero. What this proves is that the machine works end to end on real
   regulatory data — and what we need next is one Central Coast PCA to point it at. That's
   the ask."*

> Do **not** run this script on Golden Coast and describe it as label-grounded. Its stored
> decision payloads are frozen snapshots from seed time and still read *"no label database
> exists"* — true when they were written, false now. Re-seed (see the order above) if you
> want that wording refreshed.

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
