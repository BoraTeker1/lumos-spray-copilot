"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Droplets, FileCheck, FlaskConical, Info, Plus, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import { formatCost, formatDate } from "@/lib/format";
import { useFarmContext } from "@/lib/farm-context";
import { statusMeta } from "@/lib/status";
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
import DetailPanel, {
  DetailChain,
  DetailRow,
  DetailSection,
} from "@/components/DetailPanel";
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
  const [selectedId, setSelectedId] = useState(null);

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

  // Selection follows the FILTERED rows: a row hidden by a filter must not
  // keep a stale panel open beside a table that no longer lists it.
  const selected = rows.find((s) => s.id === selectedId) || null;

  const fields = [...new Set(sprays.map((s) => s.field_block).filter(Boolean))].sort();

  const columns = [
    {
      key: "date",
      header: "Date",
      render: (s) => (
        <span className="whitespace-nowrap text-ink">
          {formatDate(s.application_date)}
        </span>
      ),
    },
    {
      key: "field",
      header: "Field",
      render: (s) => <span className="text-ink">{s.field_block || "—"}</span>,
    },
    {
      key: "product",
      header: "Product",
      render: (s) => (
        <div className="min-w-0">
          <div className="font-medium text-ink">{s.product_name}</div>
          {(s.active_ingredient || s.dose) && (
            <div className="text-xs text-muted">
              {[s.active_ingredient, s.dose].filter(Boolean).join(" · ")}
            </div>
          )}
        </div>
      ),
    },
    {
      key: "rate",
      header: "Rate / acres",
      priority: "secondary",
      render: (s) => (
        <span className="whitespace-nowrap text-xs text-muted">
          {s.rate_amount != null ? `${s.rate_amount} ${s.rate_unit || ""}`.trim() : "—"}
          {" · "}
          {s.treated_acres != null ? `${s.treated_acres} ac` : "—"}
        </span>
      ),
    },
    {
      key: "target",
      header: "Target",
      priority: "secondary",
      render: (s) => (
        <span className="text-xs text-muted">{s.target_pest_or_disease || "—"}</span>
      ),
    },
    {
      key: "phi",
      header: "PHI / REI",
      priority: "secondary",
      render: (s) => (
        <span className="whitespace-nowrap text-ink">
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
        <span className="text-xs text-muted">
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
          <span className="text-xs text-muted">—</span>
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
        <span className="whitespace-nowrap font-medium text-ink">
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

  if (farmsLoading) return <p className="text-sm text-muted">Loading…</p>;
  if (!activeFarm) {
    return (
      <p className="text-sm text-muted">
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
        <div className="rounded-control border border-risk-line bg-risk-bg p-3 text-sm text-risk-fg">
          {error}
        </div>
      )}

      {/* Entered values are not label values. Stated once, above the table. */}
      <div className="flex items-start gap-2 rounded-card border border-warn-line bg-warn-bg px-4 py-2.5 text-sm text-warn-fg">
        <Info className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
        PHI and REI values below are entered per application; confirm against the
        product label.
      </div>

      <div
        className={`grid grid-cols-1 gap-4 ${
          selected ? "2xl:grid-cols-[minmax(0,1fr)_340px]" : "grid-cols-1"
        }`}
      >
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
              onRowClick={(s) => setSelectedId((cur) => (cur === s.id ? null : s.id))}
              selectedKey={selected?.id ?? null}
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
            <p className="mt-3 border-t border-line pt-3 text-meta text-muted">
              Entered values are not a substitute for the current product label.
            </p>
          </CardContent>
        </Card>

        {/* Detail rail. Renders the row the table already has plus the decision
            link the table column already derives — no extra fetch. */}
        {selected && (
          <ApplicationDetail
            spray={selected}
            decision={decisionBySprayId.get(selected.id) || null}
            country={activeFarm?.country}
            onClose={() => setSelectedId(null)}
          />
        )}
      </div>
    </div>
  );
}

function ApplicationDetail({ spray: s, decision, country, onClose }) {
  // The record chain restates links that already exist on the row: a planned
  // decision (only if one points at this spray), the application itself, and the
  // decision's server-derived evidence state. Nothing is inferred.
  const chain = [
    {
      label: "Planned-spray decision",
      value: decision ? "Linked" : "Not linked",
      icon: ShieldCheck,
      tone: decision ? "good" : "neutral",
    },
    { label: "Application", value: "Logged", icon: Droplets, tone: "neutral" },
    {
      label: "Follow-up",
      value: decision ? statusMeta("evidence", decision.evidence_state).label : "—",
      icon: FileCheck,
      tone: decision?.evidence_state === "verified" ? "good" : "neutral",
    },
  ];
  return (
    <DetailPanel
      className="h-fit 2xl:sticky 2xl:top-20"
      title={s.product_name}
      subtitle={`Applied ${formatDate(s.application_date)}${
        s.field_block ? ` · ${s.field_block}` : ""
      }`}
      badges={
        <>
          {decision ? (
            <StatusBadge kind="evidence" value={decision.evidence_state} />
          ) : (
            <Badge variant="neutral">Logged</Badge>
          )}
          {(s.data_source === "demo" || s.data_confidence === "simulated") && (
            <Badge variant="outline">
              <FlaskConical />
              Simulated demo
            </Badge>
          )}
        </>
      }
      onClose={onClose}
      footer={
        decision ? (
          <Link href={`/decisions/${decision.id}`}>
            <Button className="w-full">View decision record</Button>
          </Link>
        ) : (
          <p className="text-meta text-muted">
            This application was logged directly — no pre-spray decision record points
            at it.
          </p>
        )
      }
    >
      <DetailSection title="Application details">
        <DetailRow
          label="Rate"
          value={
            s.rate_amount != null
              ? `${s.rate_amount} ${s.rate_unit || ""}`.trim()
              : null
          }
        />
        <DetailRow label="Active ingredients" value={s.active_ingredient} />
        <DetailRow label="Target" value={s.target_pest_or_disease} />
        <DetailRow
          label="Entered PHI"
          value={
            s.pre_harvest_interval_days != null
              ? `${s.pre_harvest_interval_days} days`
              : null
          }
        />
        <DetailRow
          label="Entered REI"
          value={
            s.re_entry_interval_hours != null
              ? `${s.re_entry_interval_hours} hours`
              : null
          }
        />
        <DetailRow
          label="Cost"
          value={s.cost != null ? formatCost(s.cost, country) : null}
        />
      </DetailSection>
      <DetailSection title="Record chain">
        <DetailChain stages={chain} />
      </DetailSection>
      <DetailSection title="Provenance">
        <DetailRow
          label="Source"
          value={(s.data_source || "—").replace(/_/g, " ")}
        />
        <DetailRow
          label="Confidence"
          value={(s.data_confidence || "—").replace(/_/g, " ")}
        />
        {/* Always stated, never conditional: no label record backs these values. */}
        <DetailRow
          label="Label verification"
          value="Not independently verified"
          tone="warn"
        />
        {s.source_order_id && (
          <DetailRow label="Source order" value={`Order #${s.source_order_id}`} />
        )}
      </DetailSection>
    </DetailPanel>
  );
}
