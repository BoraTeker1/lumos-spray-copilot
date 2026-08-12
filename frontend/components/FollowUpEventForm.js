"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { FormError } from "@/components/ui/field";

// Appending one follow-up event to a decision's timeline.
//
// Extracted from app/decisions/[id]/page.js, where it lived inline and was the ONLY
// place in the app a follow-up could be recorded — which mattered because follow-up
// evidence is exactly what moves attributable value from estimated to verified. A
// grower who never opened a decision's detail page could not complete the loop.
//
// Append-only in the strictest sense: there is no edit and no delete, and the form
// keeps the event type and date after a submit so a run of observations is quick to
// enter without re-selecting everything.

export const FOLLOW_UP_TYPES = [
  { value: "scouting_observation", label: "Scouting observation" },
  { value: "actual_application", label: "Actual application" },
  { value: "rescue_application", label: "Rescue application" },
  { value: "harvest_outcome", label: "Harvest outcome" },
  { value: "yield_quality_outcome", label: "Yield / quality outcome" },
  { value: "note", label: "Note" },
];

const INPUT_CLS = "rounded-control border border-line px-2 py-1 text-xs";

export default function FollowUpEventForm({ plannedId, onAdded, heading }) {
  const [form, setForm] = useState({
    event_type: "scouting_observation",
    observed_at: new Date().toISOString().slice(0, 10),
    severity: "",
    actual_product: "",
    cost: "",
    rescue_required: false,
    yield_impact: "",
    quality_impact: "",
    evidence_notes: "",
    entered_by: "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (k) => (e) =>
    setForm({ ...form, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.addFollowUpEvent(plannedId, {
        event_type: form.event_type,
        observed_at: form.observed_at,
        severity: form.severity === "" ? null : Number(form.severity),
        severity_scale: form.severity === "" ? null : "1-5",
        actual_product: form.actual_product || null,
        cost: form.cost === "" ? null : Number(form.cost),
        rescue_required: ["rescue_application"].includes(form.event_type)
          ? true
          : form.rescue_required,
        yield_impact: form.yield_impact || null,
        quality_impact: form.quality_impact || null,
        evidence_notes: form.evidence_notes || null,
        entered_by: form.entered_by || null,
      });
      onAdded && (await onAdded());
      setForm({ ...form, severity: "", actual_product: "", cost: "", evidence_notes: "" });
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const needsProduct = ["actual_application", "rescue_application"].includes(form.event_type);
  return (
    <form onSubmit={submit} className="no-print mt-2 space-y-2 rounded-control border bg-canvas p-3">
      <p className="text-xs font-medium text-ink">
        {heading || "Add follow-up event (append-only — events are never edited or deleted)"}
      </p>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        <select className={INPUT_CLS} value={form.event_type} onChange={set("event_type")}>
          {FOLLOW_UP_TYPES.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
        <input
          type="date"
          className={INPUT_CLS}
          value={form.observed_at}
          onChange={set("observed_at")}
        />
        {/* Both of these are REQUIRED by the API for their event type, and were
            marked optional here — so submitting returned a raw 422 that the user had
            to read to discover the rule. Marking them lets the browser say it first. */}
        {form.event_type === "scouting_observation" && (
          <input
            type="number"
            min="0"
            max="5"
            required
            placeholder="Severity (1-5), required"
            className={INPUT_CLS}
            value={form.severity}
            onChange={set("severity")}
          />
        )}
        {needsProduct && (
          <input
            placeholder="Product applied, required"
            required
            className={INPUT_CLS}
            value={form.actual_product}
            onChange={set("actual_product")}
          />
        )}
        <input
          type="number"
          step="0.01"
          placeholder="Cost (optional)"
          className={INPUT_CLS}
          value={form.cost}
          onChange={set("cost")}
        />
        {["harvest_outcome", "yield_quality_outcome"].includes(form.event_type) && (
          <>
            <select className={INPUT_CLS} value={form.yield_impact} onChange={set("yield_impact")}>
              <option value="">Yield impact: unknown</option>
              <option value="positive">Yield: positive</option>
              <option value="neutral">Yield: neutral</option>
              <option value="negative">Yield: negative</option>
            </select>
            <select
              className={INPUT_CLS}
              value={form.quality_impact}
              onChange={set("quality_impact")}
            >
              <option value="">Quality impact: unknown</option>
              <option value="positive">Quality: positive</option>
              <option value="neutral">Quality: neutral</option>
              <option value="negative">Quality: negative</option>
            </select>
          </>
        )}
        <input
          placeholder="Entered by"
          className={INPUT_CLS}
          value={form.entered_by}
          onChange={set("entered_by")}
        />
      </div>
      <textarea
        rows={2}
        placeholder="Evidence notes (what was actually seen/done)"
        className="w-full rounded-control border border-line px-2 py-1 text-xs"
        value={form.evidence_notes}
        onChange={set("evidence_notes")}
      />
      <Button type="submit" size="sm" disabled={busy}>
        {busy ? "Saving…" : "Append event"}
      </Button>
      <FormError size="sm">{error}</FormError>
    </form>
  );
}
