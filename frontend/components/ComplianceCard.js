import { CircleCheck, TriangleAlert } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { REVIEW_STATE_TONES, tone } from "@/lib/tones";

// One compliance signal row: green pill when OK, amber pill when at risk. The
// wording stays cautious ("May be active", not "violation") — the signals may
// come from user-entered values or from a PCA-verified label, and the card says
// which via the server-owned `basis_text` below rather than assuming either.
function Row({ label, danger, okText = "OK", warnText = "Review" }) {
  return (
    <div className="flex items-center justify-between gap-2 border-b border-line py-1.5 last:border-0">
      <span className="text-xs text-muted">{label}</span>
      <Badge variant={danger ? "amber" : "green"} className="shrink-0 uppercase">
        {danger ? <TriangleAlert /> : <CircleCheck />}
        {danger ? warnText : okText}
      </Badge>
    </div>
  );
}

const REVIEW_VARIANTS = Object.fromEntries(
  Object.entries(REVIEW_STATE_TONES).map(([k, t]) => [k, tone(t).badge])
);

// Compact compliance snapshot for the right rail. Receives `data` from the page
// (the farm detail page already fetches /compliance for the header KPIs).
export default function ComplianceCard({ data }) {
  if (!data) return <p className="text-sm text-muted">Loading compliance…</p>;

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
        <div className="mt-2 border-t border-line pt-2">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs text-muted">Pre-spray decisions</span>
            <Badge variant={data.decision_review.needs_review_count > 0 ? "amber" : "neutral"}>
              {data.decision_review.needs_review_count > 0
                ? `${data.decision_review.needs_review_count} pending review`
                : "none pending"}
            </Badge>
          </div>
          <p className="mt-1 text-[11px] text-muted">
            {data.decision_review.approved} approved · {data.decision_review.edited} edited ·{" "}
            {data.decision_review.rejected} rejected
          </p>
        </div>
      )}
      <div className="mt-2 flex items-center justify-between border-t border-line pt-2">
        <span className="text-xs text-muted">
          Weekly review (recommendations)
        </span>
        <Badge variant={REVIEW_VARIANTS[data.recommendation_review_status] || "neutral"}>
          {data.recommendation_review_status}
        </Badge>
      </div>
      {/* Server-owned basis sentence. Four surfaces used to hardcode their own
          wording, which could drift apart and could never become conditional.
          The fallback is the pre-label wording, byte-for-byte. */}
      <p className="mt-2 border-t border-line pt-2 text-[11px] leading-snug text-muted">
        {data.basis_text ||
          "These signals come from PHI/REI values entered by the user, not from verified label data. Confirm them against the product label and a licensed PCA."}
      </p>
    </div>
  );
}
