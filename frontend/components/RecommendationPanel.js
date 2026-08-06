"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import RiskBadge from "./RiskBadge";
import NextActionCard from "./NextActionCard";
import AgronomistReview from "./AgronomistReview";
import { formatDate } from "@/lib/format";
import { RISK_LEVEL_TONES, tone } from "@/lib/tones";

const BOX_STYLES = Object.fromEntries(
  Object.entries(RISK_LEVEL_TONES).map(([k, t]) => [k, tone(t).box])
);

// Shows the latest recommendation (next action + risk + agronomist review) and
// lets the user generate a fresh one.
export default function RecommendationPanel({ farmId, latest, onChanged }) {
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState(null);

  async function generate() {
    setGenerating(true);
    setError(null);
    try {
      await api.generateRecommendation(farmId);
      onChanged && (await onChanged());
    } catch (err) {
      setError(err.message);
    } finally {
      setGenerating(false);
    }
  }

  const boxCls = (latest && BOX_STYLES[latest.risk_level]) || "border-line bg-canvas";

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">Spray-decision recommendation</h2>
        <button
          onClick={generate}
          disabled={generating}
          className="rounded-control border border-line bg-surface px-3 py-1.5 text-sm font-medium text-ink shadow-sm transition hover:bg-canvas disabled:opacity-50"
        >
          {generating ? "Generating…" : latest ? "Re-generate" : "Generate recommendation"}
        </button>
      </div>

      {error && <p className="text-sm text-risk-fg">{error}</p>}

      {latest ? (
        <>
          <NextActionCard action={latest.next_action} />

          <div className={`rounded-control border p-4 ${boxCls}`}>
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <RiskBadge level={latest.risk_level} />
              <span className="text-xs text-muted">
                generated {formatDate(latest.created_at)}
              </span>
            </div>
            <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-ink">
              {latest.recommendation_text}
            </pre>

            <AgronomistReview recommendation={latest} onUpdated={onChanged} />
          </div>
        </>
      ) : (
        <div className="rounded-control border border-dashed bg-canvas p-4 text-sm text-muted">
          No recommendation yet. Click{" "}
          <span className="font-medium">Generate recommendation</span> to review
          the farm&apos;s current sprays and scouting.
        </div>
      )}

    </div>
  );
}
