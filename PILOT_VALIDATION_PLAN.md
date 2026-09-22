# PILOT_VALIDATION_PLAN.md — Concierge Pilot Mode

How to run real-world validation with growers/PCAs using **manually collected** data — from
calls, WhatsApp, spreadsheets, or emails. The goal is learning and useful pilot conversations,
**not** more product surface area and **not** automated integrations.

This pairs with the positioning document's "Pilot evidence we are collecting" and
"What we are NOT claiming yet" sections (kept in the private repo).

---

## What "concierge" means here
We (the founders) are the integration. A grower or PCA tells us what they sprayed and what they
saw; we transcribe it into Lumos by hand. No API hookups, no automated data feeds, no scraping.
This lets us validate the **decision/compliance workflow** before building any plumbing.

Every imported record is tagged with its provenance so the numbers stay honest:
- **`data_source`**: `demo` · `grower_interview` · `spreadsheet` · `whatsapp` · `email` ·
  `manual_entry` · `unknown`
- **`data_confidence`**: `simulated` · `user_provided` · `pca_reviewed` · `incomplete`

---

## How to run a concierge pilot
1. **Set up the farm.** Create the grower's farm (or use the demo farm) and note crop, location,
   country, and expected harvest date.
2. **Have the conversation.** On a call/WhatsApp/email, walk through recent sprays and scouting
   (see "What data to ask for" below). Keep it to ~20 minutes.
3. **Import what you heard.** On the farm detail page → **🤝 Concierge pilot**, set a
   `source_label` (e.g. *"Call with PCA Maria, 20 Jun"*), pick the **data source** and **data
   confidence**, and paste the records as JSON (`spray_events` + `scouting_observations`). Submit.
   - API: `POST /farms/{farm_id}/pilot-import`.
4. **Generate + review.** Generate a recommendation and have the PCA/agronomist approve, edit, or
   reject it — that creates the human-in-the-loop audit trail.
5. **Show it back.** Open **View pilot case study** (`GET /farms/{farm_id}/pilot-case-study`) and
   walk the grower/PCA through the one-pager. Capture a quote in place of `quote_placeholder`.
6. **Log the takeaways.** Use the existing pilot-feedback capture (would they use it with real
   data? would they pay? who owns data entry?).

---

## What data to ask growers/PCAs for
For each **spray** in roughly the last 30 days:
- Product name and active ingredient
- Application date
- Cost (rough is fine — mark confidence `incomplete` if guessed)
- Pre-harvest interval (PHI, days) and worker re-entry interval (REI, hours) if known

For **scouting**:
- Date, what they saw (pest/disease), and a 1–5 severity
- Crop stage if relevant

Also useful (not stored as records): how they keep records today, biggest pain (cost / PHI / REI
/ residue / resistance / audits / labor), and whether a PCA already signs their recommendations.

---

## What metrics to show back
The case study (`pilot-case-study`) and evidence (`pilot-evidence`) surface:
- Spray events and scouting observations analyzed, and the inferred pilot window.
- **Scouting-backed vs. scouting-light sprays** — where calendar-habit spraying hides.
- **PHI/REI flags** caught before harvest or worker re-entry.
- **Resistance / repeated active-ingredient** flags.
- **Weather disease-pressure** flags.
- **PCA review status** (approved / pending / changes requested) — the audit trail.
- **Estimated avoidable cost** per prevented spray (USD farms), framed as *potential*.
- **What Lumos helped surface** and **what is still unknown** bullets.

---

## What counts as strong validation
Strong (worth leaning in):
- A PCA/grower says the flags caught something **they would have missed or had to chase manually**
  (a PHI/REI near-miss, an over-used chemistry).
- They want the **weekly report / case study** to share with a grower, buyer, or crew.
- A clear **willingness to pay** signal and agreement on who owns data entry.
- They ask to run it on **more of their farms** (especially a PCA/packer with many growers).

Weak / inconclusive (keep probing):
- "Neat demo" with no pull to use it on real data.
- Interest only in features outside the wedge (financing, marketplace, hardware) — out of scope.
- Enthusiasm but nobody will actually enter the data.

A pilot is **not** proof of pesticide reduction. Reduction requires a pre-Lumos baseline and a
full crop cycle of measurement — see below.

---

## What we are NOT claiming yet
- **Not** guaranteed pesticide reduction. The case study is descriptive evidence; real reduction
  must be measured against a baseline over a season. We surface *potential* avoidable cost only.
- **Not** replacing the PCA/agronomist — every recommendation is gated behind their review.
- **Not** autonomous pesticide prescriptions — we never tell anyone they "must spray."
- **Not** a compliance or legal guarantee — PHI, REI, and label requirements must be confirmed
  with a licensed advisor and the product label.
- **Not** an automated integration — concierge import is deliberately manual in this phase.

---

## V1 pilot operating mode (concierge)

The Real Pilot Evidence Loop V1 is deliberately **operator-run**:

- **We run the import.** A PCA/grower sends redacted spray recommendations and scouting
  records (CSV/spreadsheet); the operator anonymizes them **before upload**, then imports
  via the CSV pilot import (dry-run validation → mapping correction → commit).
- **Every imported value is `imported_unverified`** until the PCA reviews the decision —
  the check can never auto-approve on imported data, and PCA edits supersede (never
  overwrite) the imported values with attributed `pca_verified` rows.
- **Follow-up is mandatory** before anything is called confirmed: avoided/delayed/changed
  decisions stay "estimated" until follow-up events (re-scouts, actual/rescue
  applications, harvest outcomes) are recorded. Failures (rescues, negative net results)
  are counted and shown — that is what makes the evidence credible.
- **The deliverable** is the anonymized evidence export (`/farms/{id}/evidence-export`,
  JSON + CSV): decisions, provenance, immutable audit history, follow-up timeline,
  confirmed-vs-estimated metrics, limitations, correlation-not-causality statement.

**This build is not customer-facing production software.** Before any self-serve
customer use it would need: authentication, per-tenant data isolation, backups, and a
data-security review. Completing this milestone is infrastructure for obtaining
validation from real PCA records — it is **not** validation of the business.
