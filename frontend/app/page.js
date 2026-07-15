"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  CalendarClock,
  ClipboardCheck,
  CloudSun,
  Eye,
  FlaskConical,
  ListChecks,
  Plus,
  ShieldCheck,
  TriangleAlert,
  Users,
} from "lucide-react";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useFarmContext } from "@/lib/farm-context";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import Breadcrumbs from "@/components/Breadcrumbs";
import KpiTile from "@/components/KpiTile";
import NextActionBanner from "@/components/NextActionBanner";
import ProgressBar from "@/components/ProgressBar";
import ActivityTimeline from "@/components/ActivityTimeline";
import ComplianceCard from "@/components/ComplianceCard";
import DecisionQueueTable from "@/components/DecisionQueueTable";
import PreSpraySheet from "@/components/PreSpraySheet";
import ScoutObservationForm from "@/components/ScoutObservationForm";
import WeatherCard from "@/components/WeatherCard";

function SectionCard({ title, icon, description, action, children }) {
  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-2 space-y-0">
        <div>
          <CardTitle>
            {icon}
            {title}
          </CardTitle>
          {description && <p className="mt-0.5 text-xs text-gray-500">{description}</p>}
        </div>
        {action}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

// Operations overview for the active farm: what needs attention right now,
// the decision queue, and the evidence trail. All numbers are real fields from
// existing endpoints — no invented metrics.
export default function OperationsPage() {
  const { activeFarm, loading: farmsLoading, error: farmsError } = useFarmContext();
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
      <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
        {farmsError} — is the backend running on <code>http://localhost:8000</code>?
      </div>
    );
  }
  if (!activeFarm) {
    return (
      <div className="space-y-3">
        <h1 className="text-lg font-semibold text-gray-900">Operations</h1>
        <div className="rounded-xl border border-gray-200 bg-white p-4 text-sm text-gray-500">
          No farms yet. Seed the demo data (<code>cd backend &amp;&amp; python -m app.seed</code>)
          or{" "}
          <Link href="/pilot/new" className="font-medium text-leaf-700 hover:underline">
            add a pilot farm
          </Link>
          .
        </div>
      </div>
    );
  }

  const openPlanned = planned
    .filter((p) => p.is_open)
    .sort((a, b) => (a.intended_date < b.intended_date ? -1 : 1));
  const checkedReal = evidence?.decisions_checked ?? 0;
  const reviewedReal = evidence?.decisions_reviewed ?? 0;
  const followUp = evidence?.follow_up;

  return (
    <div className="space-y-5">
      <Breadcrumbs items={[{ label: "Operations" }, { label: "Today" }]} />

      {/* Header + primary CTAs */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-gray-900">Operations overview</h1>
          <p className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-gray-500">
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
          </p>
        </div>
        <div className="flex items-center gap-2">
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
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Server-computed next action for this farm */}
      {overview && (
        <NextActionBanner
          nextAction={overview.next_action}
          why={overview.why}
          urgency={overview.urgency}
          cta={
            overview.needs_review_count > 0 ? (
              <Link href="/decisions">
                <Button variant="secondary" size="sm">
                  <ListChecks />
                  Open decisions
                </Button>
              </Link>
            ) : null
          }
        />
      )}

      {/* KPI tiles — real overview counts only */}
      {overview && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <KpiTile
            icon={ClipboardCheck}
            label="Open decisions"
            value={overview.awaiting_outcome_count}
            hint="checked, no recorded outcome"
            tone={overview.awaiting_outcome_count > 0 ? "warn" : "neutral"}
          />
          <KpiTile
            icon={Users}
            label="Needs PCA review"
            value={overview.needs_review_count}
            hint="pending pre-spray reviews"
            tone={overview.needs_review_count > 0 ? "warn" : "neutral"}
          />
          <KpiTile
            icon={TriangleAlert}
            label="Risk flags"
            value={overview.flag_count}
            hint="PHI · REI · rotation · scouting"
            tone={overview.flag_count > 0 ? "warn" : "good"}
          />
          <KpiTile
            icon={CalendarClock}
            label="Days to harvest"
            value={overview.days_to_harvest ?? "—"}
            hint={
              overview.expected_harvest_date
                ? `expected ${formatDate(overview.expected_harvest_date)}`
                : "no harvest date entered"
            }
            tone="neutral"
          />
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        {/* Main column */}
        <div className="space-y-4 lg:col-span-2">
          <SectionCard
            title="Decision queue"
            icon={<ShieldCheck />}
            description="Planned sprays checked by the rule engine. Reviews and outcomes are recorded on the decision record."
          >
            <DecisionQueueTable planned={planned} limit={5} viewAllHref="/decisions" />
          </SectionCard>

          <SectionCard
            title="Recent activity"
            icon={<Eye />}
            description="Sprays and scouting, newest first."
          >
            <ActivityTimeline
              sprays={sprays}
              observations={observations}
              country={activeFarm.country}
              limit={6}
            />
          </SectionCard>
        </div>

        {/* Right rail */}
        <div className="space-y-4">
          <SectionCard
            title="Upcoming work"
            icon={<CalendarClock />}
            description="Open decisions by intended date."
          >
            {openPlanned.length === 0 ? (
              <p className="text-sm text-gray-500">No open decisions.</p>
            ) : (
              <ul className="divide-y divide-gray-100">
                {openPlanned.slice(0, 4).map((p) => (
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
                          {p.target_pest_or_disease ? ` · ${p.target_pest_or_disease}` : ""}
                        </div>
                      </div>
                      <ArrowRight className="h-3.5 w-3.5 shrink-0 text-gray-300 group-hover:text-leaf-700" />
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </SectionCard>

          <SectionCard
            title="Pre-spray risk snapshot"
            icon={<TriangleAlert />}
            description="From entered spray + scouting records — not verified label data."
          >
            <ComplianceCard data={compliance} />
          </SectionCard>

          <SectionCard title="Field conditions" icon={<CloudSun />}>
            <WeatherCard farmId={farmId} />
          </SectionCard>

          <SectionCard
            title="Pilot evidence"
            icon={<ClipboardCheck />}
            description="Real (non-demo) decisions only."
            action={
              <Link
                href="/evidence"
                className="inline-flex items-center gap-1 text-xs font-medium text-leaf-700 hover:underline"
              >
                View all <ArrowRight className="h-3 w-3" />
              </Link>
            }
          >
            {checkedReal === 0 ? (
              <p className="text-xs text-gray-500">
                No real (non-demo) decisions recorded yet — evidence metrics count
                real pilot data only.
              </p>
            ) : (
              <div className="space-y-3 text-xs text-gray-600">
                <div>
                  <div className="mb-1 flex items-center justify-between">
                    <span>PCA-reviewed decisions</span>
                    <span className="font-medium text-gray-900">
                      {reviewedReal}/{checkedReal}
                    </span>
                  </div>
                  <ProgressBar ratio={checkedReal ? reviewedReal / checkedReal : 0} />
                </div>
                {followUp && followUp.follow_up_required > 0 && (
                  <div>
                    <div className="mb-1 flex items-center justify-between">
                      <span>Follow-up recorded</span>
                      <span className="font-medium text-gray-900">
                        {followUp.follow_up_with_events}/{followUp.follow_up_required}
                      </span>
                    </div>
                    <ProgressBar
                      ratio={
                        followUp.follow_up_required
                          ? followUp.follow_up_with_events / followUp.follow_up_required
                          : 0
                      }
                    />
                  </div>
                )}
              </div>
            )}
          </SectionCard>

          <Link
            href={`/farms/${farmId}`}
            className="flex items-center justify-between rounded-xl border border-gray-200 bg-white p-3 text-sm font-medium text-gray-700 shadow-sm transition-colors hover:border-gray-400"
          >
            <span className="inline-flex items-center gap-2">
              <Plus className="h-4 w-4 text-leaf" />
              Full farm record
            </span>
            <ArrowRight className="h-3.5 w-3.5 text-gray-300" />
          </Link>
        </div>
      </div>
    </div>
  );
}
