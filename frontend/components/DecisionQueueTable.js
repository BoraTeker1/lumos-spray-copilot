"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { formatDate } from "@/lib/format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { OUTCOME_META } from "@/components/DecisionResult";
import { RECORDED_OUTCOME_LABELS } from "@/lib/labels";

// Read-only decision queue table (mockup style: uppercase headers, roomy rows,
// per-row outlined-green action). Reviews and outcome recording deliberately do
// NOT happen here — they live in the PlannedSprayList workflow and on the
// decision record page. `limit` caps rows; `viewAllHref` shows the green link.
const FILTERS = [
  { key: "all", label: "All", match: () => true },
  { key: "open", label: "Needs action", match: (p) => p.is_open },
  { key: "resolved", label: "Resolved", match: (p) => !p.is_open },
];

const HEADER_CLS =
  "px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wide text-gray-500";

export default function DecisionQueueTable({ planned = [], limit, viewAllHref }) {
  const [filter, setFilter] = useState("all");
  const active = FILTERS.find((f) => f.key === filter) || FILTERS[0];
  const filtered = planned.filter(active.match);
  const shown = limit ? filtered.slice(0, limit) : filtered;

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-1.5">
        {FILTERS.map((f) => {
          const count = planned.filter(f.match).length;
          const selected = f.key === filter;
          return (
            <button
              key={f.key}
              onClick={() => setFilter(f.key)}
              className={`rounded-full px-2.5 py-1 text-xs font-medium transition-colors ${
                selected
                  ? "bg-leaf-700 text-white"
                  : "border border-gray-200 bg-white text-gray-600 hover:bg-gray-50"
              }`}
            >
              {f.label} <span className={selected ? "opacity-80" : "text-gray-400"}>{count}</span>
            </button>
          );
        })}
      </div>

      {shown.length === 0 ? (
        <p className="py-3 text-sm text-gray-500">
          {planned.length === 0
            ? "No planned sprays checked yet."
            : "Nothing matches this filter."}
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-sm">
            <thead>
              <tr className="border-b border-gray-200">
                <th className={HEADER_CLS}>Decision</th>
                <th className={HEADER_CLS}>Status</th>
                <th className={HEADER_CLS}>Target</th>
                <th className={HEADER_CLS}>Planned</th>
                <th className={HEADER_CLS}>Next action</th>
                <th className={HEADER_CLS}>
                  <span className="sr-only">Open</span>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {shown.map((p) => {
                const meta = OUTCOME_META[p.decision_outcome] || OUTCOME_META.pca_review_required;
                const resolved = p.outcome && p.outcome !== "planned";
                return (
                  <tr key={p.id} className="align-top">
                    <td className="px-3 py-3">
                      <div className="font-medium text-gray-900">{p.product_name}</div>
                      {p.active_ingredient && (
                        <div className="text-xs text-gray-500">{p.active_ingredient}</div>
                      )}
                    </td>
                    <td className="px-3 py-3">
                      <Badge variant={meta.badge}>{meta.label}</Badge>
                      {resolved && (
                        <div className="mt-1 text-[11px] text-gray-500">
                          {RECORDED_OUTCOME_LABELS[p.outcome] || p.outcome}
                        </div>
                      )}
                    </td>
                    <td className="px-3 py-3 text-gray-700">
                      {p.target_pest_or_disease || "—"}
                    </td>
                    <td className="whitespace-nowrap px-3 py-3 text-gray-700">
                      {formatDate(p.intended_date)}
                    </td>
                    <td className="max-w-[220px] px-3 py-3 text-xs text-gray-600">
                      <span className="line-clamp-2">{p.required_next_action}</span>
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

      {viewAllHref && filtered.length > (limit || 0) && limit && (
        <div className="mt-2">
          <Link
            href={viewAllHref}
            className="inline-flex items-center gap-1 text-xs font-medium text-leaf-700 hover:underline"
          >
            View all decisions <ArrowRight className="h-3 w-3" />
          </Link>
        </div>
      )}
    </div>
  );
}
