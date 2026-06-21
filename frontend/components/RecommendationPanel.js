"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import RiskBadge from "./RiskBadge";
import { formatDate } from "@/lib/format";

const BOX_STYLES = {
  low: "border-green-200 bg-green-50",
  moderate: "border-amber-200 bg-amber-50",
  elevated: "border-red-200 bg-red-50",
};

// Shows the latest recommendation and lets the user generate a fresh one.
export default function RecommendationPanel({ farmId, latest, onGenerated }) {
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState(null);

  async function generate() {
    setGenerating(true);
    setError(null);
    try {
      await api.generateRecommendation(farmId);
      onGenerated && (await onGenerated());
    } catch (err) {
      setError(err.message);
    } finally {
      setGenerating(false);
    }
  }

  const boxCls = (latest && BOX_STYLES[latest.risk_level]) || "border-gray-200 bg-gray-50";

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">🧭 Spray-decision recommendation</h2>
        <button
          onClick={generate}
          disabled={generating}
          className="rounded-md bg-leaf px-3.5 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-green-700 disabled:opacity-50"
        >
          {generating ? "Generating…" : latest ? "Re-generate" : "Generate recommendation"}
        </button>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}

      {latest ? (
        <div className={`rounded-lg border p-4 ${boxCls}`}>
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <RiskBadge level={latest.risk_level} />
            <span className="rounded-full bg-white/70 px-2 py-0.5 text-xs text-gray-600">
              status: {latest.agronomist_status}
            </span>
            <span className="text-xs text-gray-500">
              generated {formatDate(latest.created_at)}
            </span>
          </div>
          <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-gray-800">
            {latest.recommendation_text}
          </pre>
        </div>
      ) : (
        <div className="rounded-lg border border-dashed bg-gray-50 p-4 text-sm text-gray-500">
          No recommendation yet. Click{" "}
          <span className="font-medium">Generate recommendation</span> to review
          the farm&apos;s current sprays and scouting.
        </div>
      )}
    </div>
  );
}
