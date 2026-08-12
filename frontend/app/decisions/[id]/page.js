"use client";

import { LoadingState } from "@/components/SystemState";
import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, CircleCheck, Info, Printer, TriangleAlert } from "lucide-react";
import { api } from "@/lib/api";
import DecisionEconomics from "@/components/DecisionEconomics";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { OUTCOME_META } from "@/components/DecisionResult";
import Breadcrumbs from "@/components/Breadcrumbs";
import StatusBadge from "@/components/StatusBadge";
import { nextActionLabel } from "@/lib/status";
import { DecisionReview, OutcomeRecorder } from "@/components/PreSpraySheet";
import PcaDispositionCard from "@/components/PcaDispositionCard";
import FollowUpEventForm from "@/components/FollowUpEventForm";

// One-page printable/shareable decision record for a single pre-spray check:
// inputs, every rule with its calculation and source authority, missing data,
// the PCA review, the final recorded outcome, and the disclaimers.
// Print via the button (app chrome + the interactive right rail are hidden in
// print — the print CSS lives in globals.css).
// NOTE: this page is the always-expanded print/audit surface — unlike the in-app
// DecisionResult card it deliberately collapses nothing.

import AiBriefCard from "@/components/AiBriefCard";
import InputPlanForm from "@/components/InputPlanForm";
import {
  AUTHORITY_SOURCE_LABELS,
  CLEARANCE_CAVEAT,
  RECORDED_OUTCOME_LABELS,
  REVIEW_STATE_LABELS,
  decisionAuthorityLabel,
  dispositionSummary,
  isProvisionalAuthority,
} from "@/lib/labels";
import { tone } from "@/lib/tones";
import { formatArea, formatCost, formatDate } from "@/lib/format";
import { FormError } from "@/components/ui/field";

// Section numbers are allocated in render order rather than hardcoded: two of
// these sections are conditional, and hand-computed numbers (previously
// `auditEvents.length > 0 ? 6 : 5`) drift the moment another one is added.
function makeCounter() {
  let n = 0;
  return () => (n += 1);
}

function Section({ number, title, children }) {
  return (
    <section className="break-inside-avoid">
      <h2 className="mb-2 flex items-center gap-2 border-b border-line pb-1.5 text-sm font-semibold text-ink">
        {number != null && (
          <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-line text-[11px] font-semibold text-muted">
            {number}
          </span>
        )}
        {title}
      </h2>
      {children}
    </section>
  );
}

function Row({ label, value }) {
  return (
    <div className="flex justify-between gap-3 py-0.5 text-sm">
      <span className="text-muted">{label}</span>
      <span className="text-right font-medium text-ink">{value ?? "—"}</span>
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

// Mirrors STATUS.disposition in lib/status.js; used in the printable record where
// a badge component would not survive print styling.
const DISPOSITION_LABELS = {
  follow_baseline: "Spray as scheduled",
  defer: "Defer",
  rescout: "Re-scout first",
  insufficient_evidence: "Insufficient evidence",
};

// "So can it be sprayed?" — the verdict restated as the question a grower asks.
//
// This panel has NO logic of its own: the headline is a pure lookup on
// decision_outcome (lib/labels.js DISPOSITION_SUMMARY), the next line is the
// server's required_next_action verbatim, and the two rows below read
// server-derived state. It can never render an affirmative clearance — an
// approve reads "NO ENGINE BLOCK FOUND" and carries the label/PCA caveat,
// because an approve in this engine is never definitive.
function DispositionSummary({ planned }) {
  const disp = dispositionSummary(planned.decision_outcome);
  const t = tone(disp.tone);
  const isApprove = planned.decision_outcome === "approve";
  return (
    <div className="rounded-card border border-line bg-surface p-4">
      <div className="text-[11px] font-semibold uppercase tracking-wider text-muted">
        Spray disposition
      </div>
      <div className={`mt-1.5 text-base font-bold leading-tight ${t.text}`}>
        {disp.headline}
      </div>
      <p className="mt-1.5 text-meta text-muted">{planned.required_next_action}</p>
      {isApprove && (
        <p className="mt-2 border-t border-line pt-2 text-[11px] leading-snug text-muted">
          {CLEARANCE_CAVEAT}
        </p>
      )}
      <dl className="mt-3 space-y-1.5 border-t border-line pt-3 text-xs">
        <div className="flex items-center justify-between gap-2">
          <dt className="text-muted">Inspection required</dt>
          <dd className="font-medium text-ink">
            {planned.decision_outcome === "inspect_first" ? "Yes" : "No"}
          </dd>
        </div>
        <div className="flex items-center justify-between gap-2">
          <dt className="text-muted">PCA review</dt>
          <dd className="font-medium text-ink">
            {REVIEW_STATE_LABELS[planned.review_state] || planned.review_state}
          </dd>
        </div>
      </dl>
    </div>
  );
}

export default function DecisionRecordPage({ params }) {
  const [planned, setPlanned] = useState(null);
  const [farm, setFarm] = useState(null);
  const [inputValues, setInputValues] = useState([]);
  const [auditEvents, setAuditEvents] = useState([]);
  const [followUps, setFollowUps] = useState([]);
  const [dispositions, setDispositions] = useState([]);
  const [error, setError] = useState(null);

  async function loadTrail(id) {
    const [values, audit, events, calls] = await Promise.all([
      api.listInputValues(id),
      api.listAuditEvents(id),
      api.listFollowUpEvents(id),
      // Dispositions only exist for pilot (block-linked) decisions; an empty list
      // is the normal case everywhere else.
      api.listPcaDispositions(id).catch(() => []),
    ]);
    setInputValues(values);
    setAuditEvents(audit);
    setFollowUps(events);
    setDispositions(calls);
  }

  async function loadAll() {
    const p = await api.getPlannedSpray(params.id);
    setPlanned(p);
    setFarm(await api.getFarm(p.farm_id));
    await loadTrail(p.id);
  }

  useEffect(() => {
    loadAll().catch((err) => setError(err.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.id]);

  if (error) return <FormError>{error}</FormError>;
  if (!planned || !farm) return <LoadingState message="Loading decision record…" />;

  const payload = planned.decision_payload || {};
  const rules = payload.rules || [];
  const triggered = rules.filter((r) => r.triggered);
  const topRule =
    triggered.find((r) => r.severity === "critical") || triggered[0] || null;
  const provisional = isProvisionalAuthority(planned.decision_authority);
  const isDemo = planned.data_source === "demo" || planned.data_confidence === "simulated";
  const meta = OUTCOME_META[planned.decision_outcome] || OUTCOME_META.pca_review_required;
  const OutcomeIcon = meta.icon;
  const showProvisionalPrefix =
    provisional && ["approve", "block"].includes(planned.decision_outcome);
  const decided = planned.outcome !== "planned";
  const reviewed = ["approved", "edited", "rejected"].includes(planned.review_state);
  // Allocates section numbers in render order; see makeCounter above.
  const step = makeCounter();

  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <Breadcrumbs
        items={[
          { label: "Decisions", href: "/decisions" },
          { label: farm.name, href: `/farms/${planned.farm_id}?tab=planned` },
          { label: planned.product_name },
        ]}
      />

      {/* Page header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <p className="text-meta text-muted">
          Pre-spray decision record #{planned.id} · {farm.name} · intended{" "}
          {formatDate(planned.intended_date)} · generated by Lumos Spray Copilot
        </p>
        <div className="no-print flex items-center gap-2">
          <Button type="button" size="sm" variant="secondary" onClick={() => window.print()}>
            <Printer />
            Print / save as PDF
          </Button>
        </div>
      </div>

      {/* Verdict banner. The verdict is the immutable historical decision; the
          disposition panel beside it restates that verdict as the question a
          grower actually asks, and adds no logic of its own. */}
      <div className={`rounded-card border p-5 ${meta.box}`}>
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_300px]">
          <div className="flex gap-3.5">
            <span
              className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-full ${meta.dot}`}
            >
              <OutcomeIcon className="h-5 w-5" />
            </span>
            <div className="min-w-0 flex-1">
              <div
                className={`text-[11px] font-semibold uppercase tracking-wider ${meta.text}`}
              >
                {showProvisionalPrefix ? `Provisional ${meta.label}` : meta.label}
              </div>
              <h1 className="mt-1 text-title font-semibold text-ink">
                {planned.product_name}
              </h1>
              <p className={`mt-1.5 text-sm font-medium ${meta.text}`}>
                {topRule ? topRule.detail : "All checks passed from entered records."}
              </p>
              <p className="mt-2 text-meta text-muted">
                {[
                  planned.field_block,
                  planned.target_pest_or_disease,
                  `planned ${formatDate(planned.intended_date)}`,
                  planned.rate_amount != null && planned.rate_unit
                    ? `${planned.rate_amount} ${planned.rate_unit}`
                    : null,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
              <div className="mt-3 flex flex-wrap items-center gap-1.5">
                {/* The verdict above is the immutable historical decision; these say
                    what (if anything) is still owed right now. */}
                <StatusBadge kind="workflow" value={planned.workflow_state} />
                <StatusBadge kind="evidence" value={planned.evidence_state} />
                <Badge variant={provisional ? "amber" : "green"}>
                  {decisionAuthorityLabel(planned.decision_authority)}
                </Badge>
                <Badge variant="outline">confidence: {planned.decision_confidence}</Badge>
                <Badge variant="outline">{rules.length} checks run</Badge>
                {isDemo && <Badge variant="outline">Simulated demo record</Badge>}
              </div>
              {/* Says who decided. The engine is deterministic rules; the AI
                  features in this product never issue a verdict. */}
              <p className="mt-3 flex items-start gap-1.5 text-meta text-muted">
                <Info className="mt-px h-3.5 w-3.5 shrink-0" aria-hidden />
                Verdict source: deterministic rule engine. AI did not issue this verdict.
              </p>
            </div>
          </div>

          <DispositionSummary planned={planned} />
        </div>
      </div>

      {/* What happened after the check. Separated from the verdict on purpose:
          the verdict is a fact about one moment and never changes, while the
          outcome is a later, different fact. */}
      {decided && (
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 rounded-card border border-line bg-surface px-4 py-3">
          <div className="flex items-center gap-2 text-sm">
            <span className="text-muted">Outcome:</span>
            <StatusBadge kind="outcome" value={planned.outcome} />
          </div>
          <div className="flex items-center gap-2 text-sm">
            <span className="text-muted">Follow-up evidence:</span>
            <StatusBadge kind="evidence" value={planned.evidence_state} />
          </div>
          {/* basis-full below lg: given a flex-1 with no basis, this sentence
              shrinks to one word per line on a phone. */}
          <p className="min-w-0 flex-1 basis-full text-meta text-muted lg:basis-auto lg:text-right">
            This historical decision remains {meta.label}. Anything applied instead was
            checked separately.
          </p>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_320px]">
        {/* ------------------------------------------------ printable record */}
        <div className="rounded-card border border-line bg-surface p-6 print:border-0 print:p-0">
          <div className="space-y-5">
            <Section number={step()} title="Decision rationale — checks performed">
              <ul className="space-y-2">
                {rules.map((r) => (
                  <li key={r.rule_id} className="text-sm">
                    <div className="flex flex-wrap items-center gap-1.5">
                      {/* Was "⚠"/"✓" text glyphs, which render at whatever the
                          font happens to supply and print inconsistently — on
                          the one page a PCA is expected to sign and file. The
                          icon shape, not just the colour, carries the state. */}
                      <span
                        className={
                          r.triggered
                            ? "inline-flex items-center gap-1.5 font-semibold text-risk-fg"
                            : "inline-flex items-center gap-1.5 font-medium text-ink"
                        }
                      >
                        {r.triggered ? (
                          <TriangleAlert className="h-3.5 w-3.5 shrink-0" aria-hidden />
                        ) : (
                          <CircleCheck className="h-3.5 w-3.5 shrink-0 text-ok-fg" aria-hidden />
                        )}
                        <span className="sr-only">
                          {r.triggered ? "Triggered:" : "Passed:"}
                        </span>
                        {r.name}
                      </span>
                      <span className="rounded bg-draft-bg px-1.5 py-0.5 text-[10px] text-muted">
                        {AUTHORITY_SOURCE_LABELS[r.source_authority] || r.source_authority} ·{" "}
                        {r.verification_status}
                        {r.entered_by ? ` · ${r.entered_by}` : ""}
                      </span>
                    </div>
                    <p className="mt-0.5 text-xs text-ink">{r.detail}</p>
                    {r.calculation && (
                      <p className="mt-0.5 font-mono text-[11px] text-muted">
                        {r.calculation}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
              {payload.authority_basis && (
                <p className="mt-2 text-xs text-muted">{payload.authority_basis}</p>
              )}
            </Section>

            <Section number={step()} title="Supporting evidence — inputs used">
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
                <p className="mt-1.5 rounded border border-warn-line bg-warn-bg p-2 text-xs text-warn-fg">
                  The farm&apos;s expected harvest date has changed since this check ran —
                  the calculations in this record use the harvest date entered at check
                  time. Re-run the check before relying on this decision.
                </p>
              )}

              {planned.label_reference_stale && (
                <p className="mt-1.5 rounded border border-warn-line bg-warn-bg p-2 text-xs text-warn-fg">
                  The pesticide label this check was run against has since been revised —
                  the calculations in this record use the label values on record at check
                  time. Re-run the check against the current label before relying on this
                  decision.
                </p>
              )}

              {(payload.missing_information || []).length > 0 && (
                <div className="mt-3">
                  <h3 className="text-xs font-semibold text-ink">Missing information</h3>
                  <ul className="mt-1 list-disc space-y-0.5 pl-5 text-xs text-ink">
                    {payload.missing_information.map((m, i) => (
                      <li key={i}>{m}</li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Checks that did NOT run, and why. Part of the printed record on
                  purpose: an auditor reading this needs to know what was never
                  examined, not just what passed. */}
              {(payload.not_evaluated || []).length > 0 && (
                <div className="mt-3">
                  <h3 className="text-xs font-semibold text-ink">
                    Not evaluated ({payload.not_evaluated.length})
                  </h3>
                  <p className="mt-0.5 text-[11px] text-muted">
                    These checks did not run. Each states why — none was guessed or
                    simulated.
                  </p>
                  <ul className="mt-1 list-disc space-y-0.5 pl-5 text-xs text-ink">
                    {payload.not_evaluated.map((c) => (
                      <li key={c.check_id || c.check}>
                        <span className="font-medium">{c.check}</span> — {c.reason}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {inputValues.length > 0 && (
                <div className="mt-3">
                  <h3 className="text-xs font-semibold text-ink">
                    Input provenance (field-level, append-only)
                  </h3>
                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-[11px]">
                      <thead>
                        <tr className="text-[10px] font-semibold uppercase tracking-wide text-muted">
                          <th className="py-1 pr-3">Field</th>
                          <th className="py-1 pr-3">Value</th>
                          <th className="py-1 pr-3">Source</th>
                          <th className="py-1">Verified by</th>
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
                                className={`border-t border-line ${superseded ? "text-muted line-through" : ""}`}
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
                  <p className="mt-1 text-[11px] text-muted">
                    Corrections append a superseding row — original values are kept,
                    struck through, never overwritten. Imported values stay
                    &quot;imported, unverified&quot; until a PCA verifies them.
                  </p>
                </div>
              )}
            </Section>

            <Section number={step()} title="PCA / agronomist review">
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
                <p className="mt-1 text-sm text-ink">
                  <span className="font-medium">Comment:</span> {planned.review_comment}
                </p>
              )}
              {planned.pca_next_action && (
                <p className="mt-1 rounded bg-info-bg p-2 text-sm text-info-fg">
                  <span className="font-semibold">PCA guidance:</span> {planned.pca_next_action}
                </p>
              )}
            </Section>

            {dispositions.length > 0 && (
              <Section number={step()} title="PCA pilot decision (Botrytis deferral)">
                <p className="mb-2 text-xs text-muted">
                  The licensed advisor&apos;s judgement about this scheduled
                  application, recorded separately from the compliance check above and
                  from what was ultimately done. Append-only: a change supersedes the
                  earlier entry and never removes it.
                </p>
                <ul className="space-y-2">
                  {dispositions.map((d) => {
                    const isSuperseded = dispositions.some(
                      (o) => o.supersedes_id === d.id
                    );
                    return (
                      <li
                        key={d.id}
                        className={`rounded border border-line p-2 text-sm ${
                          isSuperseded ? "text-muted" : "text-ink"
                        }`}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-medium">
                            {DISPOSITION_LABELS[d.disposition] || d.disposition}
                            {isSuperseded && " (superseded)"}
                          </span>
                          <span className="text-xs text-muted">
                            {d.decided_at?.slice(0, 16).replace("T", " ")}
                          </span>
                        </div>
                        <p className="mt-1">{d.rationale}</p>
                        <p className="mt-1 text-[11px] text-muted">
                          Credential #{d.pca_credential_id} · inputs digest{" "}
                          {d.snapshot_digest_at_decision?.slice(0, 12)}…
                        </p>
                      </li>
                    );
                  })}
                </ul>
              </Section>
            )}

            <Section number={step()} title="Cost of each choice">
              <DecisionEconomics plannedId={planned.id} country={farm.country} />
            </Section>

            <Section number={step()} title="Final recorded outcome">
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
                <p className="mt-1 text-sm text-ink">
                  <span className="font-medium">Stated reason:</span> {planned.outcome_reason}
                </p>
              )}
              {planned.outcome === "avoided" && planned.estimated_cost != null && (
                <p className="mt-1.5 rounded bg-ok-bg p-2 text-sm text-ok-fg">
                  Entered application cost not spent:{" "}
                  <span className="font-semibold">
                    {formatCost(planned.estimated_cost, farm.country)}
                  </span>
                  {farm.greenhouse_area != null && (
                    <> · planned across {formatArea(farm.greenhouse_area, farm.country)}</>
                  )}
                  <span className="text-xs text-ok-fg">
                    {" "}
                    (entered estimate; yield impact not yet known or measured)
                  </span>
                </p>
              )}
            </Section>

            {auditEvents.length > 0 && (
              <Section number={step()} title="Immutable audit history">
                <ol className="space-y-1.5">
                  {auditEvents.map((e) => (
                    <li key={e.id} className="text-xs">
                      <span className="font-mono text-muted">
                        {e.created_at?.slice(0, 16).replace("T", " ")}
                      </span>{" "}
                      <span className="font-semibold text-ink">
                        {e.event_type.replace(/_/g, " ")}
                      </span>
                      {e.actor && <span className="text-muted"> · {e.actor}</span>}
                      {e.event_type === "reviewed" && e.after?.review_action && (
                        <span className="text-muted"> · action: {e.after.review_action}</span>
                      )}
                      {e.event_type === "input_value_superseded" && e.after && (
                        <span className="text-muted">
                          {" "}· {e.after.field}: {String(e.after.from)} → {String(e.after.to)}
                        </span>
                      )}
                      {e.before?.decision_outcome &&
                        e.after?.decision_outcome &&
                        e.before.decision_outcome !== e.after.decision_outcome && (
                          <span className="text-info-fg">
                            {" "}· decision re-ran: {e.before.decision_outcome} →{" "}
                            {e.after.decision_outcome}
                          </span>
                        )}
                      {e.rationale && (
                        <p className="ml-4 text-muted">“{e.rationale}”</p>
                      )}
                    </li>
                  ))}
                </ol>
                <p className="mt-1 text-[11px] text-muted">
                  Append-only: every state change is recorded with its prior state; no
                  event is ever edited or deleted.
                </p>
              </Section>
            )}

            <Section number={step()} title="Follow-up timeline">
              {planned.follow_up_required && followUps.length === 0 && (
                <p className="rounded border border-warn-line bg-warn-bg p-2 text-xs text-warn-fg">
                  Follow-up required: this outcome ({planned.outcome.replace(/_/g, " ")})
                  is NOT a confirmed result until follow-up evidence is recorded here.
                </p>
              )}
              {followUps.length > 0 && (
                <ol className="mt-1 space-y-1.5">
                  {followUps.map((e) => (
                    <li key={e.id} className="text-xs">
                      <span className="font-mono text-muted">{e.observed_at}</span>{" "}
                      <span className="font-semibold text-ink">
                        {e.event_type.replace(/_/g, " ")}
                      </span>
                      {e.severity != null && (
                        <span className="text-muted"> · severity {e.severity}</span>
                      )}
                      {e.actual_product && (
                        <span className="text-muted"> · {e.actual_product}</span>
                      )}
                      {e.cost != null && (
                        <span className="text-muted">
                          {" "}· {formatCost(e.cost, farm.country)}
                        </span>
                      )}
                      {e.rescue_required && (
                        <Badge variant="red" className="ml-1">rescue required</Badge>
                      )}
                      {(e.yield_impact || e.quality_impact) && (
                        <span className="text-muted">
                          {" "}· yield: {e.yield_impact || "unknown"} · quality:{" "}
                          {e.quality_impact || "unknown"}
                        </span>
                      )}
                      {e.evidence_notes && (
                        <p className="ml-4 text-muted">{e.evidence_notes}</p>
                      )}
                    </li>
                  ))}
                </ol>
              )}
              {followUps.length === 0 && !planned.follow_up_required && (
                <p className="text-xs text-muted">
                  No follow-up events recorded{planned.outcome === "planned" ? " — record the real-world outcome first" : ""}.
                </p>
              )}
              {planned.outcome !== "planned" && (
                <FollowUpEventForm
                  plannedId={planned.id}
                  onAdded={() => loadTrail(planned.id)}
                />
              )}
            </Section>

            <Section title="Disclaimers">
              <ul className="space-y-1 text-[11px] leading-snug text-muted">
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

        {/* ------------------------------------------- interactive right rail */}
        <div className="no-print space-y-4">
          <div className="rounded-card border border-line bg-surface p-4">
            <h2 className="text-sm font-semibold text-ink">Planned application</h2>
            <div className="mt-2 space-y-0.5">
              <Row label="Product" value={planned.product_name} />
              <Row label="Active ingredient" value={planned.active_ingredient} />
              <Row label="Target" value={planned.target_pest_or_disease} />
              <Row label="Intended date" value={formatDate(planned.intended_date)} />
              <Row label="Entered PHI" value={planned.pre_harvest_interval_days != null ? `${planned.pre_harvest_interval_days} days` : null} />
              <Row label="Entered REI" value={planned.re_entry_interval_hours != null ? `${planned.re_entry_interval_hours} hours` : null} />
              {planned.moa_group && <Row label="MoA group" value={planned.moa_group} />}
              {planned.estimated_cost != null && (
                <Row label="Entered cost" value={formatCost(planned.estimated_cost, farm.country)} />
              )}
            </div>
          </div>

          <div className="rounded-card border border-line bg-surface p-4">
            <h2 className="text-sm font-semibold text-ink">Review workflow</h2>
            <div className="mt-2 space-y-0.5">
              <Row
                label="Review status"
                value={REVIEW_STATE_LABELS[planned.review_state] || planned.review_state}
              />
              {planned.reviewed_by && <Row label="Reviewed by" value={planned.reviewed_by} />}
              <Row
                label="Outcome"
                value={RECORDED_OUTCOME_LABELS[planned.outcome] || planned.outcome}
              />
              <Row
                label="Current next step"
                value={
                  planned.current_next_action === "none"
                    ? "None — fully documented"
                    : nextActionLabel(planned.current_next_action)
                }
              />
            </div>
            {!decided && (
              <div className="mt-2 border-t border-line pt-2">
                {!reviewed && <DecisionReview planned={planned} onChanged={loadAll} />}
                <OutcomeRecorder planned={planned} onChanged={loadAll} />
              </div>
            )}
            {planned.current_next_action === "record_follow_up" && (
              <p className="mt-2 rounded-control border border-warn-line bg-warn-bg p-2 text-xs text-warn-fg">
                Follow-up evidence is due — append the real-world evidence in the
                follow-up timeline on the left.
              </p>
            )}
            <p className="mt-3 text-[11px] leading-snug text-muted">
              Decision support only. Confirm the current product label and PCA guidance
              before application.
            </p>
          </div>

          {/* Only meaningful for block-linked decisions: a disposition must be
              anchored to a risk snapshot, and a snapshot is always about a block. */}
          {planned.block_id && <PcaDispositionCard plannedId={planned.id} />}

          <AiBriefCard plannedId={planned.id} />

          <div className="rounded-card border border-line bg-surface p-4">
            <h2 className="text-sm font-semibold text-ink">Inputs & finance</h2>
            {(() => {
              const links = planned.procurement_links || [];
              const active = links.filter((l) => l.plan_status !== "cancelled");
              const cancelled = links.filter((l) => l.plan_status === "cancelled");
              if (active.length > 0) {
                // Procurement already exists — link to it instead of offering
                // to create a duplicate plan.
                return (
                  <div className="mt-1 space-y-2">
                    {active.map((l) => (
                      <div key={l.input_plan_id} className="text-xs text-muted">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <Link
                            href={`/inputs/plans/${l.input_plan_id}`}
                            className="font-medium text-leaf-700 hover:underline"
                          >
                            View input plan #{l.input_plan_id}
                          </Link>
                          <StatusBadge kind="planStatus" value={l.plan_status} />
                        </div>
                        {l.order_id && (
                          <div className="mt-1 flex flex-wrap items-center gap-1.5">
                            <Link
                              href={`/inputs/orders/${l.order_id}`}
                              className="font-medium text-leaf-700 hover:underline"
                            >
                              View order #{l.order_id}
                            </Link>
                            <StatusBadge kind="orderStatus" value={l.order_status} />
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                );
              }
              if (planned.procurement_eligible) {
                return (
                  <>
                    <p className="mt-1 text-xs text-muted">
                      This decision is cleared for procurement — build an input plan
                      and request supplier quotes for the product it authorizes.
                    </p>
                    {cancelled.length > 0 && (
                      <p className="mt-1 text-xs text-muted">
                        {cancelled
                          .map((l) => `Previous plan #${l.input_plan_id} was cancelled`)
                          .join("; ")}
                        .
                      </p>
                    )}
                    <div className="mt-2">
                      <InputPlanForm
                        farmId={planned.farm_id}
                        plannedSpray={planned}
                        triggerLabel="Request supplier quotes"
                      />
                    </div>
                  </>
                );
              }
              return (
                <p className="mt-1 text-xs text-muted">
                  Not eligible for procurement:{" "}
                  {planned.outcome === "avoided"
                    ? "the recorded outcome is avoided — nothing should be purchased for it."
                    : planned.review_state === "rejected"
                      ? "the PCA rejected this decision."
                      : "a PCA review (approve or edit) is still required before inputs can be purchased."}
                </p>
              );
            })()}
          </div>

          <Link
            href={`/farms/${planned.farm_id}?tab=planned`}
            className="block rounded-card border border-line bg-surface p-3 text-center text-sm font-medium text-ink shadow-sm transition-colors hover:border-muted"
          >
            Back to {farm.name}
          </Link>
        </div>
      </div>
    </div>
  );
}
