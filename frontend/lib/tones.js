// Single source of visual "tone" recipes so every surface colors the same
// semantic state the same way. Components look up a tone by domain value
// (decision outcome, review state, risk level, …) instead of declaring their
// own palette maps. Labels stay in lib/labels.js — this file is styling only.
//
// Colors resolve through the semantic token pairs in tailwind.config.js
// (ok / risk / warn / inspect / review / info / draft). Badge variant KEYS keep
// their historical color names ("green", "amber", …) so the ~45 existing
// call sites re-skin without edits; the values behind them are the tokens.

export const TONES = {
  good: {
    badge: "green",
    box: "border-ok-line bg-ok-bg",
    text: "text-ok-fg",
    icon: "text-ok-fg",
    dot: "bg-ok-bg text-ok-fg",
    bar: "bg-leaf",
  },
  warn: {
    badge: "amber",
    box: "border-warn-line bg-warn-bg",
    text: "text-warn-fg",
    icon: "text-warn-fg",
    dot: "bg-warn-bg text-warn-fg",
    bar: "bg-warn-fg",
  },
  // Distinct from `warn`: "go look at it first" is a different instruction
  // from "this is late". The spec gives them separate swatches.
  inspect: {
    badge: "inspect",
    box: "border-inspect-line bg-inspect-bg",
    text: "text-inspect-fg",
    icon: "text-inspect-fg",
    dot: "bg-inspect-bg text-inspect-fg",
    bar: "bg-inspect-fg",
  },
  risk: {
    badge: "red",
    box: "border-risk-line bg-risk-bg",
    text: "text-risk-fg",
    icon: "text-risk-fg",
    dot: "bg-risk-bg text-risk-fg",
    bar: "bg-risk-fg",
  },
  info: {
    badge: "blue",
    box: "border-info-line bg-info-bg",
    text: "text-info-fg",
    icon: "text-info-fg",
    dot: "bg-info-bg text-info-fg",
    bar: "bg-info-fg",
  },
  // "A licensed human must sign this" — deliberately NOT info blue, so a
  // pending professional act never reads as an FYI.
  review: {
    badge: "purple",
    box: "border-review-line bg-review-bg",
    text: "text-review-fg",
    icon: "text-review-fg",
    dot: "bg-review-bg text-review-fg",
    bar: "bg-review-fg",
  },
  neutral: {
    badge: "neutral",
    box: "border-line bg-draft-bg",
    text: "text-draft-fg",
    icon: "text-muted",
    dot: "bg-draft-bg text-draft-fg",
    bar: "bg-muted",
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
  inspect_first: "inspect",
  pca_review_required: "review",
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
