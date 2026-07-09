"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { CalendarClock, Droplets, FlaskConical, MapPin, Plus } from "lucide-react";
import { api } from "@/lib/api";
import { formatArea, formatDate } from "@/lib/format";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import RiskBadge from "@/components/RiskBadge";

// Demo ordering: lead with the U.S. strawberry wedge demo, keep Türkiye tomato
// farms secondary. Rank = (TR after US) + (non-strawberry after strawberry).
function sortForDemo(farms) {
  const rank = (f) => {
    const isTR = (f.country || "").toUpperCase() === "TR";
    const isStrawberry = (f.crop_type || "").toLowerCase().startsWith("straw");
    return (isTR ? 10 : 0) + (isStrawberry ? 0 : 1);
  };
  return [...farms].sort((a, b) => rank(a) - rank(b) || a.id - b.id);
}

function isDemoRecord(r) {
  return r.data_source === "demo" || r.data_confidence === "simulated";
}

// Farms list: the operational entry point. Open a farm to run pre-spray checks,
// review compliance, and build pilot evidence.
export default function DashboardPage() {
  const [farms, setFarms] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    async function load() {
      try {
        const list = await api.listFarms();
        const enriched = await Promise.all(
          list.map(async (farm) => {
            const [sprays, recs] = await Promise.all([
              api.listSprayEvents(farm.id),
              api.listRecommendations(farm.id),
            ]);
            return {
              ...farm,
              sprayCount: sprays.length,
              latestRisk: recs[0]?.risk_level || null,
              isDemo: sprays.length > 0 && sprays.every(isDemoRecord),
            };
          })
        );
        setFarms(sortForDemo(enriched));
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
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-gray-900">Farms</h1>
          <p className="mt-0.5 max-w-2xl text-xs text-gray-500">
            The decision layer before the spray: check planned applications, avoid PHI/REI
            mistakes, and keep PCA-reviewed, audit-ready records.
          </p>
        </div>
        <Link
          href="/pilot/new"
          className="inline-flex h-9 items-center gap-2 rounded-md bg-leaf px-4 text-sm font-medium text-white shadow-sm hover:bg-green-700"
        >
          <Plus className="h-4 w-4" />
          Add pilot farm
        </Link>
      </div>

      {loading && <p className="text-sm text-gray-500">Loading farms…</p>}
      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error} — is the backend running on <code>http://localhost:8000</code>?
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {farms.map((farm) => (
          <Link key={farm.id} href={`/farms/${farm.id}`} className="group block">
            <Card className="h-full transition-colors group-hover:border-gray-300">
              <CardContent className="p-4">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-semibold text-gray-900">
                      {farm.name}
                    </div>
                    <div className="mt-0.5 flex items-center gap-1 text-xs text-gray-500">
                      <MapPin className="h-3 w-3 shrink-0" />
                      <span className="truncate">
                        {farm.location || "—"} · {(farm.country || "US").toUpperCase()}
                      </span>
                    </div>
                  </div>
                  <RiskBadge level={farm.latestRisk} />
                </div>

                <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-500">
                  <span className="capitalize">{farm.crop_type?.replace(/_/g, " ")}</span>
                  {farm.greenhouse_area != null && (
                    <span>{formatArea(farm.greenhouse_area, farm.country)}</span>
                  )}
                  <span className="inline-flex items-center gap-1">
                    <Droplets className="h-3 w-3" />
                    {farm.sprayCount} sprays
                  </span>
                  <span className="inline-flex items-center gap-1">
                    <CalendarClock className="h-3 w-3" />
                    harvest {formatDate(farm.expected_harvest_date)}
                  </span>
                </div>

                {farm.isDemo && (
                  <div className="mt-3">
                    <Badge variant="outline">
                      <FlaskConical />
                      Simulated demo data
                    </Badge>
                  </div>
                )}
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>

      {!loading && !error && farms.length === 0 && (
        <div className="rounded-md border border-gray-200 bg-white p-4 text-sm text-gray-500">
          No farms yet. Seed the demo data: <code>cd backend &amp;&amp; python -m app.seed</code>
        </div>
      )}
    </div>
  );
}
