"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FlaskConical, Package, ShoppingCart, TriangleAlert } from "lucide-react";
import { api } from "@/lib/api";
import { useFarmContext } from "@/lib/farm-context";
import { formatCost, formatDate } from "@/lib/format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import DataTable from "@/components/DataTable";
import EmptyState from "@/components/EmptyState";
import FilterBar from "@/components/FilterBar";
import InputPlanForm from "@/components/InputPlanForm";
import PageHeader from "@/components/PageHeader";
import StatusBadge from "@/components/StatusBadge";
import { planNextStep } from "@/lib/status";

const TABS = ["plans", "orders"];

function isDemoRecord(r) {
  return r.data_source === "demo" || r.data_confidence === "simulated";
}

// Chip predicates shared by counts and rows (they can never disagree).
const PLAN_FILTERS = [
  { key: "all", label: "All", match: () => true },
  { key: "draft", label: "Draft", match: (p) => p.status === "draft" },
  {
    key: "awaiting_quotes",
    label: "Awaiting quotes",
    match: (p) => p.status === "submitted_for_quotes",
  },
  {
    key: "compare",
    label: "Quotes received",
    match: (p) => p.status === "quoted",
  },
  {
    key: "ready",
    label: "Ready to order",
    match: (p) => p.status === "quote_selected",
  },
  { key: "ordered", label: "Ordered", match: (p) => p.status === "ordered" },
  { key: "overdue", label: "Overdue", match: (p) => p.overdue },
];

function planColumns() {
  return [
    {
      key: "plan",
      header: "Plan",
      render: (p) => (
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Link
              href={`/inputs/plans/${p.id}`}
              className="font-medium text-leaf-700 hover:underline"
            >
              Plan #{p.id}
            </Link>
            {isDemoRecord(p) && (
              <Badge variant="outline">
                <FlaskConical /> Simulated demo data
              </Badge>
            )}
          </div>
          <div className="text-xs text-muted">
            {p.items.map((i) => `${i.product_name} (${i.quantity} ${i.unit})`).join(", ") ||
              "No items"}
          </div>
        </div>
      ),
    },
    {
      key: "status",
      header: "Stage",
      render: (p) => <StatusBadge kind="planStatus" value={p.status} />,
    },
    {
      key: "next",
      header: "Next action",
      render: (p) => (
        <span className="text-xs text-muted">{planNextStep(p.status)}</span>
      ),
    },
    {
      key: "needed",
      header: "Needed by",
      render: (p) => (
        <div className="text-sm text-ink">
          {formatDate(p.needed_by)}
          {p.overdue && (
            <div>
              <Badge variant="red">
                <TriangleAlert /> Overdue
              </Badge>
            </div>
          )}
        </div>
      ),
    },
    {
      key: "supplier",
      header: "Selected supplier",
      priority: "secondary",
      render: (p) => (
        <span className="text-sm text-ink">
          {p.order_id
            ? `Order #${p.order_id}`
            : p.selected_quote_id
            ? `Quote #${p.selected_quote_id}`
            : "—"}
        </span>
      ),
    },
    {
      key: "financing",
      header: "Financing",
      priority: "secondary",
      render: (p) => <StatusBadge kind="financing" value={p.financing_state} />,
    },
    {
      key: "quotes",
      header: "Quotes",
      align: "right",
      priority: "secondary",
      render: (p) => <span className="text-sm text-ink">{p.quote_count}</span>,
    },
    {
      key: "action",
      header: "",
      align: "right",
      render: (p) => (
        <Button asChild variant="secondary" size="sm">
          <Link href={p.order_id ? `/inputs/orders/${p.order_id}` : `/inputs/plans/${p.id}`}>
            {p.order_id ? "View order" : "Open plan"}
          </Link>
        </Button>
      ),
    },
  ];
}

function orderColumns(country) {
  return [
    {
      key: "order",
      header: "Order",
      render: (o) => (
        <div className="flex flex-wrap items-center gap-2">
          <Link
            href={`/inputs/orders/${o.id}`}
            className="font-medium text-leaf-700 hover:underline"
          >
            Order #{o.id}
          </Link>
          {isDemoRecord(o) && (
            <Badge variant="outline">
              <FlaskConical /> Simulated demo data
            </Badge>
          )}
        </div>
      ),
    },
    {
      key: "supplier",
      header: "Supplier",
      render: (o) => <span className="text-sm text-ink">{o.supplier_name || "—"}</span>,
    },
    {
      key: "total",
      header: "Total",
      align: "right",
      render: (o) => (
        <span className="text-sm font-medium text-ink">
          {formatCost(o.total_cost, country)}
        </span>
      ),
    },
    {
      key: "status",
      header: "Status",
      render: (o) => (
        <div className="space-y-1">
          <StatusBadge kind="orderStatus" value={o.status} />
          {o.overdue && (
            <div>
              <Badge variant="red">
                <TriangleAlert /> Overdue
              </Badge>
            </div>
          )}
        </div>
      ),
    },
    {
      key: "applied",
      header: "Application",
      priority: "secondary",
      render: (o) =>
        o.spray_event_id || o.applied_planned_spray_id ? (
          <Badge variant="green">Linked</Badge>
        ) : (
          <span className="text-xs text-muted">Not linked</span>
        ),
    },
    {
      key: "placed",
      header: "Placed",
      priority: "secondary",
      render: (o) => (
        <span className="text-sm text-ink">{formatDate(o.created_at)}</span>
      ),
    },
    {
      key: "action",
      header: "",
      align: "right",
      render: (o) => (
        <Button asChild variant="secondary" size="sm">
          <Link href={`/inputs/orders/${o.id}`}>Open order</Link>
        </Button>
      ),
    },
  ];
}

function InputsPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { activeFarm, loading: farmsLoading } = useFarmContext();
  const farmId = activeFarm?.id;

  const tabParam = searchParams.get("tab");
  const tab = TABS.includes(tabParam) ? tabParam : "plans";
  const setTab = (next) =>
    router.replace(next === "plans" ? "/inputs" : `/inputs?tab=${next}`);

  const [plans, setPlans] = useState([]);
  const [orders, setOrders] = useState([]);
  const [error, setError] = useState(null);
  const [planFilter, setPlanFilter] = useState("all");

  const load = useCallback(async () => {
    if (!farmId) return;
    try {
      const [p, o] = await Promise.all([
        api.listInputPlans(farmId),
        api.listOrders(farmId),
      ]);
      setPlans(p);
      setOrders(o);
      setError(null);
    } catch (err) {
      setError(err.message);
    }
  }, [farmId]);

  useEffect(() => {
    load();
  }, [load]);

  const activeFilter =
    PLAN_FILTERS.find((f) => f.key === planFilter) || PLAN_FILTERS[0];
  const planRows = useMemo(
    () => plans.filter(activeFilter.match),
    [plans, activeFilter]
  );

  if (farmsLoading) return <p className="text-sm text-muted">Loading…</p>;
  if (!activeFarm) {
    return (
      <p className="text-sm text-muted">
        No farms yet — seed the demo data or add a pilot farm first.
      </p>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumbs={[{ label: "Inputs & finance" }, { label: activeFarm.name }]}
        title="Inputs & finance"
        meta={
          <span>Turn PCA-reviewed decisions into supplier-ready input orders.</span>
        }
        actions={<InputPlanForm farmId={farmId} onCreated={load} />}
      />

      {error && (
        <div className="rounded-control border border-risk-line bg-risk-bg p-3 text-sm text-risk-fg">
          {error}
        </div>
      )}

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="plans">Input plans</TabsTrigger>
          <TabsTrigger value="orders">Orders</TabsTrigger>
        </TabsList>
        <p className="mt-2 text-xs text-muted">
          Draft plan → quotes requested → quotes received → quote selected →
          financing (optional) → order confirmed → delivered → applied. Supplier
          quotes and financing terms are concierge-entered; no money moves through
          Lumos.
        </p>

        <TabsContent value="plans">
          <Card>
            <CardContent className="p-5">
              <FilterBar
                chips={PLAN_FILTERS.map((f) => ({
                  key: f.key,
                  label: f.label,
                  count: plans.filter(f.match).length,
                  selected: f.key === planFilter,
                  onClick: () => setPlanFilter(f.key),
                }))}
              />
              <DataTable
                columns={planColumns()}
                rows={planRows}
                rowKey={(p) => p.id}
                minWidth={680}
                empty={
                  <EmptyState
                    icon={ShoppingCart}
                    title={
                      plans.length === 0
                        ? "No input plans yet"
                        : "Nothing matches this filter"
                    }
                    description={
                      plans.length === 0
                        ? "Start from an approved decision (Request supplier quotes) or build a plan manually."
                        : "Clear the filter to see more plans."
                    }
                  />
                }
              />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="orders">
          <Card>
            <CardContent className="p-5">
              <DataTable
                columns={orderColumns(activeFarm.country)}
                rows={orders}
                rowKey={(o) => o.id}
                minWidth={680}
                empty={
                  <EmptyState
                    icon={Package}
                    title="No orders yet"
                    description="An order is created from a plan's selected quote and tracked here through delivery and application."
                  />
                }
              />
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}

export default function Page() {
  return (
    <Suspense fallback={<p className="text-sm text-muted">Loading…</p>}>
      <InputsPage />
    </Suspense>
  );
}
