"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  CalendarClock,
  ClipboardCheck,
  CloudSun,
  Droplets,
  Eye,
  FlaskConical,
  ListChecks,
  MapPin,
  Plus,
  ShoppingCart,
  Sprout,
  TriangleAlert,
  Users,
  Wrench,
} from "lucide-react";
import { api } from "@/lib/api";
import { formatArea, formatDate } from "@/lib/format";
import { URGENCY_META } from "@/lib/labels";
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import ActivityTimeline from "@/components/ActivityTimeline";
import Breadcrumbs from "@/components/Breadcrumbs";
import ComplianceCard from "@/components/ComplianceCard";
import EvidencePanel from "@/components/EvidencePanel";
import InputPlanForm from "@/components/InputPlanForm";
import MetricCard from "@/components/MetricCard";
import NextActionBanner from "@/components/NextActionBanner";
import PhotoScoutCard from "@/components/PhotoScoutCard";
import PilotImportCard from "@/components/PilotImportCard";
import PreSpraySheet, { PlannedSprayList } from "@/components/PreSpraySheet";
import ScoutObservationForm from "@/components/ScoutObservationForm";
import SectionCard from "@/components/SectionCard";
import SprayEventForm from "@/components/SprayEventForm";
import SprayImportCard from "@/components/SprayImportCard";
import WeatherCard from "@/components/WeatherCard";

const TABS = ["overview", "planned", "records", "evidence"];

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
      const [f, ov, s, o, r, p, c, plans, orders] = await Promise.all([
        api.getFarm(farmId),
        api.getFarmOverview(farmId),
        api.listSprayEvents(farmId),
        api.listScoutObservations(farmId),
        api.listRecommendations(farmId),
        api.listPlannedSprays(farmId),
        api.getCompliance(farmId),
        api.listInputPlans(farmId),
        api.listOrders(farmId),
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
    } catch (err) {
      setError(err.message);
    }
  }, [farmId]);

  useEffect(() => {
    load();
  }, [load]);

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
    return {
      openPlanned,
      hasDocumentedSkip,
      provenanceSources,
      provenanceConfidence,
      lastScoutedStage,
    };
  }, [sprays, observations, planned]);

  if (error)
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
        {error} — is the backend running on <code>http://localhost:8000</code>?
      </div>
    );
  if (!farm || !overview) return <p className="text-sm text-gray-500">Loading…</p>;

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
      {/* Farm header */}
      <div>
        <Breadcrumbs
          items={[{ label: "Farms & fields", href: "/farms" }, { label: farm.name }]}
        />
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-lg font-semibold text-gray-900">{farm.name}</h1>
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
            </div>
            {/* Meta strip — real farm fields only */}
            <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-gray-500">
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
            </div>
          </div>
          <PreSpraySheet farmId={farmId} onChanged={load} />
        </div>
      </div>

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
          <TabsTrigger value="planned">
            Planned sprays
            {overview.awaiting_outcome_count > 0 && (
              <span className="rounded-full bg-amber-100 px-1.5 text-[11px] font-semibold text-amber-800">
                {overview.awaiting_outcome_count}
              </span>
            )}
          </TabsTrigger>
          <TabsTrigger value="records">Records</TabsTrigger>
          <TabsTrigger value="evidence">Evidence</TabsTrigger>
        </TabsList>

        {/* ------------------------------------------------------------ Overview */}
        <TabsContent value="overview">
          <div className="grid gap-4 lg:grid-cols-3">
            <div className="min-w-0 space-y-4 lg:col-span-2">
              <SectionCard
                title="Decision queue"
                icon={<ListChecks />}
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

              <SectionCard
                title="Inputs & orders"
                icon={<ShoppingCart />}
                description="Input plans, supplier quotes, and orders for this farm."
                action={<InputPlanForm farmId={farmId} onCreated={load} />}
              >
                {inputPlans.length === 0 && purchaseOrders.length === 0 ? (
                  <p className="text-sm text-gray-500">
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
                        <dt className="text-gray-500">{label}</dt>
                        <dd className="font-medium text-gray-900">{value}</dd>
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
                      <dt className="text-gray-500">{label}</dt>
                      <dd className="text-right font-medium capitalize text-gray-800">
                        {value}
                      </dd>
                    </div>
                  ))}
                </dl>
              </SectionCard>

              <SectionCard title="Data provenance" icon={<FlaskConical />}>
                <div className="space-y-1.5 text-xs text-gray-600">
                  <div className="flex items-center justify-between gap-2">
                    <span>Sources</span>
                    <span className="text-right font-medium text-gray-800">
                      {derived.provenanceSources.length
                        ? derived.provenanceSources.map((s) => s.replace(/_/g, " ")).join(", ")
                        : "—"}
                    </span>
                  </div>
                  <div className="flex items-center justify-between gap-2">
                    <span>Confidence</span>
                    <span className="text-right font-medium text-gray-800">
                      {derived.provenanceConfidence.length
                        ? derived.provenanceConfidence.map((c) => c.replace(/_/g, " ")).join(", ")
                        : "—"}
                    </span>
                  </div>
                  {isDemoFarm && (
                    <p className="rounded bg-gray-50 px-2 py-1 text-[11px] text-gray-500">
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

// useSearchParams requires a Suspense boundary for the production build.
export default function FarmDetailPage({ params }) {
  return (
    <Suspense fallback={<p className="text-sm text-gray-500">Loading…</p>}>
      <FarmDetail farmId={params.id} />
    </Suspense>
  );
}
