# Lumos Spray Copilot — 2-Minute Demo Script

A tight, repeatable script for demoing the MVP to a farmer, agronomist, or investor.

---

## 0. Before you start (1 min, off-camera)

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

Open **http://localhost:3000** in your browser. Re-run `python -m app.seed` any time you
want a fresh demo (it clears generated recommendations so the "Generate" click looks live).

**One-line pitch to open with:**
> "Lumos Spray Copilot helps greenhouse tomato growers spray less, avoid residue problems at
> harvest, and keep an agronomist in the loop — without ever telling them they *must* spray."

---

## The 2-minute flow

### 1. Dashboard — "Here are two greenhouses" (15s)
- Point at the two farm cards. Each shows **pesticide spend** and a **risk badge**.
- Say: *"Green Valley is a real-world mess; Sunrise is healthy. Let's look at the problem farm."*

### 2. Open **Green Valley Greenhouse** → the high-risk story (45s)
- Top stats: **₺205 pesticide spend, 4 sprays, harvest in 3 days.**
- Click **"Generate recommendation."**
- A red **Elevated risk** panel appears with three cautious, specific flags:
  1. **Repeated active ingredient** — "mancozeb used 3 times in 30 days → resistance/residue risk, consider rotating."
  2. **Pre-harvest interval risk** — "a spray's PHI clears *after* the harvest date → residue risk, review harvest timing."
  3. **High-severity scouting** — "severity 4/5 leaf spots → pressure elevated, inspect closely."
- Key line to say: *"Notice it never says 'spray now.' It flags risks and routes the decision to the agronomist."*

### 3. Show the data behind it (15s)
- Scroll to **Spray history** (the three mancozeb entries + cost) and **Scouting history**
  (the severity 4/5 badge). *"Everything is evidence-based — no black box."*

### 4. Weekly report → WhatsApp (20s)
- Scroll to **Weekly report** → click **"Build report"** → click **"Copy for WhatsApp."**
- Say: *"Growers live in WhatsApp. One tap gives the agronomist a clean weekly summary to paste into a chat."*

### 5. Contrast with the healthy farm (15s)
- Go **Back to farms → Sunrise Tomato House → Generate recommendation.**
- A green **Low risk** panel says: *"Evidence is weak — inspect/scout first rather than spraying preventively."*
- Say: *"Same engine, opposite advice. It actively discourages unnecessary spraying — that's the whole point."*

### 6. (Optional) Live data entry (10s)
- On either farm, use **"Log scouting note"** with severity 5, then **Re-generate** — the risk updates instantly.

---

## Closing line
> "So in one screen: less pesticide, no residue surprises at harvest, full cost visibility, and
> an agronomist who stays in control. No hardware, no black-box AI — just a clear, cautious copilot."

---

## What to emphasise / avoid
- ✅ Emphasise: **cautious language**, **agronomist-in-the-loop**, **PHI/residue safety**, **cost tracking**, **WhatsApp-native report**.
- 🚫 Avoid promising: financing, marketplace, IoT/drones/sensors, or "automatic" disease diagnosis — none of that is in this MVP, by design.

## If something looks off
- Cards show "Not yet assessed" / empty risk → that's expected until you click **Generate**.
- Page shows a red "is the backend running?" banner → start the backend (Terminal 1) and refresh.
- Want a totally clean slate → re-run `python -m app.seed` and refresh the browser.
