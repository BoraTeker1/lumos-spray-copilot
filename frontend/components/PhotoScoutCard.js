"use client";

import { useState } from "react";
import { AlertTriangle, Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import { useDemoTag } from "@/lib/farm-context";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Field, FormError } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";

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

  // Higher confidence in a *problem* is the more actionable state, which is why
  // this scale runs neutral → amber → red rather than the other way round.
  const confidenceVariant =
    result?.confidence === "high"
      ? "red"
      : result?.confidence === "medium"
      ? "amber"
      : "neutral";

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Badge variant="purple">
          <Sparkles aria-hidden />
          AI · decision support
        </Badge>
        <span className="min-w-0 flex-1 text-xs text-muted">
          The model describes what it appears to see and drafts a scouting note for you to
          review — it does not diagnose disease or tell you to spray.
        </span>
      </div>

      <form onSubmit={analyze} className="space-y-3">
        <Field label="Field photo" required>
          <input
            type="file"
            accept="image/*"
            onChange={(e) => pickFile(e.target.files?.[0] || null)}
            className="block w-full cursor-pointer text-sm text-muted file:mr-3 file:cursor-pointer file:rounded-control file:border-0 file:bg-leaf-700 file:px-3 file:py-2 file:text-sm file:font-medium file:text-white hover:file:bg-leaf-800"
          />
        </Field>
        {preview && (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={preview}
            alt="Selected field photo, awaiting analysis"
            className="max-h-48 rounded-control border border-line"
          />
        )}
        <Field label="What are you worried about?" hint="Optional, e.g. spots on leaves">
          <Input value={concern} onChange={(e) => setConcern(e.target.value)} />
        </Field>
        <Button type="submit" disabled={!file || analyzing}>
          {analyzing ? "Analyzing…" : "Analyze photo"}
        </Button>
      </form>

      <FormError className="mt-2">{error}</FormError>

      {result && (
        <div className="mt-4 space-y-3 rounded-control border border-line bg-canvas p-3">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={confidenceVariant}>{result.confidence} confidence</Badge>
            <Badge variant="purple">AI-suggested · not confirmed</Badge>
            {result.is_mock && <Badge variant="neutral">demo model (no API key)</Badge>}
          </div>

          {result.observations?.length > 0 && (
            <ul className="list-disc space-y-1 pl-4 text-sm text-ink">
              {result.observations.map((o, i) => (
                <li key={i}>{o}</li>
              ))}
            </ul>
          )}

          {result.caveats?.length > 0 && (
            <ul className="space-y-1 text-[11px] text-muted">
              {result.caveats.map((c, i) => (
                <li key={i} className="flex gap-1.5">
                  <AlertTriangle className="mt-px h-3 w-3 shrink-0 text-warn-fg" aria-hidden />
                  <span className="min-w-0">{c}</span>
                </li>
              ))}
            </ul>
          )}

          {/* Human-in-the-loop confirmation: edit, then save as a real scouting note. */}
          <div className="rounded-control border border-line bg-surface p-3">
            <p className="mb-2 text-xs font-medium text-muted">
              Review &amp; confirm as a scouting note (you can edit before saving):
            </p>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Field label="Visible issue">
                <Input value={issue} onChange={(e) => setIssue(e.target.value)} />
              </Field>
              <Field label="Severity (1–5)">
                <Select value={severity} onChange={(e) => setSeverity(e.target.value)}>
                  <option value="">—</option>
                  {[1, 2, 3, 4, 5].map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </Select>
              </Field>
            </div>
            <Button
              type="button"
              onClick={confirmAsNote}
              disabled={saving}
              className="mt-3"
            >
              {saving ? "Saving…" : "Confirm as scouting note"}
            </Button>
          </div>

          <p className="text-[11px] text-muted">{result.disclaimer}</p>
        </div>
      )}
    </div>
  );
}
