"use client";

import { useState } from "react";
import { ChevronDown, Coins, ShieldCheck, Sprout, Wallet } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import SectionCard from "@/components/SectionCard";
import EmptyState from "@/components/EmptyState";
import {
  BLOCK_OUTCOME_TYPE_LABELS,
  DECISION_OUTCOME_LABELS,
  OPERATION_TYPE_LABELS,
  RECORDED_OUTCOME_LABELS,
  REVIEW_STATE_LABELS,
  VALUE_SOURCE_LABELS,
  VALUE_TIER_LABELS,
} from "@/lib/labels";
import {
  DECISION_OUTCOME_TONES,
  RECORDED_OUTCOME_TONES,
  VALUE_TIER_TONES,
  tone,
} from "@/lib/tones";
import { formatDate } from "@/lib/format";

// The Lumos Value Ledger: recommendation → action → outcome → attributable value.
//
// Every figure on this card is server-computed and arrives with the sentence that
// explains its own arithmetic (`basis`), rendered verbatim — this component writes
// no wording of its own about how a number was reached. A row with nothing
// attributable renders its reason, never a 0: the API omits the `amount` key
// entirely rather than nulling it, precisely so a template cannot turn a gap into
// a zero.

function money(amount, currency) {
  if (amount === null || amount === undefined) return null;
  const sign = amount < 0 ? "−" : "";
  const body = Math.abs(amount).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return `${sign}${currency ? `${currency} ` : ""}${body}`;
}

function TierTotal({ tierKey, block, currency, icon: Icon, hint }) {
  const t = tone(VALUE_TIER_TONES[tierKey]);
  const sources = Object.entries(block.by_source || {});
  return (
    <div className={`rounded-lg border p-3 ${t.box}`}>
      <div className="flex items-center gap-2">
        <Icon className={`h-4 w-4 ${t.icon}`} aria-hidden />
        <span className={`text-meta font-medium ${t.text}`}>
          {VALUE_TIER_LABELS[tierKey]}
        </span>
      </div>
      <div className="tabular mt-1 text-[22px] font-semibold leading-7 text-ink">
        {money(block.total, currency) ?? "—"}
      </div>
      <div className="mt-0.5 text-[11px] leading-4 text-muted">{hint}</div>
      {sources.length > 0 && (
        <ul className="mt-2 space-y-0.5 border-t border-line/60 pt-2">
          {sources.map(([source, amount]) => (
            <li key={source} className="flex justify-between gap-2 text-[11px] text-muted">
              <span className="truncate">
                {VALUE_SOURCE_LABELS[source] || source}
              </span>
              <span className="tabular shrink-0 text-ink">{money(amount, currency)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// One row of the loop. Collapsed it answers what was recommended, what was done and
// what it was worth; expanded it shows the arithmetic and the records behind it.
function LedgerRow({ item, currency }) {
  const [open, setOpen] = useState(false);
  const t = tone(VALUE_TIER_TONES[item.tier]);
  const hasAmount = item.amount !== undefined && item.amount !== null;

  return (
    <li className="border-t border-line first:border-t-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-start gap-3 px-1 py-3 text-left hover:bg-subtle/50"
      >
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="truncate text-sm font-medium text-ink">{item.label}</span>
            {item.verdict && (
              <Badge variant={tone(DECISION_OUTCOME_TONES[item.verdict]).badge}>
                {DECISION_OUTCOME_LABELS[item.verdict] || item.verdict}
              </Badge>
            )}
          </div>
          {/* recommendation → action → outcome, in one line */}
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-muted">
            {item.review_state && <span>{REVIEW_STATE_LABELS[item.review_state]}</span>}
            {item.action && (
              <>
                <span aria-hidden>→</span>
                <span className={tone(RECORDED_OUTCOME_TONES[item.action] || "neutral").text}>
                  {RECORDED_OUTCOME_LABELS[item.action] || item.action}
                </span>
              </>
            )}
            {item.occurred_on && <span>· {formatDate(item.occurred_on)}</span>}
          </div>
        </div>
        <div className="shrink-0 text-right">
          <div className={`tabular text-sm font-semibold ${hasAmount ? "text-ink" : "text-muted"}`}>
            {hasAmount ? money(item.amount, item.currency || currency) : "Not calculated"}
          </div>
          {/* The tier badge only earns its place when there is a figure to qualify.
              On an uncalculated row it would just repeat the words above it. */}
          {hasAmount && (
            <Badge variant={t.badge} className="mt-1">
              {VALUE_TIER_LABELS[item.tier]}
            </Badge>
          )}
        </div>
        <ChevronDown
          className={`mt-1 h-4 w-4 shrink-0 text-muted transition-transform ${open ? "rotate-180" : ""}`}
          aria-hidden
        />
      </button>

      {open && (
        <div className="space-y-2 px-1 pb-3 pl-1 text-[11px] leading-4 text-muted">
          {/* The server-owned explanation, verbatim. */}
          <p className="text-ink">{item.basis || item.not_calculated_reason}</p>
          {item.action_reason && (
            <p>
              <span className="font-medium text-ink">Reason recorded:</span>{" "}
              {item.action_reason}
            </p>
          )}
          {item.informational && (
            <p>
              <span className="font-medium text-ink">
                Shown, not counted
                {item.informational.delta !== undefined &&
                  `: ${money(item.informational.delta, currency)}`}
              </span>{" "}
              — {item.informational.note}
            </p>
          )}
          {item.evidence?.length > 0 && (
            <div>
              <span className="font-medium text-ink">Evidence:</span>
              <ul className="mt-0.5 space-y-0.5">
                {item.evidence.map((ref) => (
                  <li key={ref} className="font-mono text-[10px]">
                    {ref}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </li>
  );
}

export default function ValueLedgerCard({ ledger, cycles = [], activeCycleId, onSelectCycle }) {
  const [showAll, setShowAll] = useState(false);
  if (!ledger) return null;

  const currency = ledger.currency;
  const items = ledger.items || [];
  const counted = items.filter((i) => i.tier !== "not_calculated");
  const visible = showAll ? items : items.slice(0, 6);
  const costs = ledger.season_costs || {};
  const outcomes = ledger.season_outcomes || [];

  return (
    <SectionCard
      title="Value ledger"
      size="section"
      icon={<Coins className="h-4 w-4 text-muted" aria-hidden />}
      description="What Lumos recommended, what was done, what happened, and how much of it is money."
      action={
        cycles.length > 0 && (
          <select
            value={activeCycleId ?? ""}
            onChange={(e) => onSelectCycle?.(e.target.value ? Number(e.target.value) : null)}
            className="rounded-md border border-line bg-surface px-2 py-1 text-meta text-ink"
            aria-label="Season"
          >
            <option value="">All seasons</option>
            {cycles.map((c) => (
              <option key={c.id} value={c.id}>
                {c.season_label || `${c.season_year} ${c.crop}`}
              </option>
            ))}
          </select>
        )
      }
    >
      {ledger.is_simulated && (
        <p className="mb-3 rounded-md border border-draft-line bg-draft-bg px-3 py-2 text-[11px] leading-4 text-draft-fg">
          Simulated demo records. These figures illustrate how the ledger works and are
          not value anyone created.
        </p>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        <TierTotal
          tierKey="verified"
          block={ledger.verified}
          currency={currency}
          icon={ShieldCheck}
          hint="Backed by recorded follow-up evidence or a placed order."
        />
        <TierTotal
          tierKey="estimated"
          block={ledger.estimated}
          currency={currency}
          icon={Wallet}
          hint="Recorded outcome, not corroborated yet."
        />
      </div>
      {/* There is deliberately no combined figure — see the server's totals_note. */}
      <p className="mt-2 text-[11px] leading-4 text-muted">{ledger.totals_note}</p>

      <div className="mt-4">
        <div className="flex items-baseline justify-between gap-2">
          <h4 className="text-meta font-medium text-ink">Recommendation history</h4>
          <span className="text-[11px] text-muted">
            {counted.length} of {items.length} carry a figure
          </span>
        </div>
        {items.length === 0 ? (
          <EmptyState
            title="No decisions in this season yet"
            description="Run a pre-spray check and record its outcome — the ledger fills in from the decision loop."
          />
        ) : (
          <>
            <ul className="mt-1">
              {visible.map((item) => (
                <LedgerRow
                  key={`${item.kind}-${item.reference_id}`}
                  item={item}
                  currency={currency}
                />
              ))}
            </ul>
            {items.length > visible.length && (
              <Button
                variant="ghost"
                size="sm"
                className="mt-2"
                onClick={() => setShowAll(true)}
              >
                Show {items.length - visible.length} more
              </Button>
            )}
          </>
        )}
      </div>

      <div className="mt-4 grid gap-3 border-t border-line pt-4 sm:grid-cols-2">
        <div>
          <h4 className="text-meta font-medium text-ink">Recorded season costs</h4>
          <div className="tabular mt-1 text-lg font-semibold text-ink">
            {money(costs.total, currency) ?? "—"}
          </div>
          <ul className="mt-1 space-y-0.5 text-[11px] text-muted">
            <li className="flex justify-between gap-2">
              <span>Applications ({costs.applications_counted ?? 0})</span>
              <span className="tabular text-ink">{money(costs.applications, currency)}</span>
            </li>
            {Object.entries(costs.operations_by_type || {}).map(([type, amount]) => (
              <li key={type} className="flex justify-between gap-2">
                <span>{OPERATION_TYPE_LABELS[type] || type}</span>
                <span className="tabular text-ink">{money(amount, currency)}</span>
              </li>
            ))}
          </ul>
          {costs.note && <p className="mt-1 text-[11px] leading-4 text-muted">{costs.note}</p>}
        </div>

        <div>
          <h4 className="flex items-center gap-1.5 text-meta font-medium text-ink">
            <Sprout className="h-3.5 w-3.5 text-muted" aria-hidden />
            Recorded outcomes
          </h4>
          {outcomes.length === 0 ? (
            <p className="mt-1 text-[11px] leading-4 text-muted">
              Not calculated — no harvest outcome has been recorded for this season.
            </p>
          ) : (
            <ul className="mt-1 space-y-0.5 text-[11px] text-muted">
              {outcomes.map((o) => (
                <li key={`${o.outcome_type}-${o.unit}`} className="flex justify-between gap-2">
                  <span>
                    {BLOCK_OUTCOME_TYPE_LABELS[o.outcome_type] || o.outcome_type}
                    {o.observations > 1 && ` (${o.observations})`}
                  </span>
                  <span className="tabular text-ink">
                    {/* Never converted between units — the unit is part of the number. */}
                    {o.total.toLocaleString()} {o.unit || ""}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <p className="mt-4 border-t border-line pt-3 text-[11px] leading-4 text-muted">
        {ledger.disclaimer}
      </p>
    </SectionCard>
  );
}
