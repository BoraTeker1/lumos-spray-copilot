"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { formatCost, formatDate, formatArea } from "@/lib/format";
import RiskBadge from "@/components/RiskBadge";

// Small flag + crop hint so US vs. Türkiye farms are visible at a glance.
function cropIcon(crop) {
  return (crop || "").toLowerCase().startsWith("straw") ? "🍓" : "🍅";
}
function countryFlag(country) {
  return (country || "").toUpperCase() === "TR" ? "🇹🇷" : "🇺🇸";
}

// Dashboard: lists all farms with a quick summary (risk + pesticide spend).
export default function DashboardPage() {
  const [farms, setFarms] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    async function load() {
      try {
        const list = await api.listFarms();
        // Enrich each farm with its latest risk + spend for the card summary.
        const enriched = await Promise.all(
          list.map(async (farm) => {
            const [sprays, recs] = await Promise.all([
              api.listSprayEvents(farm.id),
              api.listRecommendations(farm.id),
            ]);
            return {
              ...farm,
              totalCost: sprays.reduce((sum, s) => sum + (s.cost || 0), 0),
              sprayCount: sprays.length,
              latestRisk: recs[0]?.risk_level || null,
            };
          })
        );
        setFarms(enriched);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold">Specialty-crop farms</h1>
        <p className="mt-1 text-sm text-gray-500">
          Pesticide decision &amp; compliance copilot — log sprays &amp; scouting, then generate
          a cautious recommendation with PHI/REI checks and agronomist/PCA review.
        </p>
      </div>

      {loading && (
        <p className="text-sm text-gray-500">Loading farms…</p>
      )}
      {error && (
        <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error} — is the backend running on <code>http://localhost:8000</code>?
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        {farms.map((farm) => (
          <Link
            key={farm.id}
            href={`/farms/${farm.id}`}
            className="group block rounded-lg border bg-white p-5 shadow-sm transition hover:border-leaf hover:shadow-md"
          >
            <div className="flex items-start justify-between gap-2">
              <div>
                <h2 className="font-semibold group-hover:text-leaf">
                  {countryFlag(farm.country)} {farm.name}
                </h2>
                <p className="text-sm text-gray-500">📍 {farm.location}</p>
              </div>
              <RiskBadge level={farm.latestRisk} />
            </div>

            <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
              <div className="rounded bg-gray-50 p-2">
                <div className="text-xs text-gray-500">Pesticide spend</div>
                <div className="font-semibold">{formatCost(farm.totalCost, farm.country)}</div>
              </div>
              <div className="rounded bg-gray-50 p-2">
                <div className="text-xs text-gray-500">Sprays logged</div>
                <div className="font-semibold">{farm.sprayCount}</div>
              </div>
            </div>

            <p className="mt-3 text-xs text-gray-500">
              {cropIcon(farm.crop_type)} {farm.crop_type?.replace(/_/g, " ")}
              {farm.greenhouse_area != null && ` · ${formatArea(farm.greenhouse_area, farm.country)}`}
              {" · "}harvest {formatDate(farm.expected_harvest_date)}
            </p>
          </Link>
        ))}
      </div>

      {!loading && !error && farms.length === 0 && (
        <div className="rounded border bg-white p-4 text-sm text-gray-500">
          No farms yet. Seed the demo data:{" "}
          <code>cd backend &amp;&amp; python -m app.seed</code>
        </div>
      )}
    </div>
  );
}
