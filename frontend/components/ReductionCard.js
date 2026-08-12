"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useDemoTag } from "@/lib/farm-context";
import { Button } from "@/components/ui/button";
import { FormError } from "@/components/ui/field";
import { fieldClass } from "@/components/ui/input";

// Measured spray reduction vs. a grower/PCA-declared baseline. Honest by design:
// no baseline -> no number; low-confidence/early-window numbers are clearly marked
// "illustrative" and never shown as a headline result. `refreshKey` re-fetches.
export default function ReductionCard({ farmId, refreshKey }) {
  // Demo farms only accept simulated records (the backend 409s on mixing).
  const demoTag = useDemoTag(farmId);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [showForm, setShowForm] = useState(false);

  // Baseline form state
  const [method, setMethod] = useState("stated_cadence");
  const [cadenceDays, setCadenceDays] = useState("");
  const [seasonCount, setSeasonCount] = useState("");
  const [program, setProgram] = useState("weekly");
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [declaredBy, setDeclaredBy] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(() => {
    api
      .getReduction(farmId)
      .then(setData)
      .catch((err) => setError(err.message));
  }, [farmId]);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  async function saveBaseline(e) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    const payload = {
      method,
      data_source: "grower_interview",
      data_confidence: "user_provided",
      ...demoTag,
      declared_by: declaredBy || null,
    };
    if (method === "stated_cadence") {
      if (cadenceDays) payload.cadence_days = Number(cadenceDays);
      else if (seasonCount) payload.season_spray_count = Number(seasonCount);
    } else if (method === "calendar_program") {
      payload.calendar_program = program;
    } else if (method === "prior_period") {
      payload.baseline_period_start = periodStart || null;
      payload.baseline_period_end = periodEnd || null;
    }
    try {
      await api.setSprayBaseline(farmId, payload);
      setShowForm(false);
      load();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  if (error) return <FormError>{error}</FormError>;
  if (!data) return <p className="text-sm text-muted">Loading reduction…</p>;

  const pct = data.reduction_pct;
  const hasNumber = data.has_baseline && pct != null;
  const headline = data.is_headline_safe;

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-end gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          aria-expanded={showForm}
          onClick={() => setShowForm((v) => !v)}
        >
          {data.has_baseline ? "Edit baseline" : "Set baseline"}
        </Button>
      </div>

      {!data.has_baseline && (
        <p className="rounded bg-canvas px-3 py-2 text-sm text-muted">
          No baseline set yet — declare the grower&apos;s normal spray cadence (or a pre-Lumos
          period) to measure reduction. Until then this stays a descriptive picture, not a
          before/after result.
        </p>
      )}

      {hasNumber && (
        <div className="flex flex-wrap items-end gap-4">
          <div>
            <div
              className={`text-2xl font-semibold ${
                pct > 0 ? "text-ok-fg" : pct < 0 ? "text-risk-fg" : "text-muted"
              }`}
            >
              {pct > 0 ? "−" : pct < 0 ? "+" : ""}
              {Math.abs(pct).toFixed(0)}%
            </div>
            <div className="text-xs text-muted">
              {pct >= 0 ? "fewer sprays vs. baseline" : "more sprays vs. baseline"}
            </div>
          </div>
          <div className="text-sm text-ink">
            <div>
              <strong>{data.actual_sprays}</strong> logged vs.{" "}
              <strong>{data.baseline_expected_sprays}</strong> baseline
              {data.observed_window_days ? ` over ~${data.observed_window_days} days` : ""}
            </div>
            <div className="text-xs text-muted">
              Baseline: {String(data.baseline_method).replace(/_/g, " ")} ·{" "}
              {String(data.baseline_confidence).replace(/_/g, " ")}
            </div>
          </div>
        </div>
      )}

      {hasNumber && !headline && (
        <p className="mt-2 inline-block rounded bg-warn-bg px-2 py-0.5 text-[11px] font-medium text-warn-fg">
          Illustrative — not yet a headline-safe result
        </p>
      )}

      {data.reduction_statement && (
        <p className="mt-3 text-sm text-ink">{data.reduction_statement}</p>
      )}

      {data.confidence_caveats?.length > 0 && (
        <ul className="mt-2 space-y-1 text-[11px] text-muted">
          {data.confidence_caveats.map((c, i) => (
            <li key={i} className="flex gap-1">
              <span>•</span>
              <span>{c}</span>
            </li>
          ))}
        </ul>
      )}

      {showForm && (
        <form onSubmit={saveBaseline} className="mt-4 space-y-3 rounded-control border bg-canvas p-3">
          <label className="block text-xs font-medium text-muted">
            Baseline method
            <select
              value={method}
              onChange={(e) => setMethod(e.target.value)}
              className={`mt-1 ${fieldClass}`}
            >
              <option value="stated_cadence">Stated cadence (most common)</option>
              <option value="prior_period">Prior period (grower&apos;s own history)</option>
              <option value="calendar_program">Calendar program (lowest rigor)</option>
            </select>
          </label>

          {method === "stated_cadence" && (
            <div className="grid grid-cols-2 gap-2">
              <label className="block text-xs text-muted">
                Sprays every N days
                <input
                  type="number"
                  min="1"
                  value={cadenceDays}
                  onChange={(e) => setCadenceDays(e.target.value)}
                  placeholder="e.g. 7"
                  className={`mt-1 ${fieldClass}`}
                />
              </label>
              <label className="block text-xs text-muted">
                or sprays per season
                <input
                  type="number"
                  min="1"
                  value={seasonCount}
                  onChange={(e) => setSeasonCount(e.target.value)}
                  placeholder="e.g. 20"
                  className={`mt-1 ${fieldClass}`}
                />
              </label>
            </div>
          )}

          {method === "calendar_program" && (
            <label className="block text-xs text-muted">
              Program
              <select
                value={program}
                onChange={(e) => setProgram(e.target.value)}
                className={`mt-1 ${fieldClass}`}
              >
                <option value="weekly">Weekly</option>
                <option value="every_10_days">Every 10 days</option>
                <option value="biweekly">Biweekly</option>
                <option value="every_3_weeks">Every 3 weeks</option>
                <option value="monthly">Monthly</option>
              </select>
            </label>
          )}

          {method === "prior_period" && (
            <div className="grid grid-cols-2 gap-2">
              <label className="block text-xs text-muted">
                Baseline start
                <input
                  type="date"
                  value={periodStart}
                  onChange={(e) => setPeriodStart(e.target.value)}
                  className={`mt-1 ${fieldClass}`}
                />
              </label>
              <label className="block text-xs text-muted">
                Baseline end
                <input
                  type="date"
                  value={periodEnd}
                  onChange={(e) => setPeriodEnd(e.target.value)}
                  className={`mt-1 ${fieldClass}`}
                />
              </label>
            </div>
          )}

          <label className="block text-xs text-muted">
            Declared by (grower / PCA)
            <input
              value={declaredBy}
              onChange={(e) => setDeclaredBy(e.target.value)}
              placeholder="e.g. PCA Jane Doe"
              className={`mt-1 ${fieldClass}`}
            />
          </label>

          <Button type="submit" disabled={saving}>
            {saving ? "Saving…" : "Save baseline"}
          </Button>
        </form>
      )}
    </div>
  );
}
