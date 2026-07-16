// Single source of visual "tone" recipes so every surface colors the same
// semantic state the same way. Components look up a tone by domain value
// (decision outcome, review state, risk level, …) instead of declaring their
// own palette maps. Labels stay in lib/labels.js — this file is styling only.

export const TONES = {
  good: {
    badge: "green",
    box: "border-green-200 bg-green-50",
    text: "text-green-900",
    icon: "text-leaf",
    dot: "bg-leaf-100 text-leaf-700",
    bar: "bg-leaf",
  },
  warn: {
    badge: "amber",
    box: "border-amber-300 bg-amber-50",
    text: "text-amber-900",
    icon: "text-amber-600",
    dot: "bg-amber-100 text-amber-700",
    bar: "bg-amber-500",
  },
  risk: {
    badge: "red",
    box: "border-red-300 bg-red-50",
    text: "text-red-900",
    icon: "text-red-600",
    dot: "bg-red-100 text-red-700",
    bar: "bg-red-500",
  },
  info: {
    badge: "blue",
    box: "border-blue-200 bg-blue-50",
    text: "text-blue-900",
    icon: "text-blue-600",
    dot: "bg-blue-100 text-blue-700",
    bar: "bg-blue-500",
  },
  neutral: {
    badge: "neutral",
    box: "border-gray-200 bg-gray-50",
    text: "text-gray-700",
    icon: "text-gray-400",
    dot: "bg-gray-100 text-gray-600",
    bar: "bg-gray-400",
  },
};

export function tone(name) {
  return TONES[name] || TONES.neutral;
}

// Engine decision outcomes (the check's verdict).
export const DECISION_OUTCOME_TONES = {
  approve: "good",
  block: "risk",
  delay: "warn",
  inspect_first: "warn",
  pca_review_required: "info",
};

// Recorded real-world outcomes (what the humans actually did).
export const RECORDED_OUTCOME_TONES = {
  sprayed_as_planned: "neutral",
  changed_product: "info",
  delayed: "warn",
  avoided: "good",
  inspected_first: "good",
};

// Derived review states (server-computed `review_state`).
export const REVIEW_STATE_TONES = {
  approved: "good",
  edited: "info",
  rejected: "risk",
  pending: "warn",
  not_required: "neutral",
  none: "neutral",
};

// Recommendation / weather risk levels.
export const RISK_LEVEL_TONES = {
  low: "good",
  moderate: "warn",
  elevated: "risk",
};

// Input-value provenance source types (DecisionInputValue.source_type).
export const SOURCE_TYPE_TONES = {
  pca_verified: "good",
  authoritative_provider: "good",
  imported_unverified: "warn",
  user_entered: "neutral",
  demo: "neutral",
};

// Farm urgency (server-computed by /farms-overview).
export const URGENCY_TONES = {
  conflict: "risk",
  harvest_overdue: "risk",
  needs_review: "warn",
  awaiting_outcome: "warn",
  flags: "warn",
  ok: "neutral",
};
