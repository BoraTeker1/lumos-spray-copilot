"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Droplets, Plus } from "lucide-react";
import { api } from "@/lib/api";
import { formatCost, formatDate } from "@/lib/format";
import { useFarmContext } from "@/lib/farm-context";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import DataTable from "@/components/DataTable";
import { inDateRange } from "@/components/DateRangeFilter";
import EmptyState from "@/components/EmptyState";
import FilterBar from "@/components/FilterBar";
import PageHeader from "@/components/PageHeader";
import SprayEventForm from "@/components/SprayEventForm";
import StatusBadge from "@/components/StatusBadge";

export default function ApplicationsPage() {
  const { activeFarm, loading: farmsLoading } = useFarmContext();
  const farmId = activeFarm?.id;

  const [sprays, setSprays] = useState([]);
  const [planned, setPlanned] = useState([]);
  const [error, setError] = useState(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [fieldFilter, setFieldFilter] = useState("");
  const [dateRange, setDateRange] = useState({ from: "", to: "" });

  const load = useCallback(async () => {
    if (!farmId) return;
    try {
      const [s, p] = await Promise.all([
        api.listSprayEvents(farmId),
        api.listPlannedSprays(farmId),
      ]);
      setSprays(s);
      setPlanned(p);
      setError(null);
    } catch (err) {
      setError(err.message);
    }
  }, [farmId]);

  useEffect(() => {
    load();
  }, [load]);

  // Documentation status: only real for sprays that came from a checked decision
  // (linked via planned.spray_event_id) — the decision's server-derived
  // evidence_state. A directly logged spray is just "Logged" (no invented state).
  const decisionBySprayId = useMemo(() => {
    const map = new Map();
    for (const p of planned) {
      if (p.spray_event_id != null) map.set(p.spray_event_id, p);
    }
    return map;
  }, [planned]);

  const rows = useMemo(
    () =>
      sprays
        .filter(
          (s) =>
            (!fieldFilter || s.field_block === fieldFilter) &&
            inDateRange(s.application_date, dateRange)
        )
        .sort((a, b) => (a.application_date < b.application_date ? 1 : -1)),
    [sprays, fieldFilter, dateRange]
  );

  const fields = [...new Set(sprays.map((s) => s.field_block).filter(Boolean))].sort();

  const columns = [
    {
      key: "date",
      header: "Date",
      render: (s) => (
        <span className="whitespace-nowrap text-gray-700">
          {formatDate(s.application_date)}
        </span>
      ),
    },
    {
      key: "field",
      header: "Field",
      render: (s) => <span className="text-gray-700">{s.field_block || "—"}</span>,
    },
    {
      key: "product",
      header: "Product",
      render: (s) => (
        <div className="min-w-0">
          <div className="font-medium text-gray-900">{s.product_name}</div>
          {(s.active_ingredient || s.dose) && (
            <div className="text-xs text-gray-500">
              {[s.active_ingredient, s.dose].filter(Boolean).join(" · ")}
            </div>
          )}
        </div>
      ),
    },
    {
      key: "target",
      header: "Target",
      priority: "secondary",
      render: (s) => (
        <span className="text-xs text-gray-600">{s.target_pest_or_disease || "—"}</span>
      ),
    },
    {
      key: "phi",
      header: "PHI / REI",
      priority: "secondary",
      render: (s) => (
        <span className="whitespace-nowrap text-gray-700">
          {s.pre_harvest_interval_days != null ? `${s.pre_harvest_interval_days}d` : "—"}
          {" / "}
          {s.re_entry_interval_hours != null ? `${s.re_entry_interval_hours}h` : "—"}
        </span>
      ),
    },
    {
      key: "source",
      header: "Source",
      priority: "secondary",
      render: (s) => (
        <span className="text-xs text-gray-600">
          {(s.data_source || "—").replace(/_/g, " ")}
        </span>
      ),
    },
    {
      key: "order",
      header: "Source order",
      priority: "secondary",
      // Only applications procured through Inputs & finance carry an order link —
      // most applications are not procured through Lumos, and that stays visible.
      render: (s) =>
        s.source_order_id ? (
          <Link
            href={`/inputs/orders/${s.source_order_id}`}
            className="text-xs font-medium text-leaf-700 hover:underline"
          >
            Order #{s.source_order_id}
          </Link>
        ) : (
          <span className="text-xs text-gray-500">—</span>
        ),
    },
    {
      key: "doc",
      header: "Documentation",
      render: (s) => {
        const decision = decisionBySprayId.get(s.id);
        return decision ? (
          <StatusBadge kind="evidence" value={decision.evidence_state} />
        ) : (
          <Badge variant="neutral" className="whitespace-nowrap">
            Logged
          </Badge>
        );
      },
    },
    {
      key: "cost",
      header: "Cost",
      align: "right",
      render: (s) => (
        <span className="whitespace-nowrap font-medium text-gray-900">
          {s.cost != null ? formatCost(s.cost, activeFarm?.country) : "—"}
        </span>
      ),
    },
    {
      key: "action",
      header: <span className="sr-only">Action</span>,
      align: "right",
      render: (s) => {
        const decision = decisionBySprayId.get(s.id);
        return decision ? (
          <Link href={`/decisions/${decision.id}`}>
            <Button variant="secondary" size="sm">
              View record
            </Button>
          </Link>
        ) : (
          <Link href={`/farms/${farmId}?tab=records`}>
            <Button variant="secondary" size="sm">
              View
            </Button>
          </Link>
        );
      },
    },
  ];

  if (farmsLoading) return <p className="text-sm text-gray-500">Loading…</p>;
  if (!activeFarm) {
    return (
      <p className="text-sm text-gray-500">
        No farms yet — seed the demo data or add a pilot farm first.
      </p>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumbs={[{ label: "Applications" }, { label: activeFarm.name }]}
        title="Applications"
        meta={
          <span>
            Applied sprays for {activeFarm.name}. PHI/REI are the entered
            per-application values, not verified label data.
          </span>
        }
        actions={
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
        }
      />

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <Card>
        <CardContent className="p-5">
          <FilterBar dateRange={{ value: dateRange, onChange: setDateRange }}>
            <Select
              value={fieldFilter}
              onChange={(e) => setFieldFilter(e.target.value)}
              className="h-9 w-auto text-xs"
              aria-label="Filter by field"
            >
              <option value="">All fields</option>
              {fields.map((f) => (
                <option key={f} value={f}>{f}</option>
              ))}
            </Select>
          </FilterBar>

          <DataTable
            columns={columns}
            rows={rows}
            rowKey={(s) => s.id}
            minWidth={760}
            empty={
              <EmptyState
                icon={Droplets}
                title={
                  sprays.length === 0
                    ? "No spray applications recorded yet"
                    : "Nothing matches these filters"
                }
                description={
                  sprays.length === 0
                    ? "Log applied sprays (or import a spray history) so PHI/REI and rotation checks have records to work from."
                    : "Clear a filter to see more applications."
                }
              />
            }
          />
        </CardContent>
      </Card>
    </div>
  );
}
