"use client";

import { useCallback, useEffect, useState } from "react";
import { Eye, Plus } from "lucide-react";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useFarmContext } from "@/lib/farm-context";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import Breadcrumbs from "@/components/Breadcrumbs";
import ScoutObservationForm from "@/components/ScoutObservationForm";
import SeverityBadge from "@/components/SeverityBadge";

const HEADER_CLS =
  "px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wide text-gray-500";

// Scouting log for the active farm. Field evidence recorded here feeds the
// pre-spray decision checks (scouting-threshold and stale-scouting rules).
export default function ScoutingPage() {
  const { activeFarm, loading: farmsLoading } = useFarmContext();
  const farmId = activeFarm?.id;

  const [observations, setObservations] = useState([]);
  const [error, setError] = useState(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  const load = useCallback(async () => {
    if (!farmId) return;
    try {
      setObservations(await api.listScoutObservations(farmId));
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

  const sorted = [...observations].sort((a, b) =>
    a.observation_date < b.observation_date ? 1 : -1
  );

  return (
    <div className="space-y-5">
      <Breadcrumbs items={[{ label: "Scouting" }, { label: activeFarm.name }]} />
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-gray-900">Scouting</h1>
          <p className="mt-0.5 text-xs text-gray-500">
            Observations for {activeFarm.name}. Scouting evidence feeds the pre-spray
            decision checks.
          </p>
        </div>
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button>
              <Plus />
              Log scouting
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Log a scouting observation</DialogTitle>
              <DialogDescription>
                Date, visible issue, and severity 1–5.
              </DialogDescription>
            </DialogHeader>
            <ScoutObservationForm
              farmId={farmId}
              onCreated={async () => {
                setDialogOpen(false);
                await load();
              }}
            />
          </DialogContent>
        </Dialog>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>
            <Eye />
            Observations
          </CardTitle>
        </CardHeader>
        <CardContent>
          {sorted.length === 0 ? (
            <p className="text-sm text-gray-500">No scouting observations recorded yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[560px] text-sm">
                <thead>
                  <tr className="border-b border-gray-200">
                    <th className={HEADER_CLS}>Date</th>
                    <th className={HEADER_CLS}>Visible issue</th>
                    <th className={HEADER_CLS}>Severity</th>
                    <th className={HEADER_CLS}>Crop stage</th>
                    <th className={HEADER_CLS}>Notes</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {sorted.map((o) => (
                    <tr key={o.id} className="align-top">
                      <td className="whitespace-nowrap px-3 py-3 text-gray-700">
                        {formatDate(o.observation_date)}
                      </td>
                      <td className="px-3 py-3 font-medium text-gray-900">
                        {o.visible_issue || "—"}
                      </td>
                      <td className="px-3 py-3">
                        <SeverityBadge value={o.severity_1_to_5} />
                      </td>
                      <td className="px-3 py-3 capitalize text-gray-700">
                        {o.crop_stage ? o.crop_stage.replace(/_/g, " ") : "—"}
                      </td>
                      <td className="max-w-[280px] px-3 py-3 text-xs text-gray-600">
                        {o.notes || "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
