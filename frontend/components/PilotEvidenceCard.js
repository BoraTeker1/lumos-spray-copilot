"use client";

import { useEffect, useState } from "react";
import { api, API_BASE_URL } from "@/lib/api";
import { formatCost } from "@/lib/format";

// One labelled metric tile.
// Pilot Evidence: a descriptive snapshot of what the pilot has logged so far, plus a
// link/copy for the consolidated audit packet. Framed as evidence, not a guarantee.
// `refreshKey` re-fetches when records change.
export default function PilotEvidenceCard({ farmId, country, refreshKey, hasDocumentedSkip = false }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    api
      .getPilotEvidence(farmId)
      .then(setData)
      .catch((err) => setError(err.message));
  }, [farmId, refreshKey]);

  async function copyPacket() {
    try {
      const packet = await api.getAuditPacket(farmId);
      await navigator.clipboard.writeText(JSON.stringify(packet, null, 2));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setError("Could not copy the audit packet — open it with the link instead.");
    }
  }

  if (error) return <p className="text-sm text-risk-fg">{error}</p>;
  if (!data) return <p className="text-sm text-muted">Loading pilot evidence…</p>;

  const reviewSummary = `${data.pca_approved_count} approved · ${data.pca_pending_count} pending · ${data.pca_changes_requested_count} changes`;
  const avoidable =
    data.estimated_avoidable_cost_usd != null
      ? formatCost(data.estimated_avoidable_cost_usd, country)
      : "—";

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-end gap-2">
        <div className="flex gap-2 text-xs">
          <a
            href={`${API_BASE_URL}/farms/${farmId}/audit-packet`}
            target="_blank"
            rel="noreferrer"
            className="rounded border px-2 py-1 hover:border-muted"
          >
            View audit packet
          </a>
          <button
            onClick={copyPacket}
            className="rounded border px-2 py-1 hover:border-muted"
          >
            {copied ? "Copied" : "Copy audit packet"}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <StatTile label="Sprays logged" value={data.total_spray_events} />
        <StatTile
          label="Scouting-backed sprays"
          value={`${data.sprays_with_recent_scouting_count} / ${data.total_spray_events}`}
          hint={`${data.sprays_without_recent_scouting_count} scouting-light`}
        />
        <StatTile label="PHI / REI flags" value={data.phi_rei_risk_flags_count} />
        <StatTile
          label="Resistance flags"
          value={data.resistance_or_repeated_active_ingredient_flags_count}
          hint="repeated active ingredient"
        />
        <StatTile label="PCA review" value={reviewSummary} />
        <StatTile
          label={
            hasDocumentedSkip
              ? "Potential avoidable cost"
              : "Estimated cost of one planned application"
          }
          value={avoidable}
          hint={hasDocumentedSkip ? "a planned spray was avoided" : "estimate, not a saving claim"}
        />
      </div>

      {data.evidence_summary?.length > 0 && (
        <ul className="mt-3 space-y-1 text-sm text-ink">
          {data.evidence_summary.map((line, i) => (
            <li key={i} className="flex gap-2">
              <span className="text-leaf">•</span>
              <span>{line}</span>
            </li>
          ))}
        </ul>
      )}

      <p className="mt-3 rounded bg-warn-bg px-3 py-2 text-xs text-warn-fg">
        This is <strong>pilot evidence</strong> — a descriptive record of what was logged. It is
        <strong> not</strong> a guarantee of pesticide reduction, not a compliance/legal
        guarantee, and never an autonomous spray instruction. Real reduction must be measured
        against a baseline over a full crop cycle with the grower/PCA.
      </p>
    </div>
  );
}
