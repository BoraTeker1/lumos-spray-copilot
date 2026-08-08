"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ShoppingCart } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeaderBar,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { Input, fieldClass } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

const CATEGORIES = [
  "fungicide", "insecticide", "herbicide", "miticide", "fertilizer", "adjuvant",
  "other",
];

// Create a draft input plan with its first item. When `plannedSpray` is passed
// (the decisions-page "Request supplier quotes" action) the item is prefilled
// from the reviewed decision and linked via planned_spray_id — the server
// enforces procurement eligibility; this form never re-derives it.
export default function InputPlanForm({
  farmId,
  plannedSpray = null,
  triggerLabel = "Build input plan",
  // "secondary" suits an inline card action; a page header's primary CTA
  // passes "default" so it matches every other page's primary button.
  triggerVariant = "secondary",
  onCreated,
}) {
  const router = useRouter();
  const emptyForm = {
    product_name: plannedSpray?.outcome_product_name || plannedSpray?.product_name || "",
    category: "other",
    active_ingredient:
      plannedSpray?.outcome_active_ingredient || plannedSpray?.active_ingredient || "",
    quantity: "",
    unit: "",
    acres: plannedSpray?.treated_acres ?? "",
    needed_by_date: plannedSpray?.intended_date || "",
    field_block: plannedSpray?.field_block || "",
    crop: plannedSpray?.crop || "",
    intended_use: plannedSpray?.target_pest_or_disease || "",
    estimated_cost: plannedSpray?.estimated_cost ?? "",
    notes: "",
    requested_by: "",
    financing_requested: false,
    financing_notes: "",
  };

  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const set = (field) => (e) =>
    setForm((f) => ({
      ...f,
      [field]: e.target.type === "checkbox" ? e.target.checked : e.target.value,
    }));

  async function submit(e) {
    e.preventDefault();
    if (!form.product_name.trim() || !form.quantity || !form.unit.trim() || !form.needed_by_date) {
      setError("Product, quantity, unit, and needed-by date are required.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const plan = await api.createInputPlan(farmId, {
        requested_by: form.requested_by || null,
        financing_requested: form.financing_requested,
        financing_requested_by: form.financing_requested ? form.requested_by || null : null,
        financing_notes: form.financing_requested ? form.financing_notes || null : null,
        items: [
          {
            planned_spray_id: plannedSpray?.id ?? null,
            product_name: form.product_name,
            category: form.category,
            active_ingredient: form.active_ingredient || null,
            quantity: Number(form.quantity),
            unit: form.unit,
            acres: form.acres === "" ? null : Number(form.acres),
            needed_by_date: form.needed_by_date,
            field_block: form.field_block || null,
            crop: form.crop || null,
            intended_use: form.intended_use || null,
            estimated_cost: form.estimated_cost === "" ? null : Number(form.estimated_cost),
            notes: form.notes || null,
            created_by: form.requested_by || null,
          },
        ],
      });
      setOpen(false);
      setForm(emptyForm);
      if (onCreated) await onCreated(plan);
      router.push(`/inputs/plans/${plan.id}`);
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    // A side drawer rather than a centred dialog: this form is long, and the
    // pinned footer keeps "Create draft plan" reachable without scrolling past
    // the fields.
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button variant={triggerVariant}>
          <ShoppingCart />
          {triggerLabel}
        </Button>
      </SheetTrigger>
      <SheetContent padded={false}>
        <SheetHeaderBar>
          <SheetTitle>New input plan</SheetTitle>
          <SheetDescription className="mt-1">
            {plannedSpray
              ? `Prefilled from decision #${plannedSpray.id}. The plan starts as a draft — submit it for quotes when it's ready.`
              : "A draft plan for what this farm expects to purchase. Submit it for quotes when it's ready."}
          </SheetDescription>
        </SheetHeaderBar>
        <form onSubmit={submit} className="flex min-h-0 flex-1 flex-col">
          <SheetBody className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <label className="col-span-2 text-xs font-medium text-muted">
              Product *
              <Input value={form.product_name} onChange={set("product_name")} className="mt-1" />
            </label>
            <label className="text-xs font-medium text-muted">
              Category
              <Select value={form.category} onChange={set("category")} className="mt-1">
                {CATEGORIES.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </Select>
            </label>
            <label className="text-xs font-medium text-muted">
              Active ingredient
              <Input value={form.active_ingredient} onChange={set("active_ingredient")} className="mt-1" />
            </label>
            <label className="text-xs font-medium text-muted">
              Quantity *
              <Input type="number" min="0" step="any" value={form.quantity} onChange={set("quantity")} className="mt-1" />
            </label>
            <label className="text-xs font-medium text-muted">
              Unit *
              <Input value={form.unit} onChange={set("unit")} placeholder="oz, lb, gal…" className="mt-1" />
            </label>
            <label className="text-xs font-medium text-muted">
              Acres
              <Input type="number" min="0" step="any" value={form.acres} onChange={set("acres")} className="mt-1" />
            </label>
            <label className="text-xs font-medium text-muted">
              Needed by *
              <Input type="date" value={form.needed_by_date} onChange={set("needed_by_date")} className="mt-1" />
            </label>
            <label className="text-xs font-medium text-muted">
              Field / block
              <Input value={form.field_block} onChange={set("field_block")} className="mt-1" />
            </label>
            <label className="text-xs font-medium text-muted">
              Intended use / target
              <Input value={form.intended_use} onChange={set("intended_use")} className="mt-1" />
            </label>
            <label className="text-xs font-medium text-muted">
              Estimated cost
              <Input type="number" min="0" step="any" value={form.estimated_cost} onChange={set("estimated_cost")} className="mt-1" />
            </label>
            <label className="text-xs font-medium text-muted">
              Requested by
              <Input value={form.requested_by} onChange={set("requested_by")} className="mt-1" />
            </label>
          </div>
          <label className="flex items-start gap-2 rounded-control border border-line bg-canvas p-3 text-xs text-ink">
            <input
              type="checkbox"
              checked={form.financing_requested}
              onChange={set("financing_requested")}
              className="mt-0.5"
            />
            <span>
              <span className="font-medium">Request financing options.</span>{" "}
              Asks the concierge to collect indicative terms alongside cash
              quotes. A request is not an offer, and an offer is never a loan
              approval.
            </span>
          </label>
          {form.financing_requested && (
            <Textarea
              value={form.financing_notes}
              onChange={set("financing_notes")}
              placeholder="Financing notes (optional) — e.g. preferred payment timing"
              className={`${fieldClass} h-16`}
            />
          )}
          {error && <p className="text-sm text-risk-fg">{error}</p>}
          </SheetBody>
          <SheetFooter>
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={saving}>
              {saving ? "Saving…" : "Create draft plan"}
            </Button>
          </SheetFooter>
        </form>
      </SheetContent>
    </Sheet>
  );
}
