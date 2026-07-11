// Shared user-facing label vocabularies (single source — mirrors the backend's
// app/decision_engine.py and app/decision_status.py). Components must import from
// here instead of declaring their own copies, so two surfaces can never disagree.

// Per-rule input-source authority (chip next to each check).
export const AUTHORITY_SOURCE_LABELS = {
  verified_label: "verified label",
  pca_entered: "PCA-entered",
  grower_entered: "grower-entered",
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
// Shared by the dashboard cards and the farm-page header chip.
export const URGENCY_META = {
  conflict: { label: "Timing conflict", variant: "red", border: "border-red-300" },
  needs_review: { label: "Needs PCA review", variant: "amber", border: "border-amber-300" },
  awaiting_outcome: { label: "Awaiting outcome", variant: "amber", border: "border-amber-200" },
  flags: { label: "Risk flags", variant: "amber", border: "border-gray-200" },
  ok: { label: "No open decisions", variant: "neutral", border: "border-gray-200" },
};
