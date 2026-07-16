"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
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
} from "lucide-react";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
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
import ComplianceCard from "@/components/ComplianceCard";
import DecisionQueue from "@/components/DecisionQueue";
import EmptyState from "@/components/EmptyState";
import MetricCard from "@/components/MetricCard";
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
  const [compliance, setCompliance] = useState(null);
  const [evidence, setEvidence] = useState(null);
  const [error, setError] = useState(null);
  const [scoutDialogOpen, setScoutDialogOpen] = useState(false);

  const load = useCallback(async () => {
    if (!farmId) return;
    try {
      const [ov, p, s, o, c, ev] = await Promise.all([
        api.getFarmOverview(farmId),
        api.listPlannedSprays(farmId),
        api.listSprayEvents(farmId),
        api.listScoutObservations(farmId),
        api.getCompliance(farmId),
        api.getDecisionEvidence(farmId),
      ]);
      setOverview(ov);
      setPlanned(p);
      setSprays(s);
      setObservations(o);
      setCompliance(c);
      setEvidence(ev);
      setError(null);
    } catch (err) {
      setError(err.message);
    }
  }, [farmId]);

  useEffect(() => {
    load();
  }, [load]);

  if (farmsLoading) return <p className="text-sm text-gray-500">Loading farms…</p>;
  if (farmsError) {
    return (
      <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
        {farmsError} — is the backend running on <code>http://localhost:8000</code>?
      </div>
    );
  }
  if (!activeFarm) {
    return (
      <EmptyState
        icon={ShieldCheck}
        title="No farms yet"
        description="Seed the demo data (cd backend && python -m app.seed) or add a pilot farm to start checking planned sprays."
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
      <Link href="/compliance">
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
        title="Operations"
        meta={
          <>
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
        <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
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
              className="text-xs font-medium text-gray-600 underline-offset-2 hover:underline"
            >
              View decision queue
            </Link>
          }
        />
      )}

      {/* KPI row — counts come from the same array the queue below renders. */}
      {overview && (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <MetricCard
            icon={TriangleAlert}
            label="Needs action"
            value={needsAction.length}
            hint="open decisions waiting on you"
            tone={needsAction.length > 0 ? "warn" : "neutral"}
          />
          <MetricCard
            icon={Users}
            label="Awaiting PCA"
            value={awaitingPca.length}
            hint="reviews still outstanding"
            tone={awaitingPca.length > 0 ? "info" : "neutral"}
          />
          <MetricCard
            icon={FileWarning}
            label="Follow-ups due"
            value={followUpsDue.length}
            hint="outcomes needing follow-up evidence"
            tone={followUpsDue.length > 0 ? "warn" : "neutral"}
          />
          {harvestOverdue ? (
            <MetricCard
              icon={CalendarClock}
              label="Harvest date passed"
              value={`${-days} day${days === -1 ? "" : "s"} overdue`}
              hint={`Expected ${formatDate(overview.expected_harvest_date)}`}
              tone="risk"
              action={
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
              }
            />
          ) : (
            <MetricCard
              icon={CalendarClock}
              label={days === 0 ? "Harvest" : "Days to harvest"}
              value={days == null ? "—" : days === 0 ? "Today" : days}
              hint={
                overview.expected_harvest_date
                  ? `expected ${formatDate(overview.expected_harvest_date)}`
                  : "no harvest date entered"
              }
              tone="neutral"
            />
          )}
        </div>
      )}

      {/* Main grid: decision queue (8) | upcoming work + field risk (4) */}
      <div className="grid gap-4 lg:grid-cols-12">
        <div className="min-w-0 lg:col-span-8">
          <SectionCard
            title="Decision queue"
            icon={<ShieldCheck />}
            description="Verdict = the engine's historical decision. State = what (if anything) is still owed."
          >
            <DecisionQueue planned={queueRows} limit={5} viewAllHref="/decisions" />
          </SectionCard>
        </div>
        <div className="space-y-4 lg:col-span-4">
          <SectionCard
            title="Upcoming work"
            icon={<CalendarClock />}
            description="Open decisions by intended date."
          >
            {openByDate.length === 0 ? (
              <p className="text-sm text-gray-500">No open decisions.</p>
            ) : (
              <ul className="divide-y divide-gray-100">
                {openByDate.slice(0, 4).map((p) => (
                  <li key={p.id}>
                    <Link
                      href={`/decisions/${p.id}`}
                      className="group flex items-center justify-between gap-2 py-2"
                    >
                      <div className="min-w-0">
                        <div className="truncate text-sm font-medium text-gray-900">
                          {p.product_name}
                        </div>
                        <div className="text-xs text-gray-500">
                          {formatDate(p.intended_date)}
                          {p.field_block ? ` · ${p.field_block}` : ""}
                        </div>
                      </div>
                      <StatusBadge kind="workflow" value={p.workflow_state} />
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </SectionCard>

          <SectionCard
            title="Field risk"
            icon={<TriangleAlert />}
            description="Pre-spray risk snapshot — entered values, not verified label data."
          >
            <ComplianceCard data={compliance} />
          </SectionCard>
        </div>
      </div>

      {/* Bottom grid: recent activity (7) | pilot evidence (5) */}
      <div className="grid gap-4 lg:grid-cols-12">
        <div className="min-w-0 lg:col-span-7">
          <SectionCard title="Recent activity" icon={<Eye />}>
            <ActivityTimeline
              sprays={sprays}
              observations={observations}
              country={activeFarm.country}
              limit={6}
            />
          </SectionCard>
        </div>
        <div className="space-y-4 lg:col-span-5">
          <SectionCard
            title="Field conditions"
            icon={<CloudSun />}
            description="Simulated demo weather — not a live feed."
          >
            <WeatherCard farmId={farmId} />
          </SectionCard>

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
              <p className="text-xs text-gray-500">
                No decisions recorded yet — run a pre-spray check to start the
                evidence trail.
              </p>
            ) : (
              <div className="space-y-3 text-xs text-gray-600">
                {useDemoScope && (
                  <Badge variant="outline">
                    <FlaskConical />
                    Simulated
                  </Badge>
                )}
                <div>
                  <div className="mb-1 flex items-center justify-between">
                    <span>PCA-reviewed decisions</span>
                    <span className="font-medium text-gray-900">
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
                      <span className="font-medium text-gray-900">
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
                <div className="flex items-center justify-between border-t border-gray-100 pt-2">
                  <span>Sprays changed / delayed / avoided</span>
                  <span className="font-medium text-gray-900">
                    {scope.sprays_changed_delayed_or_avoided}/{scope.decisions_checked}
                  </span>
                </div>
              </div>
            )}
          </SectionCard>

          <Link
            href={`/farms/${farmId}`}
            className="flex items-center justify-between rounded-[10px] border border-gray-200 bg-white p-3 text-sm font-medium text-gray-700 shadow-sm transition-colors hover:border-gray-400"
          >
            <span className="inline-flex items-center gap-2">
              <ListChecks className="h-4 w-4 text-leaf" />
              Full farm record
            </span>
            <ArrowRight className="h-3.5 w-3.5 text-gray-300" />
          </Link>
        </div>
      </div>
    </div>
  );
}
