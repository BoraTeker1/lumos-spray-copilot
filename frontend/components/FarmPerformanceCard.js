"use client";

import { ArrowDown, ArrowUp, Minus } from "lucide-react";
import { HEADLINE_PERFORMANCE_METRICS } from "@/lib/labels";
import { tone, TREND_TONES } from "@/lib/tones";

// How this farm has actually done, season over season.
//
// There is no overall score and no peer benchmark, deliberately — see
// app/farm_performance.py. The story is the individual metrics and the movement
// between two seasons that are genuinely comparable.
//
// A trend's DIRECTION is a fact; whether it is good news is `higher_is_better`, a
// property the server declares per metric. That is why a falling cost per kilo
// renders as good rather than as a red arrow.
//
// THE VALUES AND THE TREND ARE NOT ALWAYS THE SAME SEASON. The server prefers two
// CLOSED seasons for a comparison, because a season still in progress has recorded
// only part of its costs and flatters every cost metric. So while the current season
// is open, the values shown are this season's and the trend is between the two
// closed ones before it — and those must never be printed on the same line, which
// would read as "this season is up 32%" when the 32% is about two earlier seasons.

function trendTone(trend) {
  if (!trend || trend.not_calculated || trend.direction === "unchanged") {
    return TREND_TONES.neutral;
  }
  if (trend.higher_is_better == null) return TREND_TONES.neutral;
  const favourable =
    trend.direction === "up" ? trend.higher_is_better : !trend.higher_is_better;
  return favourable ? TREND_TONES.favourable : TREND_TONES.unfavourable;
}

function TrendChip({ trend, suffix }) {
  if (!trend || trend.not_calculated) return null;
  const t = tone(trendTone(trend));
  const Icon =
    trend.direction === "up"
      ? ArrowUp
      : trend.direction === "down"
        ? ArrowDown
        : Minus;
  return (
    <span className={`inline-flex items-center gap-1 text-xs ${t.text}`}>
      <Icon className="h-3 w-3" />
      {trend.delta_pct != null
        ? `${trend.delta_pct > 0 ? "+" : ""}${trend.delta_pct}%`
        : `${trend.delta > 0 ? "+" : ""}${trend.delta}`}
      {suffix && <span className="text-muted">{suffix}</span>}
    </span>
  );
}

function MetricRow({ label, metric, trend, trendSuffix }) {
  // The abstention rule: "Not calculated" plus the reason, never a 0 and never blank.
  if (!metric || metric.not_calculated) {
    return (
      <div className="py-2">
        <div className="text-xs text-muted">{label}</div>
        <div className="text-sm text-muted">Not calculated</div>
        {metric?.reason && (
          <div className="text-[11px] text-muted">{metric.reason}</div>
        )}
      </div>
    );
  }
  const value = Number(metric.value).toLocaleString(undefined, {
    maximumFractionDigits: 2,
  });
  return (
    <div className="py-2">
      <div className="text-xs text-muted">{label}</div>
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="text-lg font-semibold text-ink">{value}</span>
        {metric.unit && <span className="text-xs text-muted">{metric.unit}</span>}
        <TrendChip trend={trend} suffix={trendSuffix} />
      </div>
    </div>
  );
}

export default function FarmPerformanceCard({ performance, metrics }) {
  if (!performance) return null;

  const seasons = performance.seasons || [];
  if (!seasons.length) {
    return (
      <p className="text-sm text-muted">
        No crop cycle has been recorded for this farm yet. Performance appears once a
        season carries records — and becomes a comparison once a second season closes.
      </p>
    );
  }

  const latest = seasons[0];
  const keys = metrics || HEADLINE_PERFORMANCE_METRICS;
  const labels = performance.metric_labels || {};
  const comparison = performance.trend_comparison;

  // Only attach a trend to a value when the trend is ABOUT that value's season.
  const trendIsAboutLatest =
    comparison && comparison.later_crop_cycle_id === latest.crop_cycle_id;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
        <span className="font-medium text-ink">
          {latest.season_label || latest.season_year}
        </span>
        {!latest.is_closed && <span>· season to date</span>}
        <span>·</span>
        <span>
          {performance.season_count} season(s) on record,{" "}
          {performance.closed_season_count} closed
        </span>
      </div>

      <div className="grid gap-x-6 sm:grid-cols-2">
        {keys.map((key) => (
          <MetricRow
            key={key}
            label={labels[key] || key}
            metric={latest.metrics?.[key]}
            trend={trendIsAboutLatest ? performance.trends?.[key] : null}
            trendSuffix={
              trendIsAboutLatest
                ? `vs ${comparison.earlier_season}`
                : undefined
            }
          />
        ))}
      </div>

      {performance.season_count < 2 && (
        <p className="text-xs text-muted">
          Season-over-season comparison appears once a second crop cycle carries
          records. One season is a reading, not a trend.
        </p>
      )}

      {/* The comparison lives in its own block whenever it is about EARLIER seasons
          than the ones shown above — printing a 2025-vs-2024 delta beside a 2026
          figure would read as a claim about 2026. */}
      {comparison && !trendIsAboutLatest && (
        <div className="rounded-md border border-line bg-surface-2 p-3">
          <div className="text-xs font-medium text-ink">
            Last completed comparison: {comparison.later_season} vs{" "}
            {comparison.earlier_season}
          </div>
          <p className="mt-0.5 text-[11px] text-muted">
            The season above is still in progress, so it is not compared: a partial
            season has recorded only part of its costs and would look better than it
            is. These are the two most recent closed seasons.
          </p>
          <div className="mt-2 grid gap-x-6 sm:grid-cols-2">
            {keys.map((key) => {
              const trend = performance.trends?.[key];
              if (!trend || trend.not_calculated) return null;
              return (
                <div
                  key={key}
                  className="flex items-baseline justify-between gap-2 py-0.5"
                >
                  <span className="text-xs text-muted">{labels[key] || key}</span>
                  <TrendChip trend={trend} />
                </div>
              );
            })}
          </div>
        </div>
      )}

      {comparison?.compares_a_season_in_progress && (
        <p className="text-xs text-muted">
          This comparison includes a season still in progress, so its costs and
          harvest are only what has been recorded so far.
        </p>
      )}
      <p className="text-[11px] text-muted">{performance.comparison_basis}</p>
    </div>
  );
}
