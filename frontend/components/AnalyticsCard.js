"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { formatCost } from "@/lib/format";

// Pesticide cost analytics for one farm. `refreshKey` re-fetches when records change.
// `hasDocumentedSkip`: only call the figure "avoidable" when a planned spray was
// actually documented as skipped; otherwise it is just the cost of one application.
export default function AnalyticsCard({ farmId, country, refreshKey, hasDocumentedSkip = false }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api
      .getAnalytics(farmId)
      .then(setData)
      .catch((err) => setError(err.message));
  }, [farmId, refreshKey]);

  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (!data) return <p className="text-sm text-gray-500">Loading analytics…</p>;

  const rows = [
    { label: "Total pesticide spend (cycle)", value: formatCost(data.total_spend, country) },
    { label: "Average cost per spray", value: formatCost(data.average_cost_per_spray, country) },
    {
      label: "Most-used active ingredient",
      value: data.most_used_active_ingredient
        ? `${data.most_used_active_ingredient} (×${data.most_used_count})`
        : "—",
    },
    { label: "Sprays in last 30 days", value: data.sprays_last_30_days },
    {
      label: "Cost of repeated-ingredient sprays",
      value: formatCost(data.repeated_ingredient_cost, country),
    },
  ];

  return (
    <div>
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {rows.map((r) => (
          <div key={r.label} className="rounded bg-gray-50 p-3">
            <dt className="text-xs text-gray-500">{r.label}</dt>
            <dd className="mt-0.5 text-base font-semibold">{r.value}</dd>
          </div>
        ))}
      </dl>

      <div className="mt-3 rounded-md border border-gray-200 bg-gray-50 p-3 text-sm text-gray-700">
        <span className="font-medium">
          {formatCost(data.potential_avoidable_cost, country)}
        </span>{" "}
        {hasDocumentedSkip
          ? "— potential avoidable cost: a planned spray was documented as skipped (based on your average spray cost). This is an estimate, not a guaranteed saving."
          : "— estimated cost of one planned application (based on your average spray cost). This is an estimate, not a saving claim."}
      </div>
    </div>
  );
}
