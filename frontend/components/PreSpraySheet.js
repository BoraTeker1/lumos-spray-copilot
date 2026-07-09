"use client";

import { useCallback, useEffect, useState } from "react";
import { ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import RiskBadge from "@/components/RiskBadge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";

const EMPTY = {
  product_name: "",
  active_ingredient: "",
  target_pest_or_disease: "",
  intended_date: "",
  pre_harvest_interval_days: "",
  re_entry_interval_hours: "",
  estimated_cost: "",
};

// Required verbatim: PHI/REI values come from the user, not a label database.
const DISCLAIMER =
  "PHI and REI checks use values entered by the user and are not independently " +
  "verified against the current pesticide label.";

const OUTCOME_LABELS = { sprayed: "Sprayed", skipped: "Skipped", postponed: "Postponed" };
const OUTCOME_VARIANTS = { sprayed: "neutral", skipped: "green", postponed: "amber" };

// One planned spray with its check snapshot and outcome controls.
export function PlannedSprayItem({ planned, onChanged }) {
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  async function record(outcome) {
    if ((outcome === "skipped" || outcome === "postponed") && !reason.trim()) {
      setError("A reason is required when skipping or postponing.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api.updatePlannedSprayOutcome(planned.id, {
        outcome,
        outcome_reason: reason.trim() || null,
      });
      onChanged && (await onChanged());
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  const decided = planned.outcome !== "planned";

  return (
    <li className="rounded-lg border border-gray-200 bg-white p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium text-gray-900">{planned.product_name}</span>
        <RiskBadge level={planned.check_risk_level} />
        {decided && (
          <Badge variant={OUTCOME_VARIANTS[planned.outcome] || "neutral"}>
            {OUTCOME_LABELS[planned.outcome] || planned.outcome}
          </Badge>
        )}
      </div>
      <div className="mt-0.5 text-xs text-gray-500">
        Intended {planned.intended_date}
        {planned.active_ingredient && ` · ${planned.active_ingredient}`}
        {planned.target_pest_or_disease && ` · target: ${planned.target_pest_or_disease}`}
      </div>
      <pre className="mt-2 whitespace-pre-wrap rounded-md bg-gray-50 p-2.5 font-sans text-xs leading-relaxed text-gray-700">
        {planned.check_text}
      </pre>
      {decided ? (
        planned.outcome_reason && (
          <p className="mt-2 text-xs text-gray-600">Stated reason: {planned.outcome_reason}</p>
        )
      ) : (
        <div className="mt-2 space-y-2">
          <input
            className="w-full rounded-md border border-gray-300 px-2.5 py-1.5 text-sm"
            placeholder="Reason (required for skipped / postponed)"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <div className="flex gap-2">
            {Object.keys(OUTCOME_LABELS).map((outcome) => (
              <Button
                key={outcome}
                type="button"
                variant="outline"
                size="sm"
                disabled={saving}
                onClick={() => record(outcome)}
              >
                {OUTCOME_LABELS[outcome]}
              </Button>
            ))}
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
        </div>
      )}
    </li>
  );
}

// Full list of planned sprays for the "Planned sprays" tab.
export function PlannedSprayList({ planned, onChanged, emptyText }) {
  if (!planned || planned.length === 0) {
    return (
      <p className="text-sm text-gray-500">
        {emptyText || "No pre-spray checks yet. Run one before the next planned application."}
      </p>
    );
  }
  return (
    <ul className="space-y-3">
      {planned.map((p) => (
        <PlannedSprayItem key={p.id} planned={p} onChanged={onChanged} />
      ))}
    </ul>
  );
}

// The single dominant CTA: enter an intended spray in a right-side sheet, see
// the cautious check result, and record the real outcome in the same sheet.
export default function PreSpraySheet({ farmId, onChanged }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(EMPTY);
  const [lastCheck, setLastCheck] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const refreshLastCheck = useCallback(async () => {
    if (!lastCheck) return;
    try {
      const list = await api.listPlannedSprays(farmId);
      const updated = list.find((p) => p.id === lastCheck.id);
      if (updated) setLastCheck(updated);
    } catch {
      /* list refresh is best-effort; the page reload below still runs */
    }
  }, [farmId, lastCheck]);

  useEffect(() => {
    if (!open) {
      setError(null);
    }
  }, [open]);

  function update(field, value) {
    setForm((f) => ({ ...f, [field]: value }));
  }

  async function submit(e) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const created = await api.createPlannedSpray(farmId, {
        ...form,
        pre_harvest_interval_days:
          form.pre_harvest_interval_days === "" ? null : Number(form.pre_harvest_interval_days),
        re_entry_interval_hours:
          form.re_entry_interval_hours === "" ? null : Number(form.re_entry_interval_hours),
        estimated_cost: form.estimated_cost === "" ? null : Number(form.estimated_cost),
      });
      setLastCheck(created);
      setForm(EMPTY);
      onChanged && (await onChanged());
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  async function outcomeChanged() {
    await refreshLastCheck();
    onChanged && (await onChanged());
  }

  const input = "w-full rounded-md border border-gray-300 px-2.5 py-1.5 text-sm";

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button>
          <ShieldCheck />
          Check a planned spray
        </Button>
      </SheetTrigger>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>Pre-spray check</SheetTitle>
          <SheetDescription>
            Enter a spray you are <em>considering</em>. Lumos checks it against recent chemistry,
            harvest timing, and scouting evidence — decision support only, never a prescription.{" "}
            {DISCLAIMER}
          </SheetDescription>
        </SheetHeader>

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
              placeholder="Target pest / disease"
              value={form.target_pest_or_disease}
              onChange={(e) => update("target_pest_or_disease", e.target.value)}
            />
            <label className="text-xs text-gray-500">
              Intended date *
              <input
                type="date"
                className={input}
                required
                value={form.intended_date}
                onChange={(e) => update("intended_date", e.target.value)}
              />
            </label>
            <input
              type="number"
              min="0"
              className={input}
              placeholder="PHI (days, from label)"
              value={form.pre_harvest_interval_days}
              onChange={(e) => update("pre_harvest_interval_days", e.target.value)}
            />
            <input
              type="number"
              min="0"
              className={input}
              placeholder="REI (hours, from label)"
              value={form.re_entry_interval_hours}
              onChange={(e) => update("re_entry_interval_hours", e.target.value)}
            />
            <input
              type="number"
              step="0.01"
              className={input}
              placeholder="Estimated cost"
              value={form.estimated_cost}
              onChange={(e) => update("estimated_cost", e.target.value)}
            />
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <Button type="submit" disabled={saving}>
            {saving ? "Checking…" : "Check this spray"}
          </Button>
        </form>

        {lastCheck && (
          <div className="mt-4">
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
              Check result
            </h4>
            <ul>
              <PlannedSprayItem planned={lastCheck} onChanged={outcomeChanged} />
            </ul>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
