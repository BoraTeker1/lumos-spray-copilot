"use client";

import { Check, AlertCircle } from "lucide-react";
import { EVIDENCE_CATEGORY_LABELS } from "@/lib/labels";
import { Badge } from "@/components/ui/badge";

// The lender-ready evidence package: what this farm has on record, and what it does not.
//
// A checklist of records, never a score. There is no percentage, no approval
// likelihood, and no rate — Lumos has no lender policy to form a credit opinion with,
// and forming one anyway is the failure mode this card is shaped to avoid.
//
// The point it makes visible: the operational data that lets Lumos advise the grower
// is the same data that makes the farm legible to credit.

function Item({ item }) {
  const Icon = item.present ? Check : AlertCircle;
  return (
    <li className="flex items-start gap-2 py-2">
      <Icon
        className={`mt-0.5 h-4 w-4 shrink-0 ${
          item.present ? "text-ok-fg" : "text-warn-fg"
        }`}
      />
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium text-ink">{item.label}</div>
        {item.present ? (
          <div className="text-xs text-muted">
            {item.value_summary}
            {item.source && <span> · {item.source}</span>}
          </div>
        ) : (
          <div className="text-xs text-muted">
            {item.how}
            {item.who_fixes === "operator" && (
              <span className="ml-1 text-[11px]">(entered by Lumos)</span>
            )}
          </div>
        )}
      </div>
    </li>
  );
}

export default function EvidencePackageCard({ package: pkg }) {
  if (!pkg) return null;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="text-2xl font-semibold text-ink">
          {pkg.present_count}
          <span className="text-base font-normal text-muted">
            {" "}
            of {pkg.total_count}
          </span>
        </div>
        <div className="text-sm text-muted">evidence items on record</div>
        {pkg.is_simulated && <Badge variant="neutral">Simulated data</Badge>}
      </div>

      <p className="text-xs text-muted">{pkg.basis_text}</p>

      <div className="space-y-4">
        {pkg.categories
          .filter((c) => c.total_count > 0)
          .map((category) => (
            <div key={category.key}>
              <div className="flex items-baseline justify-between border-b border-line pb-1">
                <h4 className="text-sm font-medium text-ink">
                  {EVIDENCE_CATEGORY_LABELS[category.key] || category.label}
                </h4>
                <span className="text-xs text-muted">
                  {category.present_count}/{category.total_count}
                </span>
              </div>
              <ul className="divide-y divide-line">
                {category.items.map((item) => (
                  <Item key={item.key} item={item} />
                ))}
              </ul>
            </div>
          ))}
      </div>

      <p className="text-[11px] text-muted">{pkg.disclaimer}</p>
    </div>
  );
}
