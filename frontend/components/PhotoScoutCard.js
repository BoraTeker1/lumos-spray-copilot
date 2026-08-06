"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useDemoTag } from "@/lib/farm-context";

// "Do I really need to spray?" photo copilot. Upload a field photo, a multimodal model
// (Claude) describes what it appears to see, and the finding pre-fills a scouting note the
// grower/PCA must review and confirm. Honest by design: AI-suggested, not a diagnosis, never
// "spray now". The confirmed note feeds the existing rule engine (CV is an input, not the decider).
export default function PhotoScoutCard({ farmId, onCreated }) {
  // Demo farms only accept simulated records (the backend 409s on mixing).
  const demoTag = useDemoTag(farmId);
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [concern, setConcern] = useState("");
  const [result, setResult] = useState(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  // Editable confirmation fields (pre-filled from the AI suggestion).
  const [issue, setIssue] = useState("");
  const [severity, setSeverity] = useState("");

  function pickFile(f) {
    setFile(f);
    setResult(null);
    setError(null);
    setPreview(f ? URL.createObjectURL(f) : null);
  }

  async function analyze(e) {
    e.preventDefault();
    if (!file) return;
    setAnalyzing(true);
    setError(null);
    try {
      const res = await api.analyzePhoto(farmId, file, concern || undefined);
      setResult(res);
      setIssue(res.detected_issue || "");
      setSeverity(res.suggested_severity != null ? String(res.suggested_severity) : "");
    } catch (err) {
      setError(err.message);
    } finally {
      setAnalyzing(false);
    }
  }

  // The human confirms: save the (edited) suggestion as a real scouting observation.
  async function confirmAsNote() {
    if (!result) return;
    setSaving(true);
    setError(null);
    try {
      await api.createScoutObservation(farmId, {
        ...result.suggested_observation,
        ...demoTag,
        visible_issue: issue || null,
        severity_1_to_5: severity === "" ? null : Number(severity),
      });
      setResult(null);
      setFile(null);
      setPreview(null);
      setConcern("");
      onCreated && (await onCreated());
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  const input = "w-full rounded border px-2 py-1 text-sm";
  const confidenceColor =
    result?.confidence === "high"
      ? "bg-risk-bg text-risk-fg"
      : result?.confidence === "medium"
      ? "bg-warn-bg text-warn-fg"
      : "bg-draft-bg text-ink";

  return (
    <div>
      <div className="mb-3 flex items-center gap-2">
        <span className="rounded bg-leaf/10 px-1.5 py-0.5 text-[10px] font-medium text-leaf">
          AI · decision support
        </span>
        <span className="text-xs text-muted">
          The model describes what it appears to see and drafts a scouting note for you to
          review — it does not diagnose disease or tell you to spray.
        </span>
      </div>

      <form onSubmit={analyze} className="space-y-2">
        <input
          type="file"
          accept="image/*"
          onChange={(e) => pickFile(e.target.files?.[0] || null)}
          className="block w-full text-sm file:mr-3 file:rounded file:border-0 file:bg-leaf file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-white"
        />
        {preview && (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={preview} alt="field preview" className="max-h-48 rounded border" />
        )}
        <input
          className={input}
          placeholder="What are you worried about? (optional, e.g. spots on leaves)"
          value={concern}
          onChange={(e) => setConcern(e.target.value)}
        />
        <button
          type="submit"
          disabled={!file || analyzing}
          className="rounded bg-leaf px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
        >
          {analyzing ? "Analyzing…" : "Analyze photo"}
        </button>
      </form>

      {error && <p className="mt-2 text-sm text-risk-fg">{error}</p>}

      {result && (
        <div className="mt-4 space-y-3 rounded-control border bg-canvas p-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`rounded px-2 py-0.5 text-[11px] font-medium ${confidenceColor}`}>
              {result.confidence} confidence
            </span>
            <span className="rounded bg-review-bg px-2 py-0.5 text-[11px] font-medium text-review-fg">
              AI-suggested · not confirmed
            </span>
            {result.is_mock && (
              <span className="rounded bg-draft-bg px-2 py-0.5 text-[11px] font-medium text-ink">
                demo model (no API key)
              </span>
            )}
          </div>

          {result.observations?.length > 0 && (
            <ul className="space-y-1 text-sm text-ink">
              {result.observations.map((o, i) => (
                <li key={i} className="flex gap-1">
                  <span>•</span>
                  <span>{o}</span>
                </li>
              ))}
            </ul>
          )}

          {result.caveats?.length > 0 && (
            <ul className="space-y-1 text-[11px] text-muted">
              {result.caveats.map((c, i) => (
                <li key={i} className="flex gap-1">
                  <span>⚠</span>
                  <span>{c}</span>
                </li>
              ))}
            </ul>
          )}

          {/* Human-in-the-loop confirmation: edit, then save as a real scouting note. */}
          <div className="rounded border bg-surface p-2">
            <p className="mb-2 text-xs font-medium text-muted">
              Review &amp; confirm as a scouting note (you can edit before saving):
            </p>
            <div className="grid grid-cols-2 gap-2">
              <input
                className={input}
                placeholder="Visible issue"
                value={issue}
                onChange={(e) => setIssue(e.target.value)}
              />
              <label className="text-xs text-muted">
                Severity (1–5)
                <select
                  className={input}
                  value={severity}
                  onChange={(e) => setSeverity(e.target.value)}
                >
                  <option value="">—</option>
                  {[1, 2, 3, 4, 5].map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <button
              onClick={confirmAsNote}
              disabled={saving}
              className="mt-2 rounded bg-leaf px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
            >
              {saving ? "Saving…" : "Confirm as scouting note"}
            </button>
          </div>

          <p className="text-[11px] text-muted">{result.disclaimer}</p>
        </div>
      )}
    </div>
  );
}
