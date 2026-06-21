# DEMO_DATA.md — What the seed data represents

The seed (`backend/app/seed.py`) creates two greenhouse tomato farms designed to tell a clear
before/after story. Dates are relative to "today" so the demo always looks current. Re-run
`python -m app.seed` any time to reset.

---

## Farm 1 — Green Valley Greenhouse (Antalya) → the HIGH-RISK story

**Represents:** a typical grower who sprays on habit/calendar, repeats the same chemistry, and
is heading into harvest without checking residue timing. This is the "money leaking + risk
building" farm.

**Profile:** 4,000 m², planted ~70 days ago, **expected harvest in 3 days**.

**Spray history (4 sprays, ₺205 total):**
| Product | Active ingredient | Cost | PHI | When |
|---|---|---|---|---|
| Dithane M-45 | mancozeb | ₺45 | 7d | 2 days ago |
| Dithane M-45 | mancozeb | ₺45 | 7d | 12 days ago |
| Dithane M-45 | mancozeb | ₺45 | 7d | 22 days ago |
| Confidor 200 SL | imidacloprid | ₺70 | 3d | 8 days ago |

**Scouting:** "spreading leaf spots on lower canopy", **severity 4/5**, 1 day ago.

### Risk flags intentionally built in
1. **Repeated active ingredient** — mancozeb used **3×** in 30 days → resistance/residue
   warning, "consider rotating chemistry."
2. **Pre-harvest interval (PHI) risk** — the 2-days-ago mancozeb spray (PHI 7) clears
   *after* the harvest date → **residue risk**, "review harvest timing before picking."
3. **High-severity scouting** — severity 4/5 → "pest/disease pressure appears elevated."
4. **Weather risk (Antalya mock)** — 28 °C, 85% RH → **elevated fungal disease pressure**.

### Expected output
- **Risk level:** Elevated · **Next action:** 🌡️ *Harvest timing risk — review before picking*
  (PHI safety takes priority over the other flags).
- **Analytics:** total ₺205 · avg ₺51.25/spray · most-used **mancozeb ×3** · repeated-ingredient
  cost **₺90** · potential avoidable cost **₺51.25** (= one average spray).

---

## Farm 2 — Sunrise Tomato House (Mersin) → the LOW-RISK / healthy contrast

**Represents:** a disciplined grower who scouts, sprays only when targeted, and has plenty of
runway to harvest. This farm proves the tool **discourages** unnecessary spraying.

**Profile:** 2,500 m², planted ~40 days ago, **expected harvest in 45 days**.

**Spray history (1 spray, ₺60):** Vertimec 1.8 EC (abamectin), PHI 7d, 18 days ago — a single
targeted application after scouting.

**Scouting:** "a few mites on one plant", **severity 2/5**, 3 days ago.

### Expected output
- **Risk level:** Low · **Next action:** ✅ *Low risk — continue monitoring*.
- **Weather (Mersin mock):** 24 °C, 60% RH → moderate/low pressure.
- No PHI risk, no over-use, no high-severity flags.

---

## What the founder should SAY during the demo

- Open: *"This is a real-world greenhouse problem — growers spray too often, repeat the same
  chemistry, and risk un-sellable fruit at harvest because of residue limits."*
- On analytics: *"We don't promise savings. We show where money leaks — ₺90 went to repeating
  one fungicide — and what's avoidable if one unnecessary spray is skipped."*
- On the recommendation: *"Notice it never says 'spray now.' It flags risk and routes the
  decision to the agronomist."* (This is the core trust message.)
- On agronomist approval: *"Nothing reaches the grower as guidance until a human signs off."*
- On the WhatsApp report: *"Growers live in WhatsApp — one tap and the agronomist has a clean
  weekly summary to send."*
- On the low-risk farm: *"Same engine, opposite advice. It actively tells you NOT to spray
  when evidence is weak."*

### Do NOT say
- ❌ "It diagnoses the disease." (It does not — it flags pressure cautiously.)
- ❌ "It tells you when to spray." (It never prescribes spraying.)
- ❌ "Guaranteed savings of X." (Use "potential avoidable cost," always.)
- ❌ Anything about financing, marketplace, drones, sensors, or AI vision — out of scope.

---

## Questions to ASK the farmer / agronomist after the demo
1. Does the **next-action** line match what you'd actually do this week?
2. Is the **repeated-ingredient** warning something you currently track? How?
3. How do you decide harvest timing today vs. last spray — gut feel, a notebook, the label?
4. Would you trust guidance more because an **agronomist approved** it? Why / why not?
5. What's missing before you'd log your **real** sprays here instead of paper/WhatsApp?
6. Who would actually enter the data — you, a foreman, or the agronomist?
7. Is the weekly WhatsApp report something you'd forward to your agronomist / buyer?
8. What would make this worth paying for per greenhouse per season?

Capture answers verbatim where possible — see `CUSTOMER_DISCOVERY.md`.
