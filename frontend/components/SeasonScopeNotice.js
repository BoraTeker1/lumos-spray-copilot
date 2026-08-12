"use client";

import { useState } from "react";
import { Unlink } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import Callout from "@/components/Callout";

// Records the farm holds that are NOT attributed to the season being displayed.
//
// The API has always returned `scope.records_outside_cycle` and nothing rendered it,
// which is the worst version of this: a season total that silently excluded four
// sprays looked exactly like one that included everything. A grower should never read
// a season figure without knowing what was left out of it.
//
// The fix is one click, because the backend already has it — `POST
// /crop-cycles/{id}/link-records` attaches only rows whose `crop_cycle_id` is NULL, so
// a record already assigned to another season is never moved between them.

const RECORD_LABELS = {
  planned_sprays: "pre-spray decision",
  spray_events: "application",
  input_plans: "input plan",
  block_outcomes: "harvest outcome",
};

function phrase(key, count) {
  const label = RECORD_LABELS[key] || key.replace(/_/g, " ");
  return `${count} ${label}${count === 1 ? "" : "s"}`;
}

export default function SeasonScopeNotice({ scope, cycleId, onLinked, className = "" }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const outside = scope?.records_outside_cycle;
  if (!outside) return null;
  const entries = Object.entries(outside).filter(([, count]) => count > 0);
  if (entries.length === 0) return null;

  const total = entries.reduce((sum, [, count]) => sum + count, 0);

  async function link() {
    setBusy(true);
    setError(null);
    try {
      await api.linkCropCycleRecords(cycleId);
      await onLinked?.();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Callout tone="warn" icon={Unlink} title="Some farm records are outside this season" className={className}>
      <p>
        {entries.map(([key, count]) => phrase(key, count)).join(", ")} on this farm{" "}
        {total === 1 ? "is" : "are"} not attributed to this season, so{" "}
        {total === 1 ? "it is" : "they are"} excluded from every figure here.
      </p>
      {cycleId && (
        <Button variant="secondary" size="sm" className="mt-2" onClick={link} disabled={busy}>
          {busy ? "Linking…" : "Link records that fall in this season"}
        </Button>
      )}
      <p className="mt-1.5 text-[11px] leading-4 opacity-80">
        Only records inside this season&apos;s date window and not already assigned to
        another season are attached. Nothing is moved between seasons.
      </p>
      {error && <p className="mt-1 text-[11px] text-risk-fg">{error}</p>}
    </Callout>
  );
}
