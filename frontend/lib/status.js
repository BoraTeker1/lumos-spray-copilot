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
    inspect_first: { label: "INSPECT FIRST", tone: "warn", icon: Search },
    pca_review_required: { label: "PCA REVIEW", tone: "info", icon: CircleHelp },
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
  // and an accepted offer is never a loan approval — the labels say so.
  financing: {
    cash: { label: "Cash", tone: "neutral", icon: Banknote },
    financing_requested: { label: "Financing requested", tone: "info", icon: CircleHelp },
    offer_received: { label: "Indicative offer received", tone: "info", icon: Landmark },
    offer_accepted: { label: "Accepted (indicative)", tone: "info", icon: Landmark },
    offer_declined_or_expired: {
      label: "Offer declined / expired", tone: "neutral", icon: Ban,
    },
  },
  // Financing offer state (offer_state). Accepted keeps the info tone — an
  // approval tone would imply approval, and none happened.
  offerState: {
    indicative: { label: "Indicative", tone: "info", icon: Landmark },
    accepted: { label: "Accepted (indicative)", tone: "info", icon: CircleCheck },
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

// current_next_action machine key -> the specific button/action label.
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
