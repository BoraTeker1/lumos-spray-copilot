"use client";

import { useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  ChevronDown,
  ChevronRight,
  Sparkles,
  CheckCircle2,
} from "lucide-react";
import { formatDate } from "@/lib/format";
import { ADVISORY_KIND_LABELS, ADVISORY_URGENCY_LABELS } from "@/lib/labels";
import { tone, ADVISORY_URGENCY_TONES } from "@/lib/tones";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import EmptyState from "@/components/EmptyState";

// The farm's ranked action list, and the surface the whole operating loop hangs off.
//
// Everything rendered here is derived server-side by app/advisory.py: there is no
// dismiss, no snooze, and no "mark as read", because an item disappears when the
// record behind it moves. That is the honest behaviour — a queue you can silence
// stops describing the farm.
//
// The economic consequence follows the DataReadinessCard rule: an item with no
// documented baseline renders "Not calculated" plus its reason, never a zero and
// never a blank.

function EconomicLine({ economic, showLabel = true }) {
  if (!economic) return null;
  if (economic.not_calculated) {
    return (
      <div className="text-xs text-muted">
        {showLabel && <span className="font-medium">Economic consequence: </span>}
        Not calculated — {economic.reason}
      </div>
    );
  }
  const amount = Number(economic.amount).toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  });
  return (
    <div className="text-xs text-muted">
      {showLabel && <span className="font-medium">At stake: </span>}
      <span className="font-medium text-ink">
        {amount} {economic.currency}
      </span>{" "}
      — {economic.basis}
    </div>
  );
}

function Explanation({ farmId, item, cropCycleId }) {
  const [state, setState] = useState(null);
  const [loading, setLoading] = useState(false);

  async function explain() {
    setLoading(true);
    try {
      setState(await api.explainAdvisoryItem(farmId, item.item_key, cropCycleId));
    } catch (err) {
      setState({ refused: true, detail: err.message });
    } finally {
      setLoading(false);
    }
  }

  if (state) {
    // A refusal here changes nothing about the item: its urgency, next action and
    // figures are computed from records, not written by the model.
    if (state.refused) {
      return <p className="text-xs text-muted">Not available — {state.detail}</p>;
    }
    return (
      <div className="space-y-2 rounded-md border border-line bg-surface-2 p-3">
        <p className="text-sm text-ink">{state.summary}</p>
        {state.what_the_data_shows?.length > 0 && (
          <ul className="list-inside list-disc space-y-0.5 text-xs text-muted">
            {state.what_the_data_shows.map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>
        )}
        {state.what_the_data_does_not_show?.length > 0 && (
          <div className="text-xs text-muted">
            <span className="font-medium">What this does not show: </span>
            {state.what_the_data_does_not_show.join(" ")}
          </div>
        )}
        <p className="text-[11px] text-muted">
          {state.is_mock && "Offline mock output. "}
          {state.disclaimer}
        </p>
      </div>
    );
  }

  return (
    <Button variant="ghost" size="sm" onClick={explain} disabled={loading}>
      <Sparkles className="mr-1.5 h-3.5 w-3.5" />
      {loading ? "Explaining…" : "Explain this"}
    </Button>
  );
}

function AdvisoryRow({ item, farmId, cropCycleId }) {
  const [open, setOpen] = useState(false);
  const t = tone(ADVISORY_URGENCY_TONES[item.urgency] || "info");
  const Chevron = open ? ChevronDown : ChevronRight;

  return (
    <li className="border-b border-line last:border-0">
      <div className="flex items-start gap-3 py-3">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="mt-0.5 shrink-0 text-muted hover:text-ink"
          aria-expanded={open}
          aria-label={open ? "Hide detail" : "Show detail"}
        >
          <Chevron className="h-4 w-4" />
        </button>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={t.badge}>
              {ADVISORY_URGENCY_LABELS[item.urgency] || item.urgency}
            </Badge>
            <span className="text-xs text-muted">
              {ADVISORY_KIND_LABELS[item.kind] || item.kind}
            </span>
            {item.due_on && (
              <span className="text-xs text-muted">· by {formatDate(item.due_on)}</span>
            )}
          </div>

          <p className="mt-1 font-medium text-ink">{item.title}</p>
          <p className="mt-0.5 text-sm text-muted">{item.recommendation}</p>

          {open && (
            <div className="mt-3 space-y-3">
              <div className="text-sm text-muted">
                <span className="font-medium text-ink">Why: </span>
                {item.why}
              </div>
              {item.agronomic_consequence && (
                <div className="text-sm text-muted">
                  <span className="font-medium text-ink">If nothing changes: </span>
                  {item.agronomic_consequence}
                </div>
              )}
              <EconomicLine economic={item.economic_consequence} />
              {item.evidence?.length > 0 && (
                <div className="text-[11px] text-muted">
                  <span className="font-medium">Evidence: </span>
                  {item.evidence.join(" · ")}
                </div>
              )}
              <Explanation
                farmId={farmId}
                item={item}
                cropCycleId={cropCycleId}
              />
            </div>
          )}
        </div>

        {item.next_action?.href && (
          <Link href={item.next_action.href} className="shrink-0">
            <Button variant="secondary" size="sm">
              {item.next_action.label}
              <ArrowRight className="ml-1.5 h-3.5 w-3.5" />
            </Button>
          </Link>
        )}
      </div>
    </li>
  );
}

export default function AdvisoryQueue({ queue, farmId, cropCycleId, limit }) {
  if (!queue) return null;

  const items = limit ? queue.items.slice(0, limit) : queue.items;

  if (!queue.items.length) {
    return (
      <EmptyState
        icon={CheckCircle2}
        title="Nothing needs attention"
        description={
          "No decision, conflict, follow-up, or procurement step is outstanding for " +
          "this season. Items appear here on their own as records change."
        }
      />
    );
  }

  return (
    <div>
      <ul className="divide-y-0">
        {items.map((item) => (
          <AdvisoryRow
            key={item.item_key}
            item={item}
            farmId={farmId}
            cropCycleId={cropCycleId}
          />
        ))}
      </ul>
      {limit && queue.items.length > limit && (
        <p className="pt-3 text-xs text-muted">
          {queue.items.length - limit} more item(s) not shown.
        </p>
      )}
      <p className="pt-3 text-[11px] text-muted">{queue.disclaimer}</p>
    </div>
  );
}
