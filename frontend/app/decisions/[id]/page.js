"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Printer } from "lucide-react";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

// One-page printable/shareable decision record for a single pre-spray check:
// inputs, every rule with its calculation and source authority, missing data,
// the PCA review, the final recorded outcome, and the disclaimers.
// Print via the button (app chrome is hidden in print).
// NOTE: this page is the always-expanded print/audit surface — unlike the in-app
// DecisionResult card it deliberately collapses nothing.

import {
  AUTHORITY_SOURCE_LABELS,
  DECISION_OUTCOME_LABELS,
  RECORDED_OUTCOME_LABELS,
  REVIEW_STATE_LABELS,
  decisionAuthorityLabel,
  isProvisionalAuthority,
} from "@/lib/labels";
import { formatArea, formatCost } from "@/lib/format";

function Section({ title, children }) {
  return (
    <section className="break-inside-avoid">
      <h2 className="mb-1.5 border-b border-gray-200 pb-1 text-sm font-semibold text-gray-900">
        {title}
      </h2>
      {children}
    </section>
  );
}

function Row({ label, value }) {
  return (
    <div className="flex justify-between gap-3 py-0.5 text-sm">
      <span className="text-gray-500">{label}</span>
      <span className="text-right font-medium text-gray-900">{value ?? "—"}</span>
    </div>
  );
}

// Compact badge colors for field-level provenance source types.
const SOURCE_TYPE_LABELS = {
  demo: "Demo (simulated)",
  user_entered: "User entered",
  imported_unverified: "Imported, unverified",
  pca_verified: "PCA verified",
  authoritative_provider: "Verified (authoritative provider)",
};
const SOURCE_TYPE_BADGE = {
  pca_verified: "green",
  authoritative_provider: "green",
  imported_unverified: "amber",
  user_entered: "outline",
  demo: "outline",
};

const FOLLOW_UP_TYPES = [
  { value: "scouting_observation", label: "Scouting observation" },
  { value: "actual_application", label: "Actual application" },
  { value: "rescue_application", label: "Rescue application" },
  { value: "harvest_outcome", label: "Harvest outcome" },
  { value: "yield_quality_outcome", label: "Yield / quality outcome" },
  { value: "note", label: "Note" },
];

function FollowUpForm({ plannedId, onAdded }) {
  const [form, setForm] = useState({
    event_type: "scouting_observation",
    observed_at: new Date().toISOString().slice(0, 10),
    severity: "",
    actual_product: "",
    cost: "",
    rescue_required: false,
    yield_impact: "",
    quality_impact: "",
    evidence_notes: "",
    entered_by: "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (k) => (e) =>
    setForm({ ...form, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.addFollowUpEvent(plannedId, {
        event_type: form.event_type,
        observed_at: form.observed_at,
        severity: form.severity === "" ? null : Number(form.severity),
        severity_scale: form.severity === "" ? null : "1-5",
        actual_product: form.actual_product || null,
        cost: form.cost === "" ? null : Number(form.cost),
        rescue_required: ["rescue_application"].includes(form.event_type)
          ? true
          : form.rescue_required,
        yield_impact: form.yield_impact || null,
        quality_impact: form.quality_impact || null,
        evidence_notes: form.evidence_notes || null,
        entered_by: form.entered_by || null,
      });
      onAdded && (await onAdded());
      setForm({ ...form, severity: "", actual_product: "", cost: "", evidence_notes: "" });
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const needsProduct = ["actual_application", "rescue_application"].includes(form.event_type);
  return (
    <form onSubmit={submit} className="no-print mt-2 space-y-2 rounded-md border bg-gray-50 p-3">
      <p className="text-xs font-medium text-gray-700">
        Add follow-up event (append-only — events are never edited or deleted)
      </p>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        <select className="rounded border border-gray-300 px-2 py-1 text-xs" value={form.event_type} onChange={set("event_type")}>
          {FOLLOW_UP_TYPES.map((t) => (
            <option key={t.value} value={t.value}>{t.label}</option>
          ))}
        </select>
        <input type="date" className="rounded border border-gray-300 px-2 py-1 text-xs" value={form.observed_at} onChange={set("observed_at")} />
        {form.event_type === "scouting_observation" && (
          <input type="number" min="0" max="5" placeholder="Severity (1-5)" className="rounded border border-gray-300 px-2 py-1 text-xs" value={form.severity} onChange={set("severity")} />
        )}
        {needsProduct && (
          <input placeholder="Product applied" className="rounded border border-gray-300 px-2 py-1 text-xs" value={form.actual_product} onChange={set("actual_product")} />
        )}
        <input type="number" step="0.01" placeholder="Cost (optional)" className="rounded border border-gray-300 px-2 py-1 text-xs" value={form.cost} onChange={set("cost")} />
        {["harvest_outcome", "yield_quality_outcome"].includes(form.event_type) && (
          <>
            <select className="rounded border border-gray-300 px-2 py-1 text-xs" value={form.yield_impact} onChange={set("yield_impact")}>
              <option value="">Yield impact: unknown</option>
              <option value="positive">Yield: positive</option>
              <option value="neutral">Yield: neutral</option>
              <option value="negative">Yield: negative</option>
            </select>
            <select className="rounded border border-gray-300 px-2 py-1 text-xs" value={form.quality_impact} onChange={set("quality_impact")}>
              <option value="">Quality impact: unknown</option>
              <option value="positive">Quality: positive</option>
              <option value="neutral">Quality: neutral</option>
              <option value="negative">Quality: negative</option>
            </select>
          </>
        )}
        <input placeholder="Entered by" className="rounded border border-gray-300 px-2 py-1 text-xs" value={form.entered_by} onChange={set("entered_by")} />
      </div>
      <textarea rows={2} placeholder="Evidence notes (what was actually seen/done)" className="w-full rounded border border-gray-300 px-2 py-1 text-xs" value={form.evidence_notes} onChange={set("evidence_notes")} />
      <Button type="submit" size="sm" disabled={busy}>
        {busy ? "Saving…" : "Append event"}
      </Button>
      {error && <p className="text-xs text-red-600">{error}</p>}
    </form>
  );
}

export default function DecisionRecordPage({ params }) {
  const [planned, setPlanned] = useState(null);
  const [farm, setFarm] = useState(null);
  const [inputValues, setInputValues] = useState([]);
  const [auditEvents, setAuditEvents] = useState([]);
  const [followUps, setFollowUps] = useState([]);
  const [error, setError] = useState(null);

  async function loadTrail(id) {
    const [values, audit, events] = await Promise.all([
      api.listInputValues(id),
      api.listAuditEvents(id),
      api.listFollowUpEvents(id),
    ]);
    setInputValues(values);
    setAuditEvents(audit);
    setFollowUps(events);
  }

  useEffect(() => {
    api
      .getPlannedSpray(params.id)
      .then(async (p) => {
        setPlanned(p);
        setFarm(await api.getFarm(p.farm_id));
        await loadTrail(p.id);
      })
      .catch((err) => setError(err.message));
  }, [params.id]);

  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (!planned || !farm) return <p className="text-sm text-gray-500">Loading decision record…</p>;

  const payload = planned.decision_payload || {};
  const rules = payload.rules || [];
  const provisional = isProvisionalAuthority(planned.decision_authority);
  const isDemo = planned.data_source === "demo" || planned.data_confidence === "simulated";

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      {/* Hide app chrome when printing; keep only the record. */}
      <style>{`@media print { aside, header, footer, .no-print { display: none !important; } main { padding: 0 !important; } }`}</style>

      <div className="no-print flex items-center justify-between gap-2">
        <Link
          href={`/farms/${planned.farm_id}?tab=planned`}
          className="inline-flex items-center gap-1 text-xs text-gray-500 hover:text-gray-900"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Back to {farm.name}
        </Link>
        <Button type="button" size="sm" onClick={() => window.print()}>
          <Printer />
          Print / save as PDF
        </Button>
      </div>

      <div className="rounded-lg border border-gray-200 bg-white p-6 print:border-0 print:p-0">
        {/* Header */}
        <div className="flex flex-wrap items-start justify-between gap-2 border-b border-gray-200 pb-3">
          <div>
            <h1 className="text-base font-semibold text-gray-900">
              Pre-spray decision record #{planned.id}
            </h1>
            <p className="mt-0.5 text-xs text-gray-500">
              {farm.name} · {farm.location} · generated by Lumos Spray Copilot
            </p>
          </div>
          <div className="flex flex-col items-end gap-1">
            <Badge
              variant={
                planned.decision_outcome === "block"
                  ? "red"
                  : planned.decision_outcome === "approve"
                  ? "green"
                  : "amber"
              }
            >
              {provisional && ["approve", "block"].includes(planned.decision_outcome)
                ? "PROVISIONAL "
                : ""}
              {DECISION_OUTCOME_LABELS[planned.decision_outcome] || planned.decision_outcome}
            </Badge>
            <Badge variant={provisional ? "amber" : "green"}>
              {decisionAuthorityLabel(planned.decision_authority)}
            </Badge>
            {isDemo && <Badge variant="outline">Simulated demo record</Badge>}
          </div>
        </div>

        <div className="mt-4 space-y-5">
          <Section title="Inputs used">
            <div className="grid gap-x-8 sm:grid-cols-2">
              <Row label="Product" value={planned.product_name} />
              <Row label="Active ingredient" value={planned.active_ingredient} />
              <Row label="Target pest / disease" value={planned.target_pest_or_disease} />
              <Row label="Intended date" value={planned.intended_date} />
              <Row label="Entered PHI (days)" value={planned.pre_harvest_interval_days} />
              <Row label="Entered REI (hours)" value={planned.re_entry_interval_hours} />
              <Row label="Expected harvest" value={farm.expected_harvest_date} />
              <Row
                label="PHI/REI values source"
                value={`${AUTHORITY_SOURCE_LABELS[planned.values_source] || planned.values_source}${
                  planned.values_entered_by ? ` (${planned.values_entered_by})` : ""
                }`}
              />
            </div>
            {planned.harvest_date_changed_since_check && (
              <p className="mt-1.5 rounded border border-amber-300 bg-amber-50 p-2 text-xs text-amber-900">
                The farm&apos;s expected harvest date has changed since this check ran —
                the calculations in this record use the harvest date entered at check
                time. Re-run the check before relying on this decision.
              </p>
            )}
          </Section>

          <Section title="Checks performed">
            <ul className="space-y-2">
              {rules.map((r) => (
                <li key={r.rule_id} className="text-sm">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className={r.triggered ? "font-semibold text-red-800" : "font-medium text-gray-900"}>
                      {r.triggered ? "⚠" : "✓"} {r.name}
                    </span>
                    <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-600">
                      {AUTHORITY_SOURCE_LABELS[r.source_authority] || r.source_authority} ·{" "}
                      {r.verification_status}
                      {r.entered_by ? ` · ${r.entered_by}` : ""}
                    </span>
                  </div>
                  <p className="mt-0.5 text-xs text-gray-700">{r.detail}</p>
                  {r.calculation && (
                    <p className="mt-0.5 font-mono text-[11px] text-gray-500">
                      {r.calculation}
                    </p>
                  )}
                </li>
              ))}
            </ul>
            {payload.authority_basis && (
              <p className="mt-2 text-xs text-gray-600">{payload.authority_basis}</p>
            )}
          </Section>

          {(payload.missing_information || []).length > 0 && (
            <Section title="Missing information">
              <ul className="list-disc space-y-0.5 pl-5 text-xs text-gray-700">
                {payload.missing_information.map((m, i) => (
                  <li key={i}>{m}</li>
                ))}
              </ul>
            </Section>
          )}

          <Section title="PCA / agronomist review">
            <div className="grid gap-x-8 sm:grid-cols-2">
              <Row
                label="Review status"
                value={REVIEW_STATE_LABELS[planned.review_state] || planned.review_state}
              />
              <Row label="Reviewed by" value={planned.reviewed_by} />
              <Row
                label="Reviewed on"
                value={planned.reviewed_at ? planned.reviewed_at.slice(0, 10) : null}
              />
            </div>
            {planned.review_comment && (
              <p className="mt-1 text-sm text-gray-700">
                <span className="font-medium">Comment:</span> {planned.review_comment}
              </p>
            )}
            {planned.pca_next_action && (
              <p className="mt-1 rounded bg-indigo-50 p-2 text-sm text-indigo-900">
                <span className="font-semibold">PCA guidance:</span> {planned.pca_next_action}
              </p>
            )}
          </Section>

          <Section title="Final recorded outcome">
            <div className="grid gap-x-8 sm:grid-cols-2">
              <Row
                label="Outcome"
                value={RECORDED_OUTCOME_LABELS[planned.outcome] || planned.outcome}
              />
              <Row label="Recorded on" value={planned.outcome_date} />
              {planned.outcome_product_name && (
                <Row label="Product actually applied" value={planned.outcome_product_name} />
              )}
              {planned.outcome_active_ingredient && (
                <Row label="Its active ingredient" value={planned.outcome_active_ingredient} />
              )}
            </div>
            {planned.outcome_reason && (
              <p className="mt-1 text-sm text-gray-700">
                <span className="font-medium">Stated reason:</span> {planned.outcome_reason}
              </p>
            )}
            {planned.outcome === "avoided" && planned.estimated_cost != null && (
              <p className="mt-1.5 rounded bg-green-50 p-2 text-sm text-green-900">
                Entered application cost not spent:{" "}
                <span className="font-semibold">
                  {formatCost(planned.estimated_cost, farm.country)}
                </span>
                {farm.greenhouse_area != null && (
                  <> · planned across {formatArea(farm.greenhouse_area, farm.country)}</>
                )}
                <span className="text-xs text-green-800">
                  {" "}
                  (entered estimate; yield impact not yet known or measured)
                </span>
              </p>
            )}
          </Section>

          {inputValues.length > 0 && (
            <Section title="Input provenance (field-level, append-only)">
              <div className="overflow-x-auto">
                <table className="w-full text-left text-[11px]">
                  <thead>
                    <tr className="text-gray-500">
                      <th className="py-1 pr-3 font-medium">Field</th>
                      <th className="py-1 pr-3 font-medium">Value</th>
                      <th className="py-1 pr-3 font-medium">Source</th>
                      <th className="py-1 font-medium">Verified by</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(() => {
                      const supersededIds = new Set(
                        inputValues.map((v) => v.supersedes_input_value_id).filter(Boolean)
                      );
                      return inputValues.map((v) => {
                        const superseded = supersededIds.has(v.id);
                        return (
                          <tr
                            key={v.id}
                            className={`border-t border-gray-100 ${superseded ? "text-gray-400 line-through" : ""}`}
                          >
                            <td className="py-1 pr-3 font-mono">{v.field_name}</td>
                            <td className="py-1 pr-3">
                              {v.raw_value}
                              {v.unit ? ` ${v.unit}` : ""}
                              {superseded ? " (superseded)" : ""}
                            </td>
                            <td className="py-1 pr-3">
                              <Badge variant={SOURCE_TYPE_BADGE[v.source_type] || "outline"}>
                                {SOURCE_TYPE_LABELS[v.source_type] || v.source_type}
                              </Badge>
                            </td>
                            <td className="py-1">{v.verified_by || "—"}</td>
                          </tr>
                        );
                      });
                    })()}
                  </tbody>
                </table>
              </div>
              <p className="mt-1 text-[11px] text-gray-400">
                Corrections append a superseding row — original values are kept,
                struck through, never overwritten. Imported values stay
                &quot;imported, unverified&quot; until a PCA verifies them.
              </p>
            </Section>
          )}

          {auditEvents.length > 0 && (
            <Section title="Immutable audit history">
              <ol className="space-y-1.5">
                {auditEvents.map((e) => (
                  <li key={e.id} className="text-xs">
                    <span className="font-mono text-gray-400">
                      {e.created_at?.slice(0, 16).replace("T", " ")}
                    </span>{" "}
                    <span className="font-semibold text-gray-900">
                      {e.event_type.replace(/_/g, " ")}
                    </span>
                    {e.actor && <span className="text-gray-600"> · {e.actor}</span>}
                    {e.event_type === "reviewed" && e.after?.review_action && (
                      <span className="text-gray-600"> · action: {e.after.review_action}</span>
                    )}
                    {e.event_type === "input_value_superseded" && e.after && (
                      <span className="text-gray-600">
                        {" "}· {e.after.field}: {String(e.after.from)} → {String(e.after.to)}
                      </span>
                    )}
                    {e.before?.decision_outcome &&
                      e.after?.decision_outcome &&
                      e.before.decision_outcome !== e.after.decision_outcome && (
                        <span className="text-indigo-700">
                          {" "}· decision re-ran: {e.before.decision_outcome} →{" "}
                          {e.after.decision_outcome}
                        </span>
                      )}
                    {e.rationale && (
                      <p className="ml-4 text-gray-500">“{e.rationale}”</p>
                    )}
                  </li>
                ))}
              </ol>
              <p className="mt-1 text-[11px] text-gray-400">
                Append-only: every state change is recorded with its prior state; no
                event is ever edited or deleted.
              </p>
            </Section>
          )}

          <Section title="Follow-up timeline">
            {planned.follow_up_required && followUps.length === 0 && (
              <p className="rounded border border-amber-300 bg-amber-50 p-2 text-xs text-amber-900">
                Follow-up required: this outcome ({planned.outcome.replace(/_/g, " ")})
                is NOT a confirmed result until follow-up evidence is recorded here.
              </p>
            )}
            {followUps.length > 0 && (
              <ol className="mt-1 space-y-1.5">
                {followUps.map((e) => (
                  <li key={e.id} className="text-xs">
                    <span className="font-mono text-gray-400">{e.observed_at}</span>{" "}
                    <span className="font-semibold text-gray-900">
                      {e.event_type.replace(/_/g, " ")}
                    </span>
                    {e.severity != null && (
                      <span className="text-gray-600"> · severity {e.severity}</span>
                    )}
                    {e.actual_product && (
                      <span className="text-gray-600"> · {e.actual_product}</span>
                    )}
                    {e.cost != null && (
                      <span className="text-gray-600">
                        {" "}· {formatCost(e.cost, farm.country)}
                      </span>
                    )}
                    {e.rescue_required && (
                      <Badge variant="red" className="ml-1">rescue required</Badge>
                    )}
                    {(e.yield_impact || e.quality_impact) && (
                      <span className="text-gray-600">
                        {" "}· yield: {e.yield_impact || "unknown"} · quality:{" "}
                        {e.quality_impact || "unknown"}
                      </span>
                    )}
                    {e.evidence_notes && (
                      <p className="ml-4 text-gray-500">{e.evidence_notes}</p>
                    )}
                  </li>
                ))}
              </ol>
            )}
            {followUps.length === 0 && !planned.follow_up_required && (
              <p className="text-xs text-gray-500">
                No follow-up events recorded{planned.outcome === "planned" ? " — record the real-world outcome first" : ""}.
              </p>
            )}
            {planned.outcome !== "planned" && (
              <FollowUpForm plannedId={planned.id} onAdded={() => loadTrail(planned.id)} />
            )}
          </Section>

          <Section title="Disclaimers">
            <ul className="space-y-1 text-[11px] leading-snug text-gray-500">
              <li>
                {payload.disclaimer ||
                  "PHI and REI checks use values entered by the user and are not independently verified against the current pesticide label."}
              </li>
              <li>
                Decision support only — never a prescription and never a diagnosis. Final
                pesticide decisions must be made by the grower and a licensed PCA / agronomist
                according to the product label and applicable regulations.
              </li>
              <li>
                Recorded outcomes are the humans&apos; decisions that this check documented —
                not outcomes the check caused.
              </li>
            </ul>
          </Section>
        </div>
      </div>
    </div>
  );
}
