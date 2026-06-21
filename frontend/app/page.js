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

  // CTA targets: first US farm (strawberry demo) and first Türkiye farm (tomato demo).
  const usFarm = farms.find((f) => (f.country || "").toUpperCase() !== "TR");
  const trFarm = farms.find((f) => (f.country || "").toUpperCase() === "TR");

  return (
    <div className="space-y-5">
      {/* Landing / positioning hero */}
      <section className="rounded-xl border bg-white p-6 shadow-sm">
        <h1 className="text-2xl font-bold">
          The pesticide decision &amp; compliance copilot
        </h1>
        <p className="mt-2 max-w-2xl text-sm text-gray-600">
          For <span className="font-medium">specialty-crop growers and their PCAs / agronomists</span>.
          Spray decisions are risky and records are messy — pre-harvest intervals, worker
          re-entry intervals, repeated active ingredients, residue limits, and buyer audits.
          Lumos helps you <span className="font-medium">spray less, avoid PHI/REI mistakes, and
          keep clean, PCA-reviewed records</span> — the decision layer <em>before</em> the spray.
        </p>

        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          {[
            ["👩‍🌾 Who it's for", "Specialty-crop growers + PCAs / agronomists"],
            ["⚠️ The pain", "PHI / REI risk, repeated chemistry, messy records, audits"],
            ["✅ The outcome", "Fewer sprays, cleaner compliance, a clear PCA review trail"],
          ].map(([h, b]) => (
            <div key={h} className="rounded-lg bg-gray-50 p-3">
              <div className="text-sm font-semibold">{h}</div>
              <div className="mt-1 text-xs text-gray-600">{b}</div>
            </div>
          ))}
        </div>

        <div className="mt-5 flex flex-wrap gap-3">
          {usFarm && (
            <Link
              href={`/farms/${usFarm.id}`}
              className="rounded-md bg-leaf px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-green-700"
            >
              🇺🇸 View U.S. strawberry demo
            </Link>
          )}
          {trFarm && (
            <Link
              href={`/farms/${trFarm.id}`}
              className="rounded-md border px-4 py-2 text-sm font-medium hover:border-leaf"
            >
              🇹🇷 View Türkiye greenhouse tomato demo
            </Link>
          )}
          <Link
            href="/pilot/new"
            className="rounded-md border px-4 py-2 text-sm font-medium hover:border-leaf"
          >
            ➕ Add pilot farm
          </Link>
          <Link
            href="/feedback"
            className="rounded-md border px-4 py-2 text-sm font-medium hover:border-leaf"
          >
            📝 Pilot feedback
          </Link>
        </div>
      </section>

      <div>
        <h2 className="text-xl font-semibold">Farms</h2>
        <p className="mt-1 text-sm text-gray-500">
          Open a farm to log sprays &amp; scouting, run compliance checks, and generate a
          cautious recommendation with PHI/REI checks and agronomist/PCA review.
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
