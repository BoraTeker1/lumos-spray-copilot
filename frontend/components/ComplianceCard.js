import { CircleCheck, TriangleAlert } from "lucide-react";
import { Badge } from "@/components/ui/badge";

// One compliance signal row: neutral check when OK, amber warning when at risk.
function Row({ label, danger, okText = "OK", warnText = "Review" }) {
  return (
    <div className="flex items-center justify-between gap-2 border-b border-gray-100 py-1.5 last:border-0">
      <span className="text-xs text-gray-600">{label}</span>
      <span
        className={`inline-flex shrink-0 items-center gap-1 text-xs font-medium ${
          danger ? "text-amber-700" : "text-gray-500"
        }`}
      >
        {danger ? <TriangleAlert className="h-3.5 w-3.5" /> : <CircleCheck className="h-3.5 w-3.5" />}
        {danger ? warnText : okText}
      </span>
    </div>
  );
}

const REVIEW_VARIANTS = {
  approved: "green",
  edited: "indigo",
  rejected: "red",
  pending: "amber",
  none: "neutral",
};

// Compact compliance snapshot for the right rail. Receives `data` from the page
// (the farm detail page already fetches /compliance for the header KPIs).
export default function ComplianceCard({ data }) {
  if (!data) return <p className="text-sm text-gray-500">Loading compliance…</p>;

  return (
    <div>
      <div>
        <Row label="Pre-harvest interval (PHI)" danger={data.phi_risk} warnText="At risk" />
        <Row label="Re-entry interval (REI)" danger={data.rei_risk} warnText="May be active" />
        <Row
          label="Repeated ingredient / resistance"
          danger={data.repeated_active_ingredient_risk}
          warnText="Repeated"
        />
        <Row
          label={`Scouting pressure${
            data.max_recent_severity ? ` (max ${data.max_recent_severity}/5)` : ""
          }`}
          danger={data.high_severity_scouting}
          warnText="High"
          okText="Low"
        />
      </div>
      {/* Pre-spray decision reviews (the canonical decision-queue state) — kept
          strictly separate from the weekly recommendation's review status so an
          edited decision can never read as "review: none". */}
      {data.decision_review && (
        <div className="mt-2 border-t border-gray-100 pt-2">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs text-gray-600">Pre-spray decisions</span>
            <Badge variant={data.decision_review.needs_review_count > 0 ? "amber" : "neutral"}>
              {data.decision_review.needs_review_count > 0
                ? `${data.decision_review.needs_review_count} pending review`
                : "none pending"}
            </Badge>
          </div>
          <p className="mt-1 text-[11px] text-gray-500">
            {data.decision_review.approved} approved · {data.decision_review.edited} edited ·{" "}
            {data.decision_review.rejected} rejected
          </p>
        </div>
      )}
      <div className="mt-2 flex items-center justify-between border-t border-gray-100 pt-2">
        <span className="text-xs text-gray-600">
          Weekly review (recommendations)
        </span>
        <Badge variant={REVIEW_VARIANTS[data.recommendation_review_status] || "neutral"}>
          {data.recommendation_review_status}
        </Badge>
      </div>
    </div>
  );
}
