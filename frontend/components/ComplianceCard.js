"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

// A red/green row for a single compliance signal.
function Row({ label, danger, okText = "OK", warnText = "Review" }) {
  return (
    <div className="flex items-center justify-between border-b py-1.5 last:border-0">
      <span className="text-sm text-gray-700">{label}</span>
      <span
        className={`rounded-full px-2 py-0.5 text-xs font-medium ${
          danger ? "bg-red-100 text-red-800" : "bg-green-100 text-green-800"
        }`}
      >
        {danger ? `⚠️ ${warnText}` : `✓ ${okText}`}
      </span>
    </div>
  );
}

const REVIEW_STYLES = {
  approved: "bg-green-100 text-green-800",
  edited: "bg-indigo-100 text-indigo-800",
  rejected: "bg-red-100 text-red-800",
  pending: "bg-amber-100 text-amber-800",
  none: "bg-gray-100 text-gray-600",
};

// U.S.-style compliance snapshot: PHI, REI, resistance, scouting, weather, review trail.
// `refreshKey` re-fetches when records change.
export default function ComplianceCard({ farmId, refreshKey }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api
      .getCompliance(farmId)
      .then(setData)
      .catch((err) => setError(err.message));
  }, [farmId, refreshKey]);

  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (!data) return <p className="text-sm text-gray-500">Loading compliance…</p>;

  const reviewCls = REVIEW_STYLES[data.review_status] || REVIEW_STYLES.none;

  return (
    <div>
      <h2 className="mb-3 font-semibold">🛡️ Compliance snapshot</h2>
      <div className="rounded-lg border bg-white">
        <div className="px-3">
          <Row label="Pre-harvest interval (PHI)" danger={data.phi_risk} warnText="At risk" />
          <Row label="Worker re-entry interval (REI)" danger={data.rei_risk} warnText="May be active" />
          <Row
            label="Repeated active ingredient / resistance"
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
          <Row
            label="Weather disease pressure"
            danger={data.weather_risk_level === "elevated"}
            warnText="Elevated"
            okText={data.weather_risk_level === "moderate" ? "Moderate" : "Low"}
          />
        </div>
        <div className="flex items-center justify-between border-t bg-gray-50 px-3 py-2">
          <span className="text-sm text-gray-700">
            {data.advisor_label} review status
          </span>
          <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${reviewCls}`}>
            {data.review_status}
          </span>
        </div>
      </div>
      <p className="mt-2 text-xs text-gray-500">
        Decision support only. Always confirm PHI, REI, rates, crop use, and restrictions with
        the product label and a licensed {data.advisor_label}.
      </p>
    </div>
  );
}
