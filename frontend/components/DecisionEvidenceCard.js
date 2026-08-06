"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { formatArea, formatCost } from "@/lib/format";

// One labelled metric tile (same look as PilotEvidenceCard's).
function Metric({ label, value, hint }) {
  return (
    <div className="rounded-control border bg-surface p-3">
      <div className="text-xs text-muted">{label}</div>
      <div className="mt-0.5 text-lg font-semibold">{value}</div>
      {hint && <div className="text-[11px] text-muted">{hint}</div>}
    </div>
  );
}

// Pre-spray decision workflow metrics: decisions reviewed, sprays changed/delayed/
// avoided, conflicts caught, PCA acceptance, and the (assumption-based) review time.
// Demo/simulated decisions are excluded server-side; every caveat is shown.
export default function DecisionEvidenceCard({ farmId, country, area, refreshKey }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api
      .getDecisionEvidence(farmId)
      .then(setData)
      .catch((err) => setError(err.message));
  }, [farmId, refreshKey]);

  if (error) return <p className="text-sm text-risk-fg">{error}</p>;
  if (!data) return <p className="text-sm text-muted">Loading decision evidence…</p>;

  const o = data.outcomes || {};
  const acceptance =
    data.pca_acceptance_rate_pct != null ? `${data.pca_acceptance_rate_pct}%` : "—";

  return (
    <div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <Metric label="Decisions checked" value={data.decisions_checked} />
        <Metric
          label="Decisions PCA-reviewed"
          value={`${data.decisions_reviewed} / ${data.decisions_checked}`}
        />
        <Metric
          label="PCA acceptance rate"
          value={acceptance}
          hint="approved or edited, of reviewed"
        />
        <Metric
          label="Sprays changed / delayed / avoided"
          value={data.sprays_changed_delayed_or_avoided}
          hint={`${o.changed_product ?? 0} changed · ${o.delayed ?? 0} delayed · ${o.avoided ?? 0} avoided`}
        />
        <Metric
          label="Compliance conflicts caught"
          value={data.compliance_conflicts_caught}
          hint="critical PHI/REI conflicts, pre-application"
        />
        <Metric
          label="Est. chemical cost avoided"
          value={
            data.estimated_chemical_cost_avoided
              ? formatCost(data.estimated_chemical_cost_avoided, country)
              : "—"
          }
          hint={`entered application-cost estimates only${
            area != null ? ` · across ${formatArea(area, country)}` : ""
          } · yield impact not yet known/measured`}
        />
      </div>

      <p className="mt-2 text-xs text-muted">
        Est. review time: ~{data.estimated_review_minutes_saved} min.{" "}
        {data.review_minutes_assumption}
      </p>

      {/* Confirmed vs estimated — never combined into one score. */}
      {data.confirmed && (
        <div className="mt-3">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-muted">
            Confirmed (follow-up-backed)
          </h4>
          <div className="mt-1 grid grid-cols-2 gap-3 sm:grid-cols-3">
            <Metric
              label="Applications confirmed avoided"
              value={data.confirmed.applications_confirmed_avoided}
              hint={
                // Area is only shown with its unit. A refusal (mixed units) shows
                // the reason instead of a number — never a unitless total.
                data.confirmed.treated_area_confirmed_avoided === null
                  ? data.confirmed.treated_area_confirmed_avoided_note
                  : `${data.confirmed.treated_area_confirmed_avoided} ${
                      data.confirmed.treated_area_confirmed_avoided_unit ||
                      "(unit not recorded)"
                    } confirmed avoided`
              }
            />
            <Metric
              label="Rescue treatments (failures)"
              value={data.confirmed.confirmed_rescue_treatments}
              hint={
                data.confirmed.confirmed_rescue_cost
                  ? `rescue cost ${formatCost(data.confirmed.confirmed_rescue_cost, country)}`
                  : "reported plainly when they happen"
              }
            />
            <Metric
              label="Confirmed delay"
              value={
                data.confirmed.confirmed_delayed_decisions
                  ? `${data.confirmed.confirmed_delay_days_total} day(s)`
                  : "—"
              }
              hint={`${data.confirmed.confirmed_delayed_decisions} decision(s) with a dated later application`}
            />
            <Metric
              label="Confirmed gross spend avoided"
              value={formatCost(data.confirmed.confirmed_gross_spend_avoided, country)}
              hint="entered planned costs of confirmed-avoided applications"
            />
            <div
              className={`rounded-control border p-3 ${
                data.confirmed.confirmed_net_financial_result < 0
                  ? "border-risk-line bg-risk-bg"
                  : "bg-surface"
              }`}
            >
              <div className="text-xs text-muted">Confirmed net financial result</div>
              <div
                className={`mt-0.5 text-lg font-semibold ${
                  data.confirmed.confirmed_net_financial_result < 0 ? "text-risk-fg" : ""
                }`}
              >
                {formatCost(data.confirmed.confirmed_net_financial_result, country)}
              </div>
              <div className="text-[11px] text-muted">
                gross avoided − scouting − rescue; negatives shown as negatives
              </div>
            </div>
            <Metric
              label="Yield / quality coverage"
              value={`${
                (data.confirmed.yield_impact_counts?.neutral ?? 0) +
                (data.confirmed.yield_impact_counts?.positive ?? 0) +
                (data.confirmed.yield_impact_counts?.negative ?? 0)
              } known · ${data.confirmed.yield_impact_counts?.unknown ?? 0} unknown`}
              hint={`${data.confirmed.yield_impact_counts?.negative ?? 0} negative yield · ${
                data.confirmed.rejected_or_downgraded_count
              } rejected/downgraded — unknown stays unknown`}
            />
          </div>
          <p className="mt-1 text-[11px] text-muted">{data.confirmed.basis}</p>
        </div>
      )}

      {data.estimated && (
        <div className="mt-3">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-muted">
            Estimated (no follow-up yet — not confirmed)
          </h4>
          <div className="mt-1 grid grid-cols-2 gap-3 sm:grid-cols-3">
            <Metric
              label="Potential gross savings (unconfirmed)"
              value={formatCost(data.estimated.potential_gross_savings_unconfirmed, country)}
              hint={`${data.estimated.avoided_outcomes_without_follow_up} avoided outcome(s) still lacking follow-up`}
            />
            <Metric
              label="Planned application cost (all real decisions)"
              value={formatCost(data.estimated.planned_application_cost_total, country)}
              hint="entered estimates only"
            />
            <Metric
              label="Follow-up completion"
              value={
                data.follow_up?.follow_up_completion_rate_pct != null
                  ? `${data.follow_up.follow_up_completion_rate_pct}%`
                  : "—"
              }
              hint={`${data.follow_up?.follow_up_with_events ?? 0} of ${
                data.follow_up?.follow_up_required ?? 0
              } decisions requiring follow-up have events`}
            />
          </div>
          <p className="mt-1 text-[11px] text-muted">{data.estimated.basis}</p>
        </div>
      )}

      {data.not_calculated && (
        <ul className="mt-2 space-y-0.5 rounded bg-canvas px-3 py-2 text-[11px] text-muted">
          {Object.entries(data.not_calculated).map(([k, v]) => (
            <li key={k}>
              <span className="font-medium">{k.replace(/_/g, " ")}:</span> {v}
            </li>
          ))}
        </ul>
      )}

      <p className="mt-2 text-xs text-muted">
        Anonymized evidence export:{" "}
        <a
          className="font-medium underline underline-offset-2 hover:text-ink"
          href={api.exportUrl(`/farms/${farmId}/evidence-export`)}
          target="_blank"
          rel="noreferrer"
        >
          JSON
        </a>{" "}
        ·{" "}
        <a
          className="font-medium underline underline-offset-2 hover:text-ink"
          href={api.exportUrl(`/farms/${farmId}/export/evidence.csv`)}
        >
          CSV
        </a>{" "}
        (real records only; the farm appears as pilot-farm-{farmId})
      </p>

      {data.demo_decisions_checked > 0 && (
        <p className="mt-2 rounded bg-canvas px-3 py-2 text-xs text-muted">
          Simulated demo decisions on this farm: {data.demo_decisions_checked} (
          {Object.entries(data.demo_outcomes || {})
            .filter(([, n]) => n > 0)
            .map(([k, n]) => `${n} ${k.replace(/_/g, " ")}`)
            .join(", ") || "no outcome yet"}
          ) — visible in the decision queue but excluded from every number above.
        </p>
      )}

      {data.limitations?.length > 0 && (
        <ul className="mt-2 space-y-0.5 rounded bg-warn-bg px-3 py-2 text-[11px] text-warn-fg">
          {data.limitations.map((l, i) => (
            <li key={i}>• {l}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
