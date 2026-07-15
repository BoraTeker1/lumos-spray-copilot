"use client";

import { useCallback, useEffect, useState } from "react";
import { ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import { useFarmContext } from "@/lib/farm-context";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import Breadcrumbs from "@/components/Breadcrumbs";
import DecisionQueueTable from "@/components/DecisionQueueTable";
import PreSpraySheet from "@/components/PreSpraySheet";

// All pre-spray decisions for the active farm. Read-only queue — PCA reviews
// and outcomes are recorded on each decision record (or in the check sheet).
export default function DecisionsPage() {
  const { activeFarm, loading: farmsLoading } = useFarmContext();
  const farmId = activeFarm?.id;

  const [planned, setPlanned] = useState([]);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    if (!farmId) return;
    try {
      setPlanned(await api.listPlannedSprays(farmId));
      setError(null);
    } catch (err) {
      setError(err.message);
    }
  }, [farmId]);

  useEffect(() => {
    load();
  }, [load]);

  if (farmsLoading) return <p className="text-sm text-gray-500">Loading…</p>;
  if (!activeFarm) {
    return (
      <p className="text-sm text-gray-500">
        No farms yet — seed the demo data or add a pilot farm first.
      </p>
    );
  }

  return (
    <div className="space-y-5">
      <Breadcrumbs items={[{ label: "Decisions" }, { label: activeFarm.name }]} />
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-gray-900">Decisions</h1>
          <p className="mt-0.5 text-xs text-gray-500">
            Every planned spray checked by the rule engine for {activeFarm.name}. Open a
            record for the full calculation trail, PCA review, and outcome.
          </p>
        </div>
        <PreSpraySheet farmId={farmId} onChanged={load} />
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>
            <ShieldCheck />
            Decision queue
          </CardTitle>
        </CardHeader>
        <CardContent>
          <DecisionQueueTable planned={planned} />
        </CardContent>
      </Card>
    </div>
  );
}
