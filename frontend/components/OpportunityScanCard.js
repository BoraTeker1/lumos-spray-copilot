"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import SectionCard from "@/components/SectionCard";
import { Button } from "@/components/ui/button";
import { History } from "lucide-react";
import { FormError } from "@/components/ui/field";
import { fieldClass } from "@/components/ui/input";

// Historical opportunity scan — pilot ladder Stage 2, operator only.
//
// THE REASON HISTOGRAM IS THE PRODUCT RIGHT NOW, not the band counts. While the
// threshold table is empty every date abstains, and a card that led with "0 low-pressure
// dates" would read as "your season had no opportunity" — the opposite of the truth,
// which is that nothing could be assessed yet. So reasons are rendered first and
// largest: they are the per-farm work list.
//
// This card writes NO interpretation of its own. `cannot_conclude` comes from the server
// and is rendered verbatim, the same discipline as DataReadinessCard's `basis_text`. A
// number here must never acquire a caption that a slide could quote as a reduction.

const BAND_STYLES = {
  low: "bg-ok-bg text-ok-fg border-ok-line",
  moderate: "bg-warn-bg text-warn-fg border-warn-line",
  high: "bg-risk-bg text-risk-fg border-risk-line",
  abstain: "bg-canvas text-muted border-line",
};

const EMPTY_FORM = { farm_id: "", block_id: "", dates: "" };

function BandChip({ band, count }) {
  return (
    <span
      className={`inline-block rounded border px-1.5 py-0.5 text-[11px] font-medium ${
        BAND_STYLES[band] || BAND_STYLES.abstain
      }`}
    >
      {band} · {count}
    </span>
  );
}

export default function OpportunityScanCard() {
  const [scans, setScans] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    api
      .getOpportunityScans({ limit: 10 })
      .then(setScans)
      .catch((err) => setError(err.message));
  }, []);

  useEffect(load, [load]);

  const submit = async (event) => {
    event.preventDefault();
    setError(null);
    try {
      // Dates are typed by the operator from the partner's own records. They are NEVER
      // generated as a regular grid: a date nobody scheduled is not evidence of a
      // decision, and inventing them would fabricate the denominator the whole
      // opportunity figure is a fraction of.
      const dates = form.dates
        .split(/[\s,]+/)
        .map((d) => d.trim())
        .filter(Boolean);
      await api.runOpportunityScan(Number(form.farm_id), {
        block_id: Number(form.block_id),
        decision_dates: dates,
      });
      setForm(EMPTY_FORM);
      load();
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <SectionCard
      title="Historical opportunity scan"
      icon={<History />}
      description="Replays past scheduled spray dates — sizing only, never a reduction"
      action={
        <Button type="button" variant="outline" size="sm" onClick={load}>
          Refresh
        </Button>
      }
    >
      <div className="flex flex-col gap-4">
        <form onSubmit={submit} className="flex flex-wrap items-end gap-2">
          <label className="flex flex-col text-xs text-muted">
            Farm id
            <input
              value={form.farm_id}
              onChange={(e) => setForm({ ...form, farm_id: e.target.value })}
              className={`mt-0.5 h-9 w-20 py-1 text-sm ${fieldClass}`}
              required
            />
          </label>
          <label className="flex flex-col text-xs text-muted">
            Block id
            <input
              value={form.block_id}
              onChange={(e) => setForm({ ...form, block_id: e.target.value })}
              className={`mt-0.5 h-9 w-20 py-1 text-sm ${fieldClass}`}
              required
            />
          </label>
          <label className="flex flex-1 flex-col text-xs text-muted">
            Scheduled spray dates (from the partner&rsquo;s records)
            <input
              value={form.dates}
              onChange={(e) => setForm({ ...form, dates: e.target.value })}
              placeholder="2026-03-14, 2026-03-28, 2026-04-11"
              className="mt-0.5 rounded border px-2 py-1 font-mono text-sm"
              required
            />
          </label>
          <Button type="submit" size="sm">
            Run scan
          </Button>
        </form>

        <p className="text-xs text-muted">
          Snapshots are <span className="font-mono">retrospective_reconstruction</span>,
          not point-in-time — backfilled records carry an ingest-time{" "}
          <span className="font-mono">recorded_at</span>, so a true replay of a past
          season admits nothing at all.
        </p>

        <FormError size="sm">{error}</FormError>

        {scans === null ? (
          <p className="text-sm text-muted">Loading…</p>
        ) : scans.length === 0 ? (
          <p className="text-sm text-muted">No scans yet.</p>
        ) : (
          <ul className="flex flex-col gap-4">
            {scans.map((scan) => (
              <li key={scan.id} className="border-l-2 border-line pl-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-xs text-ink">
                    #{scan.id} farm {scan.farm_id} · block {scan.block_id}
                  </span>
                  <span className="text-xs text-muted">
                    {scan.dates_scanned} dates · {scan.assessed_count} assessed
                  </span>
                </div>

                {/* Reasons first and unconditional — see the note at the top. */}
                {scan.reason_counts &&
                  Object.keys(scan.reason_counts).length > 0 && (
                    <ul className="mt-1 text-xs text-muted">
                      {Object.entries(scan.reason_counts)
                        .sort((a, b) => b[1] - a[1])
                        .map(([reason, count]) => (
                          <li key={reason}>
                            <span className="font-mono">{reason}</span> — {count}
                          </li>
                        ))}
                    </ul>
                  )}

                {scan.assessed_count > 0 && scan.band_counts && (
                  <div className="mt-1 flex flex-wrap gap-1">
                    {Object.entries(scan.band_counts).map(([band, count]) => (
                      <BandChip key={band} band={band} count={count} />
                    ))}
                  </div>
                )}

                {/* Server-owned, rendered verbatim. This card adds no wording. */}
                {scan.cannot_conclude && (
                  <ul className="mt-2 text-[11px] text-muted">
                    {Object.entries(scan.cannot_conclude).map(([metric, why]) => (
                      <li key={metric}>
                        <span className="font-mono">{metric}</span>: {why}
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </SectionCard>
  );
}
