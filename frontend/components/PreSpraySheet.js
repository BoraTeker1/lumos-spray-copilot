"use client";

import { useCallback, useRef, useState } from "react";
import { FileText, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { api } from "@/lib/api";
import { useDemoTag, useFarm } from "@/lib/farm-context";
import { formatCost } from "@/lib/format";
import { RECORDED_OUTCOME_LABELS, REVIEW_STATE_LABELS } from "@/lib/labels";
import { RECORDED_OUTCOME_TONES, REVIEW_STATE_TONES, tone } from "@/lib/tones";
import Callout from "@/components/Callout";
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
  epa_reg_no: "",
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

// Renders what a label lookup found, in the label layer's own words. Three states,
// and the distinction between the last two is the whole point of the layer:
//   * promotable  — a PCA verified this label for THIS farm; PHI/REI come from it
//   * on file     — a record exists but nobody verified it; it cannot back a check
//   * nothing     — no record matches this registration number
// The values are shown read-only and are NEVER written into the grower's inputs:
// they are the label's fact, not the grower's, and the input-provenance chain
// records that difference. The backend supersedes them at check time.
function LabelResolutionNote({ resolution }) {
  if (!resolution) return null;

  if (resolution.promotable && resolution.label_record) {
    const r = resolution.label_record;
    return (
      <p className="rounded-control border border-ok-line bg-ok-bg p-2 text-[11px] leading-snug text-ok-fg">
        <span className="font-medium">Verified label found.</span> PHI and REI will come
        from it — you don&apos;t need to type them.
        {r.pre_harvest_interval_days != null && ` PHI ${r.pre_harvest_interval_days} days.`}
        {r.re_entry_interval_hours != null && ` REI ${r.re_entry_interval_hours} hours.`}
      </p>
    );
  }

  const reason = resolution.promotion_blocked_reason || resolution.unresolved_reason;
  if (!reason) return null;
  return (
    <p className="rounded-control border border-line bg-canvas p-2 text-[11px] leading-snug text-muted">
      <span className="font-medium">No verified label for this product yet</span> — {reason}{" "}
      Enter PHI and REI below from the product label.
    </p>
  );
}

// The five recordable outcomes, in display order (labels live in lib/labels.js).
const RECORDABLE_OUTCOMES = [
  "sprayed_as_planned", "changed_product", "delayed", "avoided", "inspected_first",
];
const OUTCOME_VARIANTS = Object.fromEntries(
  Object.entries(RECORDED_OUTCOME_TONES).map(([k, t]) => [k, tone(t).badge])
);
const REVIEW_VARIANTS = Object.fromEntries(
  Object.entries(REVIEW_STATE_TONES).map(([k, t]) => [k, tone(t).badge])
);

const inputCls =
  "w-full rounded-control border border-line px-2.5 py-1.5 text-sm focus:border-leaf-600 focus:outline-none focus:ring-1 focus:ring-leaf-600";

// PCA review controls for one pre-spray decision (approve / edit / reject + comment).
export function DecisionReview({ planned, onChanged }) {
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
    <div className="mt-2 rounded-control border border-line bg-surface p-2.5">
      <div className="mb-1.5 text-xs font-semibold text-ink">
        PCA / agronomist review
        {planned.review_required && (
          <span className="ml-1.5 font-normal text-info-fg">
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
      {error && <p className="mt-1.5 text-sm text-risk-fg">{error}</p>}
    </div>
  );
}

// Records what actually happened in the field (the five real-world outcomes).
export function OutcomeRecorder({ planned, onChanged }) {
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
    // Every field is LABELLED and the pair STACKS. This form renders in a 320px
    // context rail, where two inputs side by side clipped their own placeholders
    // to "Changed to produ" / "…its active ingredi" — and a placeholder that is
    // also the only label disappears the moment someone types.
    <div className="mt-2 space-y-2.5">
      <div className="text-xs font-semibold text-ink">What actually happened?</div>
      <label className="block">
        <span className="mb-1 block text-xs font-medium text-muted">
          Reason <span className="font-normal">(required unless sprayed as planned)</span>
        </span>
        <input
          className={inputCls}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
      </label>
      <label className="block">
        <span className="mb-1 block text-xs font-medium text-muted">
          Outcome date <span className="font-normal">(optional)</span>
        </span>
        <input
          type="date"
          className={inputCls}
          value={outcomeDate}
          onChange={(e) => setOutcomeDate(e.target.value)}
        />
        <span className="mt-1 block text-[11px] text-muted">
          Defaults to today. The server rejects impossible chronology, e.g. an
          application before the intended date.
        </span>
      </label>
      <div className="grid grid-cols-1 gap-2">
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-muted">
            Changed to product <span className="font-normal">(if changed)</span>
          </span>
          <input
            className={inputCls}
            value={changedProduct}
            onChange={(e) => setChangedProduct(e.target.value)}
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-muted">
            Its active ingredient
          </span>
          <input
            className={inputCls}
            value={changedAi}
            onChange={(e) => setChangedAi(e.target.value)}
          />
        </label>
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
        <p className="rounded-control border border-info-line bg-info-bg px-2.5 py-1.5 text-[11px] text-info-fg">
          Applied outcomes unlock after a PCA approves or edits this decision.
        </p>
      )}
      {error && <p className="text-sm text-risk-fg">{error}</p>}
    </div>
  );
}

// Labelled form field. Every control in this panel used its placeholder as its
// only label, so the field name vanished the moment someone typed and the two
// side-by-side inputs in the 320px rail clipped theirs outright. A `*` alone is
// not an accessible required marker, so the word is in the label text too.
function Field({ label, hint, required = false, children }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-ink">
        {label}
        {required && (
          <span className="ml-1 font-normal text-muted">(required)</span>
        )}
      </span>
      {children}
      {hint && <span className="mt-1 block text-[11px] text-muted">{hint}</span>}
    </label>
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
    <li className="rounded-control border border-line bg-surface p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium text-ink">{planned.product_name}</span>
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
      <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-muted">
        <span>
          Intended {planned.intended_date}
          {planned.active_ingredient && ` · ${planned.active_ingredient}`}
          {planned.target_pest_or_disease && ` · target: ${planned.target_pest_or_disease}`}
        </span>
        <Link
          href={`/decisions/${planned.id}`}
          className="inline-flex items-center gap-1 font-medium text-muted underline-offset-2 hover:text-ink hover:underline"
        >
          <FileText className="h-3 w-3" />
          Decision record
        </Link>
      </div>

      <div className="mt-2">
        <DecisionResult planned={planned} compact={compact} />
      </div>

      {planned.review_comment && (
        <p className="mt-2 text-xs text-muted">
          <span className="font-medium">PCA comment{planned.reviewed_by ? ` (${planned.reviewed_by})` : ""}:</span>{" "}
          {planned.review_comment}
        </p>
      )}

      {decided ? (
        <>
          <p className="mt-2 text-xs text-muted">
            <span className="font-medium">
              Recorded outcome: {RECORDED_OUTCOME_LABELS[planned.outcome] || planned.outcome}
              {planned.outcome_product_name && ` → ${planned.outcome_product_name}`}.
            </span>{" "}
            {planned.outcome_reason && `Stated reason: ${planned.outcome_reason}`}
          </p>
          {planned.outcome === "avoided" && planned.estimated_cost != null && (
            <p className="mt-1 rounded-control bg-ok-bg p-2 text-xs text-ok-fg">
              Entered application cost not spent:{" "}
              <span className="font-semibold">
                {formatCost(planned.estimated_cost, country)}
              </span>{" "}
              (entered estimate; yield impact not yet known or measured).
            </p>
          )}
          {planned.follow_up_required && (
            <p className="mt-1 rounded-control border border-warn-line bg-warn-bg p-2 text-xs text-warn-fg">
              Follow-up required ({planned.follow_up_event_count} event
              {planned.follow_up_event_count === 1 ? "" : "s"} so far) — this is not a
              confirmed result until follow-up evidence is recorded.{" "}
              <a
                href={`/decisions/${planned.id}`}
                className="font-medium underline underline-offset-2"
              >
                Record follow-up on the decision record →
              </a>
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
      <p className="text-sm text-muted">
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
  // On a demo farm, records created here are saved as simulated demo data — the
  // backend refuses to mix real and demo records on one farm.
  const demoTag = useDemoTag(farmId);
  // The farm's crop decides WHICH label use applies — a label's directions differ
  // per registered crop, so a lookup without it cannot resolve a record.
  const farm = useFarm(farmId);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(EMPTY);
  const [lastCheck, setLastCheck] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [labelResolution, setLabelResolution] = useState(null);
  // Instrumentation: did this open-session produce a completed check?
  const completedThisSession = useRef(false);

  // Look the product up in the label library when the grower leaves the field.
  // Read-only and advisory: it changes nothing about the submitted values — the
  // backend applies verified label values itself at check time, and reports any
  // disagreement with what was typed. A failed lookup is silent; a label the
  // system does not have is a normal state, not an error worth interrupting for.
  async function lookUpLabel() {
    const epaRegNo = form.epa_reg_no.trim();
    if (!epaRegNo) {
      setLabelResolution(null);
      return;
    }
    try {
      setLabelResolution(
        await api.resolveLabel({ epaRegNo, crop: farm?.crop_type, farmId })
      );
    } catch {
      setLabelResolution(null);
    }
  }

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
        ...demoTag,
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
      setLabelResolution(null);
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
            {demoTag.data_source ? (
              <>
                {" "}
                This is a demo farm — checks you run here are saved as simulated
                demo data, never as pilot evidence.
              </>
            ) : null}
          </SheetDescription>
        </SheetHeader>

        {/* Mobile-first: two required fields + target; everything else is collapsible. */}
        <form onSubmit={submit} className="space-y-3">
          <Field label="Product name" required>
            <input
              className={inputCls}
              required
              value={form.product_name}
              onChange={(e) => update("product_name", e.target.value)}
            />
          </Field>
          {/* The join key to the label library. Without it no label check can run,
              which is why it sits here rather than behind the collapsed section. */}
          <Field label="EPA Reg. No." hint="Unlocks the label checks.">
            <input
              className={inputCls}
              value={form.epa_reg_no}
              onChange={(e) => update("epa_reg_no", e.target.value)}
              onBlur={lookUpLabel}
            />
          </Field>
          <LabelResolutionNote resolution={labelResolution} />
          <Field label="Intended date" required>
            <input
              type="date"
              className={inputCls}
              required
              value={form.intended_date}
              onChange={(e) => update("intended_date", e.target.value)}
            />
          </Field>
          <Field
            label="Target pest / disease"
            hint="Links this check to your scouting evidence."
          >
            <input
              className={inputCls}
              value={form.target_pest_or_disease}
              onChange={(e) => update("target_pest_or_disease", e.target.value)}
            />
          </Field>

          <details className="rounded-control border border-line p-2.5">
            <summary className="cursor-pointer select-none text-xs font-medium text-muted">
              Compliance values — PHI, REI, active ingredient, cost, who entered them
            </summary>
            <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Field label="Active ingredient">
                <input
                  className={inputCls}
                  value={form.active_ingredient}
                  onChange={(e) => update("active_ingredient", e.target.value)}
                />
              </Field>
              <Field label="PHI (days, from label)">
                <input
                  type="number"
                  min="0"
                  className={inputCls}
                  value={form.pre_harvest_interval_days}
                  onChange={(e) => update("pre_harvest_interval_days", e.target.value)}
                />
              </Field>
              <Field label="REI (hours, from label)">
                <input
                  type="number"
                  min="0"
                  className={inputCls}
                  value={form.re_entry_interval_hours}
                  onChange={(e) => update("re_entry_interval_hours", e.target.value)}
                />
              </Field>
              <Field label="Estimated cost">
                <input
                  type="number"
                  step="0.01"
                  className={inputCls}
                  value={form.estimated_cost}
                  onChange={(e) => update("estimated_cost", e.target.value)}
                />
              </Field>
              <Field label="Values entered by">
                <select
                  className={inputCls}
                  value={form.values_source}
                  onChange={(e) => update("values_source", e.target.value)}
                >
                  <option value="grower_entered">Grower</option>
                  <option value="pca_entered">PCA</option>
                </select>
              </Field>
              <Field label="Name of the person entering">
                <input
                  className={inputCls}
                  value={form.values_entered_by}
                  onChange={(e) => update("values_entered_by", e.target.value)}
                />
              </Field>
            </div>
            <p className="mt-1.5 text-[11px] text-muted">
              Only PCA-entered values can make a BLOCK PCA-authorized; grower-entered
              values always yield a provisional result a PCA must confirm. (Verified-label
              grounding requires label data that does not exist in Lumos yet.)
            </p>
          </details>

          {error && <Callout tone="risk">{error}</Callout>}
          {/* The caveat sits ABOVE the button: it qualifies what pressing the
              button will do, and below it was read after the decision to press. */}
          <p className="border-t border-line pt-3 text-[11px] text-muted">
            Leaving PHI, REI, harvest date, or the active ingredient blank never yields an
            APPROVE — checks that can’t run escalate to PCA review.
          </p>
          <Button type="submit" disabled={saving} size="lg" className="w-full">
            {saving ? "Checking…" : "Run the decision check"}
          </Button>
        </form>

        {lastCheck && (
          <div className="mt-4">
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
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
