// THE single frontend status registry. Every semantic state renders from here —
// icon + explicit text label + tone (never color alone) — so no page can invent
// its own status-to-color mapping. Values mirror the backend's canonical
// vocabularies (app/decision_status.py); the frontend never re-derives them.

import {
  Ban,
  Banknote,
  CircleCheck,
  CircleDashed,
  CircleHelp,
  Clock,
  Droplets,
  FileText,
  FileWarning,
  Landmark,
  OctagonX,
  Package,
  PackageCheck,
  RefreshCw,
  Search,
  ShieldCheck,
  Sprout,
  Truck,
  TriangleAlert,
  Users,
} from "lucide-react";

// kind -> value -> { label, tone, icon }
export const STATUS = {
  // Engine verdict (decision_outcome) — the immutable historical decision.
  verdict: {
    approve: { label: "APPROVED", tone: "good", icon: CircleCheck },
    block: { label: "BLOCKED", tone: "risk", icon: OctagonX },
    delay: { label: "DELAYED", tone: "warn", icon: Clock },
    inspect_first: { label: "INSPECT FIRST", tone: "inspect", icon: Search },
    pca_review_required: { label: "PCA REVIEW", tone: "review", icon: CircleHelp },
  },
  // Workflow state (workflow_state) — is anyone still on the hook?
  workflow: {
    needs_action: { label: "Needs action", tone: "warn", icon: TriangleAlert },
    awaiting_pca: { label: "Awaiting PCA", tone: "info", icon: Users },
    resolved: { label: "Resolved", tone: "good", icon: CircleCheck },
  },
  // Recorded real-world outcome (outcome).
  outcome: {
    planned: { label: "Not recorded", tone: "neutral", icon: CircleDashed },
    sprayed_as_planned: { label: "Applied", tone: "neutral", icon: Droplets },
    changed_product: { label: "Changed product", tone: "info", icon: RefreshCw },
    delayed: { label: "Delayed", tone: "warn", icon: Clock },
    avoided: { label: "Avoided", tone: "good", icon: Ban },
    inspected_first: { label: "Inspected first", tone: "good", icon: Search },
  },
  // PCA disposition — the licensed advisor's judgement about a scheduled spray.
  // Orthogonal to `verdict`, `review` and `outcome`: they are four different facts
  // about four different moments. No value means "safe".
  disposition: {
    follow_baseline: { label: "Spray as scheduled", tone: "neutral", icon: Droplets },
    defer: { label: "Defer", tone: "info", icon: Clock },
    rescout: { label: "Re-scout first", tone: "warn", icon: Search },
    insufficient_evidence: {
      label: "Insufficient evidence", tone: "warn", icon: FileWarning,
    },
  },
  // Disease-risk band. OPERATOR-ONLY while the pilot is blinded — the PCA-facing
  // payload carries no risk field at all, so this never renders on their surfaces.
  // `low` is a band, NOT a statement that deferring is safe.
  riskBand: {
    low: { label: "Low band", tone: "good", icon: CircleCheck },
    moderate: { label: "Moderate band", tone: "warn", icon: TriangleAlert },
    high: { label: "High band", tone: "risk", icon: OctagonX },
    abstain: { label: "Abstained", tone: "neutral", icon: CircleHelp },
  },
  // Evidence / documentation state (evidence_state).
  evidence: {
    complete: { label: "Complete", tone: "good", icon: CircleCheck },
    verified: { label: "Verified (follow-up)", tone: "good", icon: ShieldCheck },
    follow_up_required: { label: "Follow-up required", tone: "warn", icon: TriangleAlert },
    follow_up_in_progress: { label: "Follow-up in progress", tone: "info", icon: Clock },
    missing_documentation: { label: "Missing documentation", tone: "warn", icon: FileWarning },
  },
  // PCA review state (review_state).
  review: {
    not_required: { label: "No review required", tone: "neutral", icon: CircleDashed },
    pending: { label: "PCA review required", tone: "warn", icon: Users },
    approved: { label: "PCA approved", tone: "good", icon: CircleCheck },
    edited: { label: "PCA edited", tone: "info", icon: RefreshCw },
    rejected: { label: "PCA rejected", tone: "risk", icon: OctagonX },
  },
  // Input plan status (Inputs & finance; app/procurement_status.py).
  planStatus: {
    draft: { label: "Draft", tone: "neutral", icon: CircleDashed },
    submitted_for_quotes: { label: "Quotes requested", tone: "info", icon: FileText },
    quoted: { label: "Quotes received", tone: "info", icon: FileText },
    quote_selected: { label: "Quote selected", tone: "good", icon: CircleCheck },
    ordered: { label: "Ordered", tone: "good", icon: Package },
    cancelled: { label: "Cancelled", tone: "neutral", icon: Ban },
  },
  // Supplier quote derived state (quote_state).
  quoteState: {
    submitted: { label: "Quote received", tone: "info", icon: FileText },
    selected: { label: "Selected", tone: "good", icon: CircleCheck },
    not_selected: { label: "Not selected", tone: "neutral", icon: CircleDashed },
    withdrawn: { label: "Withdrawn", tone: "neutral", icon: Ban },
    expired: { label: "Expired", tone: "warn", icon: Clock },
  },
  // Plan-level financing state (financing_state). A request is never an offer,
  // and a SELECTED indicative offer is never a loan approval — the labels say
  // "selected", never "accepted", because nothing was approved or funded.
  financing: {
    cash: { label: "Cash", tone: "neutral", icon: Banknote },
    financing_requested: { label: "Financing requested", tone: "info", icon: CircleHelp },
    offer_received: { label: "Indicative offer received", tone: "info", icon: Landmark },
    offer_selected: { label: "Indicative offer selected", tone: "info", icon: Landmark },
    offer_declined_or_expired: {
      label: "Offer declined / expired", tone: "neutral", icon: Ban,
    },
  },
  // Financing offer state (offer_state). Selected keeps the info tone — an
  // approval tone would imply approval, and none happened.
  offerState: {
    indicative: { label: "Indicative", tone: "info", icon: Landmark },
    selected: { label: "Selected — indicative only", tone: "info", icon: CircleCheck },
    declined: { label: "Declined", tone: "neutral", icon: Ban },
    withdrawn: { label: "Withdrawn", tone: "neutral", icon: Ban },
    expired: { label: "Expired", tone: "warn", icon: Clock },
  },
  // Purchase order status.
  orderStatus: {
    placed: { label: "Placed", tone: "info", icon: Package },
    confirmed: { label: "Supplier confirmed", tone: "info", icon: CircleCheck },
    shipped: { label: "Shipped", tone: "info", icon: Truck },
    delivered: { label: "Delivered", tone: "good", icon: PackageCheck },
    partially_delivered: { label: "Partially delivered", tone: "warn", icon: Package },
    cancelled: { label: "Cancelled", tone: "neutral", icon: Ban },
  },

  // ------------------------------------------------------------- finance layer
  // Added 2026-08-07. Two things these tables must never acquire:
  //
  // 1. An "approved" value. The backend vocabulary is conditions_met /
  //    conditions_not_met / referred_to_human, and adding a friendlier label here
  //    would let the UI claim something the engine deliberately cannot express.
  // 2. A "good" tone on `unknown`. Nothing-checked is not compliance — the whole
  //    reason `standing` is three-valued is that a two-value pill would force the
  //    unchecked case into whichever colour reads well.
  standing: {
    in_good_standing: { label: "In good standing", tone: "good", icon: CircleCheck },
    in_breach: { label: "In breach", tone: "bad", icon: OctagonX },
    // Neutral, never good. A farm nobody could evaluate is not a compliant farm.
    unknown: { label: "Not evaluated", tone: "neutral", icon: CircleHelp },
  },
  underwritingOutcome: {
    conditions_met: { label: "Conditions met", tone: "good", icon: CircleCheck },
    conditions_not_met: { label: "Conditions not met", tone: "bad", icon: OctagonX },
    referred_to_human: { label: "Referred to a human", tone: "warn", icon: Users },
  },
  // Whether a stored assessment produced a result or recorded why it could not.
  assessment: {
    scored: { label: "Assessed", tone: "info", icon: FileText },
    refused: { label: "Could not assess", tone: "neutral", icon: FileWarning },
  },
  // Who can unblock a cross-layer gap. The useful half of the farm profile.
  gapOwner: {
    grower: { label: "You can fix this", tone: "info", icon: Sprout },
    operator: { label: "Waiting on Lumos", tone: "neutral", icon: Landmark },
    undetermined: { label: "Unclassified", tone: "neutral", icon: CircleHelp },
  },
};

export function statusMeta(kind, value) {
  const table = STATUS[kind] || {};
  return (
    table[value] || { label: String(value ?? "—"), tone: "neutral", icon: CircleHelp }
  );
}

// Order timeline event types -> display labels (append-only OrderEvent rows).
export const ORDER_EVENT_LABELS = {
  created: "Order created",
  quote_selected: "Quote selected",
  financing_selected: "Financing selected (indicative)",
  supplier_confirmed: "Supplier confirmed",
  shipped: "Shipped",
  delivered: "Delivered",
  partially_delivered: "Partially delivered",
  cancelled: "Cancelled",
  input_applied: "Input applied",
  exception_reported: "Exception reported",
};

export function orderEventLabel(key) {
  return ORDER_EVENT_LABELS[key] || String(key ?? "—");
}

// Plan audit-timeline event types -> display labels (append-only InputPlanEvent
// rows: the canonical history of the user's decisions on a plan).
export const PLAN_EVENT_LABELS = {
  submitted: "Submitted for quotes",
  quote_selected: "Quote selected",
  financing_offer_selected: "Indicative financing offer selected",
  financing_offer_declined: "Indicative financing offer declined",
  ordered: "Order placed",
  cancelled: "Plan cancelled",
};

export function planEventLabel(key) {
  return PLAN_EVENT_LABELS[key] || String(key ?? "—");
}

// Plan status -> the one next required action, shown on the landing-page rows
// and the plan-detail sub-line (shared so the two surfaces can never disagree).
export const PLAN_NEXT_STEP = {
  draft: "Review the items, then submit the plan for quotes.",
  submitted_for_quotes:
    "Quotes requested — the concierge is collecting supplier quotes for this plan.",
  quoted: "Compare the quotes and select one (your reason is recorded).",
  quote_selected: "Quote selected — place the order to move forward.",
  ordered: "Ordered — track delivery and application on the order page.",
  cancelled: "This plan was cancelled.",
};

export function planNextStep(status) {
  return PLAN_NEXT_STEP[status] || "";
}

// current_next_action machine key -> the specific button/action label.
// Why a risk model declined to answer. Mirrors app/disease_risk.py's ABSTAIN_*
// constants. Shown in full — an abstention with its reasons IS the useful artifact
// during the pilot, not an error to hide.
export const ABSTAIN_REASON_LABELS = {
  thresholds_not_supplied:
    "Published thresholds have not been transcribed from the primary source yet",
  no_snapshot_payload: "No input snapshot was available",
  unknown_model_version: "That model version is not registered",
  no_station_within_range: "No weather station close enough to this block",
  no_weather_in_window: "No weather readings in the lookback window",
  weather_gap_exceeds_limit: "Weather record has a gap wider than the limit",
  no_leaf_wetness_or_accepted_proxy: "No leaf-wetness data, and no accepted proxy",
  scouting_older_than_limit: "Most recent scouting sample is too old",
  no_scouting_sample_for_target: "No scouting sample for this target",
  conflicting_readings_same_hour:
    "Two stations disagree irreconcilably about the same hour",
  crop_or_target_outside_pilot_scope: "Crop or target is outside the pilot's scope",
  demo_or_simulated_input_present: "A demo/simulated input was present",
  input_observed_after_as_of:
    "An input is dated after the decision moment — this is a snapshot bug, not a data gap",
};

export function abstainReasonLabel(reason) {
  return ABSTAIN_REASON_LABELS[reason] || reason;
}

export const NEXT_ACTION_LABELS = {
  await_pca_review: "Review (PCA)",
  resolve_conflict: "Resolve conflict",
  inspect: "Inspect",
  record_outcome: "Record outcome",
  record_follow_up: "Record follow-up",
  none: "View record",
};

export function nextActionLabel(key) {
  return NEXT_ACTION_LABELS[key] || NEXT_ACTION_LABELS.none;
}

// Severity 1–5 -> explicit text label (never color alone).
export function severityLabel(value) {
  if (value == null) return "—";
  if (value >= 4) return `High (${value}/5)`;
  if (value === 3) return `Moderate (${value}/5)`;
  return `Low (${value}/5)`;
}
