"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import RiskBadge from "@/components/RiskBadge";

const EMPTY = {
  product_name: "",
  active_ingredient: "",
  target_pest_or_disease: "",
  intended_date: "",
  pre_harvest_interval_days: "",
  re_entry_interval_hours: "",
  estimated_cost: "",
};

const DISCLAIMER =
  "PHI and REI checks use values entered by the user and are not independently " +
  "verified against the current pesticide label.";

const OUTCOME_LABELS = { sprayed: "Sprayed", skipped: "Skipped", postponed: "Postponed" };

// One planned spray with its check snapshot and outcome controls.
function PlannedSprayItem({ planned, onChanged }) {
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
    <li className="rounded border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{planned.product_name}</span>
        <RiskBadge level={planned.check_risk_level} />
        {decided && (
          <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-700">
            {OUTCOME_LABELS[planned.outcome] || planned.outcome}
          </span>
        )}
      </div>
      <div className="mt-0.5 text-xs text-gray-500">
        Intended {planned.intended_date}
        {planned.active_ingredient && ` · ${planned.active_ingredient}`}
        {planned.target_pest_or_disease && ` · target: ${planned.target_pest_or_disease}`}
      </div>
      <pre className="mt-2 whitespace-pre-wrap rounded bg-gray-50 p-2 text-xs text-gray-700">
        {planned.check_text}
      </pre>
      {decided ? (
        planned.outcome_reason && (
          <p className="mt-2 text-xs text-gray-600">
            Stated reason: {planned.outcome_reason}
          </p>
        )
      ) : (
        <div className="mt-2 space-y-2">
          <input
            className="w-full rounded border px-2 py-1 text-sm"
            placeholder="Reason (required for skipped / postponed)"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <div className="flex gap-2">
            {Object.keys(OUTCOME_LABELS).map((outcome) => (
              <button
                key={outcome}
                type="button"
                disabled={saving}
                onClick={() => record(outcome)}
                className="rounded border px-3 py-1 text-sm hover:border-leaf disabled:opacity-50"
              >
                {OUTCOME_LABELS[outcome]}
              </button>
            ))}
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
        </div>
      )}
    </li>
  );
}

// Pre-spray decision check: enter an intended spray, see cautious flags before it
// happens, then record what was actually decided (sprayed / skipped / postponed).
export default function PreSprayCheckCard({ farmId, onChanged }) {
  const [planned, setPlanned] = useState([]);
  const [form, setForm] = useState(EMPTY);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    try {
      setPlanned(await api.listPlannedSprays(farmId));
    } catch (err) {
      setError(err.message);
    }
  }, [farmId]);

  useEffect(() => {
    load();
  }, [load]);

  function update(field, value) {
    setForm((f) => ({ ...f, [field]: value }));
  }

  async function submit(e) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await api.createPlannedSpray(farmId, {
        ...form,
        pre_harvest_interval_days:
          form.pre_harvest_interval_days === ""
            ? null
            : Number(form.pre_harvest_interval_days),
        re_entry_interval_hours:
          form.re_entry_interval_hours === ""
            ? null
            : Number(form.re_entry_interval_hours),
        estimated_cost:
          form.estimated_cost === "" ? null : Number(form.estimated_cost),
      });
      setForm(EMPTY);
      await load();
      onChanged && (await onChanged());
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  async function changed() {
    await load();
    onChanged && (await onChanged());
  }

  const input = "w-full rounded border px-2 py-1 text-sm";

  return (
    <div>
      <h2 className="font-semibold">🛑 Pre-spray check — before you spray</h2>
      <p className="mt-1 text-xs text-gray-500">
        Enter a spray you are <em>considering</em>. Lumos checks it against recent
        chemistry, harvest timing, and scouting evidence — decision support only, never a
        prescription. {DISCLAIMER}
      </p>

      <form onSubmit={submit} className="mt-3 space-y-2">
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
        <button
          type="submit"
          disabled={saving}
          className="rounded bg-leaf px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
        >
          {saving ? "Checking…" : "Check this spray"}
        </button>
      </form>

      {planned.length > 0 && (
        <ul className="mt-4 space-y-3 text-sm">
          {planned.map((p) => (
            <PlannedSprayItem key={p.id} planned={p} onChanged={changed} />
          ))}
        </ul>
      )}
    </div>
  );
}
