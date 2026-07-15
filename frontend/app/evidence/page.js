"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  ClipboardCheck,
  Download,
  FileCheck,
  FlaskConical,
  ListChecks,
  Search,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";
import { api, API_BASE_URL } from "@/lib/api";
import { formatCost, formatDate } from "@/lib/format";
import { useFarmContext } from "@/lib/farm-context";
import { RECORDED_OUTCOME_LABELS } from "@/lib/labels";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { OUTCOME_META } from "@/components/DecisionResult";
import Breadcrumbs from "@/components/Breadcrumbs";
import DecisionEvidenceCard from "@/components/DecisionEvidenceCard";
import KpiTile from "@/components/KpiTile";
import ProgressBar from "@/components/ProgressBar";
import SectionCard from "@/components/SectionCard";

const HEADER_CLS =
  "px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wide text-gray-500";

// Documentation status of one checked decision, derived from real fields:
// follow_up_required × follow_up_event_count (never invented).
function docStatus(p) {
  if (!p.outcome || p.outcome === "planned") {
    return { key: "awaiting", label: "Awaiting outcome", variant: "neutral" };
  }
  if (p.follow_up_required && p.follow_up_event_count === 0) {
    return { key: "follow_up_needed", label: "Follow-up needed", variant: "amber" };
  }
  if (p.follow_up_required && p.follow_up_event_count > 0) {
    return { key: "in_progress", label: "Follow-up in progress", variant: "blue" };
  }
  return { key: "documented", label: "Documented", variant: "green" };
}

const STATUS_FILTERS = [
  { key: "all", label: "All", match: () => true },
  { key: "follow_up_needed", label: "Follow-up needed", match: (p) => docStatus(p).key === "follow_up_needed" },
  { key: "documented", label: "Documented", match: (p) => docStatus(p).key === "documented" },
  { key: "reviewed", label: "PCA-reviewed", match: (p) => ["approved", "edited"].includes(p.review_state) },
];

const OUTCOME_BAR_SEGMENTS = [
  { key: "sprayed_as_planned", tone: "bg-gray-400" },
  { key: "changed_product", tone: "bg-blue-500" },
  { key: "delayed", tone: "bg-amber-500" },
  { key: "avoided", tone: "bg-leaf" },
  { key: "inspected_first", tone: "bg-leaf-100" },
];

// Evidence & reports for the active farm: audit-ready records, on-demand
// reports, and the confirmed/estimated pilot-evidence split. Every figure is a
// real endpoint field; derived ratios are labelled as such.
export default function EvidencePage() {
  const { activeFarm, loading: farmsLoading } = useFarmContext();
  const farmId = activeFarm?.id;

  const [farm, setFarm] = useState(null);
  const [planned, setPlanned] = useState([]);
  const [evidence, setEvidence] = useState(null);
  const [error, setError] = useState(null);
  const [statusFilter, setStatusFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [showAll, setShowAll] = useState(false);

  const load = useCallback(async () => {
    if (!farmId) return;
    try {
      const [f, p, ev] = await Promise.all([
        api.getFarm(farmId),
        api.listPlannedSprays(farmId),
        api.getDecisionEvidence(farmId),
      ]);
      setFarm(f);
      setPlanned(p);
      setEvidence(ev);
      setError(null);
    } catch (err) {
      setError(err.message);
    }
  }, [farmId]);

  useEffect(() => {
    load();
  }, [load]);

  const filtered = useMemo(() => {
    const f = STATUS_FILTERS.find((s) => s.key === statusFilter) || STATUS_FILTERS[0];
    const q = query.trim().toLowerCase();
    return planned
      .filter(f.match)
      .filter(
        (p) =>
          !q ||
          (p.product_name || "").toLowerCase().includes(q) ||
          (p.target_pest_or_disease || "").toLowerCase().includes(q)
      )
      .sort((a, b) => (a.intended_date < b.intended_date ? 1 : -1));
  }, [planned, statusFilter, query]);

  if (farmsLoading) return <p className="text-sm text-gray-500">Loading…</p>;
  if (!activeFarm) {
    return (
      <p className="text-sm text-gray-500">
        No farms yet — seed the demo data or add a pilot farm first.
      </p>
    );
  }

  const outstanding = planned.filter(
    (p) => p.follow_up_required && p.follow_up_event_count === 0
  );
  const outcomes = evidence?.outcomes;
  const checked = evidence?.decisions_checked ?? 0;
  const recordedTotal = outcomes
    ? OUTCOME_BAR_SEGMENTS.reduce((sum, s) => sum + (outcomes[s.key] || 0), 0)
    : 0;
  const interventionRate =
    checked > 0 && evidence
      ? Math.round((evidence.sprays_changed_delayed_or_avoided / checked) * 100)
      : null;
  const shown = showAll ? filtered : filtered.slice(0, 8);

  return (
    <div className="space-y-5">
      <Breadcrumbs items={[{ label: "Evidence & reports" }, { label: activeFarm.name }]} />

      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-gray-900">Evidence &amp; reports</h1>
          <p className="mt-0.5 text-xs text-gray-500">
            Decision records, documentation status, and on-demand reports for{" "}
            {activeFarm.name}. Confirmed and estimated figures are never combined.
          </p>
        </div>
        {activeFarm.is_demo && (
          <Badge variant="outline">
            <FlaskConical />
            Simulated demo data
          </Badge>
        )}
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* KPI tiles — real decision-evidence fields (demo data excluded by the backend) */}
      {evidence && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <KpiTile
            icon={ShieldCheck}
            label="Decisions checked"
            value={evidence.decisions_checked}
            hint="real (non-demo) pre-spray checks"
            tone="neutral"
          />
          <KpiTile
            icon={ClipboardCheck}
            label="PCA-reviewed"
            value={`${evidence.decisions_reviewed}/${evidence.decisions_checked}`}
            hint="approved, edited, or rejected"
            tone="neutral"
          />
          <KpiTile
            icon={TriangleAlert}
            label="Conflicts caught"
            value={evidence.compliance_conflicts_caught}
            hint="blocking conflicts before spraying"
            tone={evidence.compliance_conflicts_caught > 0 ? "warn" : "neutral"}
          />
          <KpiTile
            icon={ListChecks}
            label="Est. cost avoided"
            value={formatCost(evidence.estimated_chemical_cost_avoided || 0, activeFarm.country)}
            hint="entered estimates — not confirmed until follow-up"
            tone="neutral"
          />
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        {/* Main column */}
        <div className="min-w-0 space-y-4 lg:col-span-2">
          <SectionCard
            title="Application records"
            icon={<FileCheck />}
            description="Checked planned sprays with their decision, recorded outcome, and documentation status."
          >
            {/* Filters — client-side over already-loaded records */}
            <div className="mb-3 flex flex-wrap items-center gap-2">
              {STATUS_FILTERS.map((f) => {
                const selected = f.key === statusFilter;
                const count = planned.filter(f.match).length;
                return (
                  <button
                    key={f.key}
                    onClick={() => setStatusFilter(f.key)}
                    className={`rounded-full px-2.5 py-1 text-xs font-medium transition-colors ${
                      selected
                        ? "bg-leaf-700 text-white"
                        : "border border-gray-200 bg-white text-gray-600 hover:bg-gray-50"
                    }`}
                  >
                    {f.label}{" "}
                    <span className={selected ? "opacity-80" : "text-gray-400"}>{count}</span>
                  </button>
                );
              })}
              <div className="relative ml-auto w-48">
                <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-gray-400" />
                <Input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search product or target"
                  className="h-8 pl-7 text-xs"
                />
              </div>
            </div>

            {shown.length === 0 ? (
              <p className="py-2 text-sm text-gray-500">
                {planned.length === 0
                  ? "No checked planned sprays yet."
                  : "Nothing matches this filter."}
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[680px] text-sm">
                  <thead>
                    <tr className="border-b border-gray-200">
                      <th className={HEADER_CLS}>Date</th>
                      <th className={HEADER_CLS}>Product / target</th>
                      <th className={HEADER_CLS}>PHI / REI</th>
                      <th className={HEADER_CLS}>Decision</th>
                      <th className={HEADER_CLS}>Documentation</th>
                      <th className={HEADER_CLS}>
                        <span className="sr-only">Open</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {shown.map((p) => {
                      const meta =
                        OUTCOME_META[p.decision_outcome] || OUTCOME_META.pca_review_required;
                      const doc = docStatus(p);
                      return (
                        <tr key={p.id} className="align-top">
                          <td className="whitespace-nowrap px-3 py-3 text-gray-700">
                            {formatDate(p.intended_date)}
                          </td>
                          <td className="px-3 py-3">
                            <div className="font-medium text-gray-900">{p.product_name}</div>
                            <div className="text-xs text-gray-500">
                              {p.target_pest_or_disease || "—"}
                            </div>
                          </td>
                          <td className="whitespace-nowrap px-3 py-3 text-xs text-gray-700">
                            {p.pre_harvest_interval_days != null
                              ? `${p.pre_harvest_interval_days}d`
                              : "—"}
                            {" / "}
                            {p.re_entry_interval_hours != null
                              ? `${p.re_entry_interval_hours}h`
                              : "—"}
                          </td>
                          <td className="px-3 py-3">
                            <Badge variant={meta.badge}>{meta.label}</Badge>
                            {p.outcome && p.outcome !== "planned" && (
                              <div className="mt-1 text-[11px] text-gray-500">
                                {RECORDED_OUTCOME_LABELS[p.outcome] || p.outcome}
                              </div>
                            )}
                          </td>
                          <td className="px-3 py-3">
                            <Badge variant={doc.variant}>{doc.label}</Badge>
                          </td>
                          <td className="px-3 py-3 text-right">
                            <Link href={`/decisions/${p.id}`}>
                              <Button variant="secondary" size="sm">
                                Open
                              </Button>
                            </Link>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}

            {filtered.length > 8 && !showAll && (
              <button
                onClick={() => setShowAll(true)}
                className="mt-2 text-xs font-medium text-leaf-700 hover:underline"
              >
                Show all {filtered.length} records
              </button>
            )}
          </SectionCard>

          <SectionCard
            title="Reports & exports"
            icon={<Download />}
            description="Reports are generated on demand from current records; Lumos does not store report history."
          >
            <div className="overflow-x-auto">
              <table className="w-full min-w-[480px] text-sm">
                <thead>
                  <tr className="border-b border-gray-200">
                    <th className={HEADER_CLS}>Report</th>
                    <th className={HEADER_CLS}>Contents</th>
                    <th className={HEADER_CLS}>
                      <span className="sr-only">Action</span>
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {[
                    {
                      name: "Weekly report",
                      contents: "Copy-pasteable grower summary (WhatsApp / text)",
                      href: `/farms/${farmId}?tab=evidence`,
                      label: "Open",
                      internal: true,
                    },
                    {
                      name: "Audit packet (JSON)",
                      contents: "Farm record + flags + review trail + report text",
                      href: `${API_BASE_URL}/farms/${farmId}/audit-packet`,
                      label: "Download",
                    },
                    {
                      name: "Evidence export (JSON)",
                      contents: "Anonymized decisions with provenance + methodology",
                      href: `${API_BASE_URL}/farms/${farmId}/evidence-export`,
                      label: "Download",
                    },
                    {
                      name: "Evidence export (CSV)",
                      contents: "Same evidence export, one row per decision",
                      href: `${API_BASE_URL}/farms/${farmId}/export/evidence.csv`,
                      label: "Download",
                    },
                    {
                      name: "Spray events (CSV)",
                      contents: "All applied sprays with entered PHI/REI",
                      href: `${API_BASE_URL}/farms/${farmId}/export/spray-events.csv`,
                      label: "Download",
                    },
                    {
                      name: "Recommendations (CSV)",
                      contents: "Weekly risk reviews with review status",
                      href: `${API_BASE_URL}/farms/${farmId}/export/recommendations.csv`,
                      label: "Download",
                    },
                  ].map((row) => (
                    <tr key={row.name}>
                      <td className="px-3 py-3 font-medium text-gray-900">{row.name}</td>
                      <td className="px-3 py-3 text-xs text-gray-600">{row.contents}</td>
                      <td className="px-3 py-3 text-right">
                        {row.internal ? (
                          <Link href={row.href}>
                            <Button variant="secondary" size="sm">
                              {row.label}
                            </Button>
                          </Link>
                        ) : (
                          <a href={row.href} target="_blank" rel="noreferrer">
                            <Button variant="secondary" size="sm">
                              <Download />
                              {row.label}
                            </Button>
                          </a>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </SectionCard>

          {farm && (
            <SectionCard
              title="Decision evidence detail"
              icon={<ListChecks />}
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
        </div>

        {/* Right rail */}
        <div className="space-y-4">
          <SectionCard
            title="Outstanding documentation"
            icon={<TriangleAlert />}
            description="Decisions that require a follow-up event and have none yet."
          >
            {outstanding.length === 0 ? (
              <p className="text-sm text-gray-500">Nothing outstanding.</p>
            ) : (
              <ul className="divide-y divide-gray-100">
                {outstanding.map((p) => (
                  <li key={p.id} className="flex items-center justify-between gap-2 py-2">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium text-gray-900">
                        {p.product_name}
                      </div>
                      <div className="text-xs text-gray-500">
                        {RECORDED_OUTCOME_LABELS[p.outcome] || p.outcome}
                        {p.outcome_date ? ` · recorded ${formatDate(p.outcome_date)}` : ""}
                      </div>
                    </div>
                    <Link href={`/decisions/${p.id}`}>
                      <Button variant="secondary" size="sm">
                        Record
                      </Button>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </SectionCard>

          <SectionCard
            title="Recorded outcomes"
            icon={<ClipboardCheck />}
            description="Real (non-demo) decisions only."
          >
            {checked === 0 ? (
              <p className="text-xs text-gray-500">
                No real (non-demo) decisions recorded yet — evidence metrics count real
                pilot data only.
              </p>
            ) : (
              <div className="space-y-3 text-xs text-gray-600">
                {recordedTotal > 0 && (
                  <div>
                    <div className="flex h-2 w-full overflow-hidden rounded-full bg-gray-100">
                      {OUTCOME_BAR_SEGMENTS.map((s) =>
                        outcomes[s.key] > 0 ? (
                          <div
                            key={s.key}
                            className={s.tone}
                            style={{ width: `${(outcomes[s.key] / recordedTotal) * 100}%` }}
                          />
                        ) : null
                      )}
                    </div>
                    <ul className="mt-2 space-y-0.5">
                      {OUTCOME_BAR_SEGMENTS.map((s) => (
                        <li key={s.key} className="flex items-center justify-between">
                          <span className="inline-flex items-center gap-1.5">
                            <span className={`h-2 w-2 rounded-full ${s.tone}`} />
                            {RECORDED_OUTCOME_LABELS[s.key]}
                          </span>
                          <span className="font-medium text-gray-900">{outcomes[s.key]}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {interventionRate != null && (
                  <div className="flex items-center justify-between border-t border-gray-100 pt-2">
                    <span>Changed / delayed / avoided</span>
                    <span className="font-medium text-gray-900">
                      {interventionRate}% of checked decisions
                    </span>
                  </div>
                )}
                {evidence?.follow_up?.follow_up_required > 0 && (
                  <div>
                    <div className="mb-1 flex items-center justify-between">
                      <span>Follow-up recorded</span>
                      <span className="font-medium text-gray-900">
                        {evidence.follow_up.follow_up_with_events}/
                        {evidence.follow_up.follow_up_required}
                      </span>
                    </div>
                    <ProgressBar
                      ratio={
                        evidence.follow_up.follow_up_with_events /
                        evidence.follow_up.follow_up_required
                      }
                    />
                  </div>
                )}
              </div>
            )}
          </SectionCard>

          {evidence?.estimated?.basis && (
            <div className="flex items-start gap-2 rounded-xl border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900">
              <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <p>{evidence.estimated.basis}</p>
            </div>
          )}

          <Link
            href={`/farms/${farmId}?tab=evidence`}
            className="flex items-center justify-between rounded-xl border border-gray-200 bg-white p-3 text-sm font-medium text-gray-700 shadow-sm transition-colors hover:border-gray-400"
          >
            <span>Full farm evidence (reduction, analytics, weekly report)</span>
            <ArrowRight className="h-3.5 w-3.5 shrink-0 text-gray-300" />
          </Link>
        </div>
      </div>
    </div>
  );
}
