"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useDemoTag } from "@/lib/farm-context";
import { Button } from "@/components/ui/button";
import { Field, FormError } from "@/components/ui/field";
import { Input } from "@/components/ui/input";

// Recording a settlement — the revenue half of the season.
//
// Gross, deductions and net stay three numbers rather than one. What the crop sold for
// and what the farm received are different facts, and a packer withholds commission,
// freight and cooling between them.
//
// The server rejects a record that contradicts itself (quantity x unit price
// disagreeing with the stated gross beyond settlement rounding), so this form does not
// silently "correct" what someone typed — it shows them the objection.

export default function SaleRecordForm({ farmId, cycleId, currency, onDone }) {
  // One farm's records are all demo or all real; an untagged write defaults to real
  // and 409s on a seeded farm.
  const demoTag = useDemoTag(farmId);
  const [form, setForm] = useState({
    sale_date: "",
    quantity: "",
    unit: "lb",
    unit_price: "",
    gross_amount: "",
    deductions_amount: "",
    buyer_name: "",
    reference: "",
    grade: "",
    market: "fresh",
    notes: "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const num = (v) => (v === "" ? null : Number(v));

  // Shown as a hint only. The stored gross is whatever the settlement states; this
  // just lets someone see the arithmetic before the server checks it.
  const impliedGross =
    form.quantity !== "" && form.unit_price !== ""
      ? Number(form.quantity) * Number(form.unit_price)
      : null;

  async function submit(e) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await api.createSaleRecord(cycleId, {
        ...demoTag,
        sale_date: form.sale_date,
        quantity: num(form.quantity),
        unit: form.unit || null,
        unit_price: num(form.unit_price),
        gross_amount: num(form.gross_amount),
        deductions_amount: num(form.deductions_amount),
        buyer_name: form.buyer_name || null,
        reference: form.reference || null,
        grade: form.grade || null,
        market: form.market || null,
        notes: form.notes || null,
      });
      onDone?.();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Sale / settlement date" required>
          <Input type="date" value={form.sale_date} onChange={set("sale_date")} required />
        </Field>
        <Field label="Buyer">
          <Input value={form.buyer_name} onChange={set("buyer_name")} />
        </Field>
        <Field label="Quantity sold">
          <Input
            type="number"
            step="any"
            min="0"
            value={form.quantity}
            onChange={set("quantity")}
          />
        </Field>
        <Field
          label="Unit"
          hint="A weight unit (lb, kg, t) lets the season total a yield. Trays cannot be combined."
        >
          <Input value={form.unit} onChange={set("unit")} />
        </Field>
        <Field label={`Price per unit${currency ? ` (${currency})` : ""}`}>
          <Input
            type="number"
            step="any"
            min="0"
            value={form.unit_price}
            onChange={set("unit_price")}
          />
        </Field>
        <Field
          label={`Gross amount${currency ? ` (${currency})` : ""}`}
          hint={
            impliedGross !== null
              ? `Quantity x price is ${impliedGross.toLocaleString(undefined, {
                  maximumFractionDigits: 2,
                })}. Leave blank to use that.`
              : "What the crop sold for, before the buyer's deductions."
          }
        >
          <Input
            type="number"
            step="any"
            min="0"
            value={form.gross_amount}
            onChange={set("gross_amount")}
          />
        </Field>
        <Field
          label={`Deductions${currency ? ` (${currency})` : ""}`}
          hint="Commission, freight, cooling — what the buyer withheld. Not a season cost."
        >
          <Input
            type="number"
            step="any"
            min="0"
            value={form.deductions_amount}
            onChange={set("deductions_amount")}
          />
        </Field>
        <Field label="Settlement reference" hint="As printed — what you match against a cheque.">
          <Input value={form.reference} onChange={set("reference")} />
        </Field>
        <Field label="Grade">
          <Input value={form.grade} onChange={set("grade")} />
        </Field>
        <Field label="Market">
          <Input value={form.market} onChange={set("market")} />
        </Field>
      </div>
      <Field label="Notes">
        <Input value={form.notes} onChange={set("notes")} />
      </Field>
      <FormError>{error}</FormError>
      <p className="text-[11px] leading-4 text-muted">
        A recorded transaction only — a market price is never revenue. Sales are
        append-only: a corrected settlement is recorded as a new record that supersedes
        this one, so the revenue you saw before the correction stays readable.
      </p>
      <Button type="submit" disabled={saving || !form.sale_date}>
        {saving ? "Saving…" : "Record sale"}
      </Button>
    </form>
  );
}
