"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import { useFarmContext } from "@/lib/farm-context";
import { statusMeta } from "@/lib/status";
import { Card, CardContent } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import DataTable from "@/components/DataTable";
import { inDateRange } from "@/components/DateRangeFilter";
import { decisionColumns } from "@/components/DecisionQueue";
import EmptyState from "@/components/EmptyState";
import FilterBar from "@/components/FilterBar";
import PageHeader from "@/components/PageHeader";
import PreSpraySheet from "@/components/PreSpraySheet";

// Workflow filter chips — the SAME predicates produce both the chip counts and
// the rendered rows, so they can never disagree.
const WORKFLOW_FILTERS = [
  { key: "all", label: "All", match: () => true },
  { key: "needs_action", label: "Needs action", match: (p) => p.workflow_state === "needs_action" },
  { key: "awaiting_pca", label: "Awaiting PCA", match: (p) => p.workflow_state === "awaiting_pca" },
  { key: "resolved", label: "Resolved", match: (p) => p.workflow_state === "resolved" },
];

export default function DecisionsPage() {
  const { activeFarm, loading: farmsLoading } = useFarmContext();
  const farmId = activeFarm?.id;

  const [planned, setPlanned] = useState([]);
  const [error, setError] = useState(null);
  const [workflowFilter, setWorkflowFilter] = useState("all");
  const [verdictFilter, setVerdictFilter] = useState("");
  const [fieldFilter, setFieldFilter] = useState("");
  const [dateRange, setDateRange] = useState({ from: "", to: "" });

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

  // One filter pipeline: chips count what the table shows.
  const baseFiltered = useMemo(
    () =>
      planned.filter(
        (p) =>
          (!verdictFilter || p.decision_outcome === verdictFilter) &&
          (!fieldFilter || p.field_block === fieldFilter) &&
          inDateRange(p.intended_date, dateRange)
      ),
    [planned, verdictFilter, fieldFilter, dateRange]
  );
  const active = WORKFLOW_FILTERS.find((f) => f.key === workflowFilter) || WORKFLOW_FILTERS[0];
  const rows = baseFiltered
    .filter(active.match)
    .sort((a, b) => (a.intended_date < b.intended_date ? 1 : -1));

  const fields = [...new Set(planned.map((p) => p.field_block).filter(Boolean))].sort();
  const verdicts = [...new Set(planned.map((p) => p.decision_outcome).filter(Boolean))];

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
        breadcrumbs={[{ label: "Decisions" }, { label: activeFarm.name }]}
        title="Decisions"
        meta={
          <span>
            Every planned spray checked by the rule engine for {activeFarm.name}. The
            verdict is the historical decision; the state says what is still owed.
          </span>
        }
        actions={<PreSpraySheet farmId={farmId} onChanged={load} />}
      />

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <Card>
        <CardContent className="p-5">
          <FilterBar
            chips={WORKFLOW_FILTERS.map((f) => ({
              key: f.key,
              label: f.label,
              count: baseFiltered.filter(f.match).length,
              selected: f.key === workflowFilter,
              onClick: () => setWorkflowFilter(f.key),
            }))}
            dateRange={{ value: dateRange, onChange: setDateRange }}
          >
            <Select
              value={verdictFilter}
              onChange={(e) => setVerdictFilter(e.target.value)}
              className="h-9 w-auto text-xs"
              aria-label="Filter by verdict"
            >
              <option value="">All verdicts</option>
              {verdicts.map((v) => (
                <option key={v} value={v}>
                  {statusMeta("verdict", v).label}
                </option>
              ))}
            </Select>
            <Select
              value={fieldFilter}
              onChange={(e) => setFieldFilter(e.target.value)}
              className="h-9 w-auto text-xs"
              aria-label="Filter by field"
            >
              <option value="">All fields</option>
              {fields.map((f) => (
                <option key={f} value={f}>
                  {f}
                </option>
              ))}
            </Select>
          </FilterBar>

          <DataTable
            columns={decisionColumns({ includeNextActionText: true })}
            rows={rows}
            rowKey={(p) => p.id}
            minWidth={720}
            empty={
              <EmptyState
                icon={ShieldCheck}
                title={
                  planned.length === 0
                    ? "No planned sprays checked yet"
                    : "Nothing matches these filters"
                }
                description={
                  planned.length === 0
                    ? 'Use "Check planned spray" before the next application to get an explainable verdict and an audit-ready record.'
                    : "Clear a filter to see more decisions."
                }
              />
            }
          />
        </CardContent>
      </Card>
    </div>
  );
}
