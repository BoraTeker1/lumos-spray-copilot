"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import SectionCard from "@/components/SectionCard";
import { Button } from "@/components/ui/button";
import { DownloadCloud } from "lucide-react";

// Ingestion health, for an operator.
//
// THE COUNTS ARE THE POINT. A run that fetched 24 rows and admitted 24 is a different
// event from one that fetched 24 and admitted 3, and a view showing only
// succeeded/failed would render both as green. The 21 dropped rows in the second case
// are individually explained in the issue list, and that gap is how someone learns a
// feed has quietly degraded.
//
// `skipped_no_credential` is shown as its own state, not as a failure: a deployment
// with no API key is correctly configured and simply cannot fetch. Painting it red
// would make a healthy system look broken and train the operator to ignore the column
// that actually matters.

const STATUS_STYLES = {
  succeeded: "bg-ok-bg text-ok-fg border-ok-line",
  running: "bg-info-bg text-info-fg border-info-line",
  pending: "bg-canvas text-muted border-line",
  skipped_no_credential: "bg-warn-bg text-warn-fg border-warn-line",
  failed: "bg-risk-bg text-risk-fg border-risk-line",
  dead: "bg-risk-bg text-risk-fg border-risk-line",
};

const EMPTY_FORM = { farm_id: "", station_id: "", field_id: "", lookback_hours: "6" };

function StatusChip({ status }) {
  return (
    <span
      className={`inline-block rounded border px-1.5 py-0.5 text-[11px] font-medium ${
        STATUS_STYLES[status] || STATUS_STYLES.pending
      }`}
    >
      {status}
    </span>
  );
}

function Counts({ counts }) {
  // Admitted vs fetched side by side, because the DIFFERENCE is the signal.
  return (
    <span className="font-mono text-xs text-muted">
      fetched {counts.fetched} · admitted {counts.admitted} · dup {counts.duplicate} ·
      issues {counts.issues}
    </span>
  );
}

export default function IngestionCard() {
  const [runs, setRuns] = useState(null);
  const [sources, setSources] = useState([]);
  const [form, setForm] = useState(EMPTY_FORM);
  const [selected, setSelected] = useState("cimis_hourly");
  const [message, setMessage] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    api
      .getIngestionRuns({ limit: 25 })
      .then((body) => setRuns(body.runs))
      .catch((err) => setError(err.message));
    api
      .getIngestionSources()
      .then((body) => setSources(body.sources))
      .catch(() => {});
  }, []);

  useEffect(load, [load]);

  const submit = async (event) => {
    event.preventDefault();
    setError(null);
    setMessage(null);
    try {
      const body = await api.runIngestionSource(selected, {
        farm_id: Number(form.farm_id),
        station_id: form.station_id,
        field_id: form.field_id ? Number(form.field_id) : null,
        lookback_hours: Number(form.lookback_hours || 6),
      });
      // The route enqueues; it does not fetch. Say so, or an operator will watch an
      // empty runs table and conclude the feature is broken.
      setMessage(body.note);
      setForm(EMPTY_FORM);
      load();
    } catch (err) {
      setError(err.message);
    }
  };

  const runnable = sources.filter((s) => s.status !== "deferred_to_finance_phase");

  return (
    <SectionCard
      title="Ingestion"
      icon={<DownloadCloud />}
      description="Runs, counts and the rows each one dropped"
      action={
        <Button type="button" variant="outline" size="sm" onClick={load}>
          Refresh
        </Button>
      }
    >
      <div className="flex flex-col gap-4">
        <form onSubmit={submit} className="flex flex-wrap items-end gap-2">
          <label className="flex flex-col text-xs text-muted">
            Source
            <select
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
              className="mt-0.5 rounded border px-2 py-1 text-sm"
            >
              {runnable.map((s) => (
                <option key={s.source_key} value={s.source_key}>
                  {s.source_key}
                </option>
              ))}
            </select>
          </label>
          {["farm_id", "station_id", "field_id", "lookback_hours"].map((field) => (
            <label key={field} className="flex flex-col text-xs text-muted">
              {field}
              <input
                value={form[field]}
                onChange={(e) => setForm({ ...form, [field]: e.target.value })}
                className="mt-0.5 w-28 rounded border px-2 py-1 text-sm"
                required={field === "farm_id" || field === "station_id"}
              />
            </label>
          ))}
          <Button type="submit" size="sm">
            Enqueue run
          </Button>
        </form>

        {/* A field without a centroid drops every row. Saying so here saves an hour
            of staring at a run whose admitted count is zero. */}
        <p className="text-xs text-muted">
          A run whose field has no centroid drops every row with{" "}
          <span className="font-mono">no_field_geolocation</span> — set the field&rsquo;s
          coordinates first.
        </p>

        {message && <p className="text-xs text-ok-fg">{message}</p>}
        {error && <p className="text-xs text-risk-fg">{error}</p>}

        {runs === null ? (
          <p className="text-sm text-muted">Loading…</p>
        ) : runs.length === 0 ? (
          <p className="text-sm text-muted">No ingestion runs yet.</p>
        ) : (
          <ul className="flex flex-col gap-3">
            {runs.map((run) => (
              <li key={run.id} className="border-l-2 border-line pl-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-xs text-ink">
                    #{run.id} {run.source_key}
                  </span>
                  <StatusChip status={run.status} />
                  <Counts counts={run.counts} />
                </div>
                {run.error && (
                  <div className="text-xs text-risk-fg">{run.error}</div>
                )}
                {run.issues.length > 0 && (
                  <ul className="mt-1 text-xs text-muted">
                    {run.issues.map((issue, i) => (
                      <li key={i}>
                        <span className="font-mono">{issue.code}</span>
                        {issue.row_index != null && ` (row ${issue.row_index})`} —{" "}
                        {issue.message}
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
