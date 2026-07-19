# DEMO_DATA.md — What the seed data represents

The seed (`backend/app/seed.py`) creates **three** demo farms. Farm 3 (Golden Coast
Strawberry Ranch, California) is the **primary U.S./YC demo**; the two Türkiye greenhouse
tomato farms are the secondary-market contrast (hidden from lists by default, reachable by
direct URL). Dates are relative to "today" (or the `LUMOS_DEMO_TODAY` anchor) so the demo
always looks current. Re-run `python -m app.seed` any time to reset.

Every seeded record carries `data_source="demo"` / `data_confidence="simulated"` and is
**excluded from every real pilot metric**. One farm's records are either all demo or all
real — the API rejects mixing (409), and checks run live on a demo farm during a
walkthrough are saved as simulated demo data (the check sheet says so). Never present any
of this as traction.

> Ops note: pinning the clock (`LUMOS_DEMO_TODAY`) requires `LUMOS_DEMO_MODE=1` for the API
> to start — a leftover pin can no longer corrupt a real pilot. `/health` shows `clock_mode`.

---

## Farm 3 — Golden Coast Strawberry Ranch (Watsonville, CA) → the PRIMARY demo

**Represents:** a California strawberry operation two days from harvest, with a PCA in the
loop — the wedge customer. 18 acres, planted ~90 days ago, **expected harvest in 2 days**.

**Spray history (4 applied sprays, $540):** Captan 80 WDG (captan, PHI 4d, REI 24h) at
−1/−10/−20 days (×3 → repeated-ingredient flag), Brigade WSB (bifenthrin) at −8 days.
**Scouting:** Botrytis "gray mold spreading in fruit" severity **4/5**, plus lygus and mite
observations feeding the scenarios. **PCA policies (entered by "Demo PCA (simulated)"):**
treat lygus only at severity ≥ 3; treat twospotted spider mite only at severity ≥ 3.
**Baseline:** stated cadence, every 4 days (simulated confidence → any reduction figure
renders as illustrative, never a headline).

### The three seeded decision stories

1. **Blocked → changed product (the hero story).** A 4th captan cover spray planned 2 days
   before harvest → **BLOCK — PCA-authorized** (PHI arithmetic: intended + 4 days clears
   *after* harvest; plus "use number 4 of captan in 30 days"; PCA-authorized because the
   values are PCA-entered). The demo PCA **edited** the guidance — the Switch 62.5 WG
   (PHI 0) recommendation lives ONLY in `pca_next_action`, never in engine output — and the
   recorded outcome is **changed_product**, applied on the intended day, with input-value /
   audit / follow-up trails.
2. **Avoided via threshold (the reduction story).** A PyGanic EC 5.0 spray for lygus at
   scouting severity **below** the PCA-entered threshold → the scouting rule triggers →
   PCA holds it → outcome **avoided**, follow-up scouting confirms no rescue was needed.
3. **The honest FAILURE story.** An Agri-Mek SC miticide planned at mite severity 2 (below
   the threshold of 3) → **INSPECT FIRST** → the PCA held it → severity rose to 4 → a
   **rescue application** was required (extra scouting + rescue cost, nothing avoided).
   Deliberately negative: evidence that can't show failures isn't credible.

### The seeded procurement chain (Inputs & finance, Phase 1)

From scenario 1's PCA-cleared decision: an InputPlan for Switch 62.5 WG → 2 concierge-
entered supplier quotes (entry order, never ranked) → one quote selected **with a stored
reason** → an **indicative** financing offer *selected* (never "accepted" — no money moves)
→ PurchaseOrder placed/confirmed/shipped on anchor−1, **delivered 07:30**, and
**input-applied 09:00** on the anchor day, linked to the actual application. The whole
chain is demo-tagged and excluded from the evidence export's real scope.
`tests/test_procurement_demo.py` asserts the chronology; the seed itself asserts the
captan check still BLOCKs.

### What to show

- Farms page ranked by urgency → open Golden Coast → **Decision queue** (the finished
  stories) → open a **Decision record** (printable one-pager with rules, calculations,
  source authority, review, outcome, follow-ups).
- Run one **live** check (saved as simulated — see note above).
- **Evidence & compliance** page: demo scope vs real scope are separate tabs and never
  combine; the reduction card shows its honesty gates ("illustrative", "no baseline, no
  number").

---

## Farm 1 — Green Valley Greenhouse (Antalya) → secondary HIGH-RISK contrast

**Represents:** a grower who sprays on habit, repeats chemistry, and heads into harvest
without checking residue timing. 4,000 m², planted ~70 days ago, **harvest in 3 days**.

**Sprays (4, ₺205):** Dithane M-45 (mancozeb, PHI 7d) at −2/−12/−22 days (×3), Confidor
200 SL (imidacloprid, PHI 3d) at −8 days. **Scouting:** leaf spots, severity 4/5.

**Flags built in:** repeated mancozeb ×3; PHI risk (the −2d mancozeb clears after
harvest); high-severity scouting; elevated mock weather (28 °C / 85 % RH).
**Expected output:** Elevated risk · next action *"Harvest timing risk — review before
picking"* · analytics ₺205 total, mancozeb ×3, repeated-ingredient cost ₺90.

## Farm 2 — Sunrise Tomato House (Mersin) → secondary LOW-RISK contrast

**Represents:** a disciplined grower — the tool **discourages** spraying here. 2,500 m²,
**harvest in 45 days**. One targeted Vertimec spray 18 days ago; scouting severity 2/5.
**Expected output:** Low risk · *"continue monitoring"* · calm mock weather.

---

## What the founder should SAY during the demo

- Open: *"California specialty crops are sprayed often, hand-harvested, and heavily
  regulated — PHI and worker re-entry mistakes actually hurt here."*
- On the verdict: *"Notice it never says 'spray now.' It blocks, delays, or escalates —
  and a licensed PCA, already required by California law, makes the call."*
- On source authority: *"Every rule prints who supplied its values. Grower-entered values
  always yield a provisional verdict; only PCA-entered or label-verified data can back a
  PCA-authorized one — and no label database exists yet, so we say so."*
- On evidence: *"Confirmed means follow-up-backed; estimated means entered values; the two
  are never combined. Demo data is excluded from every real metric by construction."*
- On the failure story: *"Scenario 3 cost the grower money — we show it because evidence
  that can't show failures isn't credible."*

### Do NOT say
- ❌ "It diagnoses the disease." (It flags pressure cautiously; the photo copilot only
  drafts a note a human must confirm.)
- ❌ "It tells you when to spray." / "definitive verdict" (the vocabulary is
  provisional / PCA-authorized / verified-label-grounded).
- ❌ "Guaranteed savings/reduction of X." (Use "potential avoidable cost"; reduction is
  measured against a stated baseline and gated for honesty.)
- ❌ Anything implying real payments, lending, or a supplier marketplace — quotes are
  concierge-entered and financing is indicative only.

---

## Questions to ASK the grower / PCA after the demo

1. Does the **verdict + next action** match what you'd actually do this week?
2. Do you track **rotation/repeated chemistry** today? How?
3. How do you decide harvest timing vs. the last spray — gut feel, notebook, label?
4. Would the **printable decision record** satisfy your auditor / buyer? What's missing?
5. What would make you run **your real records** through this (CSV, photos, transcription)?
6. Who enters the data in practice — grower, foreman, scout, or PCA?
7. Who should pay for this — grower, PCA firm, or packer — and per what unit?

Capture answers verbatim where possible — see `CUSTOMER_DISCOVERY.md`.
