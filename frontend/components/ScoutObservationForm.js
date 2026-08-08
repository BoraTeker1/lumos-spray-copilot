"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useDemoTag } from "@/lib/farm-context";
import { Button } from "@/components/ui/button";
import { Field, FormError } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

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

  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Observation date" required>
          <Input
            type="date"
            required
            className="tabular"
            value={form.observation_date}
            onChange={(e) => update("observation_date", e.target.value)}
          />
        </Field>
        <Field label="Crop stage" hint="e.g. fruiting">
          <Input
            value={form.crop_stage}
            onChange={(e) => update("crop_stage", e.target.value)}
          />
        </Field>
        <Field label="Visible issue">
          <Input
            value={form.visible_issue}
            onChange={(e) => update("visible_issue", e.target.value)}
          />
        </Field>
        {/* Severity drives the engine's high-severity scouting check, so the
            scale belongs in the label rather than only in the option list. */}
        <Field label="Severity (1–5)">
          <Select
            value={form.severity_1_to_5}
            onChange={(e) => update("severity_1_to_5", e.target.value)}
          >
            <option value="">—</option>
            {[1, 2, 3, 4, 5].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Image URL" hint="Optional" className="sm:col-span-2">
          <Input
            type="url"
            value={form.image_url_optional}
            onChange={(e) => update("image_url_optional", e.target.value)}
          />
        </Field>
      </div>
      <Field label="Notes">
        <Textarea
          rows={3}
          value={form.notes}
          onChange={(e) => update("notes", e.target.value)}
        />
      </Field>
      <FormError>{error}</FormError>
      <Button type="submit" disabled={saving}>
        {saving ? "Saving…" : "Add scouting note"}
      </Button>
    </form>
  );
}
