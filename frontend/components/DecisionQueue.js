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
export function decisionColumns({ includeNextActionText = false } = {}) {
  const cols = [
    {
      key: "product",
      header: "Decision",
      render: (p) => (
        <div className="min-w-0">
          <div className="font-medium text-ink">{p.product_name}</div>
          {p.active_ingredient && (
            <div className="text-xs text-muted">{p.active_ingredient}</div>
          )}
        </div>
      ),
    },
    {
      key: "field",
      header: "Field",
      priority: "secondary",
      render: (p) => <span className="text-ink">{p.field_block || "—"}</span>,
    },
    {
      key: "target",
      header: "Target",
      priority: "secondary",
      render: (p) => (
        <span className="text-xs text-muted">{p.target_pest_or_disease || "—"}</span>
      ),
    },
    {
      key: "verdict",
      header: "Verdict",
      render: (p) => <StatusBadge kind="verdict" value={p.decision_outcome} />,
    },
    {
      key: "state",
      header: "State",
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
      render: (p) => (
        <span className="whitespace-nowrap text-ink">{formatDate(p.intended_date)}</span>
      ),
    },
  ];
  if (includeNextActionText) {
    cols.push({
      key: "next",
      header: "Next action",
      priority: "secondary",
      render: (p) => (
        <span className="text-xs text-muted">
          {p.current_next_action === "none" ? "—" : nextActionLabel(p.current_next_action)}
        </span>
      ),
    });
  }
  cols.push({
    key: "action",
    header: <span className="sr-only">Action</span>,
    align: "right",
    render: (p) => (
      <Link href={`/decisions/${p.id}`}>
        <Button variant="secondary" size="sm">
          {nextActionLabel(p.current_next_action)}
        </Button>
      </Link>
    ),
  });
  return cols;
}

export default function DecisionQueue({ planned = [], limit, viewAllHref, emptyState }) {
  const shown = limit ? planned.slice(0, limit) : planned;
  return (
    <div>
      <DataTable
        columns={decisionColumns()}
        rows={shown}
        rowKey={(p) => p.id}
        minWidth={640}
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
