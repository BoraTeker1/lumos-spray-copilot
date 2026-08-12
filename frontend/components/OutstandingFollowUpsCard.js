"use client";

import { useState } from "react";
import Link from "next/link";
import { ChevronDown, ClipboardCheck } from "lucide-react";
import SectionCard from "@/components/SectionCard";
import StatusBadge from "@/components/StatusBadge";
import FollowUpEventForm from "@/components/FollowUpEventForm";
import { RECORDED_OUTCOME_LABELS } from "@/lib/labels";
import { formatDate } from "@/lib/format";

// The decisions whose value is stuck at "estimated" for want of one recorded event.
//
// Follow-up evidence is the ONLY thing that moves attributable value from estimated to
// verified (`decision_status.evidence_state`), and until now the only place to record
// one was a decision's own detail page — so the work sat invisible on the farm a
// grower actually looks at. This is deliberately not a task system: no assignment, no
// due dates, no state of its own. It reads a state the backend already derives and
// puts the existing form next to it.

const OUTSTANDING = ["follow_up_required", "follow_up_in_progress"];

export default function OutstandingFollowUpsCard({ planned = [], onChanged }) {
  const [openId, setOpenId] = useState(null);

  const rows = planned.filter((p) => OUTSTANDING.includes(p.evidence_state));
  if (rows.length === 0) return null;

  return (
    <SectionCard
      title="Follow-ups outstanding"
      icon={<ClipboardCheck className="h-4 w-4 text-muted" aria-hidden />}
      description="Each of these has a recorded outcome that nothing has corroborated yet — one event moves its value from estimated to verified."
    >
      <ul className="divide-y divide-line">
        {rows.map((row) => {
          const isOpen = openId === row.id;
          return (
            <li key={row.id} className="py-2.5 first:pt-0 last:pb-0">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <Link
                    href={`/decisions/${row.id}`}
                    className="truncate text-sm font-medium text-ink hover:underline"
                  >
                    {row.product_name}
                  </Link>
                  <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-muted">
                    <span>{formatDate(row.intended_date)}</span>
                    {row.outcome && (
                      <span>
                        · {RECORDED_OUTCOME_LABELS[row.outcome] || row.outcome}
                      </span>
                    )}
                    <span>
                      · {row.follow_up_event_count} event
                      {row.follow_up_event_count === 1 ? "" : "s"} so far
                    </span>
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <StatusBadge kind="evidence" value={row.evidence_state} />
                  <button
                    type="button"
                    onClick={() => setOpenId(isOpen ? null : row.id)}
                    aria-expanded={isOpen}
                    className="inline-flex items-center gap-1 rounded-control px-1.5 py-1 text-[11px] font-medium text-muted hover:text-ink"
                  >
                    {isOpen ? "Close" : "Record"}
                    <ChevronDown
                      className={`h-3.5 w-3.5 transition-transform ${isOpen ? "rotate-180" : ""}`}
                      aria-hidden
                    />
                  </button>
                </div>
              </div>
              {isOpen && (
                <FollowUpEventForm
                  plannedId={row.id}
                  heading="What actually happened? (append-only — events are never edited or deleted)"
                  onAdded={onChanged}
                />
              )}
            </li>
          );
        })}
      </ul>
      <p className="mt-3 text-[11px] leading-4 text-muted">
        Recording what happened is documentation, not proof that the decision caused
        it. Nothing here changes a decision, a review, or an outcome.
      </p>
    </SectionCard>
  );
}
