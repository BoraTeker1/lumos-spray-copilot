"use client";

import { useCallback, useEffect, useState } from "react";
import { Banknote, Landmark, ShieldCheck, Wallet } from "lucide-react";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useFarmContext } from "@/lib/farm-context";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import DataTable from "@/components/DataTable";
import EmptyState from "@/components/EmptyState";
import PageHeader from "@/components/PageHeader";
import SectionCard from "@/components/SectionCard";
import StatusBadge from "@/components/StatusBadge";
import { FormError } from "@/components/ui/field";

// A farm's finance record: what was assessed, when, and — mostly — why it could not be.
//
// THE THING THIS PAGE EXISTS TO SHOW, and the reason it is not an empty state:
// every assessment today is a REFUSAL, because no lender document has been transcribed.
// A page that hid refusals would be blank and would imply nothing had happened. A
// history reading "could not score: no scorecard supplied, on these dates" is a
// materially different and more useful record than an empty one — it is also the record
// that protects a grower who asks why they were declined.
//
// So refusals are FIRST-CLASS ROWS here, not filtered out and not styled as errors.
//
// Nothing on this page says approved, funded, guaranteed, or quotes a premium or a
// rate. The backend has no such fields; this page must not invent them in copy.

function AssessmentState({ row }) {
  return (
    <StatusBadge
      kind="assessment"
      value={row.refusal_code ? "refused" : "scored"}
    />
  );
}

// A refusal's `detail` is written by the server and names the specific document or
// record that would unblock it. Rendered verbatim — paraphrasing loses the actionable
// part, which is the same rule DataReadinessCard follows for abstention reasons.
function Detail({ row, children }) {
  if (row.refusal_detail) {
    return <span className="text-xs text-muted">{row.refusal_detail}</span>;
  }
  return children;
}

export default function FinancePage() {
  const { activeFarm } = useFarmContext();
  const farmId = activeFarm?.id;

  const [credit, setCredit] = useState([]);
  const [underwriting, setUnderwriting] = useState([]);
  const [collateral, setCollateral] = useState([]);
  const [monitoring, setMonitoring] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    if (!farmId) return;
    try {
      const [c, u, col, m] = await Promise.all([
        api.listCreditAssessments(farmId),
        api.listUnderwritingDecisions(farmId),
        api.listCollateral(farmId),
        api.listMonitoringSnapshots(farmId),
      ]);
      setCredit(c);
      setUnderwriting(u);
      setCollateral(col);
      setMonitoring(m);
      setError(null);
    } catch (err) {
      setError(err.message);
    }
  }, [farmId]);

  useEffect(() => {
    load();
  }, [load]);

  async function run(fn) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (!activeFarm) {
    return (
      <EmptyState
        icon={Banknote}
        title="No farm selected"
        description="Finance records are per farm. Pick or add a farm to see its assessment history."
      />
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumbs={[{ label: "Finance" }]}
        title="Finance"
        meta={
          <span>
            Assessment history for {activeFarm.name}. Every record is append-only — a
            reassessment adds a row, it never edits one.
          </span>
        }
      />

      <div className="flex items-start gap-2 rounded-card border border-line bg-canvas px-4 py-2.5 text-sm text-muted">
        <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
        Decision support only. Lumos executes a lender&apos;s own scorecard and evaluates
        their own policy — it does not approve credit, price it, or move money. Nothing
        here is an offer.
      </div>

      <FormError>{error}</FormError>

      <Tabs defaultValue="credit">
        <TabsList>
          <TabsTrigger value="credit">Credit</TabsTrigger>
          <TabsTrigger value="underwriting">Underwriting</TabsTrigger>
          <TabsTrigger value="collateral">Collateral</TabsTrigger>
          <TabsTrigger value="covenants">Covenants</TabsTrigger>
        </TabsList>

        <TabsContent value="credit">
          <SectionCard
            title="Credit assessments"
            icon={<Banknote />}
            size="section"
            description="Each row is one execution of a transcribed lender scorecard, or the recorded reason one could not run."
            action={
              <Button
                size="sm"
                disabled={busy}
                onClick={() => run(() => api.recordCreditAssessment(farmId))}
              >
                Run assessment
              </Button>
            }
          >
            <DataTable
              columns={[
                {
                  key: "as_of",
                  header: "As of",
                  width: "11%",
                  nowrap: true,
                  render: (r) => formatDate(r.as_of),
                },
                {
                  key: "state",
                  header: "State",
                  width: "17%",
                  nowrap: true,
                  render: (r) => <AssessmentState row={r} />,
                },
                {
                  key: "score",
                  header: "Score",
                  width: "13%",
                  nowrap: true,
                  align: "right",
                  render: (r) =>
                    r.total === null || r.total === undefined ? (
                      // Never a 0, never a dash in a numeric slot.
                      <span className="text-xs text-muted">Not calculated</span>
                    ) : (
                      <span className="tabular-nums">
                        {r.total} / {r.maximum_score}
                      </span>
                    ),
                },
                {
                  key: "detail",
                  header: "Basis",
                  priority: "secondary",
                  render: (r) => (
                    <Detail row={r}>
                      <span className="text-xs text-muted">
                        {r.scorecard_lender} · {r.scorecard_name} v{r.scorecard_version}
                      </span>
                    </Detail>
                  ),
                },
                {
                  key: "digest",
                  header: "Inputs digest",
                  priority: "secondary",
                  width: "14%",
                  nowrap: true,
                  render: (r) =>
                    r.inputs_digest ? (
                      <code className="text-[11px] text-muted">
                        {r.inputs_digest.slice(0, 12)}
                      </code>
                    ) : (
                      <span className="text-xs text-muted">—</span>
                    ),
                },
              ]}
              rows={credit}
              rowKey={(r) => r.id}
              minWidth={720}
              empty={
                <EmptyState
                  size="sm"
                  icon={Banknote}
                  title="No assessments recorded yet"
                  description="Running one today will record why it could not score — no lender scorecard has been transcribed. That record is the point: it is what a grower sees if they ask why."
                />
              }
            />
          </SectionCard>
        </TabsContent>

        <TabsContent value="underwriting">
          <SectionCard
            title="Underwriting decisions"
            icon={<ShieldCheck />}
            size="section"
            description="Whether the conditions in a transcribed lender policy were met. Never an approval — only the lender approves."
            action={
              <Button
                size="sm"
                disabled={busy}
                onClick={() =>
                  run(() => api.recordUnderwritingDecision(farmId, {}))
                }
              >
                Evaluate policy
              </Button>
            }
          >
            <DataTable
              columns={[
                {
                  key: "as_of",
                  header: "As of",
                  width: "11%",
                  nowrap: true,
                  render: (r) => formatDate(r.as_of),
                },
                {
                  key: "outcome",
                  header: "Outcome",
                  width: "17%",
                  nowrap: true,
                  render: (r) =>
                    r.outcome ? (
                      <StatusBadge kind="underwritingOutcome" value={r.outcome} />
                    ) : (
                      <AssessmentState row={r} />
                    ),
                },
                {
                  key: "unevaluated",
                  header: "Not evaluated",
                  width: "13%",
                  nowrap: true,
                  align: "right",
                  render: (r) => (
                    // Its own column, never folded into a pass count: a policy where
                    // two of five rules could not be tested must not read as clean.
                    <span className="tabular-nums text-xs">
                      {(r.not_evaluated_rule_ids || []).length}
                    </span>
                  ),
                },
                {
                  key: "detail",
                  header: "Basis",
                  priority: "secondary",
                  render: (r) => (
                    <Detail row={r}>
                      <span className="text-xs text-muted">
                        {r.policy_lender} v{r.policy_version}
                      </span>
                    </Detail>
                  ),
                },
              ]}
              rows={underwriting}
              rowKey={(r) => r.id}
              minWidth={680}
              empty={
                <EmptyState
                  size="sm"
                  icon={ShieldCheck}
                  title="No policy evaluations yet"
                  description="No lender credit policy has been transcribed, so an evaluation today records that it could not run."
                />
              }
            />
          </SectionCard>
        </TabsContent>

        <TabsContent value="collateral">
          <SectionCard
            title="Registered collateral"
            icon={<Wallet />}
            size="section"
            description="Live assets only. A revaluation supersedes the row it replaces, so nothing is double-counted."
          >
            <DataTable
              columns={[
                { key: "type", header: "Asset", render: (r) => r.collateral_type },
                {
                  key: "description",
                  header: "Description",
                  priority: "secondary",
                  render: (r) => r.description || "—",
                },
                {
                  key: "value",
                  header: "Assessed value",
                  width: "18%",
                  nowrap: true,
                  align: "right",
                  render: (r) =>
                    r.assessed_value === null || r.assessed_value === undefined ? (
                      <span className="text-xs text-muted">Not valued</span>
                    ) : (
                      // The asset's OWN currency, printed as its ISO code rather than
                      // run through formatCost — that helper maps a farm's country to a
                      // symbol, and an asset may be denominated differently. A wrong
                      // symbol on a collateral figure is worse than a plain code.
                      <span className="tabular-nums">
                        {r.currency}{" "}
                        {Number(r.assessed_value).toLocaleString("en-US", {
                          maximumFractionDigits: 2,
                        })}
                      </span>
                    ),
                },
                {
                  key: "basis",
                  header: "Valuation basis",
                  priority: "secondary",
                  render: (r) => r.valuation_basis || "—",
                },
              ]}
              rows={collateral}
              rowKey={(r) => r.id}
              minWidth={680}
              empty={
                <EmptyState
                  size="sm"
                  icon={Wallet}
                  title="No collateral registered"
                  description="Assets are registered by an operator. Note that a value alone is not enough — an advance rate assumes a valuation basis, so both are required together."
                />
              }
            />
            {collateral.length > 0 && (
              <p className="mt-3 text-xs text-muted">
                No loan-to-value is shown: no lender advance-rate schedule has been
                transcribed, and there is no safe default — 100% would understate a
                lender&apos;s exposure and 0% would deny collateral the grower holds.
              </p>
            )}
          </SectionCard>
        </TabsContent>

        <TabsContent value="covenants">
          <SectionCard
            title="Covenant standing"
            icon={<Landmark />}
            size="section"
            description="Standing is three-valued. A farm with an unevaluated covenant is not in good standing — nobody looked at all of it."
            action={
              <Button
                size="sm"
                disabled={busy}
                onClick={() => run(() => api.recordMonitoringSnapshot(farmId))}
              >
                Take snapshot
              </Button>
            }
          >
            <DataTable
              columns={[
                {
                  key: "as_of",
                  header: "As of",
                  width: "11%",
                  nowrap: true,
                  render: (r) => formatDate(r.as_of),
                },
                {
                  key: "standing",
                  header: "Standing",
                  width: "17%",
                  nowrap: true,
                  render: (r) =>
                    r.standing ? (
                      <StatusBadge kind="standing" value={r.standing} />
                    ) : (
                      <AssessmentState row={r} />
                    ),
                },
                {
                  key: "breached",
                  header: "Breached",
                  width: "12%",
                  nowrap: true,
                  align: "right",
                  render: (r) => (
                    <span className="tabular-nums text-xs">
                      {(r.breached_covenant_ids || []).length}
                    </span>
                  ),
                },
                {
                  key: "detail",
                  header: "Basis",
                  priority: "secondary",
                  render: (r) => (
                    <Detail row={r}>
                      <span className="text-xs text-muted">
                        {r.lender} · {r.facility_reference}
                      </span>
                    </Detail>
                  ),
                },
              ]}
              rows={monitoring}
              rowKey={(r) => r.id}
              minWidth={680}
              empty={
                <EmptyState
                  size="sm"
                  icon={Landmark}
                  title="No covenant snapshots yet"
                  description="No facility covenant schedule has been transcribed. An empty schedule is not compliance — it means nothing was checked."
                />
              }
            />
          </SectionCard>
        </TabsContent>
      </Tabs>
    </div>
  );
}
