"use client";

import { useCallback, useRef, useState } from "react";
import { FileText, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { api } from "@/lib/api";
import { formatCost } from "@/lib/format";
import { RECORDED_OUTCOME_LABELS, REVIEW_STATE_LABELS } from "@/lib/labels";
import DecisionResult, { OUTCOME_META } from "@/components/DecisionResult";
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
  values_source: "grower_entered",
  values_entered_by: "",
};

// Required verbatim: PHI/REI values come from the user, not a label database.
const DISCLAIMER =
  "PHI and REI checks use values entered by the user and are not independently " +
  "verified against the current pesticide label.";

// The five recordable outcomes, in display order (labels live in lib/labels.js).
const RECORDABLE_OUTCOMES = [
  "sprayed_as_planned", "changed_product", "delayed", "avoided", "inspected_first",
];
const OUTCOME_VARIANTS = {
  sprayed_as_planned: "neutral",
  changed_product: "indigo",
  delayed: "amber",
  avoided: "green",
  inspected_first: "green",
};
const REVIEW_VARIANTS = { approved: "green", edited: "indigo", rejected: "red" };

const inputCls = "w-full rounded-md border border-gray-300 px-2.5 py-1.5 text-sm";

// PCA review controls for one pre-spray decision (approve / edit / reject + comment).
function DecisionReview({ planned, onChanged }) {
  const [comment, setComment] = useState("");
  const [reviewer, setReviewer] = useState("");
  const [editedAction, setEditedAction] = useState("");
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  async function review(action) {
    if (action === "rejected" && !comment.trim()) {
      setError("A comment is required to reject (say why the decision is wrong).");
      return;
    }
    if (action === "edited" && !editedAction.trim()) {
      setError("Edited guidance text is required.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api.reviewPlannedSpray(planned.id, {
        action,
        review_comment: comment.trim() || null,
        reviewed_by: reviewer.trim() || null,
        pca_next_action: action === "edited" ? editedAction.trim() : null,
      });
      onChanged && (await onChanged());
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mt-2 rounded-md border border-gray-200 bg-white p-2.5">
      <div className="mb-1.5 text-xs font-semibold text-gray-700">
        PCA / agronomist review
        {planned.review_required && (
          <span className="ml-1.5 font-normal text-indigo-700">
            required before this spray can be logged as applied
          </span>
        )}
      </div>
      <div className="grid gap-1.5 sm:grid-cols-2">
        <input
          className={inputCls}
          placeholder="Reviewer name (optional)"
          value={reviewer}
          onChange={(e) => setReviewer(e.target.value)}
        />
        <input
          className={inputCls}
          placeholder="Comment (required to reject)"
          value={comment}
          onChange={(e) => setComment(e.target.value)}
        />
      </div>
      {editing && (
        <textarea
          className={`${inputCls} mt-1.5`}
          rows={2}
          placeholder="Edited guidance — what should happen instead? *"
          value={editedAction}
          onChange={(e) => setEditedAction(e.target.value)}
        />
      )}
      <div className="mt-2 flex flex-wrap gap-2">
        <Button type="button" size="sm" disabled={saving} onClick={() => review("approved")}>
          Approve decision
        </Button>
        {editing ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={saving}
            onClick={() => review("edited")}
          >
            Save edited guidance
          </Button>
        ) : (
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={saving}
            onClick={() => setEditing(true)}
          >
            Edit guidance
          </Button>
        )}
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={saving}
          onClick={() => review("rejected")}
        >
          Reject
        </Button>
      </div>
      {error && <p className="mt-1.5 text-sm text-red-600">{error}</p>}
    </div>
  );
}

// Records what actually happened in the field (the five real-world outcomes).
function OutcomeRecorder({ planned, onChanged }) {
  const [reason, setReason] = useState("");
  const [outcomeDate, setOutcomeDate] = useState("");
  const [changedProduct, setChangedProduct] = useState("");
  const [changedAi, setChangedAi] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  // Server-derived gate (canonical decision_status semantics) — never re-derived here.
  const reviewGateActive = !planned.applied_outcome_allowed;

  async function record(outcome) {
    if (outcome !== "sprayed_as_planned" && !reason.trim()) {
      setError("A reason is required for every outcome except “sprayed as planned”.");
      return;
    }
    if (outcome === "changed_product" && !changedProduct.trim()) {
      setError("Enter the product that was actually applied.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api.updatePlannedSprayOutcome(planned.id, {
        outcome,
        outcome_reason: reason.trim() || null,
        outcome_date: outcomeDate || null,
        outcome_product_name: changedProduct.trim() || null,
        outcome_active_ingredient: changedAi.trim() || null,
      });
      onChanged && (await onChanged());
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mt-2 space-y-1.5">
      <div className="text-xs font-semibold text-gray-700">What actually happened?</div>
      <input
        className={inputCls}
        placeholder="Reason (required unless sprayed as planned)"
        value={reason}
        onChange={(e) => setReason(e.target.value)}
      />
      <label className="block text-xs text-gray-500">
        Outcome date (optional — defaults to today; the server rejects impossible
        chronology, e.g. an application before the intended date)
        <input
          type="date"
          className={inputCls}
          value={outcomeDate}
          onChange={(e) => setOutcomeDate(e.target.value)}
        />
      </label>
      <div className="grid grid-cols-2 gap-1.5">
        <input
          className={inputCls}
          placeholder="Changed to product… (changed product only)"
          value={changedProduct}
          onChange={(e) => setChangedProduct(e.target.value)}
        />
        <input
          className={inputCls}
          placeholder="…its active ingredient"
          value={changedAi}
          onChange={(e) => setChangedAi(e.target.value)}
        />
      </div>
      <div className="flex flex-wrap gap-1.5">
        {RECORDABLE_OUTCOMES.map((outcome) => (
          <Button
            key={outcome}
            type="button"
            variant="outline"
            size="sm"
            disabled={
              saving ||
              (reviewGateActive && ["sprayed_as_planned", "changed_product"].includes(outcome))
            }
            onClick={() => record(outcome)}
          >
            {RECORDED_OUTCOME_LABELS[outcome]}
          </Button>
        ))}
      </div>
      {reviewGateActive && (
        <p className="text-[11px] text-indigo-700">
          Applied outcomes unlock after a PCA approves or edits this decision.
        </p>
      )}
      {error && <p className="text-sm text-red-600">{error}</p>}
    </div>
  );
}

// One planned spray: decision snapshot, review state, and outcome controls.
export function PlannedSprayItem({ planned, onChanged, compact = false, country }) {
  const decided = planned.outcome !== "planned";
  // Server-derived review state: approved / edited / rejected are recorded reviews;
  // "pending" means a required review is still outstanding.
  const reviewed = ["approved", "edited", "rejected"].includes(planned.review_state);
  const meta = OUTCOME_META[planned.decision_outcome];

  return (
    <li className="rounded-lg border border-gray-200 bg-white p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium text-gray-900">{planned.product_name}</span>
        {meta && <Badge variant={meta.badge}>{meta.label}</Badge>}
        {reviewed && (
          <Badge variant={REVIEW_VARIANTS[planned.review_state] || "neutral"}>
            {REVIEW_STATE_LABELS[planned.review_state]}
          </Badge>
        )}
        {decided && (
          <Badge variant={OUTCOME_VARIANTS[planned.outcome] || "neutral"}>
            {RECORDED_OUTCOME_LABELS[planned.outcome] || planned.outcome}
          </Badge>
        )}
      </div>
      <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-gray-500">
        <span>
          Intended {planned.intended_date}
          {planned.active_ingredient && ` · ${planned.active_ingredient}`}
          {planned.target_pest_or_disease && ` · target: ${planned.target_pest_or_disease}`}
        </span>
        <Link
          href={`/decisions/${planned.id}`}
          className="inline-flex items-center gap-1 font-medium text-gray-500 underline-offset-2 hover:text-gray-900 hover:underline"
        >
          <FileText className="h-3 w-3" />
          Decision record
        </Link>
      </div>

      <div className="mt-2">
        <DecisionResult planned={planned} compact={compact} />
      </div>

      {planned.review_comment && (
        <p className="mt-2 text-xs text-gray-600">
          <span className="font-medium">PCA comment{planned.reviewed_by ? ` (${planned.reviewed_by})` : ""}:</span>{" "}
          {planned.review_comment}
        </p>
      )}

      {decided ? (
        <>
          <p className="mt-2 text-xs text-gray-600">
            <span className="font-medium">
              Recorded outcome: {RECORDED_OUTCOME_LABELS[planned.outcome] || planned.outcome}
              {planned.outcome_product_name && ` → ${planned.outcome_product_name}`}.
            </span>{" "}
            {planned.outcome_reason && `Stated reason: ${planned.outcome_reason}`}
          </p>
          {planned.outcome === "avoided" && planned.estimated_cost != null && (
            <p className="mt-1 rounded-md bg-green-50 p-2 text-xs text-green-900">
              Entered application cost not spent:{" "}
              <span className="font-semibold">
                {formatCost(planned.estimated_cost, country)}
              </span>{" "}
              (entered estimate; yield impact not yet known or measured).
            </p>
          )}
        </>
      ) : (
        <>
          {!reviewed && <DecisionReview planned={planned} onChanged={onChanged} />}
          <OutcomeRecorder planned={planned} onChanged={onChanged} />
        </>
      )}
    </li>
  );
}

// Full list of planned sprays for the "Planned sprays" tab.
export function PlannedSprayList({ planned, onChanged, emptyText, compact = false, country }) {
  if (!planned || planned.length === 0) {
    return (
      <p className="text-sm text-gray-500">
        {emptyText || "No pre-spray decisions yet. Run one before the next planned application."}
      </p>
    );
  }
  return (
    <ul className="space-y-3">
      {planned.map((p) => (
        <PlannedSprayItem
          key={p.id}
          planned={p}
          onChanged={onChanged}
          compact={compact}
          country={country}
        />
      ))}
    </ul>
  );
}

// The single dominant CTA: enter an intended spray, get ONE clear outcome
// (approve / block / delay / inspect first / PCA review required), then run the
// review and record the real outcome in the same sheet.
export default function PreSpraySheet({ farmId, onChanged }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(EMPTY);
  const [lastCheck, setLastCheck] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  // Instrumentation: did this open-session produce a completed check?
  const completedThisSession = useRef(false);

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

  function onOpenChange(next) {
    setOpen(next);
    if (next) {
      completedThisSession.current = false;
      api.trackEvent({
        event_type: "check_started",
        farm_id: Number(farmId),
        entry_source: "manual_form",
      });
    } else {
      setError(null);
      if (!completedThisSession.current) {
        api.trackEvent({
          event_type: "check_abandoned",
          farm_id: Number(farmId),
          entry_source: "manual_form",
        });
      }
    }
  }

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
        values_entered_by: form.values_entered_by.trim() || null,
        pre_harvest_interval_days:
          form.pre_harvest_interval_days === "" ? null : Number(form.pre_harvest_interval_days),
        re_entry_interval_hours:
          form.re_entry_interval_hours === "" ? null : Number(form.re_entry_interval_hours),
        estimated_cost: form.estimated_cost === "" ? null : Number(form.estimated_cost),
      });
      completedThisSession.current = true;
      setLastCheck(created);
      setForm(EMPTY);
      onChanged && (await onChanged());
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  async function itemChanged() {
    await refreshLastCheck();
    onChanged && (await onChanged());
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetTrigger asChild>
        <Button>
          <ShieldCheck />
          Check a planned spray
        </Button>
      </SheetTrigger>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>Pre-spray decision check</SheetTitle>
          <SheetDescription>
            Enter a spray you are <em>considering</em> — product and date are enough to start.
            Lumos returns one clear outcome; decision support only, never a prescription.{" "}
            {DISCLAIMER}
          </SheetDescription>
        </SheetHeader>

        {/* Mobile-first: two required fields + target; everything else is collapsible. */}
        <form onSubmit={submit} className="space-y-2.5">
          <input
            className={inputCls}
            placeholder="Product name *"
            required
            value={form.product_name}
            onChange={(e) => update("product_name", e.target.value)}
          />
          <label className="block text-xs text-gray-500">
            Intended date *
            <input
              type="date"
              className={inputCls}
              required
              value={form.intended_date}
              onChange={(e) => update("intended_date", e.target.value)}
            />
          </label>
          <input
            className={inputCls}
            placeholder="Target pest / disease (links scouting evidence)"
            value={form.target_pest_or_disease}
            onChange={(e) => update("target_pest_or_disease", e.target.value)}
          />

          <details className="rounded-md border border-gray-200 p-2.5">
            <summary className="cursor-pointer select-none text-xs font-medium text-gray-600">
              Compliance values — PHI, REI, active ingredient, cost, who entered them
            </summary>
            <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
              <input
                className={inputCls}
                placeholder="Active ingredient"
                value={form.active_ingredient}
                onChange={(e) => update("active_ingredient", e.target.value)}
              />
              <input
                type="number"
                min="0"
                className={inputCls}
                placeholder="PHI (days, from label)"
                value={form.pre_harvest_interval_days}
                onChange={(e) => update("pre_harvest_interval_days", e.target.value)}
              />
              <input
                type="number"
                min="0"
                className={inputCls}
                placeholder="REI (hours, from label)"
                value={form.re_entry_interval_hours}
                onChange={(e) => update("re_entry_interval_hours", e.target.value)}
              />
              <input
                type="number"
                step="0.01"
                className={inputCls}
                placeholder="Estimated cost"
                value={form.estimated_cost}
                onChange={(e) => update("estimated_cost", e.target.value)}
              />
              <select
                className={inputCls}
                value={form.values_source}
                onChange={(e) => update("values_source", e.target.value)}
              >
                <option value="grower_entered">Values entered by grower</option>
                <option value="pca_entered">Values entered by PCA</option>
              </select>
              <input
                className={inputCls}
                placeholder="Entered by (name)"
                value={form.values_entered_by}
                onChange={(e) => update("values_entered_by", e.target.value)}
              />
            </div>
            <p className="mt-1.5 text-[11px] text-gray-400">
              Only PCA-entered values can make a BLOCK PCA-authorized; grower-entered
              values always yield a provisional result a PCA must confirm. (Verified-label
              grounding requires label data that does not exist in Lumos yet.)
            </p>
          </details>

          {error && <p className="text-sm text-red-600">{error}</p>}
          <Button type="submit" disabled={saving} className="w-full sm:w-auto">
            {saving ? "Checking…" : "Run the decision check"}
          </Button>
          <p className="text-[11px] text-gray-400">
            Leaving PHI, REI, harvest date, or the active ingredient blank never yields an
            APPROVE — checks that can’t run escalate to PCA review.
          </p>
        </form>

        {lastCheck && (
          <div className="mt-4">
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
              Decision
            </h4>
            <ul>
              <PlannedSprayItem planned={lastCheck} onChanged={itemChanged} />
            </ul>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
