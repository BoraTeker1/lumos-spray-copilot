"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { formatDate } from "@/lib/format";
import { nextActionLabel } from "@/lib/status";
import { Button } from "@/components/ui/button";
import DataTable from "@/components/DataTable";
import EmptyState from "@/components/EmptyState";
import StatusBadge from "@/components/StatusBadge";
import { ShieldCheck } from "lucide-react";

// Shared decision-queue columns. The four concepts stay visually distinct:
// Verdict = the historical engine decision; State = workflow (or the recorded
// outcome once resolved); the action button is the SPECIFIC current next step
// (server-derived current_next_action), never a generic "Open".
//
// There is deliberately NO separate "next action" text column: it rendered
// `nextActionLabel(current_next_action)` — the identical string the action
// button already shows — so every row printed its next step twice, side by side.
// `compact` is for the dashboard rail, which is ~690px wide inside a
// two-column page. The secondary columns are hidden by a VIEWPORT breakpoint,
// which cannot see that its container is narrow — so on a wide screen they
// stayed visible in a narrow column and the fixed-width cells overlapped each
// other. The caller knows how much room it has; the media query does not.
export function decisionColumns({ compact = false } = {}) {
  const cols = [
    {
      key: "product",
      header: "Decision",
      width: compact ? "30%" : "20%",
      render: (p) => (
        <div className="min-w-0">
          <div className="truncate font-medium text-ink">{p.product_name}</div>
          {p.active_ingredient && (
            <div className="truncate text-xs text-muted">{p.active_ingredient}</div>
          )}
        </div>
      ),
    },
    {
      key: "verdict",
      header: "Verdict",
      width: compact ? "18%" : "13%",
      nowrap: true,
      render: (p) => <StatusBadge kind="verdict" value={p.decision_outcome} />,
    },
    {
      key: "state",
      header: "State",
      width: compact ? "18%" : "13%",
      render: (p) =>
        p.workflow_state === "resolved" ? (
          <div className="flex flex-col items-start gap-1">
            <StatusBadge kind="outcome" value={p.outcome} />
            {["follow_up_required", "follow_up_in_progress"].includes(p.evidence_state) && (
              <StatusBadge kind="evidence" value={p.evidence_state} />
            )}
          </div>
        ) : (
          <StatusBadge kind="workflow" value={p.workflow_state} />
        ),
    },
    {
      key: "planned",
      header: "Planned",
      width: compact ? "16%" : "11%",
      nowrap: true,
      render: (p) => (
        <span className="whitespace-nowrap text-ink">{formatDate(p.intended_date)}</span>
      ),
    },
    {
      key: "action",
      priority: "action",
      header: <span className="sr-only">Action</span>,
      align: "right",
      render: (p) => (
        <Link href={`/decisions/${p.id}`}>
          <Button variant="secondary" size="sm">
            {nextActionLabel(p.current_next_action)}
          </Button>
        </Link>
      ),
    },
  ];
  if (!compact) {
    cols.splice(
      1,
      0,
      {
        key: "field",
        header: "Field",
        priority: "secondary",
        width: "8%",
        render: (p) => <span className="text-ink">{p.field_block || "—"}</span>,
      },
      {
        key: "target",
        header: "Target",
        priority: "secondary",
        width: "16%",
        render: (p) => (
          <span className="text-xs text-muted">{p.target_pest_or_disease || "—"}</span>
        ),
      }
    );
  }
  return cols;
}

export default function DecisionQueue({ planned = [], limit, viewAllHref, emptyState }) {
  const shown = limit ? planned.slice(0, limit) : planned;
  return (
    <div>
      <DataTable
        columns={decisionColumns({ compact: true })}
        rows={shown}
        rowKey={(p) => p.id}
        minWidth={560}
        empty={
          emptyState || (
            <EmptyState
              icon={ShieldCheck}
              title="No planned sprays checked yet"
              description='Run "Check planned spray" before the next application to get an explainable verdict and an audit-ready record.'
            />
          )
        }
      />
      {viewAllHref && planned.length > (limit || 0) && limit && (
        <div className="mt-2">
          <Link
            href={viewAllHref}
            className="inline-flex items-center gap-1 text-xs font-medium text-leaf-700 hover:underline"
          >
            View all {planned.length} decisions <ArrowRight className="h-3 w-3" />
          </Link>
        </div>
      )}
    </div>
  );
}
