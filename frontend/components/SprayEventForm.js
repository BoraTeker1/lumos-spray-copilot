"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useDemoTag } from "@/lib/farm-context";

const EMPTY = {
  product_name: "",
  active_ingredient: "",
  pesticide_class: "",
  target_pest_or_disease: "",
  dose: "",
  rate_amount: "",
  rate_unit: "",
  treated_acres: "",
  application_date: "",
  cost: "",
  pre_harvest_interval_days: "",
  re_entry_interval_hours: "",
  notes: "",
};

// Form to log a pesticide spray event for a farm.
export default function SprayEventForm({ farmId, onCreated }) {
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
      await api.createSprayEvent(farmId, {
        ...form,
        ...demoTag,
        rate_amount: form.rate_amount === "" ? null : Number(form.rate_amount),
        rate_unit: form.rate_unit || null,
        treated_acres: form.treated_acres === "" ? null : Number(form.treated_acres),
        cost: form.cost === "" ? null : Number(form.cost),
        pre_harvest_interval_days:
          form.pre_harvest_interval_days === ""
            ? null
            : Number(form.pre_harvest_interval_days),
        re_entry_interval_hours:
          form.re_entry_interval_hours === ""
            ? null
            : Number(form.re_entry_interval_hours),
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
        <input
          className={input}
          placeholder="Product name *"
          required
          value={form.product_name}
          onChange={(e) => update("product_name", e.target.value)}
        />
        <input
          className={input}
          placeholder="Active ingredient"
          value={form.active_ingredient}
          onChange={(e) => update("active_ingredient", e.target.value)}
        />
        <input
          className={input}
          placeholder="Pesticide class"
          value={form.pesticide_class}
          onChange={(e) => update("pesticide_class", e.target.value)}
        />
        <input
          className={input}
          placeholder="Target pest / disease"
          value={form.target_pest_or_disease}
          onChange={(e) => update("target_pest_or_disease", e.target.value)}
        />
        <input
          className={input}
          placeholder="Dose (e.g. 2.5 g/L)"
          value={form.dose}
          onChange={(e) => update("dose", e.target.value)}
        />
        <input
          type="number"
          step="any"
          min="0"
          className={input}
          placeholder="Rate amount (e.g. 3.75)"
          value={form.rate_amount}
          onChange={(e) => update("rate_amount", e.target.value)}
        />
        <input
          className={input}
          placeholder="Rate unit (e.g. lb/acre)"
          value={form.rate_unit}
          onChange={(e) => update("rate_unit", e.target.value)}
        />
        <input
          type="number"
          step="any"
          min="0"
          className={input}
          placeholder="Treated acres"
          value={form.treated_acres}
          onChange={(e) => update("treated_acres", e.target.value)}
        />
        <label className="text-xs text-muted">
          Application date *
          <input
            type="date"
            className={input}
            required
            value={form.application_date}
            onChange={(e) => update("application_date", e.target.value)}
          />
        </label>
        <input
          type="number"
          step="0.01"
          className={input}
          placeholder="Cost"
          value={form.cost}
          onChange={(e) => update("cost", e.target.value)}
        />
        <input
          type="number"
          className={input}
          placeholder="Pre-harvest interval (days)"
          value={form.pre_harvest_interval_days}
          onChange={(e) => update("pre_harvest_interval_days", e.target.value)}
        />
        <input
          type="number"
          className={input}
          placeholder="Re-entry interval (hours)"
          value={form.re_entry_interval_hours}
          onChange={(e) => update("re_entry_interval_hours", e.target.value)}
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
        {saving ? "Saving…" : "Add spray event"}
      </button>
    </form>
  );
}
