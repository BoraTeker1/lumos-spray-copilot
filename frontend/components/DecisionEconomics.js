"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { formatCost } from "@/lib/format";

// The direct cost of each choice open on one decision, beside the agronomic verdict.
//
// Scenarios, not a recommendation: each is the cost consequence of a choice, priced
// from figures already recorded on this decision. There is no probability and no
// expected value anywhere — the honest version of "what does delaying cost" is that
// we know what acting costs and we do not know what waiting costs, and the delay
// scenario says exactly that.
//
// Fetched from its own endpoint rather than added to the decision payload: the
// Botrytis shadow study's blinding depends on the PCA-facing payload not growing.

const CHOICE_LABELS = {
  apply: "Apply as planned",
  avoid: "Do not apply",
  delay: "Delay",
  inspect_first: "Inspect first",
};

export default function DecisionEconomics({ plannedId, country }) {
  const [data, setData] = useState(null);

  useEffect(() => {
    let live = true;
    api
      .getDecisionEconomics(plannedId)
      .then((d) => live && setData(d))
      .catch(() => live && setData(null));
    return () => {
      live = false;
    };
  }, [plannedId]);

  if (!data) return null;

  if (!data.available) {
    // Not calculated, with its reason — never a zero, never a blank panel.
    return (
      <p className="text-sm text-muted">
        <span className="font-medium text-ink">Not calculated.</span> {data.reason}
      </p>
    );
  }

  return (
    <div>
      <ul className="divide-y divide-line">
        {data.scenarios.map((s) => (
          <li key={s.choice} className="flex items-baseline justify-between gap-4 py-1.5">
            <div className="min-w-0">
              <span className="text-sm font-medium text-ink">
                {CHOICE_LABELS[s.choice] || s.choice}
              </span>
              <p className="text-[11px] leading-4 text-muted">{s.note}</p>
            </div>
            <span className="tabular shrink-0 text-sm font-semibold text-ink">
              {s.direct_cost === null || s.direct_cost === undefined
                ? "Not calculated"
                : formatCost(s.direct_cost, country)}
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-1.5 text-[11px] leading-4 text-muted">{data.note}</p>
    </div>
  );
}
