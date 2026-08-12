"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Plus, Printer, Receipt, Sprout, Wallet } from "lucide-react";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import Breadcrumbs from "@/components/Breadcrumbs";
import SectionCard from "@/components/SectionCard";
import DataTable from "@/components/DataTable";
import SeasonCloseoutCard from "@/components/SeasonCloseoutCard";
import SeasonScopeNotice from "@/components/SeasonScopeNotice";
import SaleRecordForm from "@/components/SaleRecordForm";
import { ErrorState, LoadingState } from "@/components/SystemState";
import {
  BLOCK_OUTCOME_TYPE_LABELS,
  CLOSEOUT_VIEW_LABELS,
  COST_CATEGORY_LABELS,
  CROP_CYCLE_STATUS_LABELS,
  OPERATION_TYPE_LABELS,
} from "@/lib/labels";
import { formatDate } from "@/lib/format";

// One crop cycle's economics: what the season cost, produced, sold for, and what
// value can be attributed to the recommendations Lumos documented.
//
// The SAME page serves an open cycle and a closed one. An open season reads "Season
// to date" and a closed one "Season closeout"; the payload, the arithmetic and every
// caveat are identical, because a grower mid-season needs the same figures as one
// closing the books, and two surfaces would eventually disagree.
//
// Every headline number is traceable: the tables below the metric grid are the
// records each figure was built from, in entry order, with nothing sorted by value
// (sorting by amount is a ranking in everything but name).

function money(amount, currency) {
  if (amount === null || amount === undefined) return "—";
  const body = Math.abs(amount).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return `${amount < 0 ? "−" : ""}${currency ? `${currency} ` : ""}${body}`;
}

function quantity(amount, unit) {
  if (amount === null || amount === undefined) return "—";
  const body = amount.toLocaleString(undefined, { maximumFractionDigits: 2 });
  return unit ? `${body} ${unit}` : body;
}

export default function CropCycleEconomicsPage({ params }) {
  const cycleId = Number(params.id);

  const [cycle, setCycle] = useState(null);
  const [closeout, setCloseout] = useState(null);
  const [sales, setSales] = useState([]);
  const [sprays, setSprays] = useState([]);
  const [operations, setOperations] = useState([]);
  const [outcomes, setOutcomes] = useState([]);
  const [error, setError] = useState(null);
  const [saleOpen, setSaleOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      const c = await api.getCropCycle(cycleId);
      setCycle(c);
      const [co, s, ops, sp, out] = await Promise.all([
        api.getCropCycleCloseout(cycleId),
        api.listCropCycleSales(cycleId),
        api.listOperations(c.farm_id, cycleId),
        api.listSprayEvents(c.farm_id),
        api.listBlockOutcomes(c.farm_id),
      ]);
      setCloseout(co);
      setSales(s);
      setOperations(ops);
      // Only this season's records back this season's figures.
      setSprays(sp.filter((row) => row.crop_cycle_id === cycleId));
      setOutcomes(out.filter((row) => row.crop_cycle_id === cycleId));
    } catch (err) {
      setError(err.message);
    }
  }, [cycleId]);

  useEffect(() => {
    load();
  }, [load]);

  if (error) return <ErrorState message={error} />;
  if (!cycle || !closeout) return <LoadingState />;

  const currency = closeout.currency;
  const title = CLOSEOUT_VIEW_LABELS[closeout.view] || "Season economics";
  const seasonName = cycle.season_label || `${cycle.season_year} ${cycle.crop}`;
  // A superseded settlement is still listed — what the grower saw before a
  // correction stays readable — but it is visibly not part of the total.
  const supersededIds = new Set(sales.map((s) => s.supersedes_id).filter(Boolean));

  return (
    <div className="space-y-5">
      <div className="print:hidden">
        <Breadcrumbs
          items={[
            { label: "Farms", href: "/farms" },
            { label: cycle.crop, href: `/farms/${cycle.farm_id}` },
            { label: seasonName },
          ]}
        />
      </div>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-xl font-semibold text-ink">{title}</h1>
            <Badge variant={closeout.is_closed ? "neutral" : "green"}>
              {CROP_CYCLE_STATUS_LABELS[cycle.status] || cycle.status}
            </Badge>
          </div>
          <p className="mt-1 text-sm text-muted">
            {seasonName}
            {cycle.variety_name ? ` · ${cycle.variety_name}` : ""} · planted{" "}
            {formatDate(cycle.planting_date)}
            {cycle.actual_harvest_end
              ? ` · harvest ended ${formatDate(cycle.actual_harvest_end)}`
              : ""}
          </p>
          {!closeout.is_closed && (
            <p className="mt-1 text-[11px] leading-4 text-muted">
              This season is still open, so every figure below is a running total that
              will change as more records are entered.
            </p>
          )}
        </div>
        <div className="flex shrink-0 gap-2 print:hidden">
          <Dialog open={saleOpen} onOpenChange={setSaleOpen}>
            <DialogTrigger asChild>
              <Button size="sm">
                <Plus className="h-3.5 w-3.5" aria-hidden /> Record sale
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Record a sale or settlement</DialogTitle>
                <DialogDescription>
                  What the crop actually sold for on {seasonName}.
                </DialogDescription>
              </DialogHeader>
              <SaleRecordForm
                farmId={cycle.farm_id}
                cycleId={cycleId}
                currency={currency}
                onDone={() => {
                  setSaleOpen(false);
                  load();
                }}
              />
            </DialogContent>
          </Dialog>
          <Button variant="secondary" size="sm" onClick={() => window.print()}>
            <Printer className="h-3.5 w-3.5" aria-hidden /> Print
          </Button>
          <Link href={`/farms/${cycle.farm_id}`}>
            <Button variant="ghost" size="sm">
              <ArrowLeft className="h-3.5 w-3.5" aria-hidden /> Farm
            </Button>
          </Link>
        </div>
      </div>

      {/* What these figures LEFT OUT, before any of them are read. */}
      <SeasonScopeNotice scope={closeout.scope} cycleId={cycleId} onLinked={load} />

      <SeasonCloseoutCard closeout={closeout} />

      {/* ------------------------------------------------------ traceability */}
      <SectionCard
        title={`Sales (${sales.length})`}
        size="section"
        icon={<Receipt className="h-4 w-4 text-muted" aria-hidden />}
        description="The settlements revenue is built from. Append-only — a correction supersedes rather than edits."
      >
        <DataTable
          rows={sales}
          rowKey={(row) => row.id}
          empty="No sale recorded yet. Revenue is read from recorded settlements only."
          columns={[
            {
              key: "sale_date",
              header: "Date",
              nowrap: true,
              render: (row) => (
                <span className={supersededIds.has(row.id) ? "text-muted line-through" : ""}>
                  {formatDate(row.sale_date)}
                </span>
              ),
            },
            { key: "buyer_name", header: "Buyer", render: (row) => row.buyer_name || "—" },
            {
              key: "quantity",
              header: "Quantity",
              align: "right",
              nowrap: true,
              render: (row) => quantity(row.quantity, row.unit),
            },
            {
              key: "unit_price",
              header: "Price",
              align: "right",
              nowrap: true,
              priority: "secondary",
              render: (row) => money(row.unit_price, currency),
            },
            {
              key: "gross_amount",
              header: "Gross",
              align: "right",
              nowrap: true,
              render: (row) => money(row.gross_amount, currency),
            },
            {
              key: "deductions_amount",
              header: "Deductions",
              align: "right",
              nowrap: true,
              priority: "secondary",
              render: (row) => money(row.deductions_amount, currency),
            },
            {
              key: "reference",
              header: "Reference",
              priority: "secondary",
              render: (row) => row.reference || "—",
            },
            {
              key: "status",
              header: "",
              nowrap: true,
              render: (row) =>
                supersededIds.has(row.id) ? (
                  <Badge variant="outline">Superseded</Badge>
                ) : row.supersedes_id ? (
                  <Badge variant="blue">Correction</Badge>
                ) : null,
            },
          ]}
        />
      </SectionCard>

      <SectionCard
        title={`Recorded costs (${sprays.length + operations.length})`}
        size="section"
        icon={<Wallet className="h-4 w-4 text-muted" aria-hidden />}
        description="Applications and operations on this season. A record with no cost is excluded from the total, never counted as zero."
      >
        <DataTable
          rows={[
            ...sprays.map((row) => ({
              key: `spray-${row.id}`,
              date: row.application_date,
              what: row.product_name,
              type: "Application",
              category: "crop_protection",
              amount: row.cost,
              href: `/farms/${cycle.farm_id}?tab=records`,
            })),
            ...operations.map((row) => ({
              key: `op-${row.id}`,
              date: row.performed_on,
              what: row.notes || OPERATION_TYPE_LABELS[row.operation_type] || row.operation_type,
              type: OPERATION_TYPE_LABELS[row.operation_type] || row.operation_type,
              category: row.cost_category,
              amount: row.cost_amount,
            })),
          ].sort((a, b) => String(b.date || "").localeCompare(String(a.date || "")))}
          rowKey={(row) => row.key}
          empty="No cost recorded on this season yet."
          columns={[
            {
              key: "date",
              header: "Date",
              nowrap: true,
              render: (row) => formatDate(row.date),
            },
            { key: "what", header: "What", render: (row) => row.what || "—" },
            { key: "type", header: "Type", priority: "secondary", render: (row) => row.type },
            {
              key: "category",
              header: "Cost category",
              priority: "secondary",
              render: (row) =>
                row.category ? (
                  COST_CATEGORY_LABELS[row.category] || row.category
                ) : (
                  <span className="text-muted">Uncategorised</span>
                ),
            },
            {
              key: "amount",
              header: "Cost",
              align: "right",
              nowrap: true,
              render: (row) =>
                row.amount == null ? (
                  // Never a 0: an uncosted record is an unknown, not a free one.
                  <span className="text-muted">Not recorded</span>
                ) : (
                  money(row.amount, currency)
                ),
            },
          ]}
        />
      </SectionCard>

      <SectionCard
        title={`Measured outcomes (${outcomes.length})`}
        size="section"
        icon={<Sprout className="h-4 w-4 text-muted" aria-hidden />}
        description="Per block per harvest. Yield rows back the season total; percentages and weights are never added together."
      >
        <DataTable
          rows={outcomes}
          rowKey={(row) => row.id}
          empty="No harvest outcome recorded on this season yet."
          columns={[
            {
              key: "observed_on",
              header: "Observed",
              nowrap: true,
              render: (row) => formatDate(row.observed_on),
            },
            {
              key: "outcome_type",
              header: "Measurement",
              render: (row) =>
                BLOCK_OUTCOME_TYPE_LABELS[row.outcome_type] || row.outcome_type,
            },
            {
              key: "value",
              header: "Value",
              align: "right",
              nowrap: true,
              render: (row) => quantity(row.value, row.unit),
            },
            {
              key: "method",
              header: "How it was measured",
              priority: "secondary",
              render: (row) => row.method || "—",
            },
          ]}
        />
      </SectionCard>
    </div>
  );
}
