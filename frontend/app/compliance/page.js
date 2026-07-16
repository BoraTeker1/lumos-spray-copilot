"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  CalendarClock,
  CircleCheck,
  FileWarning,
  OctagonX,
  ShieldAlert,
  TriangleAlert,
} from "lucide-react";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useFarmContext } from "@/lib/farm-context";
import { AUTHORITY_SOURCE_LABELS } from "@/lib/labels";
import { nextActionLabel } from "@/lib/status";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import ComplianceCard from "@/components/ComplianceCard";
import DataTable from "@/components/DataTable";
import { inDateRange } from "@/components/DateRangeFilter";
import EmptyState from "@/components/EmptyState";
import FilterBar from "@/components/FilterBar";
import NextActionBanner from "@/components/NextActionBanner";
import PageHeader from "@/components/PageHeader";
import SectionCard from "@/components/SectionCard";
import StatusBadge from "@/components/StatusBadge";
import UpdateHarvestDialog from "@/components/UpdateHarvestDialog";

// Attention-row categories. Every row is a REAL server-derived signal: a rule the
// engine triggered on a checked decision, or a decision whose documentation is
// still owed. No compliance math happens in the frontend.
const CATEGORY_FILTERS = [
  { key: "all", label: "All" },
  { key: "triggered_rule", label: "Triggered rules" },
  { key: "open_conflict", label: "Open conflicts" },
  { key: "documentation", label: "Missing documentation" },
];

function buildAttentionRows(planned) {
  const rows = [];
  for (const p of planned) {
    const rules = (p.decision_payload?.rules || []).filter((r) => r.triggered);
    for (const r of rules) {
      rows.push({
        key: `rule-${p.id}-${r.rule_id}`,
        category: p.open_conflict && r.severity === "critical" ? "open_conflict" : "triggered_rule",
        date: p.intended_date,
        field: p.field_block,
        planned: p,
        title: r.name,
        detail: r.detail,
        calculation: r.calculation,
        severity: r.severity,
        source: r.source_authority,
      });
    }
    if (["missing_documentation", "follow_up_required"].includes(p.evidence_state)) {
      rows.push({
        key: `doc-${p.id}`,
        category: "documentation",
        date: p.outcome_date || p.intended_date,
        field: p.field_block,
        planned: p,
        title:
          p.evidence_state === "missing_documentation"
            ? "No real-world outcome recorded"
            : "Follow-up evidence required",
        detail:
          p.evidence_state === "missing_documentation"
            ? `${p.product_name}: the check ran but what actually happened was never recorded.`
            : `${p.product_name}: the recorded outcome is not a confirmed result until follow-up evidence is recorded.`,
        severity: "caution",
        source: null,
      });
    }
  }
  return rows.sort((a, b) => (a.date < b.date ? 1 : -1));
}

export default function CompliancePage() {
  const { activeFarm, loading: farmsLoading, refresh } = useFarmContext();
  const farmId = activeFarm?.id;

  const [overview, setOverview] = useState(null);
  const [compliance, setCompliance] = useState(null);
  const [planned, setPlanned] = useState([]);
  const [error, setError] = useState(null);
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [fieldFilter, setFieldFilter] = useState("");
  const [dateRange, setDateRange] = useState({ from: "", to: "" });

  const load = useCallback(async () => {
    if (!farmId) return;
    try {
      const [ov, c, p] = await Promise.all([
        api.getFarmOverview(farmId),
        api.getCompliance(farmId),
        api.listPlannedSprays(farmId),
      ]);
      setOverview(ov);
      setCompliance(c);
      setPlanned(p);
      setError(null);
    } catch (err) {
      setError(err.message);
    }
  }, [farmId]);

  useEffect(() => {
    load();
  }, [load]);

  const attention = useMemo(() => buildAttentionRows(planned), [planned]);
  const baseFiltered = attention.filter(
    (row) =>
      (!fieldFilter || row.field === fieldFilter) && inDateRange(row.date, dateRange)
  );
  const rows =
    categoryFilter === "all"
      ? baseFiltered
      : baseFiltered.filter((r) => r.category === categoryFilter);
  const fields = [...new Set(attention.map((r) => r.field).filter(Boolean))].sort();

  const days = overview?.days_to_harvest;
  const harvestOverdue = days != null && days < 0;

  const columns = [
    {
      key: "date",
      header: "Date",
      render: (r) => (
        <span className="whitespace-nowrap text-gray-700">{formatDate(r.date)}</span>
      ),
    },
    {
      key: "field",
      header: "Field",
      priority: "secondary",
      render: (r) => <span className="text-gray-700">{r.field || "—"}</span>,
    },
    {
      key: "issue",
      header: "Signal",
      render: (r) => (
        <div className="min-w-0 max-w-[340px]">
          <div className="flex items-center gap-1.5 font-medium text-gray-900">
            {r.severity === "critical" ? (
              <OctagonX className="h-3.5 w-3.5 shrink-0 text-red-600" aria-hidden />
            ) : (
              <TriangleAlert className="h-3.5 w-3.5 shrink-0 text-amber-600" aria-hidden />
            )}
            {r.title}
          </div>
          <p className="mt-0.5 text-xs text-gray-600">{r.detail}</p>
          {r.calculation && (
            <p className="mt-0.5 font-mono text-[11px] text-gray-500">{r.calculation}</p>
          )}
        </div>
      ),
    },
    {
      key: "decision",
      header: "Decision",
      priority: "secondary",
      render: (r) => (
        <div className="text-xs">
          <div className="font-medium text-gray-900">{r.planned.product_name}</div>
          <StatusBadge kind="verdict" value={r.planned.decision_outcome} className="mt-1" />
        </div>
      ),
    },
    {
      key: "source",
      header: "Source authority",
      priority: "secondary",
      render: (r) => (
        <span className="text-xs text-gray-600">
          {r.source ? AUTHORITY_SOURCE_LABELS[r.source] || r.source : "—"}
        </span>
      ),
    },
    {
      key: "action",
      header: <span className="sr-only">Action</span>,
      align: "right",
      render: (r) => (
        <Link href={`/decisions/${r.planned.id}`}>
          <Button variant="secondary" size="sm">
            {r.category === "documentation"
              ? nextActionLabel(r.planned.current_next_action)
              : "Open record"}
          </Button>
        </Link>
      ),
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
        breadcrumbs={[{ label: "Compliance" }, { label: activeFarm.name }]}
        title="Compliance"
        meta={
          <span>
            Current operational risk for {activeFarm.name} — signals come from entered
            records and checked decisions, {compliance?.basis || "not label-verified"}.
          </span>
        }
      />

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Harvest conflict — the highest-leverage stale-data risk. */}
      {harvestOverdue && overview && (
        <NextActionBanner
          issue={`Expected harvest date (${formatDate(overview.expected_harvest_date)}) has passed`}
          consequence="PHI day-math against the old date is no longer valid — update it before relying on new pre-spray checks."
          urgency="harvest_overdue"
          primary={
            <UpdateHarvestDialog
              farmId={farmId}
              currentDate={overview.expected_harvest_date}
              onUpdated={async () => {
                await load();
                await refresh();
              }}
              trigger={
                <Button size="sm">
                  <CalendarClock />
                  Update harvest date
                </Button>
              }
            />
          }
        />
      )}

      <div className="grid gap-4 lg:grid-cols-12">
        <div className="min-w-0 lg:col-span-8">
          <SectionCard
            title="Records requiring attention"
            icon={<ShieldAlert />}
            description="Rules the engine triggered on checked decisions, open conflicts, and documentation still owed — with the exact calculation and source authority."
          >
            <FilterBar
              chips={CATEGORY_FILTERS.map((f) => ({
                key: f.key,
                label: f.label,
                count:
                  f.key === "all"
                    ? baseFiltered.length
                    : baseFiltered.filter((r) => r.category === f.key).length,
                selected: f.key === categoryFilter,
                onClick: () => setCategoryFilter(f.key),
              }))}
              dateRange={{ value: dateRange, onChange: setDateRange }}
            >
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
              rowKey={(r) => r.key}
              minWidth={720}
              empty={
                <EmptyState
                  icon={CircleCheck}
                  title={
                    attention.length === 0
                      ? "Nothing requires attention"
                      : "Nothing matches these filters"
                  }
                  description={
                    attention.length === 0
                      ? "No triggered rules, open conflicts, or missing documentation from current records. Run a pre-spray check before the next application."
                      : "Clear a filter to see more signals."
                  }
                />
              }
            />
          </SectionCard>
        </div>

        <div className="space-y-4 lg:col-span-4">
          <SectionCard
            title="Pre-spray risk snapshot"
            icon={<TriangleAlert />}
            description="PHI / REI / rotation / scouting from entered records — not verified label data."
          >
            <ComplianceCard data={compliance} />
          </SectionCard>

          <SectionCard title="Harvest window" icon={<CalendarClock />}>
            <div className="space-y-1.5 text-xs text-gray-600">
              <div className="flex items-center justify-between">
                <span>Expected harvest</span>
                <span className="font-medium text-gray-900">
                  {overview?.expected_harvest_date
                    ? formatDate(overview.expected_harvest_date)
                    : "—"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span>Status</span>
                {harvestOverdue ? (
                  <Badge variant="red">
                    <TriangleAlert />
                    {-days} day{days === -1 ? "" : "s"} overdue
                  </Badge>
                ) : days != null ? (
                  <Badge variant="green">
                    <CircleCheck />
                    {days === 0 ? "Today" : `in ${days} day${days === 1 ? "" : "s"}`}
                  </Badge>
                ) : (
                  <Badge variant="neutral">
                    <FileWarning />
                    No date entered
                  </Badge>
                )}
              </div>
              {harvestOverdue && (
                <p className="rounded bg-red-50 p-2 text-[11px] text-red-800">
                  A stale harvest date can invalidate PHI checks. Update it before the
                  next pre-spray decision.
                </p>
              )}
            </div>
          </SectionCard>

          <p className="px-1 text-[11px] leading-snug text-gray-500">
            Decision support only. Always confirm PHI, REI, rates, crop use, and
            restrictions with the product label and a licensed PCA / agronomist.
          </p>
        </div>
      </div>
    </div>
  );
}
