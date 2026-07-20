"use client";

import { useEffect, useState } from "react";
import { ClipboardCheck, KeyRound } from "lucide-react";
import { api, credentials } from "@/lib/api";
import { Button } from "@/components/ui/button";
import StatusBadge from "@/components/StatusBadge";

// The licensed PCA's professional judgement about a scheduled Botrytis application.
//
// This card shows NOTHING about disease risk, and that is the design — not an
// omission. While the pilot is blinded the decision payload carries no risk field at
// all, so there is nothing here to render even if this component wanted to. A PCA who
// has seen a model's risk band can no longer provide the unbiased baseline the pilot
// exists to collect.
//
// The disposition is orthogonal to the PCA review above it: recording one changes no
// decision or review column, and "defer" neither unlocks an applied outcome nor
// satisfies a required review.

const OPTIONS = [
  {
    value: "follow_baseline",
    label: "Spray as scheduled",
    hint: "Proceed with the planned application.",
  },
  {
    value: "defer",
    label: "Defer",
    hint: "Hold the application; record how long and why.",
  },
  {
    value: "rescout",
    label: "Re-scout first",
    hint: "Gather more field evidence before deciding.",
  },
  {
    value: "insufficient_evidence",
    label: "Insufficient evidence",
    hint: "Not enough information to make a call either way.",
  },
];

export default function PcaDispositionCard({ plannedId }) {
  const [dispositions, setDispositions] = useState([]);
  const [choice, setChoice] = useState(null);
  const [rationale, setRationale] = useState("");
  const [token, setToken] = useState("");
  const [hasToken, setHasToken] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    setHasToken(Boolean(credentials.getPcaToken()));
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [plannedId]);

  async function load() {
    try {
      setDispositions(await api.listPcaDispositions(plannedId));
    } catch (err) {
      setError(err.message);
    }
  }

  function saveToken(event) {
    event.preventDefault();
    if (!token.trim()) return;
    credentials.setPcaToken(token.trim());
    setToken("");
    setHasToken(true);
    setError(null);
  }

  async function submit(event) {
    event.preventDefault();
    if (!choice || !rationale.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await api.createPcaDisposition(plannedId, {
        disposition: choice,
        rationale: rationale.trim(),
        // A change supersedes the live record rather than editing it, so the
        // original judgement stays on the pilot's record.
        supersedes_id: live ? live.id : null,
      });
      setChoice(null);
      setRationale("");
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const superseded = new Set(
    dispositions.map((d) => d.supersedes_id).filter(Boolean)
  );
  const live = dispositions.find((d) => !superseded.has(d.id)) || null;

  return (
    <section className="rounded-lg border border-gray-200 bg-white p-4">
      <div className="flex items-center gap-2">
        <ClipboardCheck className="h-4 w-4 text-gray-500" aria-hidden="true" />
        <h3 className="text-sm font-semibold text-gray-900">PCA decision (pilot)</h3>
      </div>
      <p className="mt-1 text-xs text-gray-600">
        Your professional judgement on this scheduled application. Recorded as its own
        attributed, append-only entry — it does not change the compliance check or the
        review above, and deferring does not clear the spray to go ahead.
      </p>

      {live && (
        <div className="mt-3 rounded-md border border-gray-200 bg-gray-50 p-3">
          <div className="flex items-center justify-between gap-2">
            <StatusBadge kind="disposition" value={live.disposition} />
            <span className="text-xs text-gray-500">
              {live.decided_at?.slice(0, 16).replace("T", " ")}
            </span>
          </div>
          <p className="mt-2 text-sm text-gray-800">{live.rationale}</p>
        </div>
      )}

      {!hasToken ? (
        <form onSubmit={saveToken} className="mt-3 space-y-2">
          <label className="flex items-center gap-1.5 text-xs font-medium text-gray-700">
            <KeyRound className="h-3.5 w-3.5" aria-hidden="true" />
            PCA credential token
          </label>
          <input
            type="password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="Paste the token issued to you"
            className="w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm"
          />
          <p className="text-xs text-gray-500">
            Held for this browser session only, never saved to the device. A
            disposition is always attributed to a licensed credential — there is no
            anonymous path.
          </p>
          <Button type="submit" size="sm" disabled={!token.trim()}>
            Use this token
          </Button>
        </form>
      ) : (
        <form onSubmit={submit} className="mt-3 space-y-3">
          <fieldset className="space-y-1.5">
            <legend className="text-xs font-medium text-gray-700">
              {live ? "Record a corrected decision" : "Record your decision"}
            </legend>
            {OPTIONS.map((option) => (
              <label
                key={option.value}
                className="flex cursor-pointer items-start gap-2 rounded-md border border-gray-200 p-2 hover:bg-gray-50"
              >
                <input
                  type="radio"
                  name={`disposition-${plannedId}`}
                  value={option.value}
                  checked={choice === option.value}
                  onChange={() => setChoice(option.value)}
                  className="mt-0.5"
                />
                <span>
                  <span className="block text-sm text-gray-900">{option.label}</span>
                  <span className="block text-xs text-gray-500">{option.hint}</span>
                </span>
              </label>
            ))}
          </fieldset>

          <div>
            <label
              htmlFor={`rationale-${plannedId}`}
              className="text-xs font-medium text-gray-700"
            >
              Reason (required)
            </label>
            <textarea
              id={`rationale-${plannedId}`}
              value={rationale}
              onChange={(e) => setRationale(e.target.value)}
              rows={3}
              placeholder="What drove this call? Conditions, scouting, timing…"
              className="mt-1 w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm"
            />
            <p className="mt-1 text-xs text-gray-500">
              A decision without a stated reason cannot be used as pilot evidence.
            </p>
          </div>

          <Button type="submit" size="sm" disabled={busy || !choice || !rationale.trim()}>
            {busy ? "Recording…" : "Record decision"}
          </Button>
        </form>
      )}

      {error && (
        <p className="mt-2 rounded-md border border-red-200 bg-red-50 p-2 text-xs text-red-700">
          {error}
        </p>
      )}

      {dispositions.length > 1 && (
        <div className="mt-4 border-t border-gray-100 pt-3">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500">
            Earlier decisions (superseded, never removed)
          </h4>
          <ul className="mt-2 space-y-2">
            {dispositions
              .filter((d) => superseded.has(d.id))
              .map((d) => (
                <li key={d.id} className="text-xs text-gray-500 line-through">
                  <StatusBadge kind="disposition" value={d.disposition} /> —{" "}
                  {d.rationale} ({d.decided_at?.slice(0, 16).replace("T", " ")})
                </li>
              ))}
          </ul>
        </div>
      )}
    </section>
  );
}
