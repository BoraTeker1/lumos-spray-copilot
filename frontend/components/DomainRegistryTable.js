"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import SectionCard from "@/components/SectionCard";
import { Layers } from "lucide-react";

// The seventeen declared data domains, and which of them this product may build.
//
// This table exists so the MVP/finance boundary is an OPERATOR ARTIFACT rather than a
// paragraph in a document. Eight of these domains — financing, credit scoring,
// underwriting, insurance, collateralization, hedging, pricing, portfolio monitoring —
// are things ENGINEERING_GUIDELINES.md 4 forbids, and each one shows the clause that defers it.
//
// Declaring them is not building them, and that is enforced in code rather than here:
// a source under a deferred domain cannot have an adapter, and `features.base.register`
// refuses a non-MVP domain outright. This view just makes the state visible.

const STATUS_STYLES = {
  implemented: "bg-emerald-50 text-emerald-700 border-emerald-200",
  requires_credential: "bg-amber-50 text-amber-700 border-amber-200",
  not_implemented: "bg-gray-50 text-gray-600 border-gray-200",
  deferred_to_finance_phase: "bg-rose-50 text-rose-700 border-rose-200",
};

const STATUS_LABELS = {
  implemented: "implemented",
  requires_credential: "needs credential",
  not_implemented: "not built",
  deferred_to_finance_phase: "deferred",
};

function StatusChip({ status }) {
  return (
    <span
      className={`inline-block rounded border px-1.5 py-0.5 text-[11px] font-medium ${
        STATUS_STYLES[status] || STATUS_STYLES.not_implemented
      }`}
    >
      {STATUS_LABELS[status] || status}
    </span>
  );
}

export default function DomainRegistryTable() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getIngestionSources()
      .then((body) => !cancelled && setData(body))
      .catch((err) => !cancelled && setError(err.message));
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return (
      <SectionCard title="Data domains" icon={<Layers />}>
        <p className="text-sm text-red-600">{error}</p>
      </SectionCard>
    );
  }
  if (!data) {
    return (
      <SectionCard title="Data domains" icon={<Layers />}>
        <p className="text-sm text-gray-500">Loading…</p>
      </SectionCard>
    );
  }

  const sourcesByDomain = {};
  for (const source of data.sources) {
    (sourcesByDomain[source.domain] ||= []).push(source);
  }

  const mvp = data.domains.filter((d) => d.phase === "mvp");
  const deferred = data.domains.filter((d) => d.phase === "future_finance");

  const renderDomain = (domain) => (
    <tr key={domain.key} className="border-b last:border-b-0 align-top">
      <td className="py-2 pr-3">
        <div className="text-sm font-medium text-gray-900">{domain.title}</div>
        <div className="text-xs text-gray-500">{domain.rationale}</div>
        {domain.guardrail_ref && (
          <div className="mt-1 text-xs text-rose-700">
            Deferred by ENGINEERING_GUIDELINES.md {domain.guardrail_section}:{" "}
            <span className="font-mono">&ldquo;{domain.guardrail_ref}&rdquo;</span>
          </div>
        )}
      </td>
      <td className="py-2 pl-3">
        {(sourcesByDomain[domain.key] || []).map((source) => (
          <div key={source.source_key} className="mb-1 last:mb-0">
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs text-gray-700">
                {source.source_key}
              </span>
              <StatusChip status={source.status} />
            </div>
            {source.blocker && (
              <div className="text-xs text-gray-500">{source.blocker}</div>
            )}
          </div>
        ))}
        {!sourcesByDomain[domain.key] && (
          <span className="text-xs text-gray-400">no source declared</span>
        )}
      </td>
    </tr>
  );

  return (
    <SectionCard
      title="Data domains"
      icon={<Layers />}
      description={`${data.domains.length} declared — ${mvp.length} in scope, ${deferred.length} deferred to a finance phase`}
    >
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-left">
          <thead>
            <tr className="border-b text-xs uppercase tracking-wide text-gray-500">
              <th className="py-2 pr-3 font-medium">Domain</th>
              <th className="py-2 pl-3 font-medium">Sources</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td colSpan={2} className="pt-3 pb-1 text-xs font-semibold text-gray-600">
                In scope
              </td>
            </tr>
            {mvp.map(renderDomain)}
            <tr>
              <td colSpan={2} className="pt-4 pb-1 text-xs font-semibold text-rose-700">
                Deferred — declared, not built
              </td>
            </tr>
            {deferred.map(renderDomain)}
          </tbody>
        </table>
      </div>
    </SectionCard>
  );
}
