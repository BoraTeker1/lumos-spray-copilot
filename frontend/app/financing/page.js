"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Landmark, ArrowRight } from "lucide-react";
import { api } from "@/lib/api";
import { useFarmContext } from "@/lib/farm-context";
import {
  FINANCING_REQUEST_STATUS_LABELS,
  FINANCING_PURPOSE_LABELS,
} from "@/lib/labels";
import { formatDate } from "@/lib/format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import PageHeader from "@/components/PageHeader";
import SectionCard from "@/components/SectionCard";
import DataTable from "@/components/DataTable";
import EmptyState from "@/components/EmptyState";
import FinancingRequestForm from "@/components/FinancingRequestForm";
import { ErrorState, LoadingState } from "@/components/SystemState";

// Season financing, farm-scoped.
//
// This page replaced the old unlinked `/finance` lender console. The reason is the
// product argument: financing is not a separate module, it is what the operational
// record makes possible. A grower arrives here from their farm page, not from a
// lending menu.
//
// Lumos records a request and the indicative terms that come back. It makes no credit
// decision, computes no rate, and moves no money.

export default function FinancingPage() {
  const { farmId, farms } = useFarmContext();
  const [requests, setRequests] = useState([]);
  const [cycles, setCycles] = useState([]);
  const [policies, setPolicies] = useState([]);
  const [error, setError] = useState(null);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    if (!farmId) return;
    try {
      const [r, c, p] = await Promise.all([
        api.listFinancingRequests(farmId),
        api.listCropCycles(farmId),
        // Policies are optional context; a deployment with none still works.
        api.listLenderPolicies().catch(() => []),
      ]);
      setRequests(r);
      setCycles(c);
      setPolicies(p);
      setLoaded(true);
    } catch (err) {
      setError(err.message);
    }
  }, [farmId]);

  useEffect(() => {
    load();
  }, [load]);

  if (error) return <ErrorState message={error} />;
  if (!farms?.length) {
    return (
      <EmptyState
        icon={Landmark}
        title="No farm yet"
        description="Financing readiness is assembled from a farm's records."
        actionHref="/pilot/new"
        actionLabel="Set up a farm"
      />
    );
  }
  if (!loaded) return <LoadingState />;

  const columns = [
    {
      key: "purpose",
      header: "Purpose",
      render: (r) => (
        <div className="min-w-0">
          <div className="font-medium text-ink">
            {FINANCING_PURPOSE_LABELS[r.purpose] || r.purpose}
          </div>
          <div className="text-xs text-muted">Opened {formatDate(r.created_at)}</div>
        </div>
      ),
    },
    {
      key: "amount",
      header: "Requested",
      render: (r) =>
        r.requested_amount == null ? (
          <span className="text-muted">Not stated</span>
        ) : (
          <span>
            {Number(r.requested_amount).toLocaleString()} {r.currency_code || ""}
          </span>
        ),
    },
    {
      key: "status",
      header: "Status",
      render: (r) => (
        <Badge variant="neutral">
          {FINANCING_REQUEST_STATUS_LABELS[r.status] || r.status}
        </Badge>
      ),
    },
    {
      key: "offers",
      header: "Terms received",
      render: (r) => (r.offers?.length ? r.offers.length : "—"),
    },
    {
      key: "open",
      header: "",
      render: (r) => (
        <Link href={`/financing/${r.id}`}>
          <Button variant="secondary" size="sm">
            Open <ArrowRight className="ml-1.5 h-3.5 w-3.5" />
          </Button>
        </Link>
      ),
    },
  ];

  return (
    <div className="space-y-5">
      <PageHeader
        breadcrumbs={[{ label: "Records" }, { label: "Financing" }]}
        title="Financing"
        description={
          "Lumos assembles the evidence a lender asks for from records this farm " +
          "already keeps, and records the indicative terms that come back. It makes " +
          "no credit decision and moves no money."
        }
        actions={
          <FinancingRequestForm
            farmId={farmId}
            cycles={cycles}
            policies={policies}
          />
        }
      />

      <SectionCard
        title="Requests"
        description="Every financing request opened for this farm."
      >
        {requests.length === 0 ? (
          <EmptyState
            icon={Landmark}
            title="No financing request yet"
            description={
              "Open one to see which of a lender's usual evidence items this farm " +
              "already has on record — and which it does not."
            }
          />
        ) : (
          <DataTable columns={columns} rows={requests} keyField="id" />
        )}
      </SectionCard>
    </div>
  );
}
