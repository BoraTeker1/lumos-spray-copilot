"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  CalendarClock,
  Droplets,
  FlaskConical,
  MapPin,
  Plus,
  RotateCcw,
} from "lucide-react";
import { api } from "@/lib/api";
import { formatArea, formatDate } from "@/lib/format";
import { URGENCY_META } from "@/lib/labels";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";

// Farms ranked by what needs attention: which farm, why, and the next action.
// The YC demo is the California strawberry / PCA workflow only: secondary-market
// demo farms (Türkiye greenhouse tomatoes) never render here — they stay seeded and
// reachable by direct URL, but there is deliberately no link or toggle to them.
// Real (non-demo) farms always show.
function isSecondaryDemoFarm(f) {
  return f.is_demo && (f.country || "").toUpperCase() !== "US";
}

export default function DashboardPage() {
  const [farms, setFarms] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [resetting, setResetting] = useState(false);
  const [resetError, setResetError] = useState(null);

  const loadFarms = () =>
    api
      .listFarmsOverview()
      .then(setFarms)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));

  useEffect(() => {
    loadFarms();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function resetDemo() {
    if (
      !window.confirm(
        "Reset the YC demo? This drops and re-seeds ALL demo data, anchored to today."
      )
    ) {
      return;
    }
    setResetting(true);
    setResetError(null);
    try {
      await api.resetDemo();
      await loadFarms();
    } catch (err) {
      setResetError(err.message);
    } finally {
      setResetting(false);
    }
  }

  const visibleFarms = farms.filter((f) => !isSecondaryDemoFarm(f));
  // The reset is only offered when EVERY farm is a demo farm — the backend refuses
  // (409) on real data anyway; this just keeps the button out of real pilots.
  const allDemo = farms.length > 0 && farms.every((f) => f.is_demo);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-gray-900">Farms</h1>
          <p className="mt-0.5 max-w-2xl text-xs text-gray-500">
            The decision layer before the spray — ranked by what needs attention: open
            pre-spray decisions first, then risk flags.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {allDemo && (
            <button
              onClick={resetDemo}
              disabled={resetting}
              className="inline-flex h-9 items-center gap-2 rounded-md border border-gray-300 bg-white px-3 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50 disabled:opacity-50"
            >
              <RotateCcw className="h-4 w-4" />
              {resetting ? "Resetting…" : "Reset YC demo"}
            </button>
          )}
          <Link
            href="/pilot/new"
            className="inline-flex h-9 items-center gap-2 rounded-md bg-leaf px-4 text-sm font-medium text-white shadow-sm hover:bg-green-700"
          >
            <Plus className="h-4 w-4" />
            Add pilot farm
          </Link>
        </div>
      </div>

      {resetError && (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {resetError}
        </div>
      )}

      {loading && <p className="text-sm text-gray-500">Loading farms…</p>}
      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error} — is the backend running on <code>http://localhost:8000</code>?
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {visibleFarms.map((farm) => {
          const meta = URGENCY_META[farm.urgency] || URGENCY_META.ok;
          return (
            <Link key={farm.id} href={`/farms/${farm.id}`} className="group block">
              <Card className={`h-full transition-colors group-hover:border-gray-400 ${meta.border}`}>
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
                    <Badge variant={meta.variant}>{meta.label}</Badge>
                  </div>

                  {/* Why this farm needs attention + the next action. */}
                  <p className="mt-2.5 text-xs text-gray-600">{farm.why}</p>
                  <p className="mt-1 inline-flex items-center gap-1 text-xs font-medium text-gray-900">
                    <ArrowRight className="h-3 w-3 text-leaf" />
                    {farm.next_action}
                  </p>

                  <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-500">
                    <span className="capitalize">{farm.crop_type?.replace(/_/g, " ")}</span>
                    {farm.area != null && <span>{formatArea(farm.area, farm.country)}</span>}
                    <span className="inline-flex items-center gap-1">
                      <Droplets className="h-3 w-3" />
                      {farm.spray_count} sprays
                    </span>
                    <span className="inline-flex items-center gap-1">
                      <CalendarClock className="h-3 w-3" />
                      harvest {formatDate(farm.expected_harvest_date)}
                    </span>
                  </div>

                  {farm.is_demo && (
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
          );
        })}
      </div>

      {!loading && !error && farms.length === 0 && (
        <div className="rounded-md border border-gray-200 bg-white p-4 text-sm text-gray-500">
          No farms yet. Seed the demo data: <code>cd backend &amp;&amp; python -m app.seed</code>
        </div>
      )}
    </div>
  );
}
