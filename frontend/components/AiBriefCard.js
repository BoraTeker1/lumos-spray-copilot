"use client";

import { useState } from "react";
import { Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

// AI review brief (beta): retrieval-grounded rescue-risk note + next EVIDENCE
// actions for one decision. On-demand only, clearly labeled AI-suggested, and it
// NEVER changes the deterministic compliance verdict. Abstains (server-enforced)
// when there are too few comparable real decisions to ground a risk note.

const RISK_BADGE = { low: "green", medium: "amber", high: "red", abstain: "outline" };

const ACTION_LABELS = {
  rescout_target: "Re-scout the target",
  verify_phi_rei_from_label: "Verify PHI/REI from the label",
  confirm_threshold_with_pca: "Confirm the action threshold with the PCA",
  record_follow_up: "Record follow-up events",
  wait_and_recheck: "Wait and re-check",
  consult_pca: "Consult the PCA",
};

export default function AiBriefCard({ plannedId }) {
  const [brief, setBrief] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function generate() {
    setBusy(true);
    setError(null);
    try {
      setBrief(await api.generateAiBrief(plannedId));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="no-print space-y-2 rounded-md border border-indigo-200 bg-indigo-50/40 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs font-semibold text-indigo-900">
          AI review brief (beta) — suggestion only; the verdict above stays deterministic
        </p>
        <Button type="button" size="sm" variant="outline" disabled={busy} onClick={generate}>
          <Sparkles />
          {busy ? "Generating…" : brief ? "Regenerate" : "Generate AI review brief"}
        </Button>
      </div>

      {error && <p className="text-xs text-red-600">{error}</p>}

      {brief && (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="text-gray-600">Rescue risk (qualitative):</span>
            <Badge variant={RISK_BADGE[brief.rescue_risk] || "outline"}>
              {brief.rescue_risk === "abstain" ? "ABSTAINED" : brief.rescue_risk.toUpperCase()}
            </Badge>
            <span className="text-gray-500">
              grounded in {brief.comparable_count} comparable real decision(s)
              {" · "}confidence: {brief.confidence}
              {brief.is_mock && " · mock (set ANTHROPIC_API_KEY for the real model)"}
            </span>
          </div>

          {brief.abstained ? (
            <p className="rounded bg-white px-2 py-1.5 text-xs text-amber-800">
              {brief.abstain_reason}
            </p>
          ) : (
            <p className="rounded bg-white px-2 py-1.5 text-xs text-gray-700">
              {brief.rationale}
            </p>
          )}

          {brief.next_evidence_actions?.length > 0 && (
            <div>
              <p className="text-[11px] font-medium uppercase tracking-wide text-gray-500">
                Suggested next evidence-gathering actions (never a spray or product)
              </p>
              <ul className="mt-1 space-y-1 text-xs text-gray-700">
                {brief.next_evidence_actions.map((a, i) => (
                  <li key={i} className="rounded bg-white px-2 py-1">
                    <span className="font-medium">
                      {ACTION_LABELS[a.action_type] || a.action_type.replace(/_/g, " ")}
                    </span>
                    {a.detail && <span className="text-gray-500"> — {a.detail}</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {brief.comparables?.length > 0 && (
            <details className="text-[11px] text-gray-500">
              <summary className="cursor-pointer font-medium">
                Comparable decisions the brief is grounded in
              </summary>
              <ul className="mt-1 space-y-0.5">
                {brief.comparables.map((c) => (
                  <li key={c.id}>
                    #{c.id} {c.product_name} vs {c.target_pest_or_disease} (
                    {c.match_basis.join(", ").replace(/_/g, " ")}) — recorded outcome:{" "}
                    {c.recorded_outcome.replace(/_/g, " ")}
                    {c.follow_up?.rescue_required && " · rescue was required"}
                    {c.follow_up?.confirmed_avoided && " · confirmed avoided"}
                    {!c.follow_up?.has_follow_up && " · no follow-up yet"}
                  </li>
                ))}
              </ul>
            </details>
          )}

          <p className="text-[11px] text-gray-400">{brief.disclaimer}</p>
        </div>
      )}
    </div>
  );
}
