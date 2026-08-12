"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import {
  FINANCING_REQUEST_STATUS_LABELS,
  FINANCING_PURPOSE_LABELS,
} from "@/lib/labels";
import { formatDate } from "@/lib/format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import Breadcrumbs from "@/components/Breadcrumbs";
import SectionCard from "@/components/SectionCard";
import Callout from "@/components/Callout";
import EvidencePackageCard from "@/components/EvidencePackageCard";
import FinancingOfferCard from "@/components/FinancingOfferCard";
import { ErrorState, LoadingState } from "@/components/SystemState";

// One financing request, end to end:
//   farm data → evidence package → lender criteria → indicative terms → selection
//   → ongoing monitoring
//
// The assessment and monitoring blocks both REFUSE when no lender policy is
// attached, and say so in words. That is the honest state: Lumos evaluates a
// lender's written policy and never authors one, so with nothing attached there is
// nothing to assess.

function OutcomeBadge({ outcome }) {
  const variant =
    outcome === "conditions_met"
      ? "green"
      : outcome === "conditions_not_met"
        ? "red"
        : "amber";
  const label =
    outcome === "conditions_met"
      ? "Conditions met"
      : outcome === "conditions_not_met"
        ? "Conditions not met"
        : "Referred to a human";
  return <Badge variant={variant}>{label}</Badge>;
}

function RuleRow({ rule }) {
  const state = !rule.evaluated
    ? "Not evaluated"
    : rule.passed
      ? "Met"
      : "Not met";
  return (
    <li className="flex items-start justify-between gap-3 border-b border-line py-2 last:border-0">
      <div className="min-w-0">
        <div className="text-sm text-ink">{rule.description || rule.rule_id}</div>
        {rule.not_evaluated_reason && (
          <div className="text-xs text-muted">{rule.not_evaluated_reason}</div>
        )}
        {rule.threshold != null && (
          <div className="text-[11px] text-muted">
            Threshold {rule.threshold}
            {rule.observed_value != null && ` · observed ${rule.observed_value}`}
          </div>
        )}
      </div>
      <span className="shrink-0 text-xs text-muted">{state}</span>
    </li>
  );
}

export default function FinancingRequestPage({ params }) {
  const requestId = Number(params.id);
  const [request, setRequest] = useState(null);
  const [pkg, setPkg] = useState(null);
  const [assessment, setAssessment] = useState(null);
  const [monitoring, setMonitoring] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    try {
      const [r, p, a, m] = await Promise.all([
        api.getFinancingRequest(requestId),
        api.getFinancingEvidencePackage(requestId),
        api.getFinancingAssessment(requestId),
        api.getFinancingMonitoring(requestId),
      ]);
      setRequest(r);
      setPkg(p);
      setAssessment(a);
      setMonitoring(m);
    } catch (err) {
      setError(err.message);
    }
  }, [requestId]);

  useEffect(() => {
    load();
  }, [load]);

  if (error) return <ErrorState message={error} />;
  if (!request || !pkg) return <LoadingState />;

  const liveOffers = (request.offers || []).filter(
    (o) => o.status !== "withdrawn"
  );

  return (
    <div className="space-y-5">
      <Breadcrumbs
        items={[
          { label: "Financing", href: "/financing" },
          { label: FINANCING_PURPOSE_LABELS[request.purpose] || request.purpose },
        ]}
      />

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-ink">
            {FINANCING_PURPOSE_LABELS[request.purpose] || request.purpose}
          </h1>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted">
            <Badge variant="neutral">
              {FINANCING_REQUEST_STATUS_LABELS[request.status] || request.status}
            </Badge>
            {request.requested_amount != null && (
              <span>
                {Number(request.requested_amount).toLocaleString()}{" "}
                {request.currency_code || ""} requested
              </span>
            )}
            <span>· opened {formatDate(request.created_at)}</span>
          </div>
        </div>
        <Link href="/financing">
          <Button variant="outline" size="sm">
            <ArrowLeft className="mr-1.5 h-3.5 w-3.5" /> All requests
          </Button>
        </Link>
      </div>

      <SectionCard
        title="Evidence package"
        description="Assembled from records this farm already keeps. Nothing here was entered for the lender's benefit."
      >
        <EvidencePackageCard package={pkg} />
      </SectionCard>

      <SectionCard
        title="Lender criteria"
        description="This farm's recorded evidence, read against a lender's own written policy."
      >
        {assessment?.refused ? (
          <Callout tone="info" title="No lender criteria attached">
            {assessment.detail}
          </Callout>
        ) : assessment ? (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <OutcomeBadge outcome={assessment.outcome} />
              <span className="text-sm text-muted">
                {assessment.lender} · policy {assessment.policy_version}
              </span>
            </div>
            <ul>
              {(assessment.rules || []).map((rule) => (
                <RuleRow key={rule.rule_id} rule={rule} />
              ))}
            </ul>
            <Callout tone="info" title="What this is and is not">
              &ldquo;Conditions met&rdquo; is a statement about the lender&rsquo;s
              policy, not a commitment to lend, and there is no
              &ldquo;approved&rdquo; outcome anywhere in Lumos. A rule Lumos could
              not evaluate is referred to a human rather than folded into a pass.
            </Callout>
            {assessment.source_document && (
              <p className="text-[11px] text-muted">
                Criteria source: {assessment.source_document}
              </p>
            )}
          </div>
        ) : null}
      </SectionCard>

      <SectionCard
        title="Indicative terms"
        description="Entered by Lumos from what the lender sent. Every figure is theirs — Lumos computes no rate and no repayment."
      >
        {liveOffers.length === 0 ? (
          <p className="text-sm text-muted">
            No indicative terms have been recorded for this request yet.
          </p>
        ) : (
          <div className="space-y-3">
            {liveOffers.map((offer) => (
              <FinancingOfferCard
                key={offer.id}
                offer={offer}
                canDecide
                onChanged={load}
              />
            ))}
          </div>
        )}
      </SectionCard>

      <SectionCard
        title="Monitoring"
        description="Covenant standing for a financed season, from the same operational records that drive the advisory queue."
      >
        {monitoring?.refused ? (
          <Callout tone="info" title="No covenant schedule on record">
            {monitoring.detail}
          </Callout>
        ) : monitoring ? (
          <div className="space-y-3">
            <div className="text-sm text-muted">
              Standing: <span className="text-ink">{monitoring.standing}</span>
            </div>
            <ul>
              {(monitoring.covenants || []).map((c) => (
                <li
                  key={c.covenant_id}
                  className="flex items-start justify-between gap-3 border-b border-line py-2 last:border-0"
                >
                  <div className="min-w-0">
                    <div className="text-sm text-ink">
                      {c.description || c.covenant_id}
                    </div>
                    {c.not_evaluated_reason && (
                      <div className="text-xs text-muted">
                        {c.not_evaluated_reason}
                      </div>
                    )}
                  </div>
                  <span className="shrink-0 text-xs text-muted">{c.status}</span>
                </li>
              ))}
            </ul>
            <p className="text-[11px] text-muted">
              A covenant whose input could not be computed is{" "}
              <strong>not evaluated</strong>, never &ldquo;within&rdquo; — nothing
              checked is not the same as compliant.
            </p>
          </div>
        ) : null}
      </SectionCard>

      <SectionCard title="History" description="Append-only; never rewritten.">
        <ul className="space-y-1 text-sm text-muted">
          {(request.events || []).map((e) => (
            <li key={e.id}>
              <span className="text-ink">{e.event_type}</span> ·{" "}
              {formatDate(e.occurred_on)}
              {e.notes && <span> — {e.notes}</span>}
            </li>
          ))}
        </ul>
      </SectionCard>
    </div>
  );
}
