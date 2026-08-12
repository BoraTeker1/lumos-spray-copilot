"use client";

import { LoadingState } from "@/components/SystemState";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  CalendarClock,
  ClipboardCheck,
  CloudSun,
  Database,
  Droplets,
  Eye,
  FlaskConical,
  Handshake,
  Landmark,
  ListChecks,
  MapPin,
  Plus,
  ShieldCheck,
  ShoppingCart,
  Sprout,
  TrendingUp,
  TriangleAlert,
  Users,
  Wrench,
} from "lucide-react";
import { api } from "@/lib/api";
import { formatArea, formatCost, formatDate } from "@/lib/format";
import { URGENCY_META } from "@/lib/labels";
import { useFarmContext } from "@/lib/farm-context";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import ActivityTimeline from "@/components/ActivityTimeline";
import Callout from "@/components/Callout";
import PageHeader from "@/components/PageHeader";
import ComplianceCard from "@/components/ComplianceCard";
import DataTable from "@/components/DataTable";
import DetailPanel, {
  DetailRow,
  DetailSection,
} from "@/components/DetailPanel";
import EmptyState from "@/components/EmptyState";
import DataReadinessCard from "@/components/DataReadinessCard";
import FarmProfileCard from "@/components/FarmProfileCard";
import EvidencePanel from "@/components/EvidencePanel";
import InputPlanForm from "@/components/InputPlanForm";
import MetricCard from "@/components/MetricCard";
import NextActionBanner from "@/components/NextActionBanner";
import PhotoScoutCard from "@/components/PhotoScoutCard";
import PilotImportCard from "@/components/PilotImportCard";
import PreSpraySheet, { PlannedSprayList } from "@/components/PreSpraySheet";
import ScoutObservationForm from "@/components/ScoutObservationForm";
import SeasonPanel from "@/components/SeasonPanel";
import SectionCard from "@/components/SectionCard";
import SprayEventForm from "@/components/SprayEventForm";
import SeverityBadge from "@/components/SeverityBadge";
import SprayImportCard from "@/components/SprayImportCard";
import StatusBadge from "@/components/StatusBadge";
import ValueLedgerCard from "@/components/ValueLedgerCard";
import AdvisoryQueue from "@/components/AdvisoryQueue";
import FarmPerformanceCard from "@/components/FarmPerformanceCard";
import ParticipationCard from "@/components/ParticipationCard";
import DataCoverageCard from "@/components/DataCoverageCard";
import OutstandingFollowUpsCard from "@/components/OutstandingFollowUpsCard";
import WeatherCard from "@/components/WeatherCard";

// "fields" and "conditions" are new views over data this page already fetches.
// The pre-existing keys keep working so links already in the wild (and
// /decisions/[id]'s "Back to farm" link, which uses ?tab=planned) do not break.
const TABS = ["overview", "fields", "conditions", "planned", "records", "evidence"];

// A record is "real pilot data" unless tagged demo/simulated; a farm whose
// records are all demo-tagged is a seeded demo farm (farms carry no provenance
// of their own, so this is derived from their records).
function isDemoRecord(r) {
  return r.data_source === "demo" || r.data_confidence === "simulated";
}

function FarmDetail({ farmId }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { farms, setActiveFarmId } = useFarmContext();

  // Visiting a farm makes it the active farm for the farm-scoped sidebar pages
  // (only if it's in the visible switcher list — TR demo farms stay unlinked).
  useEffect(() => {
    if (farms.some((f) => f.id === Number(farmId))) setActiveFarmId(farmId);
  }, [farmId, farms, setActiveFarmId]);

  const [farm, setFarm] = useState(null);
  const [overview, setOverview] = useState(null);
  const [sprays, setSprays] = useState([]);
  const [observations, setObservations] = useState([]);
  const [recommendations, setRecommendations] = useState([]);
  const [planned, setPlanned] = useState([]);
  const [compliance, setCompliance] = useState(null);
  const [inputPlans, setInputPlans] = useState([]);
  const [purchaseOrders, setPurchaseOrders] = useState([]);
  const [cycles, setCycles] = useState([]);
  const [blocks, setBlocks] = useState([]);
  const [ledger, setLedger] = useState(null);
  // The composed farm-intelligence payload: advisory queue, performance, coverage,
  // participation and financing in ONE call, so the overview cannot disagree with
  // the dedicated pages that serve the same builders.
  const [intelligence, setIntelligence] = useState(null);
  // null = every season; a cycle id scopes the ledger to that one.
  const [ledgerCycleId, setLedgerCycleId] = useState(null);
  const [error, setError] = useState(null);
  const [sprayDialogOpen, setSprayDialogOpen] = useState(false);
  const [scoutDialogOpen, setScoutDialogOpen] = useState(false);

  const tabParam = searchParams.get("tab");
  const tab = TABS.includes(tabParam) ? tabParam : "overview";
  const setTab = (value) => {
    router.replace(value === "overview" ? pathname : `${pathname}?tab=${value}`, {
      scroll: false,
    });
  };

  const load = useCallback(async () => {
    try {
      const [f, ov, s, o, r, p, c, plans, orders, cyc, blk] = await Promise.all([
        api.getFarm(farmId),
        api.getFarmOverview(farmId),
        api.listSprayEvents(farmId),
        api.listScoutObservations(farmId),
        api.listRecommendations(farmId),
        api.listPlannedSprays(farmId),
        api.getCompliance(farmId),
        api.listInputPlans(farmId),
        api.listOrders(farmId),
        api.listCropCycles(farmId),
        api.listBlocks(farmId),
      ]);
      setFarm(f);
      setOverview(ov);
      setSprays(s);
      setObservations(o);
      setRecommendations(r);
      setPlanned(p);
      setCompliance(c);
      setInputPlans(plans);
      setPurchaseOrders(orders);
      setCycles(cyc);
      setBlocks(blk);
      // Fetched separately and non-fatally: the intelligence view composes several
      // builders, and a farm with no season yet must still render its records.
      try {
        setIntelligence(await api.getFarmIntelligence(farmId));
      } catch {
        setIntelligence(null);
      }
    } catch (err) {
      setError(err.message);
    }
  }, [farmId]);

  useEffect(() => {
    load();
  }, [load]);

  // The ledger is its own fetch because it re-runs on a season change without
  // reloading the whole farm. `cycles` is a dependency so recording an outcome or
  // starting a season refreshes the figures.
  const loadLedger = useCallback(async () => {
    try {
      setLedger(await api.getValueLedger(farmId, ledgerCycleId ?? undefined));
    } catch (err) {
      setError(err.message);
    }
  }, [farmId, ledgerCycleId]);

  useEffect(() => {
    loadLedger();
  }, [loadLedger, cycles]);

  const latest = recommendations[0] || null;

  // Status, counts, and relative-day math all come from /farms/{id}/overview — the
  // SAME server derivation the dashboard card uses, so the two views can never
  // disagree. Only display-local bits (queue ordering, provenance lists) are derived
  // here, and those use the server's per-row `is_open` field.
  const derived = useMemo(() => {
    const records = [...sprays, ...observations];
    const openPlanned = planned.filter((p) => p.is_open);
    const hasDocumentedSkip = planned.some(
      (p) => p.outcome === "avoided" && !isDemoRecord(p)
    );
    const provenanceSources = [...new Set(records.map((r) => r.data_source).filter(Boolean))];
    const provenanceConfidence = [
      ...new Set(records.map((r) => r.data_confidence).filter(Boolean)),
    ];
    // Most recent observation that recorded a crop stage — the honest stand-in
    // for "growth stage" (it's what was last scouted, not a live sensor).
    const lastScoutedStage = [...observations]
      .sort((a, b) => (a.observation_date < b.observation_date ? 1 : -1))
      .find((o) => o.crop_stage)?.crop_stage;
    // Records grouped by the free-text field/block name entered on each row.
    // This is a GROUPING of strings, not a field entity: the backend exposes no
    // field resource, `field_block` is typed per record, and nothing reconciles
    // two spellings of the same field. Rows with no name are collected under a
    // single explicit bucket rather than silently dropped.
    const fieldNames = [
      ...new Set(
        [...sprays, ...observations, ...planned]
          .map((r) => r.field_block)
          .filter(Boolean)
      ),
    ].sort();
    const fieldGroups = fieldNames.map((name) => ({
      name,
      sprays: sprays.filter((s) => s.field_block === name),
      observations: observations.filter((o) => o.field_block === name),
      planned: planned.filter((p) => p.field_block === name),
    }));
    const unassignedCount = [...sprays, ...observations, ...planned].filter(
      (r) => !r.field_block
    ).length;

    return {
      openPlanned,
      hasDocumentedSkip,
      provenanceSources,
      provenanceConfidence,
      lastScoutedStage,
      fieldGroups,
      unassignedCount,
    };
  }, [sprays, observations, planned]);

  if (error)
    return (
      <Callout tone="risk">
        {error} — is the backend running on <code>http://localhost:8000</code>?
      </Callout>
    );
  if (!farm || !overview) return <LoadingState message="Loading farm record…" />;

  // Same urgency vocabulary as the dashboard card (shared via lib/labels.js).
  const status = URGENCY_META[overview.urgency] || URGENCY_META.ok;
  const isDemoFarm = overview.is_demo;
  // The decision queue: open checks first (review needed, then awaiting outcome),
  // then the most recent resolved ones.
  const queue = [
    ...derived.openPlanned,
    ...planned.filter((p) => !p.is_open),
  ].slice(0, 3);

  return (
    <div className="space-y-5">
      {/* Farm header. Uses the shared PageHeader so the most important record
          page in the product does not carry a smaller title than every other
          route — it was rendering at text-lg where the rest use text-title. */}
      <PageHeader
        breadcrumbs={[{ label: "Farms & fields", href: "/farms" }, { label: farm.name }]}
        title={farm.name}
        actions={<PreSpraySheet farmId={farmId} onChanged={load} />}
        meta={
          <>
            <span className="flex flex-wrap items-center gap-2">
              <Badge variant={status.variant}>{status.label}</Badge>
              {isDemoFarm && (
                <Badge variant="outline">
                  <FlaskConical />
                  Simulated demo data
                </Badge>
              )}
              {farm.is_reference && (
                <Badge variant="outline">
                  <Wrench />
                  Operator reference farm — not a customer
                </Badge>
              )}
            </span>
            {/* Meta strip — real farm fields only */}
            <span className="flex w-full flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
              <span className="inline-flex items-center gap-1">
                <MapPin className="h-3.5 w-3.5" />
                {farm.location || "—"}
              </span>
              <span className="inline-flex items-center gap-1 capitalize">
                <Sprout className="h-3.5 w-3.5" />
                {farm.crop_type?.replace(/_/g, " ") || "—"}
                {farm.greenhouse_area != null &&
                  ` · ${formatArea(farm.greenhouse_area, farm.country)}`}
              </span>
              <span className="inline-flex items-center gap-1">
                <CalendarClock className="h-3.5 w-3.5" />
                harvest {formatDate(farm.expected_harvest_date)}
              </span>
              <span className="inline-flex items-center gap-1">
                <Users className="h-3.5 w-3.5" />
                PCA involved: {farm.advisor_involved ? "yes" : "no"}
              </span>
              {derived.lastScoutedStage && (
                <span className="inline-flex items-center gap-1 capitalize">
                  <Eye className="h-3.5 w-3.5" />
                  last scouted stage: {derived.lastScoutedStage.replace(/_/g, " ")}
                </span>
              )}
            </span>
          </>
        }
      />

      {/* Server-computed next action for this farm */}
      <NextActionBanner
        issue={overview.why}
        consequence={overview.next_action}
        urgency={overview.urgency}
      />

      {/* KPI row — every number is the server's overview entry (dashboard parity). */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <MetricCard
          icon={CalendarClock}
          label="Upcoming harvest"
          value={formatDate(farm.expected_harvest_date)}
          hint={
            overview.days_to_harvest == null
              ? null
              : overview.days_to_harvest >= 0
              ? `in ${overview.days_to_harvest} day${overview.days_to_harvest === 1 ? "" : "s"}`
              : `${-overview.days_to_harvest} days ago`
          }
          tone="neutral"
        />
        <MetricCard
          icon={ClipboardCheck}
          label="Needs PCA review"
          value={overview.needs_review_count}
          tone={overview.needs_review_count > 0 ? "warn" : "neutral"}
        />
        <MetricCard
          icon={ListChecks}
          label="Awaiting outcome"
          value={overview.awaiting_outcome_count}
          hint="checked sprays, no recorded result"
          tone={overview.awaiting_outcome_count > 0 ? "warn" : "neutral"}
        />
        <MetricCard
          icon={TriangleAlert}
          label="Risk flags"
          value={overview.flag_count}
          tone={overview.flag_count > 0 ? "warn" : "good"}
          hint="PHI · REI · rotation · scouting"
        />
      </div>

      {/* Tabs */}
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="fields">
            Fields
            {derived.fieldGroups.length > 0 && (
              <span className="tabular rounded-full bg-draft-bg px-1.5 text-[11px] font-semibold text-draft-fg">
                {derived.fieldGroups.length}
              </span>
            )}
          </TabsTrigger>
          <TabsTrigger value="conditions">Conditions</TabsTrigger>
          <TabsTrigger value="planned">
            Planned sprays
            {overview.awaiting_outcome_count > 0 && (
              <span className="tabular rounded-full bg-warn-bg px-1.5 text-[11px] font-semibold text-warn-fg">
                {overview.awaiting_outcome_count}
              </span>
            )}
          </TabsTrigger>
          <TabsTrigger value="records">Records</TabsTrigger>
          <TabsTrigger value="evidence">Evidence</TabsTrigger>
        </TabsList>

        {/* -------------------------------------------------------------- Fields */}
        <TabsContent value="fields">
          <FieldsTab
            groups={derived.fieldGroups}
            unassignedCount={derived.unassignedCount}
            country={farm.country}
          />
        </TabsContent>

        {/* ---------------------------------------------------------- Conditions */}
        <TabsContent value="conditions">
          <ConditionsTab
            farmId={farmId}
            isDemo={overview.is_demo}
            observations={observations}
            overview={overview}
          />
        </TabsContent>

        {/* ------------------------------------------------------------ Overview */}
        {/* The operating loop, in the order a grower reads it:
              what needs doing → what the season is worth → what Lumos created
              → how the farm is performing → what that unlocks → what data backs it.
            Detail stays on the dedicated pages; this tab is the story. */}
        <TabsContent value="overview">
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <div className="min-w-0 space-y-4 lg:col-span-2">
              {/* 1. PRIORITIES. The advisory queue leads because it is the only
                  block that tells you what to DO. Everything below explains it. */}
              <SectionCard
                title="What needs attention"
                icon={<ListChecks />}
                description="Ranked by urgency, derived from this farm's records. Items clear themselves as records change — there is nothing to dismiss."
              >
                <AdvisoryQueue
                  queue={intelligence?.advisory}
                  farmId={farmId}
                  cropCycleId={intelligence?.crop_cycle?.id}
                  limit={6}
                />
              </SectionCard>

              {/* 2. THE DECISION LOOP, still the core product. */}
              <SectionCard
                title="Decision queue"
                icon={<ShieldCheck />}
                description="Every planned spray gets one clear outcome — approve, block, delay, inspect first, or PCA review required — then a recorded real-world result."
                action={
                  planned.length > 3 && (
                    <button
                      onClick={() => setTab("planned")}
                      className="text-xs font-medium text-leaf-700 hover:underline"
                    >
                      View all ({planned.length})
                    </button>
                  )
                }
              >
                <PlannedSprayList
                  planned={queue}
                  onChanged={load}
                  country={farm.country}
                  emptyText='No pre-spray decisions yet — use "Check a planned spray" before the next application.'
                />
              </SectionCard>

              {/* Follow-up evidence is the only thing that moves attributable value
                  from estimated to verified, so the outstanding ones belong on the
                  page a grower actually opens — not only on a decision's detail. */}
              <OutstandingFollowUpsCard planned={planned} onChanged={load} />

              {/* 3. WHAT LUMOS CREATED: recommendation → action → outcome → value. */}
              <ValueLedgerCard
                ledger={ledger}
                cycles={cycles}
                activeCycleId={ledgerCycleId}
                onSelectCycle={setLedgerCycleId}
                onChanged={load}
              />

              {/* 4. HOW THE FARM IS DOING, season over season. */}
              <SectionCard
                title="Farm performance"
                icon={<TrendingUp />}
                description="This farm against its own previous seasons. No score and no peer benchmark — the metrics and their movement are the story."
              >
                <FarmPerformanceCard performance={intelligence?.performance} />
              </SectionCard>

              {/* 5. WHAT LUMOS IS PAID, on the same recorded evidence. */}
              <SectionCard
                title="Lumos commercial model"
                icon={<Handshake />}
                description="What was agreed, what recorded evidence is the basis, and what the participation calculates to. An accounting figure — no money moves through Lumos."
              >
                <ParticipationCard
                  participation={intelligence?.participation}
                  farmId={farmId}
                />
              </SectionCard>

              <SectionCard title="Recent activity" icon={<Droplets />}>
                <ActivityTimeline
                  sprays={sprays}
                  observations={observations}
                  country={farm.country}
                  limit={6}
                />
              </SectionCard>
            </div>

            {/* Right rail */}
            <div className="space-y-4">
              <SeasonPanel
                farmId={farmId}
                farm={farm}
                cycles={cycles}
                blocks={blocks}
                onChanged={load}
              />

              {/* Weather is a mock service — demo farms only; a real pilot farm
                  never renders a simulated widget. */}
              {isDemoFarm && (
                <SectionCard
                  title="Field conditions"
                  icon={<CloudSun />}
                  description="Simulated demo weather — not a live feed."
                >
                  <WeatherCard farmId={farmId} />
                </SectionCard>
              )}

              <SectionCard
                title="Pre-spray risk snapshot"
                icon={<ClipboardCheck />}
                description={
                  compliance?.basis_text ||
                  "From user-entered PHI/REI values — not label-verified."
                }
              >
                <ComplianceCard data={compliance} />
              </SectionCard>

              {/* Renders for real and demo farms alike: unlike the weather widget
                  above, this reports what the data IS, so a demo farm honestly shows
                  its measures abstaining. */}
              <DataReadinessCard farmId={farmId} />

              {/* What data Lumos actually holds for this farm. Deliberately blunt:
                  most domains are empty for most farms, and saying so is more useful
                  than a full-looking grid. */}
              <SectionCard
                title="Data coverage"
                icon={<Database />}
                description="Which sources carry records for this farm — and which are declared but not connected."
              >
                <DataCoverageCard coverage={intelligence?.coverage} />
              </SectionCard>

              {/* The financing opportunity the operational record creates. This is
                  the product insight in one card: the same data that advises the
                  grower is what makes the farm legible to a lender. */}
              <SectionCard
                title="Financing"
                icon={<Landmark />}
                description="Evidence a lender asks for, assembled from records this farm already keeps."
                action={
                  <Link
                    href="/financing"
                    className="text-xs font-medium text-leaf-700 hover:underline"
                  >
                    Open
                  </Link>
                }
              >
                {intelligence?.financing?.request_count ? (
                  <dl className="space-y-1.5 text-xs">
                    <div className="flex items-center justify-between">
                      <dt className="text-muted">Requests</dt>
                      <dd className="font-medium text-ink">
                        {intelligence.financing.request_count}
                      </dd>
                    </div>
                    <div className="flex items-center justify-between">
                      <dt className="text-muted">Open</dt>
                      <dd className="font-medium text-ink">
                        {intelligence.financing.open_request_count}
                      </dd>
                    </div>
                  </dl>
                ) : (
                  <p className="text-sm text-muted">
                    No financing request yet. Opening one shows which of a lender&rsquo;s
                    usual evidence items this farm already has on record.
                  </p>
                )}
              </SectionCard>

              {/* The cross-layer view. Farm-scoped and grower-facing — and deliberately
                  NOT on /decisions/[id], because the Botrytis shadow study depends on
                  the reviewing PCA not seeing model output. */}
              <FarmProfileCard farmId={farmId} />

              <SectionCard
                title="Inputs & orders"
                icon={<ShoppingCart />}
                description="Input plans, supplier quotes, and orders for this farm."
                action={<InputPlanForm farmId={farmId} onCreated={load} />}
              >
                {inputPlans.length === 0 && purchaseOrders.length === 0 ? (
                  <p className="text-sm text-muted">
                    No input plans yet — build one from an approved decision or
                    manually.
                  </p>
                ) : (
                  <dl className="space-y-1.5 text-xs">
                    {[
                      [
                        "Active plans",
                        inputPlans.filter(
                          (p) => !["ordered", "cancelled"].includes(p.status)
                        ).length,
                      ],
                      [
                        "Awaiting quotes",
                        inputPlans.filter((p) => p.status === "submitted_for_quotes")
                          .length,
                      ],
                      [
                        "Quotes to compare",
                        inputPlans.filter((p) => p.status === "quoted").length,
                      ],
                      ["Orders", purchaseOrders.length],
                    ].map(([label, value]) => (
                      <div key={label} className="flex items-center justify-between">
                        <dt className="text-muted">{label}</dt>
                        <dd className="font-medium text-ink">{value}</dd>
                      </div>
                    ))}
                    <Link
                      href="/inputs"
                      className="mt-1 inline-block text-xs font-medium text-leaf-700 hover:underline"
                    >
                      Open Inputs & finance
                    </Link>
                  </dl>
                )}
              </SectionCard>

              <SectionCard title="Field details" icon={<Sprout />}>
                <dl className="space-y-1.5 text-xs">
                  {[
                    ["Crop", farm.crop_type?.replace(/_/g, " ") || "—"],
                    [
                      "Area",
                      farm.greenhouse_area != null
                        ? formatArea(farm.greenhouse_area, farm.country)
                        : "—",
                    ],
                    ["Planted", farm.planting_date ? formatDate(farm.planting_date) : "—"],
                    [
                      "Expected harvest",
                      farm.expected_harvest_date
                        ? formatDate(farm.expected_harvest_date)
                        : "—",
                    ],
                    ["Country", (farm.country || "US").toUpperCase()],
                    ["PCA / advisor involved", farm.advisor_involved ? "Yes" : "No"],
                  ].map(([label, value]) => (
                    <div key={label} className="flex items-center justify-between gap-2">
                      <dt className="text-muted">{label}</dt>
                      <dd className="text-right font-medium capitalize text-ink">
                        {value}
                      </dd>
                    </div>
                  ))}
                </dl>
              </SectionCard>

              <SectionCard title="Data provenance" icon={<FlaskConical />}>
                <div className="space-y-1.5 text-xs text-muted">
                  <div className="flex items-center justify-between gap-2">
                    <span>Sources</span>
                    <span className="text-right font-medium text-ink">
                      {derived.provenanceSources.length
                        ? derived.provenanceSources.map((s) => s.replace(/_/g, " ")).join(", ")
                        : "—"}
                    </span>
                  </div>
                  <div className="flex items-center justify-between gap-2">
                    <span>Confidence</span>
                    <span className="text-right font-medium text-ink">
                      {derived.provenanceConfidence.length
                        ? derived.provenanceConfidence.map((c) => c.replace(/_/g, " ")).join(", ")
                        : "—"}
                    </span>
                  </div>
                  {isDemoFarm && (
                    <p className="rounded bg-canvas px-2 py-1 text-[11px] text-muted">
                      Seeded demo farm — all records are simulated.
                    </p>
                  )}
                </div>
              </SectionCard>
            </div>
          </div>
        </TabsContent>

        {/* ------------------------------------------------------- Planned sprays */}
        <TabsContent value="planned">
          <SectionCard
            title="Planned sprays"
            icon={<ListChecks />}
            description="Every pre-spray decision with its snapshot, PCA review, and recorded outcome. Every outcome except “sprayed as planned” requires a stated reason."
          >
            <PlannedSprayList planned={planned} onChanged={load} country={farm.country} />
          </SectionCard>
        </TabsContent>

        {/* -------------------------------------------------------------- Records */}
        <TabsContent value="records">
          <div className="space-y-4">
            <SectionCard
              title="Spray & scouting records"
              icon={<Droplets />}
              description={`${sprays.length} sprays · ${observations.length} scouting notes`}
              action={
                <div className="flex gap-2">
                  <Dialog open={sprayDialogOpen} onOpenChange={setSprayDialogOpen}>
                    <DialogTrigger asChild>
                      <Button variant="outline" size="sm">
                        <Plus />
                        Log spray
                      </Button>
                    </DialogTrigger>
                    <DialogContent>
                      <DialogHeader>
                        <DialogTitle>Log spray event</DialogTitle>
                        <DialogDescription>
                          Record an application that already happened. To evaluate a spray before
                          applying it, use “Check a planned spray”.
                        </DialogDescription>
                      </DialogHeader>
                      <SprayEventForm
                        farmId={farmId}
                        onCreated={async () => {
                          setSprayDialogOpen(false);
                          await load();
                        }}
                      />
                    </DialogContent>
                  </Dialog>
                  <Dialog open={scoutDialogOpen} onOpenChange={setScoutDialogOpen}>
                    <DialogTrigger asChild>
                      <Button variant="outline" size="sm">
                        <Plus />
                        Add scouting note
                      </Button>
                    </DialogTrigger>
                    <DialogContent>
                      <DialogHeader>
                        <DialogTitle>Add scouting note</DialogTitle>
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
                </div>
              }
            >
              <ActivityTimeline
                sprays={sprays}
                observations={observations}
                country={farm.country}
              />
            </SectionCard>

            <SectionCard
              title="Import spray history"
              icon={<Plus />}
              description="Paste rows from a spreadsheet or upload a CSV — no formatting gymnastics."
            >
              <SprayImportCard farmId={farmId} onImported={load} />
            </SectionCard>

            <SectionCard
              title="Pilot CSV import (planned sprays & scouting)"
              icon={<Plus />}
              description="Real pilot records: dry-run validation, correctable column mapping, duplicate detection. Imported values are flagged unverified and never auto-approve."
            >
              <PilotImportCard farmId={farmId} onImported={load} />
            </SectionCard>

            <SectionCard
              title="Photo scouting (AI-assisted)"
              icon={<Eye />}
              description="Secondary tool: a photo drafts a scouting note that a human must review and confirm."
            >
              <PhotoScoutCard farmId={farmId} onCreated={load} />
            </SectionCard>
          </div>
        </TabsContent>

        {/* ------------------------------------------------------------- Evidence */}
        <TabsContent value="evidence">
          <EvidencePanel
            farmId={farmId}
            farm={farm}
            isDemoFarm={isDemoFarm}
            hasDocumentedSkip={derived.hasDocumentedSkip}
            latest={latest}
            planned={planned}
            sprays={sprays}
            observations={observations}
            recommendations={recommendations}
            onChanged={load}
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}

// Fields view: a master list of the field/block NAMES entered on records, with a
// selected-row panel. Deliberately NOT a route — `field_block` is free text typed
// per record, not a stable entity with an id, and a URL keyed on it would imply a
// data guarantee the backend does not make. Everything here filters arrays this
// page already fetched; no extra request, no new derivation.
function FieldsTab({ groups, unassignedCount, country }) {
  const [selectedName, setSelectedName] = useState(null);
  const selected = groups.find((g) => g.name === selectedName) || null;

  if (groups.length === 0) {
    return (
      <EmptyState
        icon={Sprout}
        title="No field or block names on record"
        description="Field names come from the field/block typed on each spray, scouting note, or planned-spray check. Enter one to group records here."
      />
    );
  }

  const lead = (g) =>
    [...g.observations].sort((a, b) =>
      a.observation_date < b.observation_date ? 1 : -1
    )[0] || null;

  return (
    <div className="space-y-3">
      <p className="text-meta text-muted">
        Grouped by the field/block name entered on records.
      </p>
      <div
        className={`grid grid-cols-1 gap-4 ${
          selected ? "xl:grid-cols-[minmax(0,1fr)_340px]" : "grid-cols-1"
        }`}
      >
        <Card>
          <CardContent className="p-5">
            <DataTable
              minWidth={560}
              onRowClick={(g) =>
                setSelectedName((cur) => (cur === g.name ? null : g.name))
              }
              selectedKey={selected?.name ?? null}
              rowKey={(g) => g.name}
              rows={groups}
              columns={[
                {
                  key: "field",
                  header: "Field / block",
                  render: (g) => (
                    <span className="font-medium text-ink">{g.name}</span>
                  ),
                },
                {
                  key: "obs",
                  header: "Latest observation",
                  render: (g) => {
                    const o = lead(g);
                    return o ? (
                      <div className="flex items-center gap-2">
                        <SeverityBadge value={o.severity_1_to_5} />
                        <span className="min-w-0 text-sm text-ink">
                          {o.visible_issue}
                        </span>
                      </div>
                    ) : (
                      <span className="text-xs text-muted">None recorded</span>
                    );
                  },
                },
                {
                  key: "observed",
                  header: "Observed",
                  render: (g) => {
                    const o = lead(g);
                    return (
                      <span className="tabular whitespace-nowrap text-sm text-muted">
                        {o ? formatDate(o.observation_date) : "—"}
                      </span>
                    );
                  },
                },
                {
                  key: "counts",
                  header: "Records",
                  align: "right",
                  render: (g) => (
                    <span className="whitespace-nowrap text-xs text-muted">
                      {g.planned.length} decisions · {g.sprays.length} sprays
                    </span>
                  ),
                },
              ]}
            />
            {unassignedCount > 0 && (
              <p className="mt-3 border-t border-line pt-3 text-meta text-muted">
                {unassignedCount} record{unassignedCount === 1 ? "" : "s"} carry no
                field/block name and are not grouped above.
              </p>
            )}
          </CardContent>
        </Card>

        {selected && (
          <DetailPanel
            className="h-fit xl:sticky xl:top-20"
            title={selected.name}
            subtitle="Grouped by the field/block name entered on records."
            onClose={() => setSelectedName(null)}
          >
            <DetailSection title="On record">
              <DetailRow label="Planned-spray decisions" value={selected.planned.length} />
              <DetailRow label="Applications" value={selected.sprays.length} />
              <DetailRow label="Scouting observations" value={selected.observations.length} />
            </DetailSection>
            {selected.planned.length > 0 && (
              <DetailSection title="Decision history">
                <ul className="space-y-2">
                  {selected.planned.slice(0, 5).map((p) => (
                    <li key={p.id}>
                      <Link
                        href={`/decisions/${p.id}`}
                        className="flex items-start justify-between gap-2"
                      >
                        <span className="min-w-0">
                          <span className="block truncate text-sm font-medium text-ink">
                            {p.product_name}
                          </span>
                          <span className="tabular block text-xs text-muted">
                            {formatDate(p.intended_date)}
                          </span>
                        </span>
                        <StatusBadge kind="verdict" value={p.decision_outcome} />
                      </Link>
                    </li>
                  ))}
                </ul>
              </DetailSection>
            )}
            {selected.sprays.length > 0 && (
              <DetailSection title="Application history">
                <ul className="space-y-2">
                  {selected.sprays.slice(0, 5).map((s) => (
                    <li key={s.id} className="flex items-start justify-between gap-2">
                      <span className="min-w-0">
                        <span className="block truncate text-sm text-ink">
                          {s.product_name}
                        </span>
                        <span className="tabular block text-xs text-muted">
                          {formatDate(s.application_date)}
                        </span>
                      </span>
                      <span className="tabular shrink-0 text-sm font-medium text-ink">
                        {s.cost != null ? formatCost(s.cost, country) : "—"}
                      </span>
                    </li>
                  ))}
                </ul>
              </DetailSection>
            )}
          </DetailPanel>
        )}
      </div>
    </div>
  );
}

// Conditions view: the environmental context that feeds a check, and the observed
// field issues that gate it. Weather stays DEMO-FARMS-ONLY — the weather service
// is a mock, and a real pilot farm must never render simulated numbers.
function ConditionsTab({ farmId, isDemo, observations, overview }) {
  const issues = [...observations]
    .sort((a, b) => (a.observation_date < b.observation_date ? 1 : -1))
    .slice(0, 8);
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
      <div className="min-w-0 space-y-4 lg:col-span-2">
        {isDemo ? (
          <SectionCard
            title="Current conditions"
            icon={<CloudSun />}
            description="Simulated demo weather — not a live feed. Do not use as the sole basis for an application decision."
          >
            <WeatherCard farmId={farmId} />
          </SectionCard>
        ) : (
          <SectionCard title="Current conditions" icon={<CloudSun />}>
            <EmptyState
              icon={CloudSun}
              title="No weather feed for this farm"
              description="Lumos does not display weather for real operations: the built-in service is a mock, and no live feed is connected. Weather is shown on demo farms only."
            />
          </SectionCard>
        )}

        <SectionCard
          title="Observed field issues"
          icon={<Eye />}
          description="Scouting evidence available to the deterministic planned-spray checks."
        >
          <DataTable
            minWidth={520}
            rowKey={(o) => o.id}
            rows={issues}
            columns={[
              {
                key: "field",
                header: "Field",
                render: (o) => <span className="text-ink">{o.field_block || "—"}</span>,
              },
              {
                key: "issue",
                header: "Issue",
                render: (o) => (
                  <span className="font-medium text-ink">{o.visible_issue || "—"}</span>
                ),
              },
              {
                key: "severity",
                header: "Severity",
                render: (o) => <SeverityBadge value={o.severity_1_to_5} />,
              },
              {
                key: "observed",
                header: "Observed",
                render: (o) => (
                  <span className="tabular whitespace-nowrap text-sm text-muted">
                    {formatDate(o.observation_date)}
                  </span>
                ),
              },
              {
                key: "source",
                header: "Source",
                priority: "secondary",
                render: (o) => (
                  <span className="text-xs text-muted">
                    {(o.data_source || "—").replace(/_/g, " ")}
                  </span>
                ),
              },
            ]}
            empty={
              <EmptyState
                size="sm"
                icon={Eye}
                title="No scouting observations recorded"
                description="Scouting evidence gates the pre-spray checks — a check with no observation for its target escalates rather than approves."
              />
            }
          />
        </SectionCard>
      </div>

      <div className="space-y-4">
        <SectionCard title="Decision context" icon={<ClipboardCheck />}>
          <dl className="space-y-2 text-sm">
            <div className="flex items-center justify-between gap-2">
              <dt className="text-muted">Harvest</dt>
              <dd className="tabular text-right font-medium text-ink">
                {overview.expected_harvest_date
                  ? formatDate(overview.expected_harvest_date)
                  : "Not entered"}
              </dd>
            </div>
            <div className="flex items-center justify-between gap-2 border-t border-line pt-2">
              <dt className="text-muted">Current risk flags</dt>
              <dd className="tabular font-medium text-ink">{overview.flag_count}</dd>
            </div>
            <div className="flex items-center justify-between gap-2 border-t border-line pt-2">
              <dt className="text-muted">Open planned decisions</dt>
              <dd className="tabular font-medium text-ink">
                {overview.awaiting_outcome_count}
              </dd>
            </div>
          </dl>
        </SectionCard>

        <SectionCard title="How conditions enter a decision" icon={<ListChecks />}>
          <ol className="space-y-2.5">
            {[
              "Weather context and scouting records are inputs.",
              "Deterministic rules evaluate the planned spray.",
              "A PCA / agronomist confirms label restrictions.",
            ].map((step, i) => (
              <li key={step} className="flex gap-2.5 text-sm text-ink">
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-line text-[11px] font-semibold text-muted">
                  {i + 1}
                </span>
                {step}
              </li>
            ))}
          </ol>
        </SectionCard>
      </div>
    </div>
  );
}

// useSearchParams requires a Suspense boundary for the production build.
export default function FarmDetailPage({ params }) {
  return (
    <Suspense fallback={<LoadingState message="Loading farm record…" />}>
      <FarmDetail farmId={params.id} />
    </Suspense>
  );
}
