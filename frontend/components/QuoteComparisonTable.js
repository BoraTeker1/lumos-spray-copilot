"use client";

import { FileText } from "lucide-react";
import { formatCost, formatDate } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import DataTable from "@/components/DataTable";
import EmptyState from "@/components/EmptyState";
import StatusBadge from "@/components/StatusBadge";

const AVAILABILITY_LABELS = {
  in_stock: "In stock",
  partial: "Partial",
  backordered: "Backordered",
  unknown: "Unknown",
};

// Transparent quote comparison: totals, delivery, availability, expiration,
// financing. Sorted by total cost (ascending) — a user-value sort. There is no
// supplier ranking anywhere: Lumos takes no commission and never ranks suppliers.
export default function QuoteComparisonTable({
  quotes = [],
  country,
  canSelect = false,
  onSelect,
  busy = false,
}) {
  const rows = [...quotes].sort((a, b) => a.total_cost - b.total_cost);

  const columns = [
    {
      key: "supplier",
      header: "Supplier",
      render: (q) => (
        <div className="min-w-0">
          <div className="font-medium text-gray-900">{q.supplier_name}</div>
          <div className="mt-0.5 space-y-0.5 text-xs text-gray-500">
            {q.items.map((line) => (
              <div key={line.id} className="flex flex-wrap items-center gap-1.5">
                <span>
                  {line.product_name} — {line.quantity} {line.unit} @{" "}
                  {formatCost(line.unit_price, country)}
                </span>
                {line.is_substitution && (
                  <Badge variant="amber" title={line.substitution_reason}>
                    Substitution
                  </Badge>
                )}
              </div>
            ))}
            {q.items.some((l) => l.is_substitution) && (
              <div className="text-amber-700">
                {q.items
                  .filter((l) => l.is_substitution)
                  .map((l) => `Why: ${l.substitution_reason}`)
                  .join(" · ")}
              </div>
            )}
          </div>
        </div>
      ),
    },
    {
      key: "total",
      header: "Total",
      align: "right",
      render: (q) => (
        <div>
          <div className="font-semibold text-gray-900">
            {formatCost(q.total_cost, country)}
          </div>
          <div className="text-xs text-gray-500">
            {formatCost(q.items_subtotal, country)} + {formatCost(q.delivery_cost, country)}{" "}
            delivery + {formatCost(q.fees, country)} fees
          </div>
        </div>
      ),
    },
    {
      key: "delivery",
      header: "Delivery",
      priority: "secondary",
      render: (q) => (
        <div className="text-sm text-gray-700">
          <div>{formatDate(q.expected_delivery_date)}</div>
          <div className="text-xs text-gray-500">
            {AVAILABILITY_LABELS[q.availability] || q.availability}
          </div>
        </div>
      ),
    },
    {
      key: "terms",
      header: "Cash terms",
      priority: "secondary",
      render: (q) => <span className="text-sm text-gray-700">{q.payment_terms_cash || "—"}</span>,
    },
    {
      key: "expires",
      header: "Expires",
      priority: "secondary",
      render: (q) => <span className="text-sm text-gray-700">{formatDate(q.expires_on)}</span>,
    },
    {
      key: "financing",
      header: "Financing",
      priority: "secondary",
      render: (q) =>
        q.financing_offers.length ? (
          <div className="space-y-1">
            {q.financing_offers.map((o) => (
              <StatusBadge key={o.id} kind="offerState" value={o.offer_state} />
            ))}
          </div>
        ) : (
          <span className="text-xs text-gray-500">Cash only</span>
        ),
    },
    {
      key: "state",
      header: "Status",
      render: (q) => <StatusBadge kind="quoteState" value={q.quote_state} />,
    },
    {
      key: "action",
      header: "",
      align: "right",
      render: (q) =>
        canSelect && q.quote_state === "submitted" ? (
          <Button
            variant="secondary"
            size="sm"
            disabled={busy}
            onClick={() => onSelect && onSelect(q)}
          >
            Select quote
          </Button>
        ) : null,
    },
  ];

  return (
    <div className="space-y-3">
      <DataTable
        columns={columns}
        rows={rows}
        rowKey={(q) => q.id}
        minWidth={760}
        empty={
          <EmptyState
            icon={FileText}
            title="No quotes yet"
            description="Quotes are concierge-entered against this plan and appear here for side-by-side comparison."
          />
        }
      />
      <p className="text-[11px] text-gray-500">
        Quotes are concierge-entered for comparison. Lumos takes no commission and
        never ranks suppliers — sorted by transparent total cost only.
      </p>
    </div>
  );
}
