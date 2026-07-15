"use client";

import { useCallback, useEffect, useState } from "react";
import { Droplets, Plus } from "lucide-react";
import { api } from "@/lib/api";
import { formatCost, formatDate } from "@/lib/format";
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
import SprayEventForm from "@/components/SprayEventForm";

const HEADER_CLS =
  "px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wide text-gray-500";

// Applied spray log for the active farm. PHI/REI shown are the values entered
// per application — not verified label data.
export default function ApplicationsPage() {
  const { activeFarm, loading: farmsLoading } = useFarmContext();
  const farmId = activeFarm?.id;

  const [sprays, setSprays] = useState([]);
  const [error, setError] = useState(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  const load = useCallback(async () => {
    if (!farmId) return;
    try {
      setSprays(await api.listSprayEvents(farmId));
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

  const sorted = [...sprays].sort((a, b) =>
    a.application_date < b.application_date ? 1 : -1
  );

  return (
    <div className="space-y-5">
      <Breadcrumbs items={[{ label: "Applications" }, { label: activeFarm.name }]} />
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-gray-900">Applications</h1>
          <p className="mt-0.5 text-xs text-gray-500">
            Applied sprays for {activeFarm.name}. PHI/REI are the entered per-application
            values, not verified label data.
          </p>
        </div>
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button>
              <Plus />
              Log spray
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Log a spray application</DialogTitle>
              <DialogDescription>
                Product, date, and the label values you have on hand.
              </DialogDescription>
            </DialogHeader>
            <SprayEventForm
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
            <Droplets />
            Spray log
          </CardTitle>
        </CardHeader>
        <CardContent>
          {sorted.length === 0 ? (
            <p className="text-sm text-gray-500">No spray applications recorded yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[680px] text-sm">
                <thead>
                  <tr className="border-b border-gray-200">
                    <th className={HEADER_CLS}>Date</th>
                    <th className={HEADER_CLS}>Product</th>
                    <th className={HEADER_CLS}>Target</th>
                    <th className={HEADER_CLS}>Dose</th>
                    <th className={HEADER_CLS}>PHI / REI</th>
                    <th className={HEADER_CLS}>Cost</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {sorted.map((s) => (
                    <tr key={s.id} className="align-top">
                      <td className="whitespace-nowrap px-3 py-3 text-gray-700">
                        {formatDate(s.application_date)}
                      </td>
                      <td className="px-3 py-3">
                        <div className="font-medium text-gray-900">{s.product_name}</div>
                        {s.active_ingredient && (
                          <div className="text-xs text-gray-500">{s.active_ingredient}</div>
                        )}
                      </td>
                      <td className="max-w-[200px] px-3 py-3 text-xs text-gray-600">
                        {s.target_pest_or_disease || "—"}
                      </td>
                      <td className="whitespace-nowrap px-3 py-3 text-gray-700">
                        {s.dose || "—"}
                      </td>
                      <td className="whitespace-nowrap px-3 py-3 text-gray-700">
                        {s.pre_harvest_interval_days != null
                          ? `${s.pre_harvest_interval_days}d`
                          : "—"}
                        {" / "}
                        {s.re_entry_interval_hours != null
                          ? `${s.re_entry_interval_hours}h`
                          : "—"}
                      </td>
                      <td className="whitespace-nowrap px-3 py-3 text-gray-700">
                        {s.cost != null ? formatCost(s.cost, activeFarm.country) : "—"}
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
