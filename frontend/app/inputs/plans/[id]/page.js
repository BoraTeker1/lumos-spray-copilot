"use client";

import { LoadingState } from "@/components/SystemState";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  FlaskConical,
  History,
  Landmark,
  ListChecks,
  Package,
  Send,
  Trash2,
  TriangleAlert,
} from "lucide-react";
import { api } from "@/lib/api";
import { formatCost, formatDate } from "@/lib/format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import Callout from "@/components/Callout";
import Breadcrumbs from "@/components/Breadcrumbs";
import DataTable from "@/components/DataTable";
import FinancingOfferCard from "@/components/FinancingOfferCard";
import PriceDispersionCard from "@/components/PriceDispersionCard";
import QuoteComparisonTable from "@/components/QuoteComparisonTable";
import SectionCard from "@/components/SectionCard";
import StatusBadge from "@/components/StatusBadge";
import { planEventLabel, planNextStep } from "@/lib/status";

function isDemoRecord(r) {
  return r.data_source === "demo" || r.data_confidence === "simulated";
}

export default function InputPlanDetailPage({ params }) {
  const router = useRouter();
  const [plan, setPlan] = useState(null);
  const [farm, setFarm] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const p = await api.getInputPlan(params.id);
      setPlan(p);
      setFarm(await api.getFarm(p.farm_id));
      setError(null);
    } catch (err) {
      setError(err.message);
    }
  }, [params.id]);

  useEffect(() => {
    load();
  }, [load]);

  async function act(fn, ...args) {
    setBusy(true);
    setError(null);
    try {
      await fn(...args);
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (error && !plan) {
    return (
      <Callout tone="risk">
        {error}
      </Callout>
    );
  }
  if (!plan || !farm) return <LoadingState message="Loading input plan…" />;

  const country = farm.country;
  const isDraft = plan.status === "draft";
  const offers = plan.quotes.flatMap((q) => q.financing_offers);
  const canDecideOffers = !["ordered", "cancelled"].includes(plan.status);

  const itemColumns = [
    {
      key: "product",
      header: "Input",
      render: (i) => (
        <div className="min-w-0">
          <div className="font-medium text-ink">{i.product_name}</div>
          <div className="text-xs text-muted">
            {[i.active_ingredient, i.category].filter(Boolean).join(" · ")}
          </div>
        </div>
      ),
    },
    {
      key: "qty",
      header: "Quantity",
      render: (i) => (
        <span className="text-sm text-ink">
          {i.quantity} {i.unit}
          {i.acres ? ` · ${i.acres} ac` : ""}
        </span>
      ),
    },
    {
      key: "needed",
      header: "Needed by",
      render: (i) => <span className="text-sm text-ink">{formatDate(i.needed_by_date)}</span>,
    },
    {
      key: "field",
      header: "Field",
      priority: "secondary",
      render: (i) => <span className="text-sm text-ink">{i.field_block || "—"}</span>,
    },
    {
      key: "use",
      header: "Intended use",
      priority: "secondary",
      render: (i) => <span className="text-sm text-ink">{i.intended_use || "—"}</span>,
    },
    {
      key: "est",
      header: "Est. cost",
      align: "right",
      priority: "secondary",
      render: (i) => (
        <span className="text-sm text-ink">{formatCost(i.estimated_cost, country)}</span>
      ),
    },
    {
      key: "decision",
      header: "Source decision",
      render: (i) =>
        i.planned_spray_id ? (
          <div className="flex flex-wrap items-center gap-1.5">
            <Link
              href={`/decisions/${i.planned_spray_id}`}
              className="text-sm font-medium text-leaf-700 hover:underline"
            >
              #{i.planned_spray_id}
            </Link>
            <StatusBadge kind="review" value={i.source_decision_review_state} />
          </div>
        ) : (
          <span className="text-xs text-muted">Manual entry</span>
        ),
    },
    {
      key: "action",
      priority: "action",
      header: "",
      align: "right",
      render: (i) =>
        isDraft ? (
          <Button
            variant="ghost"
            size="sm"
            disabled={busy}
            aria-label="Remove item"
            onClick={() => act(api.deleteInputPlanItem, i.id)}
          >
            <Trash2 />
          </Button>
        ) : null,
    },
  ];

  return (
    <div className="space-y-6">
      <Breadcrumbs
        items={[
          { label: "Inputs & finance", href: "/inputs" },
          { label: `Plan #${plan.id}` },
        ]}
      />
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-[22px] font-semibold text-ink">
              Input plan #{plan.id}
            </h1>
            <StatusBadge kind="planStatus" value={plan.status} />
            <StatusBadge kind="financing" value={plan.financing_state} />
            {plan.overdue && (
              <Badge variant="red">
                <TriangleAlert /> Overdue — needed by {formatDate(plan.needed_by)}
              </Badge>
            )}
            {isDemoRecord(plan) && (
              <Badge variant="outline">
                <FlaskConical /> Simulated demo data
              </Badge>
            )}
          </div>
          <p className="mt-1 text-sm text-muted">{planNextStep(plan.status)}</p>
          {plan.selection_reason && (
            <p className="mt-1 text-xs text-muted">
              <span className="font-medium">Selection reason:</span>{" "}
              {plan.selection_reason}
            </p>
          )}
          {plan.cancelled_reason && (
            <p className="mt-1 text-xs text-muted">Reason: {plan.cancelled_reason}</p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          {isDraft && (
            <Button
              disabled={busy || plan.items.length === 0}
              onClick={() => act(api.submitInputPlan, plan.id, {})}
            >
              <Send />
              Submit for quotes
            </Button>
          )}
          {plan.status === "quote_selected" && (
            <Button disabled={busy} onClick={() => act(api.createOrder, plan.id, {})}>
              <Package />
              Place order
            </Button>
          )}
          {plan.order_id && (
            <Button asChild variant="secondary">
              <Link href={`/inputs/orders/${plan.order_id}`}>View order</Link>
            </Button>
          )}
          {!["ordered", "cancelled"].includes(plan.status) && (
            <Button
              variant="outline"
              disabled={busy}
              onClick={() => {
                const reason = window.prompt("Why is this plan being cancelled?");
                if (reason) act(api.cancelInputPlan, plan.id, { reason });
              }}
            >
              Cancel plan
            </Button>
          )}
        </div>
      </div>

      {error && (
        <Callout tone="risk">
          {error}
        </Callout>
      )}

      <SectionCard
        title="Items"
        icon={<ListChecks />}
        description={
          isDraft
            ? "Items can be edited only while the plan is a draft."
            : "Items are locked — this is what suppliers were asked to quote."
        }
      >
        <DataTable
          columns={itemColumns}
          rows={plan.items}
          rowKey={(i) => i.id}
          minWidth={720}
          empty={<p className="text-sm text-muted">No items on this plan.</p>}
        />
      </SectionCard>

      {plan.status !== "draft" && (
        <SectionCard
          title="Supplier quotes"
          icon={<Package />}
          description="Concierge-entered quotes, compared on transparent totals."
        >
          <QuoteComparisonTable
            quotes={plan.quotes}
            country={country}
            canSelect={plan.status === "quoted"}
            busy={busy}
            onSelect={(q, reason) =>
              act(api.selectQuote, plan.id, {
                supplier_quote_id: q.id,
                reason,
              })
            }
          />
        </SectionCard>
      )}

      {/* Per-PRODUCT comparison, alongside the per-QUOTE table above. The two answer
          different questions: the table compares total baskets, this compares the same
          catalogued item across suppliers. Neither ranks anyone. */}
      <PriceDispersionCard planId={plan.id} />

      {plan.financing_requested && (
        <SectionCard
          title="Financing (indicative)"
          icon={<Landmark />}
          description="Manually collected indicative terms. A request is not an offer, and selecting an offer is not a loan approval, funding, or a binding agreement — no money moves through Lumos."
        >
          {offers.length === 0 ? (
            <p className="text-sm text-muted">
              Financing requested — awaiting indicative terms from the concierge.
            </p>
          ) : (
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              {offers.map((o) => (
                <FinancingOfferCard
                  key={o.id}
                  offer={o}
                  country={country}
                  canDecide={canDecideOffers}
                  onChanged={load}
                />
              ))}
            </div>
          )}
          {plan.financing_notes && (
            <p className="mt-3 text-xs text-muted">Notes: {plan.financing_notes}</p>
          )}
        </SectionCard>
      )}

      {plan.events.length > 0 && (
        <SectionCard
          title="Plan history"
          icon={<History />}
          description="Append-only audit timeline of the decisions made on this plan — submission, quote selection (with the entered reason), financing choices. Never edited."
        >
          <ol className="space-y-3">
            {plan.events.map((e) => (
              <li key={e.id} className="flex items-start gap-3 text-sm">
                <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-leaf-600" />
                <div className="min-w-0">
                  <div className="font-medium text-ink">
                    {planEventLabel(e.event_type)}
                    <span className="ml-2 text-xs font-normal text-muted">
                      {formatDate(e.occurred_on)}
                      {e.actor ? ` · ${e.actor}` : ""}
                    </span>
                  </div>
                  {e.payload?.reason && (
                    <p className="text-xs text-muted">Reason: {e.payload.reason}</p>
                  )}
                  {e.notes && <p className="text-xs text-muted">{e.notes}</p>}
                </div>
              </li>
            ))}
          </ol>
        </SectionCard>
      )}
    </div>
  );
}
