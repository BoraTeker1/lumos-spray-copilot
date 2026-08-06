"use client";

import { useState } from "react";
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

// Selecting a quote requires saying WHY. Presets cover the honest, comparable
// facts; the reason is stored verbatim and audited — never inferred.
const REASON_PRESETS = [
  "Lower total quoted cost",
  "Earlier estimated delivery",
  "Product availability",
  "Preferred payment terms",
  "Financing availability",
  "Supplier reliability",
];

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
  // Comparison baseline: the lowest quoted total among live (not withdrawn)
  // quotes. The per-row delta is a comparison of ENTERED quote totals only —
  // never a savings claim.
  const liveTotals = rows
    .filter((q) => !["withdrawn", "expired"].includes(q.quote_state))
    .map((q) => q.total_cost);
  const lowestTotal = liveTotals.length ? Math.min(...liveTotals) : null;

  const [selectingId, setSelectingId] = useState(null);
  const [preset, setPreset] = useState(REASON_PRESETS[0]);
  const [customReason, setCustomReason] = useState("");

  function confirmSelect(q) {
    const reason =
      preset === "custom" ? customReason.trim() : preset;
    if (!reason) return;
    setSelectingId(null);
    setCustomReason("");
    if (onSelect) onSelect(q, reason);
  }

  const columns = [
    {
      key: "supplier",
      header: "Supplier",
      render: (q) => (
        <div className="min-w-0">
          <div className="font-medium text-ink">{q.supplier_name}</div>
          <div className="mt-0.5 space-y-0.5 text-xs text-muted">
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
              <div className="text-warn-fg">
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
          <div className="font-semibold text-ink">
            {formatCost(q.total_cost, country)}
          </div>
          <div className="text-xs text-muted">
            {formatCost(q.items_subtotal, country)} + {formatCost(q.delivery_cost, country)}{" "}
            delivery + {formatCost(q.fees, country)} fees
          </div>
          {lowestTotal != null && (
            <div className="text-xs text-muted">
              {q.total_cost === lowestTotal
                ? "Lowest quoted total"
                : `${formatCost(q.total_cost - lowestTotal, country)} above the lowest quoted total`}
            </div>
          )}
        </div>
      ),
    },
    {
      key: "delivery",
      header: "Delivery",
      priority: "secondary",
      render: (q) => (
        <div className="text-sm text-ink">
          <div>{formatDate(q.expected_delivery_date)}</div>
          <div className="text-xs text-muted">
            {AVAILABILITY_LABELS[q.availability] || q.availability}
          </div>
        </div>
      ),
    },
    {
      key: "terms",
      header: "Cash terms",
      priority: "secondary",
      render: (q) => <span className="text-sm text-ink">{q.payment_terms_cash || "—"}</span>,
    },
    {
      key: "expires",
      header: "Expires",
      priority: "secondary",
      render: (q) => <span className="text-sm text-ink">{formatDate(q.expires_on)}</span>,
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
          <span className="text-xs text-muted">Cash only</span>
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
            onClick={() => setSelectingId(q.id)}
          >
            Select quote
          </Button>
        ) : null,
    },
  ];

  const selecting = rows.find((q) => q.id === selectingId);

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
      {selecting && (
        <div className="rounded-control border border-leaf-200 bg-leaf-50 p-3">
          <p className="text-sm font-medium text-ink">
            Select {selecting.supplier_name} —{" "}
            {formatCost(selecting.total_cost, country)}. Why this quote?
          </p>
          <p className="mt-0.5 text-xs text-muted">
            The reason is recorded in the plan&apos;s audit history and the
            evidence export. It is never inferred.
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            {REASON_PRESETS.map((r) => (
              <label key={r} className="flex items-center gap-1.5 text-xs text-ink">
                <input
                  type="radio"
                  name="quote-select-reason"
                  checked={preset === r}
                  onChange={() => setPreset(r)}
                />
                {r}
              </label>
            ))}
            <label className="flex items-center gap-1.5 text-xs text-ink">
              <input
                type="radio"
                name="quote-select-reason"
                checked={preset === "custom"}
                onChange={() => setPreset("custom")}
              />
              Other
            </label>
          </div>
          {preset === "custom" && (
            <textarea
              className="mt-2 w-full rounded-control border border-line p-2 text-sm"
              rows={2}
              placeholder="Your reason for selecting this quote (required)"
              value={customReason}
              onChange={(e) => setCustomReason(e.target.value)}
            />
          )}
          <div className="mt-3 flex gap-2">
            <Button
              size="sm"
              disabled={busy || (preset === "custom" && !customReason.trim())}
              onClick={() => confirmSelect(selecting)}
            >
              {busy ? "Saving…" : "Confirm selection"}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              disabled={busy}
              onClick={() => setSelectingId(null)}
            >
              Back
            </Button>
          </div>
        </div>
      )}
      <p className="text-[11px] text-muted">
        Quotes are concierge-entered for comparison. Lumos takes no commission and
        never ranks suppliers — sorted by transparent total cost only. &quot;Above
        the lowest quoted total&quot; compares entered quote totals (including
        delivery and fees); it is not a confirmed-savings claim.
      </p>
    </div>
  );
}
