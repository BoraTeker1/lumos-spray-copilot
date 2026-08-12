"use client";

import { useEffect, useState } from "react";
import { Scale } from "lucide-react";
import { api } from "@/lib/api";
import SectionCard from "@/components/SectionCard";

// How much each catalogued product varied in price across the suppliers who quoted it.
//
// This is the ONE new surface in the 2026-08-07 build that shows real computed numbers
// rather than a refusal — the marketplace works end to end, so a plan with two
// catalogued quotes produces an actual spread.
//
// FOUR RULES, all of them the no-ranking commitment in different clothes:
//
// 1. NEVER SORT BY PRICE. Observations render in the server's order, which is entry
//    order. Sorting here would make this a ranking in everything but name, and Lumos
//    takes no commission and does not rank suppliers.
// 2. NEVER CALL THE SPREAD A SAVING. A grower may have good reasons to buy above the
//    lowest quote — availability, terms, a relationship — and calling the difference a
//    saving assumes they did not.
// 3. NEVER HIGHLIGHT THE CHEAPEST. No "best value" badge, no green on the low row.
//    Min and max are stated as observations, not as verdicts.
// 4. SHOW THE UNLINKED COUNT. A line with no catalogue link is excluded from every
//    comparison, and hiding that would let the card understate its own blind spot.
export default function PriceDispersionCard({ planId }) {
  const [report, setReport] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!planId) return;
    let cancelled = false;
    api
      .getPriceDispersion(planId)
      .then((r) => !cancelled && setReport(r))
      .catch((err) => !cancelled && setError(err.message));
    return () => {
      cancelled = true;
    };
  }, [planId]);

  if (error || !report) return null;

  const hasContent =
    report.products.length > 0 ||
    report.not_compared.length > 0 ||
    report.unlinked_line_count > 0;
  if (!hasContent) return null;

  return (
    <SectionCard
      title="Price comparison"
      icon={<Scale />}
      size="section"
      description="How much the same catalogued product varied between the suppliers who quoted it."
    >
      <div className="space-y-4">
        {report.products.map((p) => (
          <div key={p.input_product_id} className="space-y-1.5">
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-sm font-medium text-ink">{p.product_name}</span>
              <span className="text-xs text-muted">
                {p.quote_count} quotes · spread {p.spread_pct}%
              </span>
            </div>
            <ul className="space-y-0.5">
              {/* Entry order, straight from the server. See rule 1. */}
              {p.observations.map((o, i) => (
                <li
                  key={`${o.quote_id}-${i}`}
                  className="flex items-baseline justify-between gap-2 text-xs"
                >
                  <span className="text-muted">{o.supplier_name}</span>
                  <span className="tabular-nums text-ink">
                    {o.currency} {o.unit_price} / {o.unit}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ))}

        {report.not_compared.length > 0 && (
          <div className="space-y-1">
            <div className="text-xs font-semibold uppercase tracking-wide text-muted">
              Not compared
            </div>
            <ul className="space-y-0.5 text-xs text-muted">
              {report.not_compared.map((r, i) => (
                <li key={`${r.code}-${i}`}>{r.detail}</li>
              ))}
            </ul>
          </div>
        )}

        {report.unlinked_line_count > 0 && (
          <p className="text-xs text-muted">
            {report.unlinked_line_count} quoted{" "}
            {report.unlinked_line_count === 1 ? "line is" : "lines are"} not linked to a
            catalogue product and{" "}
            {report.unlinked_line_count === 1 ? "was" : "were"} excluded.{" "}
            {report.unlinked_note}
          </p>
        )}

        {report.products.length > 0 && (
          <p className="text-xs text-muted">
            A spread is what suppliers quoted, not money saved — buying above the lowest
            quote may be the right call. Lumos takes no commission and does not rank
            suppliers.
          </p>
        )}
      </div>
    </SectionCard>
  );
}
