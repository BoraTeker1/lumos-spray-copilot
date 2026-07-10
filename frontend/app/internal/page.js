"use client";

import { useEffect, useState } from "react";
import ConciergePilotCard from "@/components/ConciergePilotCard";
import { api } from "@/lib/api";

// INTERNAL tooling — deliberately not linked from the app navigation.
// Concierge import: a team member manually transcribes pilot data collected from
// calls / WhatsApp / spreadsheets / email into an existing farm, with provenance tags.
// The customer-facing workflow is the pre-spray decision check on the farm page.
function InstrumentationSummary() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.getInstrumentation().then(setData).catch((err) => setError(err.message));
  }, []);

  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (!data) return <p className="text-sm text-gray-500">Loading telemetry…</p>;

  const rows = [
    ["Checks started (client-reported)", data.checks_started],
    ["Checks completed", data.checks_completed],
    ["Checks abandoned", data.checks_abandoned],
    ["Abandonment rate", data.abandonment_rate_pct != null ? `${data.abandonment_rate_pct}%` : "—"],
    [
      "Median time to PCA review",
      data.median_seconds_to_pca_review != null
        ? `${Math.round(data.median_seconds_to_pca_review / 60)} min`
        : "—",
    ],
    ["Outcomes recorded", data.outcomes_recorded],
    ["Decisions changed (not sprayed as planned)", data.decisions_changed],
    [
      "Entry sources",
      Object.entries(data.entry_source_breakdown || {})
        .map(([k, n]) => `${k.replace(/_/g, " ")}: ${n}`)
        .join(" · ") || "—",
    ],
  ];

  return (
    <div>
      <dl className="divide-y divide-gray-100 text-sm">
        {rows.map(([label, value]) => (
          <div key={label} className="flex justify-between gap-3 py-1.5">
            <dt className="text-gray-500">{label}</dt>
            <dd className="text-right font-medium text-gray-900">{value}</dd>
          </div>
        ))}
      </dl>
      <ul className="mt-2 space-y-0.5 text-[11px] text-gray-400">
        {(data.notes || []).map((n, i) => (
          <li key={i}>• {n}</li>
        ))}
      </ul>
    </div>
  );
}

export default function InternalToolsPage() {
  const [farms, setFarms] = useState([]);
  const [farmId, setFarmId] = useState("");
  const [error, setError] = useState(null);

  useEffect(() => {
    api
      .listFarms()
      .then((list) => {
        setFarms(list);
        if (list.length > 0) setFarmId(String(list[0].id));
      })
      .catch((err) => setError(err.message));
  }, []);

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-gray-900">Internal tools</h1>
        <p className="mt-0.5 max-w-2xl text-xs text-gray-500">
          Operator-only concierge tooling. Not part of the customer-facing workflow and not
          linked from the navigation.
        </p>
      </div>

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error} — is the backend running on <code>http://localhost:8000</code>?
        </div>
      )}

      <section className="rounded-lg border bg-white p-5 shadow-sm">
        <h2 className="font-semibold">Pilot instrumentation</h2>
        <p className="mb-3 mt-1 text-xs text-gray-500">
          Workflow telemetry for running a real pilot: the check funnel, review latency,
          changed decisions, and how data gets entered. Never customer-facing.
        </p>
        <InstrumentationSummary />
      </section>

      <section className="rounded-lg border bg-white p-5 shadow-sm">
        <h2 className="font-semibold">Concierge import</h2>
        <p className="mb-3 mt-1 text-xs text-gray-500">
          Manually transcribe pilot data (calls, WhatsApp, spreadsheets, email) into an
          existing farm, with provenance tags on every row.
        </p>
        {farms.length === 0 ? (
          <p className="text-sm text-gray-500">No farms yet — create one first.</p>
        ) : (
          <>
            <label className="mb-4 block text-xs font-medium text-gray-600">
              Target farm
              <select
                className="mt-1 w-full max-w-sm rounded border px-2 py-1.5 text-sm"
                value={farmId}
                onChange={(e) => setFarmId(e.target.value)}
              >
                {farms.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.name}
                  </option>
                ))}
              </select>
            </label>
            {farmId && (
              <ConciergePilotCard
                key={farmId}
                farmId={farmId}
                country={farms.find((f) => String(f.id) === farmId)?.country || "US"}
              />
            )}
          </>
        )}
      </section>
    </div>
  );
}
