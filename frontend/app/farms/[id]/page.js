"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api, API_BASE_URL } from "@/lib/api";
import { formatCost, formatDate, formatArea } from "@/lib/format";
import SprayEventForm from "@/components/SprayEventForm";
import ScoutObservationForm from "@/components/ScoutObservationForm";
import RecommendationPanel from "@/components/RecommendationPanel";
import WeeklyReport from "@/components/WeeklyReport";
import RiskBadge from "@/components/RiskBadge";
import SeverityBadge from "@/components/SeverityBadge";
import AnalyticsCard from "@/components/AnalyticsCard";
import WeatherCard from "@/components/WeatherCard";
import ComplianceCard from "@/components/ComplianceCard";
import PilotEvidenceCard from "@/components/PilotEvidenceCard";

// Small stat card used in the farm header.
function Stat({ label, value }) {
  return (
    <div className="rounded-lg border bg-white p-3 shadow-sm">
      <div className="text-xs text-gray-500">{label}</div>
      <div className="mt-0.5 text-lg font-semibold">{value}</div>
    </div>
  );
}

// Farm detail: records, forms, recommendation panel, and weekly report.
export default function FarmDetailPage({ params }) {
  const farmId = params.id;
  const [farm, setFarm] = useState(null);
  const [sprays, setSprays] = useState([]);
  const [observations, setObservations] = useState([]);
  const [recommendations, setRecommendations] = useState([]);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    try {
      const [f, s, o, r] = await Promise.all([
        api.getFarm(farmId),
        api.listSprayEvents(farmId),
        api.listScoutObservations(farmId),
        api.listRecommendations(farmId),
      ]);
      setFarm(f);
      setSprays(s);
      setObservations(o);
      setRecommendations(r);
    } catch (err) {
      setError(err.message);
    }
  }, [farmId]);

  useEffect(() => {
    load();
  }, [load]);

  if (error)
    return (
      <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
        {error} — is the backend running on <code>http://localhost:8000</code>?
      </div>
    );
  if (!farm) return <p className="text-sm text-gray-500">Loading…</p>;

  const totalCost = sprays.reduce((sum, s) => sum + (s.cost || 0), 0);
  const latestRisk = recommendations[0]?.risk_level || null;

  return (
    <div className="space-y-6">
      <div>
        <Link href="/" className="text-sm text-leaf hover:underline">
          ← Back to farms
        </Link>
        <div className="mt-1 flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold">{farm.name}</h1>
          <RiskBadge level={latestRisk} />
        </div>
        <p className="text-sm text-gray-500">
          📍 {farm.location} · {farm.crop_type?.replace(/_/g, " ")}
          {farm.greenhouse_area != null && ` · ${formatArea(farm.greenhouse_area, farm.country)}`}
        </p>
      </div>

      {/* Summary stats */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Pesticide spend" value={formatCost(totalCost, farm.country)} />
        <Stat label="Sprays logged" value={sprays.length} />
        <Stat label="Scouting notes" value={observations.length} />
        <Stat label="Expected harvest" value={formatDate(farm.expected_harvest_date)} />
      </div>

      {/* Recommendation */}
      <section className="rounded-lg border bg-white p-5 shadow-sm">
        <RecommendationPanel
          farmId={farmId}
          latest={recommendations[0] || null}
          onChanged={load}
        />
      </section>

      {/* Compliance snapshot (PHI / REI / resistance / scouting / weather / review) */}
      <section className="rounded-lg border bg-white p-5 shadow-sm">
        <ComplianceCard farmId={farmId} refreshKey={`${sprays.length}-${recommendations[0]?.agronomist_status || ""}`} />
      </section>

      {/* Pilot evidence + audit packet */}
      <section className="rounded-lg border bg-white p-5 shadow-sm">
        <PilotEvidenceCard
          farmId={farmId}
          country={farm.country}
          refreshKey={`${sprays.length}-${observations.length}-${recommendations.length}-${recommendations[0]?.agronomist_status || ""}`}
        />
      </section>

      {/* Weather risk + cost analytics */}
      <div className="grid gap-5 md:grid-cols-2">
        <section className="rounded-lg border bg-white p-5 shadow-sm">
          <WeatherCard farmId={farmId} />
        </section>
        <section className="rounded-lg border bg-white p-5 shadow-sm">
          <AnalyticsCard farmId={farmId} country={farm.country} refreshKey={sprays.length} />
        </section>
      </div>

      {/* Data-entry forms */}
      <div className="grid gap-5 md:grid-cols-2">
        <section className="rounded-lg border bg-white p-5 shadow-sm">
          <h2 className="mb-3 font-semibold">💧 Log spray event</h2>
          <SprayEventForm farmId={farmId} onCreated={load} />
        </section>
        <section className="rounded-lg border bg-white p-5 shadow-sm">
          <h2 className="mb-3 font-semibold">🔍 Log scouting note</h2>
          <ScoutObservationForm farmId={farmId} onCreated={load} />
        </section>
      </div>

      {/* History */}
      <div className="grid gap-5 md:grid-cols-2">
        <section className="rounded-lg border bg-white p-5 shadow-sm">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="font-semibold">Spray history</h2>
            <div className="flex gap-2 text-xs">
              <a href={`${API_BASE_URL}/farms/${farmId}/export/spray-events.csv`} className="rounded border px-2 py-1 hover:border-leaf">
                ⬇ Sprays CSV
              </a>
              <a href={`${API_BASE_URL}/farms/${farmId}/export/recommendations.csv`} className="rounded border px-2 py-1 hover:border-leaf">
                ⬇ Recs CSV
              </a>
            </div>
          </div>
          <ul className="space-y-2 text-sm">
            {sprays.map((s) => (
              <li key={s.id} className="flex items-start justify-between gap-2 border-b pb-2 last:border-0">
                <div>
                  <div className="font-medium">{s.product_name}</div>
                  <div className="text-xs text-gray-500">
                    {formatDate(s.application_date)}
                    {s.active_ingredient && ` · ${s.active_ingredient}`}
                    {s.pre_harvest_interval_days != null &&
                      ` · PHI ${s.pre_harvest_interval_days}d`}
                    {s.re_entry_interval_hours != null &&
                      ` · REI ${s.re_entry_interval_hours}h`}
                  </div>
                </div>
                <div className="shrink-0 text-sm font-medium text-gray-700">
                  {formatCost(s.cost, farm.country)}
                </div>
              </li>
            ))}
            {sprays.length === 0 && (
              <li className="text-gray-500">No sprays recorded.</li>
            )}
          </ul>
        </section>

        <section className="rounded-lg border bg-white p-5 shadow-sm">
          <h2 className="mb-3 font-semibold">Scouting history</h2>
          <ul className="space-y-2 text-sm">
            {observations.map((o) => (
              <li key={o.id} className="border-b pb-2 last:border-0">
                <div className="flex items-center gap-2">
                  <span className="font-medium">
                    {o.visible_issue || "Observation"}
                  </span>
                  <SeverityBadge value={o.severity_1_to_5} />
                </div>
                <div className="text-xs text-gray-500">
                  {formatDate(o.observation_date)}
                  {o.crop_stage && ` · ${o.crop_stage}`}
                </div>
              </li>
            ))}
            {observations.length === 0 && (
              <li className="text-gray-500">No scouting notes recorded.</li>
            )}
          </ul>
        </section>
      </div>

      {/* Weekly report */}
      <section className="rounded-lg border bg-white p-5 shadow-sm">
        <WeeklyReport farmId={farmId} />
      </section>
    </div>
  );
}
