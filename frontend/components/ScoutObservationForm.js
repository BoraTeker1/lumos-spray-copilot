"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useDemoTag } from "@/lib/farm-context";

const EMPTY = {
  observation_date: "",
  crop_stage: "",
  visible_issue: "",
  severity_1_to_5: "",
  image_url_optional: "",
  notes: "",
};

// Form to log a scouting observation for a farm.
export default function ScoutObservationForm({ farmId, onCreated }) {
  // Demo farms only accept simulated records (the backend 409s on mixing).
  const demoTag = useDemoTag(farmId);
  const [form, setForm] = useState(EMPTY);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  function update(field, value) {
    setForm((f) => ({ ...f, [field]: value }));
  }

  async function submit(e) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await api.createScoutObservation(farmId, {
        ...form,
        ...demoTag,
        severity_1_to_5:
          form.severity_1_to_5 === "" ? null : Number(form.severity_1_to_5),
        image_url_optional: form.image_url_optional || null,
      });
      setForm(EMPTY);
      onCreated && (await onCreated());
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  const input = "w-full rounded border px-2 py-1 text-sm";

  return (
    <form onSubmit={submit} className="space-y-2">
      <div className="grid grid-cols-2 gap-2">
        <label className="text-xs text-muted">
          Observation date *
          <input
            type="date"
            className={input}
            required
            value={form.observation_date}
            onChange={(e) => update("observation_date", e.target.value)}
          />
        </label>
        <input
          className={input}
          placeholder="Crop stage (e.g. fruiting)"
          value={form.crop_stage}
          onChange={(e) => update("crop_stage", e.target.value)}
        />
        <input
          className={input}
          placeholder="Visible issue"
          value={form.visible_issue}
          onChange={(e) => update("visible_issue", e.target.value)}
        />
        <label className="text-xs text-muted">
          Severity (1–5)
          <select
            className={input}
            value={form.severity_1_to_5}
            onChange={(e) => update("severity_1_to_5", e.target.value)}
          >
            <option value="">—</option>
            {[1, 2, 3, 4, 5].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
        <input
          className={input}
          placeholder="Image URL (optional)"
          value={form.image_url_optional}
          onChange={(e) => update("image_url_optional", e.target.value)}
        />
      </div>
      <textarea
        className={input}
        placeholder="Notes"
        value={form.notes}
        onChange={(e) => update("notes", e.target.value)}
      />
      {error && <p className="text-sm text-risk-fg">{error}</p>}
      <button
        type="submit"
        disabled={saving}
        className="rounded bg-leaf px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
      >
        {saving ? "Saving…" : "Add scouting note"}
      </button>
    </form>
  );
}
