"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useDemoTag } from "@/lib/farm-context";
import { Button } from "@/components/ui/button";
import { Field, FormError } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

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

  return (
    // Fields stack on a phone: two columns of labelled controls inside a farm
    // detail card left each one about 130px wide, which clipped the longer
    // regulatory labels outright.
    <form onSubmit={submit} className="space-y-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Product name" required>
          <Input
            required
            value={form.product_name}
            onChange={(e) => update("product_name", e.target.value)}
          />
        </Field>
        <Field label="Active ingredient">
          <Input
            value={form.active_ingredient}
            onChange={(e) => update("active_ingredient", e.target.value)}
          />
        </Field>
        <Field label="Pesticide class">
          <Input
            value={form.pesticide_class}
            onChange={(e) => update("pesticide_class", e.target.value)}
          />
        </Field>
        <Field label="Target pest / disease">
          <Input
            value={form.target_pest_or_disease}
            onChange={(e) => update("target_pest_or_disease", e.target.value)}
          />
        </Field>
        <Field label="Dose" hint="e.g. 2.5 g/L">
          <Input value={form.dose} onChange={(e) => update("dose", e.target.value)} />
        </Field>
        <Field label="Rate amount" hint="e.g. 3.75">
          <Input
            type="number"
            step="any"
            min="0"
            className="tabular"
            value={form.rate_amount}
            onChange={(e) => update("rate_amount", e.target.value)}
          />
        </Field>
        <Field label="Rate unit" hint="e.g. lb/acre">
          <Input
            value={form.rate_unit}
            onChange={(e) => update("rate_unit", e.target.value)}
          />
        </Field>
        <Field label="Treated acres">
          <Input
            type="number"
            step="any"
            min="0"
            className="tabular"
            value={form.treated_acres}
            onChange={(e) => update("treated_acres", e.target.value)}
          />
        </Field>
        <Field label="Application date" required>
          <Input
            type="date"
            required
            className="tabular"
            value={form.application_date}
            onChange={(e) => update("application_date", e.target.value)}
          />
        </Field>
        <Field label="Cost">
          <Input
            type="number"
            step="0.01"
            className="tabular"
            value={form.cost}
            onChange={(e) => update("cost", e.target.value)}
          />
        </Field>
        {/* PHI and REI were placeholder-only, so the label disappeared as soon
            as a number was typed — on the two fields the engine's harvest-timing
            and re-entry checks read. Both now say what unit they are in. */}
        <Field label="Pre-harvest interval (days)">
          <Input
            type="number"
            className="tabular"
            value={form.pre_harvest_interval_days}
            onChange={(e) => update("pre_harvest_interval_days", e.target.value)}
          />
        </Field>
        <Field label="Re-entry interval (hours)">
          <Input
            type="number"
            className="tabular"
            value={form.re_entry_interval_hours}
            onChange={(e) => update("re_entry_interval_hours", e.target.value)}
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
        {saving ? "Saving…" : "Add spray event"}
      </Button>
    </form>
  );
}
