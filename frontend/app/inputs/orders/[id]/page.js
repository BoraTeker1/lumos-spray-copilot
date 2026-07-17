"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { FlaskConical, History, Landmark, Package, TriangleAlert } from "lucide-react";
import { api } from "@/lib/api";
import { formatCost, formatDate } from "@/lib/format";
import { Badge } from "@/components/ui/badge";
import Breadcrumbs from "@/components/Breadcrumbs";
import DataTable from "@/components/DataTable";
import LinkApplicationDialog from "@/components/LinkApplicationDialog";
import OrderTimeline from "@/components/OrderTimeline";
import SectionCard from "@/components/SectionCard";
import StatusBadge from "@/components/StatusBadge";

function isDemoRecord(r) {
  return r.data_source === "demo" || r.data_confidence === "simulated";
}

export default function OrderDetailPage({ params }) {
  const [order, setOrder] = useState(null);
  const [farm, setFarm] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    try {
      const o = await api.getOrder(params.id);
      setOrder(o);
      setFarm(await api.getFarm(o.farm_id));
      setError(null);
    } catch (err) {
      setError(err.message);
    }
  }, [params.id]);

  useEffect(() => {
    load();
  }, [load]);

  if (error && !order) {
    return (
      <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
        {error}
      </div>
    );
  }
  if (!order || !farm) return <p className="text-sm text-gray-500">Loading order…</p>;

  const country = farm.country;
  const quote = order.selected_quote;
  const offer = order.accepted_financing_offer;
  const applied = order.spray_event_id || order.applied_planned_spray_id;
  const canLinkApplication =
    ["delivered", "partially_delivered"].includes(order.status) && !applied;

  const lineColumns = [
    {
      key: "product",
      header: "Input",
      render: (l) => (
        <div>
          <span className="font-medium text-gray-900">{l.product_name}</span>
          {l.is_substitution && (
            <Badge variant="amber" className="ml-2" title={l.substitution_reason}>
              Substitution
            </Badge>
          )}
        </div>
      ),
    },
    {
      key: "qty",
      header: "Quantity",
      render: (l) => (
        <span className="text-sm text-gray-700">
          {l.quantity} {l.unit}
        </span>
      ),
    },
    {
      key: "price",
      header: "Unit price",
      align: "right",
      render: (l) => (
        <span className="text-sm text-gray-700">{formatCost(l.unit_price, country)}</span>
      ),
    },
    {
      key: "total",
      header: "Line total",
      align: "right",
      render: (l) => (
        <span className="text-sm font-medium text-gray-900">
          {formatCost(l.line_total, country)}
        </span>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <Breadcrumbs
        items={[
          { label: "Inputs & finance", href: "/inputs?tab=orders" },
          { label: `Order #${order.id}` },
        ]}
      />
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-[22px] font-semibold text-gray-900">Order #{order.id}</h1>
            <StatusBadge kind="orderStatus" value={order.status} />
            {order.overdue && (
              <Badge variant="red">
                <TriangleAlert /> Overdue — not delivered by the needed-by date
              </Badge>
            )}
            {isDemoRecord(order) && (
              <Badge variant="outline">
                <FlaskConical /> Simulated demo data
              </Badge>
            )}
          </div>
          <p className="mt-1 text-sm text-gray-500">
            {order.supplier_name} · {formatCost(order.total_cost, country)} ·{" "}
            <Link
              href={`/inputs/plans/${order.input_plan_id}`}
              className="font-medium text-leaf-700 hover:underline"
            >
              from plan #{order.input_plan_id}
            </Link>
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {canLinkApplication && <LinkApplicationDialog order={order} onChanged={load} />}
          {applied && (
            <Badge variant="green">
              Application linked
              {order.applied_planned_spray_id ? ` — decision #${order.applied_planned_spray_id}` : ""}
            </Badge>
          )}
        </div>
      </div>

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[1fr_340px]">
        <div className="space-y-6">
          <SectionCard
            title="Order lines"
            icon={<Package />}
            description={
              quote
                ? `From the selected quote by ${quote.supplier_name}: ${formatCost(
                    quote.items_subtotal,
                    country
                  )} + ${formatCost(quote.delivery_cost, country)} delivery + ${formatCost(
                    quote.fees,
                    country
                  )} fees = ${formatCost(quote.total_cost, country)}.`
                : undefined
            }
          >
            <DataTable
              columns={lineColumns}
              rows={quote?.items || []}
              rowKey={(l) => l.id}
              minWidth={520}
              empty={<p className="text-sm text-gray-500">No lines.</p>}
            />
          </SectionCard>

          <SectionCard
            title="Order timeline"
            icon={<History />}
            description="Append-only event record — entries are never edited or deleted. Delivery never marks the input as applied; that link is recorded explicitly."
          >
            <OrderTimeline events={order.events} />
          </SectionCard>
        </div>

        <div className="space-y-6">
          {offer && (
            <SectionCard
              title="Financing — indicative offer selected"
              icon={<Landmark />}
              description="Indicative terms the grower selected before ordering. Not a loan approval, not lender confirmation; no money moves through Lumos."
            >
              <dl className="space-y-1.5 text-sm">
                <div className="flex justify-between">
                  <dt className="text-gray-500">Provider</dt>
                  <dd className="font-medium text-gray-900">{offer.provider_name}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-gray-500">Financed</dt>
                  <dd className="font-medium text-gray-900">
                    {formatCost(offer.financed_amount, country)}
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-gray-500">Down payment</dt>
                  <dd className="font-medium text-gray-900">
                    {formatCost(offer.down_payment, country)}
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-gray-500">Total repayment</dt>
                  <dd className="font-medium text-gray-900">
                    {formatCost(offer.total_repayment, country)}
                  </dd>
                </div>
                {offer.schedule_summary && (
                  <div className="flex justify-between">
                    <dt className="text-gray-500">Schedule</dt>
                    <dd className="text-gray-900">{offer.schedule_summary}</dd>
                  </div>
                )}
              </dl>
              <p className="mt-3 text-[11px] text-gray-500">{offer.disclaimer}</p>
            </SectionCard>
          )}
          <div className="rounded-md border border-gray-200 bg-gray-50 p-3 text-xs text-gray-600">
            Placed {formatDate(order.created_at)}
            {order.placed_by ? ` by ${order.placed_by}` : ""}. Supplier quotes are
            concierge-entered; Lumos takes no commission and never ranks suppliers.
          </div>
        </div>
      </div>
    </div>
  );
}
