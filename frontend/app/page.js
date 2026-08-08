"use client";

import { LoadingState } from "@/components/SystemState";
import Callout from "@/components/Callout";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  Building2,
  CalendarClock,
  ClipboardCheck,
  CloudSun,
  Eye,
  FileWarning,
  FlaskConical,
  ListChecks,
  ShieldCheck,
  TriangleAlert,
  Users,
  Wrench,
} from "lucide-react";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { tone } from "@/lib/tones";
import { useFarmContext } from "@/lib/farm-context";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import ActivityTimeline from "@/components/ActivityTimeline";
import DecisionQueue from "@/components/DecisionQueue";
import EmptyState from "@/components/EmptyState";
import NextActionBanner from "@/components/NextActionBanner";
import PageHeader from "@/components/PageHeader";
import PreSpraySheet from "@/components/PreSpraySheet";
import ProgressBar from "@/components/ProgressBar";
import ScoutObservationForm from "@/components/ScoutObservationForm";
import SectionCard from "@/components/SectionCard";
import StatusBadge from "@/components/StatusBadge";
import UpdateHarvestDialog from "@/components/UpdateHarvestDialog";
import WeatherCard from "@/components/WeatherCard";

// Operational consequence line per urgency (presentation copy only — the issue
// text itself comes verbatim from the server's overview entry).
const CONSEQUENCES = {
  conflict: "Do not apply the planned spray until the conflict is resolved with your PCA.",
  harvest_overdue: "New pre-spray checks cannot be trusted until the harvest date is corrected.",
  needs_review: "Guidance is not actionable until the PCA records a review.",
  awaiting_outcome: "Unrecorded outcomes leave the audit trail incomplete.",
  flags: "Review the flagged risks before planning the next application.",
  ok: "All clear from current records — check the next planned spray before applying.",
};

// Operations overview for the active farm. Every number is a real server field;
// the KPI counts are computed from the SAME planned-spray array the queue
// renders, so metrics and rows can never disagree.
export default function OperationsPage() {
  const { activeFarm, loading: farmsLoading, error: farmsError, refresh } = useFarmContext();
  const farmId = activeFarm?.id;

  const [overview, setOverview] = useState(null);
  const [planned, setPlanned] = useState([]);
  const [sprays, setSprays] = useState([]);
  const [observations, setObservations] = useState([]);
  const [evidence, setEvidence] = useState(null);
  const [error, setError] = useState(null);
  const [scoutDialogOpen, setScoutDialogOpen] = useState(false);

  const load = useCallback(async () => {
    if (!farmId) return;
    try {
      const [ov, p, s, o, ev] = await Promise.all([
        api.getFarmOverview(farmId),
        api.listPlannedSprays(farmId),
        api.listSprayEvents(farmId),
        api.listScoutObservations(farmId),
        api.getDecisionEvidence(farmId),
      ]);
      setOverview(ov);
      setPlanned(p);
      setSprays(s);
      setObservations(o);
      setEvidence(ev);
      setError(null);
    } catch (err) {
      setError(err.message);
    }
  }, [farmId]);

  useEffect(() => {
    load();
  }, [load]);

  if (farmsLoading) return <LoadingState message="Loading farms…" />;
  if (farmsError) {
    return (
      <Callout tone="risk">
        {farmsError} — is the backend running on <code>http://localhost:8000</code>?
      </Callout>
    );
  }
  if (!activeFarm) {
    return (
      <EmptyState
        icon={ShieldCheck}
        title="No farms yet"
        description="Add a pilot farm to start checking planned sprays — the intake takes about two minutes and nothing else is required."
        cta={
          <Link href="/pilot/new">
            <Button>Add pilot farm</Button>
          </Link>
        }
      />
    );
  }

  // Canonical per-decision states from the server — never re-derived here.
  const needsAction = planned.filter((p) => p.workflow_state === "needs_action");
  const awaitingPca = planned.filter((p) => p.workflow_state === "awaiting_pca");
  const followUpsDue = planned.filter((p) =>
    ["follow_up_required", "follow_up_in_progress"].includes(p.evidence_state)
  );
  const openByDate = planned
    .filter((p) => p.is_open)
    .sort((a, b) => (a.intended_date < b.intended_date ? -1 : 1));
  // Queue ordering: things someone owes an action on first, then recent history.
  const queueRows = [
    ...needsAction,
    ...awaitingPca,
    ...followUpsDue.filter((p) => p.workflow_state === "resolved"),
    ...planned.filter(
      (p) =>
        p.workflow_state === "resolved" &&
        !followUpsDue.some((f) => f.id === p.id)
    ),
  ];

  const days = overview?.days_to_harvest;
  const harvestOverdue = days != null && days < 0;
  const refreshAll = async () => {
    await load();
    await refresh(); // farm switcher list may re-rank after updates
  };

  // Urgency-specific banner actions.
  const bannerPrimary =
    overview?.urgency === "harvest_overdue" ? (
      <UpdateHarvestDialog
        farmId={farmId}
        currentDate={overview.expected_harvest_date}
        onUpdated={refreshAll}
        trigger={
          <Button size="sm">
            <CalendarClock />
            Update harvest date
          </Button>
        }
      />
    ) : overview?.urgency === "conflict" ? (
      <Link href="/decisions">
        <Button size="sm">Resolve conflict</Button>
      </Link>
    ) : overview?.urgency === "needs_review" ? (
      <Link href="/decisions">
        <Button size="sm">Review decisions</Button>
      </Link>
    ) : overview?.urgency === "awaiting_outcome" ? (
      <Link href="/decisions">
        <Button size="sm">Record outcomes</Button>
      </Link>
    ) : overview?.urgency === "flags" ? (
      <Link href="/evidence?tab=compliance">
        <Button size="sm">Review risks</Button>
      </Link>
    ) : null;

  // Evidence scope for the mini-card: never mix simulated and real. A demo farm
  // (no real records) shows the simulated block, clearly labeled.
  const realChecked = evidence?.decisions_checked ?? 0;
  const demoMetrics = evidence?.demo_metrics;
  const useDemoScope = realChecked === 0 && (demoMetrics?.decisions_checked ?? 0) > 0;
  const scope = useDemoScope ? demoMetrics : evidence;

  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumbs={[{ label: "Operations" }, { label: "Today" }]}
        title="Today's operations"
        meta={
          <>
            <span className="font-medium text-leaf-700">
              The decision layer before the spray.
            </span>
            <span>
              {activeFarm.name}
              {activeFarm.location ? ` · ${activeFarm.location}` : ""}
            </span>
            {overview?.is_demo && (
              <Badge variant="outline">
                <FlaskConical />
                Simulated demo data
              </Badge>
            )}
            {activeFarm.is_reference && (
              <Badge variant="outline">
                <Wrench />
                Operator reference farm — not a customer
              </Badge>
            )}
          </>
        }
        actions={
          <>
            <Dialog open={scoutDialogOpen} onOpenChange={setScoutDialogOpen}>
              <DialogTrigger asChild>
                <Button variant="secondary">
                  <Eye />
                  Log scouting
                </Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>Log a scouting observation</DialogTitle>
                  <DialogDescription>
                    Field evidence feeds the pre-spray decision checks.
                  </DialogDescription>
                </DialogHeader>
                <ScoutObservationForm
                  farmId={farmId}
                  onCreated={async () => {
                    setScoutDialogOpen(false);
                    await load();
                  }}
                />
              </DialogContent>
            </Dialog>
            <PreSpraySheet farmId={farmId} onChanged={load} />
          </>
        }
      />

      {error && (
        <Callout tone="risk">
          {error}
        </Callout>
      )}

      {overview && (
        <NextActionBanner
          issue={overview.why}
          consequence={CONSEQUENCES[overview.urgency]}
          urgency={overview.urgency}
          primary={bannerPrimary}
          secondary={
            <Link
              href="/decisions"
              className="text-xs font-medium text-muted underline-offset-2 hover:underline"
            >
              View decision queue
            </Link>
          }
        />
      )}

      {/* Main column | context rail */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0 space-y-4">
          <SectionCard
            title="Decision queue"
            icon={<ShieldCheck />}
            size="section"
            description="Verdict = the engine's historical decision. State = what (if anything) is still owed."
          >
            <DecisionQueue planned={queueRows} limit={5} viewAllHref="/decisions" />
          </SectionCard>

          <SectionCard title="Recent activity" icon={<Eye />} size="section">
            <ActivityTimeline
              sprays={sprays}
              observations={observations}
              country={activeFarm.country}
              limit={6}
            />
          </SectionCard>
        </div>

        {/* ------------------------------------------------------- context rail */}
        <div className="space-y-4">
          {overview && (
            <SectionCard title="Farm context" icon={<Building2 />}>
              <div className="flex items-start justify-between gap-3">
                <span className="inline-flex items-center gap-2 text-sm text-ink">
                  <CalendarClock className="h-4 w-4 text-muted" aria-hidden />
                  Harvest
                </span>
                <span className="text-right">
                  <span className="tabular block text-sm font-medium text-ink">
                    {overview.expected_harvest_date
                      ? formatDate(overview.expected_harvest_date)
                      : "Not entered"}
                  </span>
                  {days != null && (
                    <span
                      className={`tabular block text-xs font-medium ${
                        harvestOverdue ? "text-risk-fg" : "text-leaf-700"
                      }`}
                    >
                      {harvestOverdue
                        ? `${-days} day${days === -1 ? "" : "s"} overdue`
                        : days === 0
                          ? "Today"
                          : `${days} day${days === 1 ? "" : "s"}`}
                    </span>
                  )}
                </span>
              </div>
              {harvestOverdue && (
                <div className="mt-2 border-t border-line pt-2">
                  <UpdateHarvestDialog
                    farmId={farmId}
                    currentDate={overview.expected_harvest_date}
                    onUpdated={refreshAll}
                    trigger={
                      <button className="text-xs font-medium text-leaf-700 hover:underline">
                        Update harvest date
                      </button>
                    }
                  />
                </div>
              )}
            </SectionCard>
          )}

          {/* Weather is a mock service — shown on demo farms only; a real pilot
              farm never renders a simulated widget. */}
          {overview?.is_demo && (
            <SectionCard
              title="Field conditions"
              icon={<CloudSun />}
              description="Simulated demo weather — not a live feed."
            >
              <WeatherCard farmId={farmId} />
            </SectionCard>
          )}

          {/* Outstanding work — the same arrays the queue above renders, so a
              count here can never disagree with the rows there. */}
          {overview && (
            <SectionCard title="Outstanding work" icon={<ListChecks />}>
              <ul className="divide-y divide-line">
                {[
                  {
                    icon: TriangleAlert,
                    label: "Needs action",
                    value: needsAction.length,
                    tone: needsAction.length > 0 ? "warn" : "neutral",
                  },
                  {
                    icon: Users,
                    label: "Awaiting PCA",
                    value: awaitingPca.length,
                    tone: awaitingPca.length > 0 ? "info" : "neutral",
                  },
                  {
                    icon: FileWarning,
                    label: "Follow-ups due",
                    value: followUpsDue.length,
                    tone: followUpsDue.length > 0 ? "warn" : "neutral",
                  },
                ].map((row) => {
                  const RowIcon = row.icon;
                  return (
                    <li
                      key={row.label}
                      className="flex items-center justify-between gap-3 py-2 first:pt-0 last:pb-0"
                    >
                      <span className="inline-flex items-center gap-2 text-sm text-ink">
                        <RowIcon
                          className={`h-4 w-4 ${tone(row.tone).icon}`}
                          aria-hidden
                        />
                        {row.label}
                      </span>
                      <span className="tabular text-sm font-semibold text-ink">
                        {row.value}
                      </span>
                    </li>
                  );
                })}
              </ul>
              {openByDate.length > 0 && (
                <div className="mt-3 border-t border-line pt-3">
                  <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted">
                    Open by intended date
                  </div>
                  <ul className="divide-y divide-line">
                    {openByDate.slice(0, 4).map((p) => (
                      <li key={p.id}>
                        <Link
                          href={`/decisions/${p.id}`}
                          className="group flex items-center justify-between gap-2 py-2"
                        >
                          <div className="min-w-0">
                            <div className="truncate text-sm font-medium text-ink">
                              {p.product_name}
                            </div>
                            <div className="tabular text-xs text-muted">
                              {formatDate(p.intended_date)}
                              {p.field_block ? ` · ${p.field_block}` : ""}
                            </div>
                          </div>
                          <StatusBadge kind="workflow" value={p.workflow_state} />
                        </Link>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </SectionCard>
          )}

          <SectionCard
            title="Pilot evidence"
            icon={<ClipboardCheck />}
            description={
              useDemoScope
                ? "Simulated demo records — illustrative, never customer evidence."
                : "Real (non-demo) decisions only."
            }
            action={
              <Link
                href="/evidence"
                className="inline-flex items-center gap-1 text-xs font-medium text-leaf-700 hover:underline"
              >
                View all <ArrowRight className="h-3 w-3" />
              </Link>
            }
          >
            {!scope || scope.decisions_checked === 0 ? (
              <p className="text-xs text-muted">
                No decisions recorded yet — run a pre-spray check to start the
                evidence trail.
              </p>
            ) : (
              <div className="space-y-3 text-xs text-muted">
                {useDemoScope && (
                  <Badge variant="outline">
                    <FlaskConical />
                    Simulated
                  </Badge>
                )}
                <div>
                  <div className="mb-1 flex items-center justify-between">
                    <span>PCA-reviewed decisions</span>
                    <span className="font-medium text-ink">
                      {scope.decisions_reviewed}/{scope.decisions_checked}
                    </span>
                  </div>
                  <ProgressBar
                    ratio={
                      scope.decisions_checked
                        ? scope.decisions_reviewed / scope.decisions_checked
                        : 0
                    }
                  />
                </div>
                {scope.follow_up?.follow_up_required > 0 && (
                  <div>
                    <div className="mb-1 flex items-center justify-between">
                      <span>Follow-up recorded</span>
                      <span className="font-medium text-ink">
                        {scope.follow_up.follow_up_with_events}/
                        {scope.follow_up.follow_up_required}
                      </span>
                    </div>
                    <ProgressBar
                      ratio={
                        scope.follow_up.follow_up_with_events /
                        scope.follow_up.follow_up_required
                      }
                    />
                  </div>
                )}
                <div className="flex items-center justify-between border-t border-line pt-2">
                  <span>Sprays changed / delayed / avoided</span>
                  <span className="font-medium text-ink">
                    {scope.sprays_changed_delayed_or_avoided}/{scope.decisions_checked}
                  </span>
                </div>
              </div>
            )}
          </SectionCard>

          <Link
            href={`/farms/${farmId}`}
            className="flex items-center justify-between rounded-card border border-line bg-surface p-3 text-sm font-medium text-ink shadow-sm transition-colors hover:border-muted"
          >
            <span className="inline-flex items-center gap-2">
              <ListChecks className="h-4 w-4 text-leaf" />
              Full farm record
            </span>
            <ArrowRight className="h-4 w-4 text-muted" />
          </Link>
        </div>
      </div>
    </div>
  );
}
