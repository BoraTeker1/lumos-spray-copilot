"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  Ban,
  ClipboardCheck,
  Download,
  FileCheck,
  FlaskConical,
  ListChecks,
  RefreshCw,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";
import { api, API_BASE_URL } from "@/lib/api";
import { formatCost, formatDate } from "@/lib/format";
import { useFarmContext } from "@/lib/farm-context";
import { RECORDED_OUTCOME_LABELS } from "@/lib/labels";
import { nextActionLabel } from "@/lib/status";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import CompliancePanel from "@/components/CompliancePanel";
import DataTable from "@/components/DataTable";
import DecisionEvidenceCard from "@/components/DecisionEvidenceCard";
import ReductionCard from "@/components/ReductionCard";
import { inDateRange } from "@/components/DateRangeFilter";
import EmptyState from "@/components/EmptyState";
import FilterBar from "@/components/FilterBar";
import MetricCard from "@/components/MetricCard";
import PageHeader from "@/components/PageHeader";
import ProgressBar from "@/components/ProgressBar";
import SectionCard from "@/components/SectionCard";
import StatusBadge from "@/components/StatusBadge";

// Provenance split — mirrors backend decision_status.is_demo_record (a
// provenance filter, not business logic; the metrics themselves come scoped
// from the server and are never recomputed here).
function isDemoRecord(p) {
  return p.data_source === "demo" || p.data_confidence === "simulated";
}

// Evidence filter chips — predicates read ONLY server-derived fields, and the
// same predicate produces both the chip count and the rows.
const EVIDENCE_FILTERS = [
  { key: "all", label: "All", match: () => true },
  { key: "follow_up_required", label: "Follow-up required", match: (p) => p.evidence_state === "follow_up_required" },
  { key: "in_progress", label: "In progress", match: (p) => p.evidence_state === "follow_up_in_progress" },
  { key: "complete", label: "Complete", match: (p) => p.evidence_state === "complete" },
  { key: "verified", label: "Verified", match: (p) => p.evidence_state === "verified" },
  { key: "reviewed", label: "PCA reviewed", match: (p) => ["approved", "edited", "rejected"].includes(p.review_state) },
];

function ScopeMetrics({ metrics, simulated, country }) {
  if (!metrics) return null;
  const fu = metrics.follow_up || {};
  const badge = simulated ? (
    <Badge variant="outline">
      <FlaskConical />
      Simulated
    </Badge>
  ) : null;
  return (
    <div className="space-y-4">
      {simulated && (
        <div className="flex items-start gap-2 rounded-[10px] border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900">
          <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          <p>
            SIMULATED DEMO DATA — every figure below is derived from seeded demo
            records. Illustrative of the workflow, never customer evidence.
          </p>
        </div>
      )}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <MetricCard
          icon={ShieldCheck}
          label="Decisions reviewed"
          value={`${metrics.decisions_reviewed}/${metrics.decisions_checked}`}
          hint={simulated ? "simulated records" : "real (non-demo) records"}
          tone="neutral"
        />
        <MetricCard
          icon={Ban}
          label="Applications avoided"
          value={metrics.outcomes?.avoided ?? 0}
          hint={simulated ? "simulated outcome" : "recorded outcome"}
          tone={metrics.outcomes?.avoided > 0 ? "good" : "neutral"}
        />
        <MetricCard
          icon={RefreshCw}
          label="Changed product"
          value={metrics.outcomes?.changed_product ?? 0}
          hint="risky spray replaced"
          tone={metrics.outcomes?.changed_product > 0 ? "info" : "neutral"}
        />
        <MetricCard
          icon={TriangleAlert}
          label="Conflicts caught"
          value={metrics.compliance_conflicts_caught}
          hint="blocking conflicts before spraying"
          tone={metrics.compliance_conflicts_caught > 0 ? "warn" : "neutral"}
        />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardContent className="space-y-1 p-5 text-xs text-gray-600">
            <div className="flex items-center justify-between">
              <span className="inline-flex items-center gap-2">
                Estimated cost not spent {badge}
              </span>
              <span className="text-base font-semibold text-gray-900">
                {formatCost(metrics.estimated_chemical_cost_avoided || 0, country)}
              </span>
            </div>
            <p className="text-[11px] text-gray-500">
              Entered application-cost estimates of avoided sprays — chemicals not
              applied, not a savings or yield claim; not confirmed until follow-up.
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="space-y-2 p-5 text-xs text-gray-600">
            <div className="flex items-center justify-between">
              <span className="inline-flex items-center gap-2">Follow-up completion {badge}</span>
              <span className="font-medium text-gray-900">
                {fu.follow_up_with_events ?? 0}/{fu.follow_up_required ?? 0}
              </span>
            </div>
            <ProgressBar
              ratio={
                fu.follow_up_required ? (fu.follow_up_with_events || 0) / fu.follow_up_required : 0
              }
            />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

export default function EvidencePage() {
  const { activeFarm, loading: farmsLoading } = useFarmContext();
  const farmId = activeFarm?.id;

  const [farm, setFarm] = useState(null);
  const [planned, setPlanned] = useState([]);
  const [evidence, setEvidence] = useState(null);
  const [error, setError] = useState(null);
  const [scope, setScope] = useState(null); // "demo" | "real" (default derived on load)
  // Outer view: "evidence" | "compliance" (the old /compliance page lives here now;
  // ?tab=compliance deep-links to it — read on mount, SSR-safe).
  const [view, setView] = useState("evidence");
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("tab") === "compliance") {
      setView("compliance");
    }
  }, []);
  const [inputPlans, setInputPlans] = useState([]);
  const [statusFilter, setStatusFilter] = useState("all");
  const [fieldFilter, setFieldFilter] = useState("");
  const [dateRange, setDateRange] = useState({ from: "", to: "" });

  const load = useCallback(async () => {
    if (!farmId) return;
    try {
      const [f, p, ev, plans] = await Promise.all([
        api.getFarm(farmId),
        api.listPlannedSprays(farmId),
        api.getDecisionEvidence(farmId),
        api.listInputPlans(farmId),
      ]);
      setFarm(f);
      setPlanned(p);
      setEvidence(ev);
      setInputPlans(plans);
      setError(null);
      // Default scope: demo when only simulated records exist, else real.
      setScope((prev) =>
        prev ||
        (ev.decisions_checked === 0 && ev.demo_metrics?.decisions_checked > 0
          ? "demo"
          : "real")
      );
    } catch (err) {
      setError(err.message);
    }
  }, [farmId]);

  useEffect(() => {
    load();
  }, [load]);

  const scopedRows = useMemo(() => {
    const inScope = planned.filter((p) =>
      scope === "demo" ? isDemoRecord(p) : !isDemoRecord(p)
    );
    return inScope.filter(
      (p) =>
        (!fieldFilter || p.field_block === fieldFilter) &&
        inDateRange(p.intended_date, dateRange)
    );
  }, [planned, scope, fieldFilter, dateRange]);

  const activeFilter =
    EVIDENCE_FILTERS.find((f) => f.key === statusFilter) || EVIDENCE_FILTERS[0];
  const rows = scopedRows
    .filter(activeFilter.match)
    .sort((a, b) => (a.intended_date < b.intended_date ? 1 : -1));
  const fields = [...new Set(planned.map((p) => p.field_block).filter(Boolean))].sort();

  const columns = [
    {
      key: "date",
      header: "Date",
      render: (p) => (
        <span className="whitespace-nowrap text-gray-700">{formatDate(p.intended_date)}</span>
      ),
    },
    {
      key: "product",
      header: "Product / target",
      render: (p) => (
        <div className="min-w-0">
          <div className="font-medium text-gray-900">{p.product_name}</div>
          <div className="text-xs text-gray-500">{p.target_pest_or_disease || "—"}</div>
        </div>
      ),
    },
    {
      key: "field",
      header: "Field",
      priority: "secondary",
      render: (p) => <span className="text-gray-700">{p.field_block || "—"}</span>,
    },
    {
      key: "decision",
      header: "Decision",
      render: (p) => (
        <div className="flex flex-col items-start gap-1">
          <StatusBadge kind="verdict" value={p.decision_outcome} />
          {p.outcome && p.outcome !== "planned" && (
            <span className="text-[11px] text-gray-500">
              {RECORDED_OUTCOME_LABELS[p.outcome] || p.outcome}
            </span>
          )}
        </div>
      ),
    },
    {
      key: "review",
      header: "Review",
      priority: "secondary",
      render: (p) => <StatusBadge kind="review" value={p.review_state} />,
    },
    {
      key: "evidence",
      header: "Evidence",
      render: (p) => <StatusBadge kind="evidence" value={p.evidence_state} />,
    },
    {
      key: "action",
      header: <span className="sr-only">Action</span>,
      align: "right",
      render: (p) => (
        <Link href={`/decisions/${p.id}`}>
          <Button variant="secondary" size="sm">
            {p.current_next_action === "record_follow_up"
              ? nextActionLabel(p.current_next_action)
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

  const demoMetrics = evidence?.demo_metrics;
  const realChecked = evidence?.decisions_checked ?? 0;

  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumbs={[{ label: "Evidence & compliance" }, { label: activeFarm.name }]}
        title="Evidence & compliance"
        meta={
          <span>
            Outcomes, documentation completeness, compliance signals, and on-demand
            reports for {activeFarm.name}. Simulated and real records are never
            combined.
          </span>
        }
        actions={
          <>
            <a href={`${API_BASE_URL}/farms/${farmId}/export/evidence.csv`}>
              <Button variant="secondary">
                <Download />
                Export CSV
              </Button>
            </a>
            <a
              href={`${API_BASE_URL}/farms/${farmId}/audit-packet`}
              target="_blank"
              rel="noreferrer"
            >
              <Button>
                <FileCheck />
                Generate report
              </Button>
            </a>
          </>
        }
      />

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Outer view: pilot evidence vs. the compliance attention view (the former
          /compliance page — that route redirects here). */}
      <Tabs value={view} onValueChange={setView}>
        <TabsList>
          <TabsTrigger value="evidence">
            <FileCheck className="h-4 w-4" />
            Evidence
          </TabsTrigger>
          <TabsTrigger value="compliance">
            <TriangleAlert className="h-4 w-4" />
            Compliance
          </TabsTrigger>
        </TabsList>

        <TabsContent value="compliance">
          <CompliancePanel />
        </TabsContent>

        <TabsContent value="evidence">
          <div className="space-y-6">
      {/* Explicit scope control — simulated and real evidence never mix. */}
      <Tabs value={scope || "real"} onValueChange={setScope}>
        <TabsList>
          <TabsTrigger value="demo">
            <FlaskConical className="h-4 w-4" />
            Pilot demo (simulated)
            <span className="text-xs text-gray-400">
              {demoMetrics?.decisions_checked ?? 0}
            </span>
          </TabsTrigger>
          <TabsTrigger value="real">
            <ClipboardCheck className="h-4 w-4" />
            Real operations
            <span className="text-xs text-gray-400">{realChecked}</span>
          </TabsTrigger>
        </TabsList>

        <TabsContent value="demo">
          {demoMetrics?.decisions_checked > 0 ? (
            <ScopeMetrics metrics={demoMetrics} simulated country={activeFarm.country} />
          ) : (
            <EmptyState
              icon={FlaskConical}
              title="No simulated demo decisions"
              description="This farm has no seeded demo records."
            />
          )}
        </TabsContent>

        <TabsContent value="real">
          {realChecked > 0 ? (
            <ScopeMetrics metrics={evidence} country={activeFarm.country} />
          ) : (
            <EmptyState
              icon={ClipboardCheck}
              title="No real operations recorded yet"
              description="Evidence appears here once real (non-demo) planned sprays are checked and their outcomes recorded. Run a pre-spray check on real data or import records to start."
              cta={
                <div className="flex gap-2">
                  <Link href="/decisions">
                    <Button variant="secondary" size="sm">
                      Open decisions
                    </Button>
                  </Link>
                  <Link href={`/farms/${farmId}?tab=records`}>
                    <Button variant="secondary" size="sm">
                      Import records
                    </Button>
                  </Link>
                </div>
              }
            />
          )}
        </TabsContent>
      </Tabs>

      {/* Records table — rows are the SELECTED SCOPE only; chip counts come from
          the same predicates that filter the rows. */}
      <SectionCard
        title={scope === "demo" ? "Application records (simulated)" : "Application records"}
        icon={<ListChecks />}
        description="Each checked decision with its verdict (historical), review, and documentation state."
      >
        <FilterBar
          chips={EVIDENCE_FILTERS.map((f) => ({
            key: f.key,
            label: f.label,
            count: scopedRows.filter(f.match).length,
            selected: f.key === statusFilter,
            onClick: () => setStatusFilter(f.key),
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
          rowKey={(p) => p.id}
          minWidth={760}
          empty={
            <EmptyState
              icon={ListChecks}
              title={
                scopedRows.length === 0
                  ? scope === "demo"
                    ? "No simulated records"
                    : "No real records yet"
                  : "Nothing matches these filters"
              }
              description={
                scopedRows.length === 0 && scope === "real"
                  ? "Check a planned spray on real data to create the first record."
                  : "Clear a filter to see more records."
              }
            />
          }
        />
      </SectionCard>

      {/* Input orders in the SAME provenance scope — demo and real never mix.
          Amounts are recorded, never compared: no savings figure exists. */}
      <SectionCard
        title={scope === "demo" ? "Input orders (simulated)" : "Input orders"}
        icon={<Download />}
        description="Procurement chains: plan, quotes received, financing state, order, and the linked application. Quotes are concierge-entered; financing is indicative only; no savings figure is computed."
      >
        <DataTable
          columns={[
            {
              key: "plan",
              header: "Plan",
              render: (p) => (
                <div className="min-w-0">
                  <Link
                    href={`/inputs/plans/${p.id}`}
                    className="font-medium text-leaf-700 hover:underline"
                  >
                    Plan #{p.id}
                  </Link>
                  <div className="text-xs text-gray-500">
                    {p.items.map((i) => i.product_name).join(", ")}
                  </div>
                </div>
              ),
            },
            {
              key: "status",
              header: "Status",
              render: (p) => <StatusBadge kind="planStatus" value={p.status} />,
            },
            {
              key: "financing",
              header: "Financing",
              render: (p) => <StatusBadge kind="financing" value={p.financing_state} />,
            },
            {
              key: "quotes",
              header: "Quotes",
              align: "right",
              priority: "secondary",
              render: (p) => <span className="text-sm text-gray-700">{p.quote_count}</span>,
            },
            {
              key: "decision",
              header: "Source decision",
              priority: "secondary",
              render: (p) => {
                const linked = p.items.find((i) => i.planned_spray_id);
                return linked ? (
                  <Link
                    href={`/decisions/${linked.planned_spray_id}`}
                    className="text-sm font-medium text-leaf-700 hover:underline"
                  >
                    #{linked.planned_spray_id}
                  </Link>
                ) : (
                  <span className="text-xs text-gray-500">Manual</span>
                );
              },
            },
            {
              key: "order",
              header: "Order",
              align: "right",
              render: (p) =>
                p.order_id ? (
                  <Link
                    href={`/inputs/orders/${p.order_id}`}
                    className="text-sm font-medium text-leaf-700 hover:underline"
                  >
                    Order #{p.order_id}
                  </Link>
                ) : (
                  <span className="text-xs text-gray-500">—</span>
                ),
            },
          ]}
          rows={inputPlans.filter((p) =>
            scope === "demo" ? isDemoRecord(p) : !isDemoRecord(p)
          )}
          rowKey={(p) => p.id}
          minWidth={640}
          empty={
            <p className="text-sm text-gray-500">
              {scope === "demo"
                ? "No simulated input orders."
                : "No real input orders yet — real procurement chains appear in the evidence export automatically."}
            </p>
          }
        />
      </SectionCard>

      {/* Confirmed vs estimated detail (real scope: the honest split; the card
          itself excludes demo data and reconciles seeded outcomes separately). */}
      {farm && scope === "real" && (
        <SectionCard
          title="Decision evidence detail"
          icon={<ClipboardCheck />}
          description="Confirmed (follow-up-backed) vs estimated (entered values) — never combined into one score."
        >
          <DecisionEvidenceCard
            farmId={farmId}
            country={farm.country}
            area={farm.greenhouse_area}
            refreshKey={`${planned.length}`}
          />
        </SectionCard>
      )}

      {/* Measured spray reduction — the pesticide-reduction story, front and
          center. Its honesty gates stay: no declared baseline means no number,
          and weak/simulated baselines render as illustrative, never a headline. */}
      <SectionCard
        title="Measured spray reduction"
        icon={<ListChecks />}
        description="Sprays vs. a grower/PCA-declared baseline. No baseline, no number; low-confidence figures are marked illustrative."
      >
        <ReductionCard farmId={farmId} refreshKey={`${planned.length}`} />
      </SectionCard>

      {/* Reports & exports — generated on demand; no stored history to misstate. */}
      <SectionCard
        title="Reports & exports"
        icon={<Download />}
        description="Reports are generated on demand from current records; Lumos does not store report history."
      >
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {[
            {
              name: "Audit packet (JSON)",
              contents: "Farm record + flags + review trail + report text",
              href: `${API_BASE_URL}/farms/${farmId}/audit-packet`,
            },
            {
              name: "Evidence export (JSON)",
              contents: "Anonymized decisions with provenance + methodology",
              href: `${API_BASE_URL}/farms/${farmId}/evidence-export`,
            },
            {
              name: "Evidence export (CSV)",
              contents: "One row per decision",
              href: `${API_BASE_URL}/farms/${farmId}/export/evidence.csv`,
            },
            {
              name: "Spray events (CSV)",
              contents: "All applied sprays with entered PHI/REI",
              href: `${API_BASE_URL}/farms/${farmId}/export/spray-events.csv`,
            },
            {
              name: "Recommendations (CSV)",
              contents: "Weekly risk reviews with review status",
              href: `${API_BASE_URL}/farms/${farmId}/export/recommendations.csv`,
            },
            {
              name: "Weekly report",
              contents: "Copy-pasteable grower summary",
              href: `/farms/${farmId}?tab=evidence`,
              internal: true,
            },
          ].map((row) =>
            row.internal ? (
              <Link
                key={row.name}
                href={row.href}
                className="flex items-center justify-between gap-2 rounded-md border border-gray-200 p-3 text-sm hover:border-gray-400"
              >
                <span>
                  <span className="font-medium text-gray-900">{row.name}</span>
                  <span className="block text-[11px] text-gray-500">{row.contents}</span>
                </span>
              </Link>
            ) : (
              <a
                key={row.name}
                href={row.href}
                target="_blank"
                rel="noreferrer"
                className="flex items-center justify-between gap-2 rounded-md border border-gray-200 p-3 text-sm hover:border-gray-400"
              >
                <span>
                  <span className="font-medium text-gray-900">{row.name}</span>
                  <span className="block text-[11px] text-gray-500">{row.contents}</span>
                </span>
                <Download className="h-3.5 w-3.5 shrink-0 text-gray-400" aria-hidden />
              </a>
            )
          )}
        </div>
      </SectionCard>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
