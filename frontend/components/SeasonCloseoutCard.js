"use client";

import {
  Coins,
  Scale,
  ShieldCheck,
  Sprout,
  TriangleAlert,
  Wallet,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import SectionCard from "@/components/SectionCard";
import StatTile from "@/components/StatTile";
import ProgressBar from "@/components/ProgressBar";
import Callout from "@/components/Callout";
import { COST_CATEGORY_LABELS } from "@/lib/labels";
import { VALUE_TIER_TONES, tone } from "@/lib/tones";

// The season's economics: cost, yield, revenue, and the value attributable to what
// Lumos recommended.
//
// Two rules govern everything this component renders.
//
// A METRIC THAT COULD NOT BE COMPUTED SHOWS "Not calculated" AND ITS REASON. The API
// omits the `value` key entirely on a refusal rather than nulling it, so there is no
// path by which this file can print a `0` for a gap. "0 revenue" reads as a season
// that earned nothing, which is the opposite of "nobody has entered the settlement".
//
// EVERY SENTENCE EXPLAINING A NUMBER IS THE SERVER'S. `basis_text` is rendered
// verbatim and this component writes no wording of its own about how a figure was
// reached — same rule as DataReadinessCard, so the phrasing has one home.

function money(amount, currency) {
  if (amount === null || amount === undefined) return null;
  const sign = amount < 0 ? "−" : "";
  const body = Math.abs(amount).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return `${sign}${currency ? `${currency} ` : ""}${body}`;
}

function quantity(amount, unit) {
  if (amount === null || amount === undefined) return null;
  const body = amount.toLocaleString(undefined, { maximumFractionDigits: 2 });
  return unit ? `${body} ${unit}` : body;
}

const NOT_CALCULATED = "Not calculated";

// A metric tile that knows the difference between a figure and a refusal.
function MetricTile({ label, metric, render, hint }) {
  if (!metric) return null;
  if (metric.not_calculated) {
    return <StatTile label={label} value={NOT_CALCULATED} hint={metric.reason} />;
  }
  return <StatTile label={label} value={render(metric) ?? "—"} hint={hint || metric.basis_text} />;
}

// A per-area figure carries two renderings of one fact: the grower's own unit and
// hectares. Neither is more true; only one is the number they will recognise.
function RateTile({ label, metric, currency, unit }) {
  if (!metric) return null;
  if (metric.not_calculated) {
    return <StatTile label={label} value={NOT_CALCULATED} hint={metric.reason} />;
  }
  const isMoney = unit === "money";
  const primary =
    metric.per_display_unit !== undefined
      ? `${isMoney ? money(metric.per_display_unit, currency) : quantity(metric.per_display_unit, metric.unit)} / ${metric.display_unit}`
      : `${isMoney ? money(metric.per_hectare, currency) : quantity(metric.per_hectare, metric.unit)} / ha`;
  const secondary =
    metric.per_display_unit !== undefined
      ? `${isMoney ? money(metric.per_hectare, currency) : quantity(metric.per_hectare, metric.unit)} per hectare. ${metric.basis_text || ""}`
      : metric.basis_text;
  return <StatTile label={label} value={primary} hint={secondary} />;
}

function TierTile({ tierKey, block, currency, icon: Icon, hint }) {
  const t = tone(VALUE_TIER_TONES[tierKey]);
  return (
    <div className={`rounded-control border p-3 ${t.box}`}>
      <div className="flex items-center gap-2">
        <Icon className={`h-4 w-4 ${t.icon}`} aria-hidden />
        <span className={`text-meta font-medium ${t.text}`}>
          {tierKey === "verified" ? "Verified value" : "Estimated value"}
        </span>
      </div>
      <div className="tabular mt-1 text-[22px] font-semibold leading-7 text-ink">
        {money(block?.total, currency) ?? "—"}
      </div>
      <div className="mt-0.5 text-[11px] leading-4 text-muted">
        {block?.item_count ?? 0} decision{(block?.item_count ?? 0) === 1 ? "" : "s"} · {hint}
      </div>
    </div>
  );
}

export default function SeasonCloseoutCard({ closeout }) {
  if (!closeout) return null;
  const { metrics, lumos_value: lumos, completeness, currency } = closeout;
  const contribution = metrics.revenue_minus_recorded_costs;
  const coverage = contribution?.cost_coverage;
  const categories = Object.entries(metrics.costs?.by_cost_category || {});

  return (
    <div className="space-y-4">
      {closeout.is_simulated && (
        <Callout tone="neutral">
          Simulated demo records. These figures illustrate how the season&apos;s
          economics are assembled and are not money anyone earned or spent.
        </Callout>
      )}

      {/* ------------------------------------------------- the headline three */}
      <SectionCard
        title="Season economics"
        size="section"
        icon={<Coins className="h-4 w-4 text-muted" aria-hidden />}
        description="Built only from records entered on this crop cycle. Farm-record economics, not accounting."
      >
        <div className="grid gap-3 sm:grid-cols-3">
          <MetricTile
            label="Revenue (net of deductions)"
            metric={metrics.revenue}
            render={(m) => money(m.net, currency)}
          />
          <MetricTile
            label="Recorded costs"
            metric={{ ...metrics.costs, basis_text: metrics.costs?.note }}
            render={(m) => money(m.total, currency)}
          />
          <MetricTile
            label="Revenue minus recorded costs"
            metric={contribution}
            render={(m) => money(m.value, currency)}
          />
        </div>

        {/* The coverage statement never travels separately from the figure above
            it. An incompletely-costed season must not be able to read as earnings. */}
        {coverage && (
          <div className="mt-3">
            <Callout tone={coverage.complete ? "good" : "warn"}>
              {coverage.complete ? (
                <>
                  Every recorded application and operation on this season carries a
                  cost. That is not a guarantee the season is fully costed — only that
                  nothing recorded is missing one.
                </>
              ) : (
                <>
                  <strong>
                    {coverage.applications_without_cost + coverage.operations_without_cost}{" "}
                    recorded record(s) carry no cost
                  </strong>{" "}
                  ({coverage.applications_without_cost} application(s),{" "}
                  {coverage.operations_without_cost} operation(s)) and are excluded, so
                  the true cost of this season is higher than the figure shown. This is
                  not profit.
                </>
              )}
            </Callout>
          </div>
        )}

        {metrics.revenue?.gross !== undefined && (
          <dl className="mt-3 grid gap-x-4 gap-y-1 text-[11px] text-muted sm:grid-cols-3">
            <div className="flex justify-between gap-2">
              <dt>Gross settlement value</dt>
              <dd className="tabular text-ink">{money(metrics.revenue.gross, currency)}</dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt>Buyer deductions</dt>
              <dd className="tabular text-ink">
                {money(metrics.revenue.deductions, currency)}
              </dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt>Net to the farm</dt>
              <dd className="tabular text-ink">{money(metrics.revenue.net, currency)}</dd>
            </div>
          </dl>
        )}
        {metrics.revenue?.basis_text && (
          <p className="mt-1 text-[11px] leading-4 text-muted">
            {metrics.revenue.basis_text}
          </p>
        )}
      </SectionCard>

      {/* --------------------------------------------------- yield and per-area */}
      <SectionCard
        title="Yield and per-area"
        size="section"
        icon={<Sprout className="h-4 w-4 text-muted" aria-hidden />}
        description="Recorded harvest weight, normalised through exact unit factors. Packaging units are refused, never converted."
      >
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <MetricTile
            label="Harvested yield"
            metric={metrics.harvested_yield}
            render={(m) => quantity(m.value, m.unit)}
          />
          <MetricTile
            label="Planted area"
            metric={metrics.planted_area}
            render={(m) =>
              m.display_area != null
                ? quantity(m.display_area, m.display_area_unit)
                : quantity(m.value, m.unit)
            }
          />
          <RateTile label="Yield per area" metric={metrics.yield_per_area} />
          <RateTile
            label="Recorded cost per area"
            metric={metrics.cost_per_area}
            currency={currency}
            unit="money"
          />
        </div>
        <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <RateTile
            label="Revenue per area"
            metric={metrics.revenue_per_area}
            currency={currency}
            unit="money"
          />
          <MetricTile
            label="Recorded cost per unit"
            metric={metrics.cost_per_yield_unit}
            render={(m) => `${money(m.value, "")}${m.unit ? ` ${m.unit}` : ""}`}
          />
          <MetricTile
            label="Realised price per unit"
            metric={metrics.realised_price_per_yield_unit}
            render={(m) => `${money(m.value, "")}${m.unit ? ` ${m.unit}` : ""}`}
          />
        </div>
      </SectionCard>

      {/* --------------------------------------------------- cost breakdown */}
      {categories.length > 0 && (
        <SectionCard
          title="Where the recorded cost went"
          size="section"
          icon={<Scale className="h-4 w-4 text-muted" aria-hidden />}
          description="A grouping of costs that were actually entered — not an allocation, and not a chart of accounts."
        >
          <ul className="space-y-1">
            {categories
              .sort((a, b) => b[1] - a[1])
              .map(([key, amount]) => {
                const share = metrics.costs.total
                  ? Math.round((amount / metrics.costs.total) * 100)
                  : 0;
                return (
                  <li key={key} className="flex items-center gap-3 text-sm">
                    <span className="w-44 shrink-0 truncate text-ink">
                      {COST_CATEGORY_LABELS[key] || key}
                    </span>
                    <ProgressBar
                      ratio={metrics.costs.total ? amount / metrics.costs.total : 0}
                      tone={key === "uncategorised" ? "neutral" : "good"}
                      className="flex-1"
                    />
                    <span className="tabular w-28 shrink-0 text-right text-ink">
                      {money(amount, currency)}
                    </span>
                    <span className="tabular w-10 shrink-0 text-right text-[11px] text-muted">
                      {share}%
                    </span>
                  </li>
                );
              })}
          </ul>
        </SectionCard>
      )}

      {/* ------------------------------------------------------- Lumos value */}
      <SectionCard
        title="Value attributable to Lumos"
        size="section"
        icon={<ShieldCheck className="h-4 w-4 text-muted" aria-hidden />}
        description="What the recommendations Lumos documented were worth — never a share of the season's revenue."
      >
        <div className="grid gap-3 sm:grid-cols-2">
          <TierTile
            tierKey="verified"
            block={lumos.verified}
            currency={lumos.currency || currency}
            icon={ShieldCheck}
            hint="backed by recorded follow-up evidence"
          />
          <TierTile
            tierKey="estimated"
            block={lumos.estimated}
            currency={lumos.currency || currency}
            icon={Wallet}
            hint="recorded outcome, not corroborated yet"
          />
        </div>
        {lumos.not_calculated_count > 0 && (
          <p className="mt-2 text-[11px] leading-4 text-muted">
            {lumos.not_calculated_count} decision(s) carry no figure at all — each one
            says why in the value ledger.
          </p>
        )}
        <p className="mt-2 text-[11px] leading-4 text-muted">{lumos.basis_text}</p>
      </SectionCard>

      {/* ----------------------------------------------------- completeness */}
      <SectionCard
        title="What is missing"
        size="section"
        // The description deliberately does NOT restate the server's `basis_text`
        // below — it said the same sentence twice on screen.
        icon={<TriangleAlert className="h-4 w-4 text-muted" aria-hidden />}
        description="Why the figures above are less than the whole picture."
        action={
          <Badge variant={completeness.gap_count === 0 ? "green" : "amber"}>
            {completeness.gap_count === 0
              ? "No named gaps"
              : `${completeness.gap_count} gap${completeness.gap_count === 1 ? "" : "s"}`}
          </Badge>
        }
      >
        {completeness.gaps.length === 0 ? (
          <p className="text-sm text-muted">{completeness.basis_text}</p>
        ) : (
          <>
            <ul className="space-y-2">
              {completeness.gaps.map((gap) => (
                <li
                  key={gap.code}
                  className="rounded-control border border-line bg-subtle/40 p-2.5"
                >
                  <p className="text-sm text-ink">{gap.detail}</p>
                  <p className="mt-0.5 text-[11px] leading-4 text-muted">{gap.fix}</p>
                </li>
              ))}
            </ul>
            <p className="mt-2 text-[11px] leading-4 text-muted">
              {completeness.basis_text}
            </p>
          </>
        )}
      </SectionCard>

      <p className="text-[11px] leading-4 text-muted">{closeout.disclaimer}</p>
    </div>
  );
}
