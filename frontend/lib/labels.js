// Shared user-facing label vocabularies (single source — mirrors the backend's
// app/decision_engine.py and app/decision_status.py). Components must import from
// here instead of declaring their own copies, so two surfaces can never disagree.

import { URGENCY_TONES, tone as _tone } from "@/lib/tones";

// Per-rule input-source authority (chip next to each check).
export const AUTHORITY_SOURCE_LABELS = {
  verified_label: "verified label",
  pca_entered: "PCA-entered",
  grower_entered: "grower-entered",
  imported_unverified: "imported, unverified",
  heuristic: "heuristic",
};

// Decision-level authority (mirrors decision_engine DECISION_AUTHORITY_LABELS).
export const DECISION_AUTHORITY_LABELS = {
  verified_label_grounded: "Verified-label grounded",
  pca_authorized: "PCA-authorized",
  provisional: "Provisional",
};

// Anything unknown (including the legacy "definitive" value from a pre-rename DB)
// renders as provisional — the safe direction; reseed is the supported migration.
export function isProvisionalAuthority(value) {
  return !["verified_label_grounded", "pca_authorized"].includes(value);
}

export function decisionAuthorityLabel(value) {
  return DECISION_AUTHORITY_LABELS[value] || DECISION_AUTHORITY_LABELS.provisional;
}

// Engine decision outcomes (the check's verdict).
export const DECISION_OUTCOME_LABELS = {
  approve: "APPROVE",
  block: "BLOCK",
  delay: "DELAY",
  inspect_first: "INSPECT FIRST",
  pca_review_required: "PCA REVIEW REQUIRED",
};

// Spray-disposition summary: the one-line answer to "so can this be sprayed?",
// derived from the engine verdict ALONE. It adds no logic — it restates the
// verdict the engine already issued in the words the grower actually asks in.
//
// The mapping is deliberately asymmetric, and must stay that way:
//   * `block` is the only value that speaks in absolutes.
//   * delay / inspect_first / pca_review_required all say HOLD — the engine has
//     not cleared anything, and each carries its own server-supplied next action.
//   * `approve` says NO ENGINE BLOCK FOUND and NEVER "spraying allowed: yes".
//     An approve is currently never definitive (rotation and scouting checks are
//     heuristics; prior-REI is grower-entered), so an affirmative clearance here
//     would be a pesticide prescription the product refuses to make.
// Call sites pair the headline with the server's `required_next_action` and,
// for approve, with CLEARANCE_CAVEAT.
export const DISPOSITION_SUMMARY = {
  block: { headline: "SPRAYING ALLOWED: NO", tone: "risk" },
  delay: { headline: "NOT CURRENTLY CLEARED — HOLD", tone: "warn" },
  inspect_first: { headline: "NOT CURRENTLY CLEARED — HOLD", tone: "inspect" },
  pca_review_required: { headline: "NOT CURRENTLY CLEARED — HOLD", tone: "review" },
  approve: { headline: "NO ENGINE BLOCK FOUND", tone: "good" },
};

// Shown beside an approve headline. Says what the absence of a block does and
// does not mean.
export const CLEARANCE_CAVEAT =
  "No engine block is not a clearance to spray. Confirm PHI, REI, rates and crop use against the product label with a licensed PCA / agronomist before application.";

export function dispositionSummary(outcome) {
  return DISPOSITION_SUMMARY[outcome] || DISPOSITION_SUMMARY.pca_review_required;
}

// Recorded real-world outcomes (what the humans actually did).
export const RECORDED_OUTCOME_LABELS = {
  planned: "No outcome recorded yet",
  sprayed_as_planned: "Sprayed as planned",
  changed_product: "Changed product",
  delayed: "Delayed",
  avoided: "Avoided",
  inspected_first: "Inspected first",
};

// Derived review states (server-computed `review_state`; see app/decision_status.py).
export const REVIEW_STATE_LABELS = {
  not_required: "No review required",
  pending: "PCA review required",
  approved: "PCA approved",
  edited: "PCA edited",
  rejected: "PCA rejected",
};

// Farm urgency (server-computed by /farms-overview and /farms/{id}/overview).
// Shared by the dashboard cards and the farm-page header chip. Badge variants
// come from the shared tone table; borders keep per-urgency intensity.
const URGENCY_BORDERS = {
  conflict: "border-risk-line",
  harvest_overdue: "border-risk-line",
  needs_review: "border-warn-line",
  awaiting_outcome: "border-warn-line",
  flags: "border-line",
  ok: "border-line",
};

const URGENCY_LABELS = {
  conflict: "Timing conflict",
  harvest_overdue: "Harvest date passed",
  needs_review: "Needs PCA review",
  awaiting_outcome: "Awaiting outcome",
  flags: "Risk flags",
  ok: "No open decisions",
};

export const URGENCY_META = Object.fromEntries(
  Object.keys(URGENCY_LABELS).map((key) => [
    key,
    {
      label: URGENCY_LABELS[key],
      // "flags" and "awaiting_outcome" read as amber chips (open work), never red.
      variant: _tone(URGENCY_TONES[key]).badge,
      border: URGENCY_BORDERS[key],
    },
  ])
);

// ------------------------------------------------------- the value ledger
// Evidence tier for one attributed figure (mirrors app/value_ledger.py). The
// distinction is the whole point of the ledger: a verified dollar is backed by
// recorded follow-up evidence, an estimated one is somebody's recorded outcome
// and nothing more, and the two are never added together.
export const VALUE_TIER_LABELS = {
  verified: "Verified",
  estimated: "Estimated",
  not_calculated: "Not calculated",
};

// Where an attributed figure came from.
export const VALUE_SOURCE_LABELS = {
  avoided_application: "Application avoided",
  procurement_saving: "Input purchasing",
};

// Crop-cycle status (mirrors schemas.CropCycleStatus).
export const CROP_CYCLE_STATUS_LABELS = {
  planned: "Planned",
  planted: "Planted",
  growing: "Growing",
  harvesting: "Harvesting",
  closed: "Closed",
  abandoned: "Abandoned",
};

// Non-spray operations that carry a season cost (mirrors schemas.OperationType).
export const OPERATION_TYPE_LABELS = {
  planting: "Planting",
  irrigation: "Irrigation",
  fertilization: "Fertilization",
  crop_protection: "Crop protection",
  scouting: "Scouting",
  harvest: "Harvest",
  tillage: "Tillage",
  other: "Other",
};

// Measured block outcomes (mirrors schemas.BlockOutcomeType).
export const BLOCK_OUTCOME_TYPE_LABELS = {
  disease_incidence: "Disease incidence",
  rescue_treatment: "Rescue treatment",
  yield: "Yield",
  marketable_packout: "Marketable packout",
  cull: "Cull",
  cost: "Cost",
  adverse_event: "Adverse event",
};

// Season cost groupings (mirrors schemas.CostCategory). A breakdown, not a chart of
// accounts. `uncategorised` is not in the backend Literal — it is the bucket
// value_ledger uses for a costed row nobody classified, and it stays visibly distinct
// from "other" because those are different facts.
export const COST_CATEGORY_LABELS = {
  crop_protection: "Crop protection",
  fertilizer_nutrition: "Fertilizer / nutrition",
  irrigation: "Irrigation",
  labor: "Labor",
  equipment_operations: "Equipment / operations",
  planting_materials: "Planting / materials",
  harvest_postharvest: "Harvest / post-harvest",
  other: "Other",
  uncategorised: "Uncategorised",
};

// Season economics (mirrors app/season_closeout.py). Every one of these is a
// farm-record figure, never an accounting claim — the wording matters and lives here
// so the page and any future surface cannot disagree about what a number is called.
export const CLOSEOUT_METRIC_LABELS = {
  revenue: "Revenue",
  costs: "Recorded costs",
  revenue_minus_recorded_costs: "Revenue minus recorded costs",
  harvested_yield: "Harvested yield",
  planted_area: "Planted area",
  yield_per_area: "Yield per area",
  cost_per_area: "Recorded cost per area",
  revenue_per_area: "Revenue per area",
  cost_per_yield_unit: "Recorded cost per unit",
  realised_price_per_yield_unit: "Realised price per unit",
};

// What a season's economics page is called, per cycle state. Same payload either way
// — an open season is not a lesser version of a closed one.
export const CLOSEOUT_VIEW_LABELS = {
  season_to_date: "Season to date",
  season_closeout: "Season closeout",
};
