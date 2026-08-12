"use client";

import { LoadingState } from "@/components/SystemState";
import Callout from "@/components/Callout";
import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  CalendarClock,
  Droplets,
  EllipsisVertical,
  FlaskConical,
  MapPin,
  Plus,
  RotateCcw,
  Sprout,
  Wrench,
} from "lucide-react";
import { api } from "@/lib/api";
import { formatArea, formatDate } from "@/lib/format";
import { URGENCY_META } from "@/lib/labels";
import { isSecondaryDemoFarm } from "@/lib/farms";
import { nextActionLabel, severityLabel } from "@/lib/status";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import DataTable from "@/components/DataTable";
import EmptyState from "@/components/EmptyState";
import FilterBar from "@/components/FilterBar";
import PageHeader from "@/components/PageHeader";
import SectionCard from "@/components/SectionCard";
import SeverityBadge from "@/components/SeverityBadge";
import StatusBadge from "@/components/StatusBadge";

// Rank for "most urgent decision defines the field's status/action".
const WORKFLOW_RANK = { awaiting_pca: 0, needs_action: 1, resolved: 2 };

// Derive the per-field operational rows for one farm from its already-loaded
// records (grouping/presentation only — every state shown is a server field).
function deriveFields({ planned, observations, sprays }) {
  const names = new Set();
  for (const r of [...planned, ...observations, ...sprays]) {
    if (r.field_block) names.add(r.field_block);
  }
  return [...names].sort().map((name) => {
    const decisions = planned.filter((p) => p.field_block === name);
    const fieldObs = observations
      .filter((o) => o.field_block === name)
      .sort((a, b) => (a.observation_date < b.observation_date ? 1 : -1));
    const open = decisions
      .filter((p) => p.is_open)
      .sort((a, b) => (a.intended_date < b.intended_date ? -1 : 1));
    // The decision that defines the field's current status: most urgent workflow
    // state first, then follow-up debt, then the most recent one.
    const byUrgency = [...decisions].sort(
      (a, b) =>
        (WORKFLOW_RANK[a.workflow_state] ?? 9) - (WORKFLOW_RANK[b.workflow_state] ?? 9)
    );
    const followUpDue = decisions.find((p) =>
      ["follow_up_required", "follow_up_in_progress"].includes(p.evidence_state)
    );
    const lead = byUrgency.find((p) => p.workflow_state !== "resolved") || followUpDue || byUrgency[0];
    return {
      name,
      decisions,
      latestObs: fieldObs[0] || null,
      nextPlanned: open[0] || null,
      lead,
      sprayCount: sprays.filter((s) => s.field_block === name).length,
    };
  });
}

function DemoToolsMenu({ onReset, resetting }) {
  return (
    <details className="relative">
      <summary
        className="flex h-10 cursor-pointer select-none items-center gap-1 rounded-control border border-line bg-surface px-3 text-sm font-medium text-muted shadow-sm hover:bg-canvas focus:outline-none focus-visible:ring-2 focus-visible:ring-focus [&::-webkit-details-marker]:hidden"
        aria-label="Demo and admin tools"
      >
        <EllipsisVertical className="h-4 w-4" />
        Demo tools
      </summary>
      <div className="absolute right-0 z-20 mt-1 w-64 rounded-control border border-line bg-surface p-2 shadow-lg">
        <p className="px-2 pb-2 pt-1 text-[11px] text-muted">
          Demo administration — not an operational action.
        </p>
        <button
          onClick={onReset}
          disabled={resetting}
          className="flex w-full items-center gap-2 rounded-control px-2 py-1.5 text-left text-sm text-ink transition-colors hover:bg-canvas focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-focus disabled:opacity-50"
        >
          <RotateCcw className="h-4 w-4" />
          {resetting ? "Resetting…" : "Reset demo data"}
        </button>
      </div>
    </details>
  );
}

export default function FarmsPage() {
  const [farms, setFarms] = useState([]);
  const [records, setRecords] = useState({}); // farmId -> {planned, observations, sprays}
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [resetting, setResetting] = useState(false);
  const [resetError, setResetError] = useState(null);
  const [referenceFarmIds, setReferenceFarmIds] = useState(() => new Set());
  const [datasetScope, setDatasetScope] = useState("all"); // all | real | demo

  const load = useCallback(async () => {
    try {
      // /farms-overview carries the urgency ranking but not `is_reference`;
      // /farms carries `is_reference` but no ranking. Join them client-side so an
      // operator reference farm can be labelled as one — it is not a customer,
      // and a viewer must never read it as pilot traction.
      const [all, base] = await Promise.all([
        api.listFarmsOverview(),
        api.listFarms().catch(() => []),
      ]);
      const referenceIds = new Set(
        base.filter((f) => f.is_reference).map((f) => f.id)
      );
      setReferenceFarmIds(referenceIds);
      setFarms(all);
      const visible = all.filter((f) => !isSecondaryDemoFarm(f));
      const entries = await Promise.all(
        visible.map(async (f) => {
          const [planned, observations, sprays] = await Promise.all([
            api.listPlannedSprays(f.id),
            api.listScoutObservations(f.id),
            api.listSprayEvents(f.id),
          ]);
          return [f.id, { planned, observations, sprays }];
        })
      );
      setRecords(Object.fromEntries(entries));
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function resetDemo() {
    if (
      !window.confirm(
        "Reset the demo data? This drops and re-seeds ALL demo data, anchored to today."
      )
    ) {
      return;
    }
    setResetting(true);
    setResetError(null);
    try {
      await api.resetDemo();
      await load();
    } catch (err) {
      setResetError(err.message);
    } finally {
      setResetting(false);
    }
  }

  const visibleFarms = farms.filter((f) => !isSecondaryDemoFarm(f));
  const allDemo = farms.length > 0 && farms.every((f) => f.is_demo);

  // Dataset scope. `is_demo` is the server's own per-farm derivation (a farm is
  // demo iff it has records and all of them are demo-tagged) — not re-derived here.
  const DATASET_SCOPES = [
    { key: "all", label: "All", match: () => true },
    { key: "real", label: "Real operations", match: (f) => !f.is_demo },
    { key: "demo", label: "Simulated / test", match: (f) => f.is_demo },
  ];
  const activeScope =
    DATASET_SCOPES.find((s) => s.key === datasetScope) || DATASET_SCOPES[0];
  const scopedFarms = visibleFarms.filter(activeScope.match);

  const fieldColumns = (farm) => [
    {
      key: "field",
      header: "Field",
      render: (f) => <span className="font-medium text-ink">{f.name}</span>,
    },
    {
      key: "crop",
      header: "Crop",
      priority: "secondary",
      render: () => (
        <span className="capitalize text-ink">
          {farm.crop_type?.replace(/_/g, " ") || "—"}
        </span>
      ),
    },
    {
      key: "status",
      header: "Current status",
      render: (f) =>
        f.lead ? (
          f.lead.workflow_state !== "resolved" ? (
            <StatusBadge kind="workflow" value={f.lead.workflow_state} />
          ) : (
            <StatusBadge kind="evidence" value={f.lead.evidence_state} />
          )
        ) : (
          <span className="text-xs text-muted">No decisions</span>
        ),
    },
    {
      key: "next_spray",
      header: "Next planned spray",
      priority: "secondary",
      render: (f) =>
        f.nextPlanned ? (
          <div className="min-w-0 text-sm">
            <div className="font-medium text-ink">{f.nextPlanned.product_name}</div>
            <div className="text-xs text-muted">
              {formatDate(f.nextPlanned.intended_date)}
            </div>
          </div>
        ) : (
          <span className="text-xs text-muted">None open</span>
        ),
    },
    {
      key: "risk",
      header: "Risk",
      render: (f) =>
        f.nextPlanned ? (
          <StatusBadge kind="verdict" value={f.nextPlanned.decision_outcome} />
        ) : f.latestObs ? (
          <div className="flex items-center gap-1.5 whitespace-nowrap">
            <SeverityBadge value={f.latestObs.severity_1_to_5} />
            <span className="text-xs text-muted">
              {severityLabel(f.latestObs.severity_1_to_5)} · {f.latestObs.visible_issue}
            </span>
          </div>
        ) : (
          <span className="text-xs text-muted">—</span>
        ),
    },
    {
      key: "next_action",
      header: "Required next action",
      priority: "secondary",
      render: (f) => (
        <span className="text-xs text-muted">
          {f.lead && f.lead.current_next_action !== "none"
            ? nextActionLabel(f.lead.current_next_action)
            : "—"}
        </span>
      ),
    },
    {
      key: "action",
      priority: "action",
      header: <span className="sr-only">Action</span>,
      align: "right",
      render: (f) =>
        f.lead ? (
          <Link href={`/decisions/${f.lead.id}`}>
            <Button variant="secondary" size="sm">
              {nextActionLabel(f.lead.current_next_action)}
            </Button>
          </Link>
        ) : (
          <Link href={`/farms/${farm.id}?tab=records`}>
            <Button variant="secondary" size="sm">
              View records
            </Button>
          </Link>
        ),
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumbs={[{ label: "Farms & fields" }]}
        title="Farms & fields"
        meta={<span>Operational status ranked by what needs attention.</span>}
        actions={
          <>
            <Link href="/pilot/new">
              <Button>
                <Plus />
                Add pilot farm
              </Button>
            </Link>
            {allDemo && <DemoToolsMenu onReset={resetDemo} resetting={resetting} />}
          </>
        }
      />

      {resetError && (
        <Callout tone="risk">
          {resetError}
        </Callout>
      )}
      {loading && <LoadingState message="Loading farms…" />}
      {error && (
        <Callout tone="risk">
          {error} — is the backend running on <code>http://localhost:8000</code>?
        </Callout>
      )}

      {!loading && visibleFarms.length > 0 && (
        <FilterBar
          chips={DATASET_SCOPES.map((s) => ({
            key: s.key,
            label: s.label,
            count: visibleFarms.filter(s.match).length,
            selected: s.key === datasetScope,
            onClick: () => setDatasetScope(s.key),
          }))}
        />
      )}

      {!loading && scopedFarms.length === 0 && visibleFarms.length > 0 && (
        <EmptyState
          icon={Sprout}
          title="No farms in this dataset"
          description="Switch the dataset filter above to see the other records."
        />
      )}

      {scopedFarms.map((farm) => {
        const recs = records[farm.id] || { planned: [], observations: [], sprays: [] };
        const fields = deriveFields(recs);
        const meta = URGENCY_META[farm.urgency] || URGENCY_META.ok;
        const overdue = farm.days_to_harvest != null && farm.days_to_harvest < 0;
        return (
          // One card per farm: identity + next action, then that farm's fields
          // below a divider. The fields table used to be a second full-size
          // SectionCard sitting outside the card, so five farms produced ten
          // stacked panels and the page lost any sense of grouping.
          <Card
            key={farm.id}
            className={`overflow-hidden transition-colors hover:border-muted ${meta.border}`}
          >
            <Link href={`/farms/${farm.id}`} className="group block">
              <div>
                <CardContent className="p-5">
                  {/* A grid, not a wrapping flex row: with justify-between the
                      next-action panel landed under the title on farms with long
                      names and top-right on the others, so no two cards agreed
                      on where to look for the same information. */}
                  <div className="grid grid-cols-1 items-start gap-3 sm:grid-cols-[minmax(0,1fr)_300px]">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-base font-semibold text-ink">
                          {farm.name}
                        </span>
                        <Badge variant={meta.variant}>{meta.label}</Badge>
                        {farm.is_demo && (
                          <Badge variant="outline">
                            <FlaskConical />
                            Simulated demo data
                          </Badge>
                        )}
                        {/* A reference farm carries real provenance but has no
                            grower. Saying so here stops it being read as a pilot. */}
                        {referenceFarmIds.has(farm.id) && (
                          <Badge variant="red">
                            <Wrench />
                            Operator test — not a customer
                          </Badge>
                        )}
                      </div>
                      <div className="mt-1 flex items-center gap-1 text-xs text-muted">
                        <MapPin className="h-3 w-3 shrink-0" />
                        {farm.location || "—"} · {(farm.country || "US").toUpperCase()}
                      </div>
                    </div>
                    {/* The next action is the point of this card, so it gets a
                        labelled panel of its own. As a bare right-aligned text
                        block in a wrapping flex row it landed at a different
                        place on every card, depending on how long the farm's
                        name was, and read as floating unattached copy. */}
                    <div
                      className={`rounded-control border px-3 py-2 ${meta.border} bg-canvas/60`}
                    >
                      <div className="text-[11px] font-semibold uppercase tracking-wider text-muted">
                        Next action
                      </div>
                      <div className="mt-0.5 text-sm font-medium text-ink">
                        {farm.next_action}
                      </div>
                      <div className="mt-0.5 text-xs text-muted">{farm.why}</div>
                    </div>
                  </div>

                  <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-muted">
                    <span className="inline-flex items-center gap-1 capitalize">
                      <Sprout className="h-3 w-3" />
                      {farm.crop_type?.replace(/_/g, " ")}
                    </span>
                    {farm.area != null && <span>{formatArea(farm.area, farm.country)}</span>}
                    <span>
                      {fields.length > 0 ? `${fields.length} field(s)` : "no named fields"}
                    </span>
                    <span className="inline-flex items-center gap-1">
                      <Droplets className="h-3 w-3" />
                      {farm.spray_count} sprays
                    </span>
                    <span
                      className={`inline-flex items-center gap-1 ${
                        overdue ? "font-medium text-risk-fg" : ""
                      }`}
                    >
                      <CalendarClock className="h-3 w-3" />
                      {overdue
                        ? `Harvest date passed (expected ${formatDate(farm.expected_harvest_date)})`
                        : `harvest ${formatDate(farm.expected_harvest_date)}`}
                    </span>
                    <span>
                      {farm.flag_count > 0
                        ? `${farm.flag_count} open risk flag(s)`
                        : "no open risk flags"}
                    </span>
                  </div>
                </CardContent>
              </div>
            </Link>

            {/* Fields live inside the farm card, outside its link: a table with
                its own row actions must never be nested in an anchor. */}
            <div className="border-t border-line bg-canvas/40 px-5 py-3">
              <div className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted">
                <Sprout className="h-3.5 w-3.5" aria-hidden />
                Fields
              </div>
              {fields.length === 0 ? (
                // A one-line note, not a panel: "this farm's records carry no
                // block name" does not deserve the same weight as the farm.
                <p className="text-meta text-muted">
                  No named fields yet — records on this farm don&apos;t carry a
                  field/block name. Add one when logging sprays, scouting, or planned
                  sprays and fields will appear here.
                </p>
              ) : (
                <DataTable
                  columns={fieldColumns(farm)}
                  rows={fields}
                  rowKey={(f) => f.name}
                  minWidth={640}
                  stickyHeader={false}
                />
              )}
            </div>
          </Card>
        );
      })}

      {!loading && !error && farms.length === 0 && (
        <EmptyState
          icon={Sprout}
          title="No farms yet"
          description="Add a pilot farm to get started — the intake takes about two minutes."
          cta={
            <Link href="/pilot/new">
              <Button>Add pilot farm</Button>
            </Link>
          }
        />
      )}
    </div>
  );
}
