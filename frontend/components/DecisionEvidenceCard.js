"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { formatCost } from "@/lib/format";

// One labelled metric tile (same look as PilotEvidenceCard's).
function Metric({ label, value, hint }) {
  return (
    <div className="rounded-lg border bg-white p-3">
      <div className="text-xs text-gray-500">{label}</div>
      <div className="mt-0.5 text-lg font-semibold">{value}</div>
      {hint && <div className="text-[11px] text-gray-400">{hint}</div>}
    </div>
  );
}

// Pre-spray decision workflow metrics: decisions reviewed, sprays changed/delayed/
// avoided, conflicts caught, PCA acceptance, and the (assumption-based) review time.
// Demo/simulated decisions are excluded server-side; every caveat is shown.
export default function DecisionEvidenceCard({ farmId, country, refreshKey }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api
      .getDecisionEvidence(farmId)
      .then(setData)
      .catch((err) => setError(err.message));
  }, [farmId, refreshKey]);

  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (!data) return <p className="text-sm text-gray-500">Loading decision evidence…</p>;

  const o = data.outcomes || {};
  const acceptance =
    data.pca_acceptance_rate_pct != null ? `${data.pca_acceptance_rate_pct}%` : "—";

  return (
    <div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <Metric label="Decisions checked" value={data.decisions_checked} />
        <Metric
          label="Decisions PCA-reviewed"
          value={`${data.decisions_reviewed} / ${data.decisions_checked}`}
        />
        <Metric
          label="PCA acceptance rate"
          value={acceptance}
          hint="approved or edited, of reviewed"
        />
        <Metric
          label="Sprays changed / delayed / avoided"
          value={data.sprays_changed_delayed_or_avoided}
          hint={`${o.changed_product ?? 0} changed · ${o.delayed ?? 0} delayed · ${o.avoided ?? 0} avoided`}
        />
        <Metric
          label="Compliance conflicts caught"
          value={data.compliance_conflicts_caught}
          hint="critical PHI/REI conflicts, pre-application"
        />
        <Metric
          label="Est. chemical cost avoided"
          value={
            data.estimated_chemical_cost_avoided
              ? formatCost(data.estimated_chemical_cost_avoided, country)
              : "—"
          }
          hint="entered estimates of avoided applications"
        />
      </div>

      <p className="mt-2 text-xs text-gray-500">
        Est. review time: ~{data.estimated_review_minutes_saved} min.{" "}
        {data.review_minutes_assumption}
      </p>

      {data.demo_decisions_checked > 0 && (
        <p className="mt-2 rounded bg-gray-50 px-3 py-2 text-xs text-gray-600">
          Simulated demo decisions on this farm: {data.demo_decisions_checked} (
          {Object.entries(data.demo_outcomes || {})
            .filter(([, n]) => n > 0)
            .map(([k, n]) => `${n} ${k.replace(/_/g, " ")}`)
            .join(", ") || "no outcome yet"}
          ) — visible in the decision queue but excluded from every number above.
        </p>
      )}

      {data.limitations?.length > 0 && (
        <ul className="mt-2 space-y-0.5 rounded bg-amber-50 px-3 py-2 text-[11px] text-amber-800">
          {data.limitations.map((l, i) => (
            <li key={i}>• {l}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
