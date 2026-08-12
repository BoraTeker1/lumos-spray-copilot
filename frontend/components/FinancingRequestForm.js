"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { FINANCING_PURPOSE_LABELS } from "@/lib/labels";
import { useDemoTag } from "@/lib/farm-context";
import { Button } from "@/components/ui/button";
import { Field, FormError } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  Sheet,
  SheetTrigger,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
  SheetBody,
  SheetFooter,
} from "@/components/ui/sheet";

// Opening a financing request. Deliberately short: the evidence is assembled from
// records the farm already has, so there is no application form to fill in — which
// is the whole product argument.

export default function FinancingRequestForm({ farmId, cycles = [], policies = [] }) {
  const router = useRouter();
  const demoTag = useDemoTag();
  const [open, setOpen] = useState(false);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    purpose: "input_purchase",
    crop_cycle_id: cycles[0]?.id ? String(cycles[0].id) : "",
    requested_amount: "",
    lender_policy_id: "",
    requested_by: "",
    notes: "",
  });

  function set(key, value) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function submit(e) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const created = await api.createFinancingRequest(farmId, {
        purpose: form.purpose,
        crop_cycle_id: form.crop_cycle_id ? Number(form.crop_cycle_id) : null,
        requested_amount: form.requested_amount
          ? Number(form.requested_amount)
          : null,
        lender_policy_id: form.lender_policy_id
          ? Number(form.lender_policy_id)
          : null,
        requested_by: form.requested_by || null,
        notes: form.notes || null,
        ...demoTag,
      });
      setOpen(false);
      router.push(`/financing/${created.id}`);
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button>Request financing</Button>
      </SheetTrigger>
      <SheetContent padded={false}>
        <SheetHeader>
          <SheetTitle>Request financing</SheetTitle>
          <SheetDescription>
            Lumos assembles the evidence a lender asks for from records this farm
            already keeps. Nothing here is an application, and Lumos makes no credit
            decision.
          </SheetDescription>
        </SheetHeader>
        <form onSubmit={submit}>
          <SheetBody className="space-y-4">
            <Field label="Purpose" required>
              <Select
                value={form.purpose}
                onChange={(e) => set("purpose", e.target.value)}
              >
                {Object.entries(FINANCING_PURPOSE_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </Select>
            </Field>

            {cycles.length > 0 && (
              <Field
                label="Season"
                hint="Optional — a need may span seasons."
              >
                <Select
                  value={form.crop_cycle_id}
                  onChange={(e) => set("crop_cycle_id", e.target.value)}
                >
                  <option value="">Not tied to one season</option>
                  {cycles.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.season_label || `${c.crop} ${c.season_year}`}
                    </option>
                  ))}
                </Select>
              </Field>
            )}

            <Field label="Amount requested">
              <Input
                type="number"
                min="0"
                step="0.01"
                value={form.requested_amount}
                onChange={(e) => set("requested_amount", e.target.value)}
              />
            </Field>

            {policies.length > 0 && (
              <Field
                label="Lender criteria"
                hint="Reads your recorded evidence against a lender's written policy. Lumos never authors one."
              >
                <Select
                  value={form.lender_policy_id}
                  onChange={(e) => set("lender_policy_id", e.target.value)}
                >
                  <option value="">No lender selected yet</option>
                  {policies.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.lender} — {p.policy_version}
                    </option>
                  ))}
                </Select>
              </Field>
            )}

            <Field label="Requested by">
              <Input
                value={form.requested_by}
                onChange={(e) => set("requested_by", e.target.value)}
              />
            </Field>

            <Field label="Notes">
              <Textarea
                rows={3}
                value={form.notes}
                onChange={(e) => set("notes", e.target.value)}
              />
            </Field>

            {error && <FormError>{error}</FormError>}
          </SheetBody>
          <SheetFooter>
            <Button type="submit" disabled={saving}>
              {saving ? "Opening…" : "Open request"}
            </Button>
          </SheetFooter>
        </form>
      </SheetContent>
    </Sheet>
  );
}
