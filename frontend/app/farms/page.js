"use client";

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
        className="flex h-10 cursor-pointer select-none items-center gap-1 rounded-md border border-gray-300 bg-white px-3 text-sm font-medium text-gray-600 shadow-sm hover:bg-gray-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 [&::-webkit-details-marker]:hidden"
        aria-label="Demo and admin tools"
      >
        <EllipsisVertical className="h-4 w-4" />
        Demo tools
      </summary>
      <div className="absolute right-0 z-20 mt-1 w-64 rounded-md border border-gray-200 bg-white p-2 shadow-lg">
        <p className="px-2 pb-2 pt-1 text-[11px] text-gray-500">
          Demo administration — not an operational action.
        </p>
        <button
          onClick={onReset}
          disabled={resetting}
          className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
        >
          <RotateCcw className="h-4 w-4" />
          {resetting ? "Resetting…" : "Reset YC demo data"}
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

  const load = useCallback(async () => {
    try {
      const all = await api.listFarmsOverview();
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
        "Reset the YC demo? This drops and re-seeds ALL demo data, anchored to today."
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

  const fieldColumns = (farm) => [
    {
      key: "field",
      header: "Field",
      render: (f) => <span className="font-medium text-gray-900">{f.name}</span>,
    },
    {
      key: "crop",
      header: "Crop",
      priority: "secondary",
      render: () => (
        <span className="capitalize text-gray-700">
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
          <span className="text-xs text-gray-400">No decisions</span>
        ),
    },
    {
      key: "next_spray",
      header: "Next planned spray",
      render: (f) =>
        f.nextPlanned ? (
          <div className="min-w-0 text-sm">
            <div className="font-medium text-gray-900">{f.nextPlanned.product_name}</div>
            <div className="text-xs text-gray-500">
              {formatDate(f.nextPlanned.intended_date)}
            </div>
          </div>
        ) : (
          <span className="text-xs text-gray-400">None open</span>
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
            <span className="text-xs text-gray-600">
              {severityLabel(f.latestObs.severity_1_to_5)} · {f.latestObs.visible_issue}
            </span>
          </div>
        ) : (
          <span className="text-xs text-gray-400">—</span>
        ),
    },
    {
      key: "next_action",
      header: "Required next action",
      priority: "secondary",
      render: (f) => (
        <span className="text-xs text-gray-600">
          {f.lead && f.lead.current_next_action !== "none"
            ? nextActionLabel(f.lead.current_next_action)
            : "—"}
        </span>
      ),
    },
    {
      key: "action",
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
        meta={
          <span>
            The decision layer before the spray — ranked by what needs attention.
          </span>
        }
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
        <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {resetError}
        </div>
      )}
      {loading && <p className="text-sm text-gray-500">Loading farms…</p>}
      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error} — is the backend running on <code>http://localhost:8000</code>?
        </div>
      )}

      {visibleFarms.map((farm) => {
        const recs = records[farm.id] || { planned: [], observations: [], sprays: [] };
        const fields = deriveFields(recs);
        const meta = URGENCY_META[farm.urgency] || URGENCY_META.ok;
        const overdue = farm.days_to_harvest != null && farm.days_to_harvest < 0;
        return (
          <div key={farm.id} className="space-y-4">
            <Link href={`/farms/${farm.id}`} className="group block">
              <Card className={`transition-colors group-hover:border-gray-400 ${meta.border}`}>
                <CardContent className="p-5">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-base font-semibold text-gray-900">
                          {farm.name}
                        </span>
                        <Badge variant={meta.variant}>{meta.label}</Badge>
                        {farm.is_demo && (
                          <Badge variant="outline">
                            <FlaskConical />
                            Simulated demo data
                          </Badge>
                        )}
                      </div>
                      <div className="mt-1 flex items-center gap-1 text-xs text-gray-500">
                        <MapPin className="h-3 w-3 shrink-0" />
                        {farm.location || "—"} · {(farm.country || "US").toUpperCase()}
                      </div>
                    </div>
                    <div className="text-right text-xs text-gray-600">
                      <div className="font-medium text-gray-900">{farm.next_action}</div>
                      <div className="text-gray-500">{farm.why}</div>
                    </div>
                  </div>

                  <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-gray-600">
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
                        overdue ? "font-medium text-red-700" : ""
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
              </Card>
            </Link>

            <SectionCard
              title={`Fields — ${farm.name}`}
              icon={<Sprout />}
              description="Named field blocks from this farm's records, with each field's current operational state."
            >
              <DataTable
                columns={fieldColumns(farm)}
                rows={fields}
                rowKey={(f) => f.name}
                minWidth={760}
                empty={
                  <EmptyState
                    icon={Sprout}
                    title="No named fields yet"
                    description="Records on this farm don't carry a field/block name. Add one when logging sprays, scouting, or planned sprays and fields will appear here."
                  />
                }
              />
            </SectionCard>
          </div>
        );
      })}

      {!loading && !error && farms.length === 0 && (
        <EmptyState
          icon={Sprout}
          title="No farms yet"
          description="Seed the demo data (cd backend && python -m app.seed) or add a pilot farm."
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
