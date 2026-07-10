"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  ArrowLeft,
  CalendarClock,
  ClipboardCheck,
  Download,
  Droplets,
  Eye,
  FlaskConical,
  ListChecks,
  MapPin,
  Plus,
  TriangleAlert,
} from "lucide-react";
import { api, API_BASE_URL } from "@/lib/api";
import { formatArea, formatDate } from "@/lib/format";
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import ActivityTimeline from "@/components/ActivityTimeline";
import AnalyticsCard from "@/components/AnalyticsCard";
import ComplianceCard from "@/components/ComplianceCard";
import DecisionEvidenceCard from "@/components/DecisionEvidenceCard";
import PhotoScoutCard from "@/components/PhotoScoutCard";
import PilotEvidenceCard from "@/components/PilotEvidenceCard";
import PreSpraySheet, { PlannedSprayList } from "@/components/PreSpraySheet";
import RecommendationPanel from "@/components/RecommendationPanel";
import ReductionCard from "@/components/ReductionCard";
import ScoutObservationForm from "@/components/ScoutObservationForm";
import SprayEventForm from "@/components/SprayEventForm";
import SprayImportCard from "@/components/SprayImportCard";
import WeatherCard from "@/components/WeatherCard";
import WeeklyReport from "@/components/WeeklyReport";

const TABS = ["overview", "planned", "records", "evidence"];

// A record is "real pilot data" unless tagged demo/simulated; a farm whose
// records are all demo-tagged is a seeded demo farm (farms carry no provenance
// of their own, so this is derived from their records).
function isDemoRecord(r) {
  return r.data_source === "demo" || r.data_confidence === "simulated";
}

function Kpi({ icon: Icon, label, value, hint, tone = "neutral" }) {
  const toneCls =
    tone === "amber" ? "text-amber-700" : tone === "green" ? "text-green-700" : "text-gray-900";
  return (
    <Card>
      <CardContent className="p-3.5 pt-3.5">
        <div className="flex items-center gap-1.5 text-xs text-gray-500">
          <Icon className="h-3.5 w-3.5" />
          {label}
        </div>
        <div className={`mt-1 truncate text-lg font-semibold ${toneCls}`}>{value}</div>
        {hint && <div className="text-[11px] text-gray-400">{hint}</div>}
      </CardContent>
    </Card>
  );
}

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

// Derive the single operational status chip for the farm header. Open pre-spray
// decisions outrank record-level flags: the decision queue is the product.
function deriveStatus(compliance, openPlanned) {
  const openCritical = openPlanned.filter((p) => p.decision_severity === "critical");
  const needsReview = openPlanned.filter(
    (p) => p.review_required && !["approved", "edited", "rejected"].includes(p.review_status)
  );
  if (openCritical.length) return { label: "Blocked decision open", variant: "red" };
  if (needsReview.length) return { label: "Needs PCA review", variant: "amber" };
  if (openPlanned.length) return { label: "Awaiting outcome", variant: "amber" };
  const anyFlag =
    compliance &&
    (compliance.phi_risk ||
      compliance.rei_risk ||
      compliance.repeated_active_ingredient_risk ||
      compliance.high_severity_scouting);
  if (anyFlag) return { label: "Risk flags", variant: "amber" };
  return { label: "No open decisions", variant: "neutral" };
}

function FarmDetail({ farmId }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const [farm, setFarm] = useState(null);
  const [sprays, setSprays] = useState([]);
  const [observations, setObservations] = useState([]);
  const [recommendations, setRecommendations] = useState([]);
  const [planned, setPlanned] = useState([]);
  const [compliance, setCompliance] = useState(null);
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
      const [f, s, o, r, p, c] = await Promise.all([
        api.getFarm(farmId),
        api.listSprayEvents(farmId),
        api.listScoutObservations(farmId),
        api.listRecommendations(farmId),
        api.listPlannedSprays(farmId),
        api.getCompliance(farmId),
      ]);
      setFarm(f);
      setSprays(s);
      setObservations(o);
      setRecommendations(r);
      setPlanned(p);
      setCompliance(c);
    } catch (err) {
      setError(err.message);
    }
  }, [farmId]);

  useEffect(() => {
    load();
  }, [load]);

  const latest = recommendations[0] || null;

  const derived = useMemo(() => {
    const records = [...sprays, ...observations];
    const isDemoFarm = records.length > 0 && records.every(isDemoRecord);
    const openPlanned = planned.filter((p) => p.outcome === "planned");
    const awaiting = openPlanned.length;
    const needsReview = openPlanned.filter(
      (p) => p.review_required && !["approved", "edited", "rejected"].includes(p.review_status)
    ).length;
    const hasDocumentedSkip = planned.some(
      (p) => p.outcome === "avoided" && !isDemoRecord(p)
    );
    // Must count the SAME four signals as the dashboard card (/farms-overview
    // flag_count) so the two views never disagree in a demo.
    const riskFlags = compliance
      ? [
          compliance.phi_risk,
          compliance.rei_risk,
          compliance.repeated_active_ingredient_risk,
          compliance.high_severity_scouting,
        ].filter(Boolean).length
      : 0;
    const harvestDays = farm?.expected_harvest_date
      ? Math.round(
          (new Date(farm.expected_harvest_date) - new Date(new Date().toDateString())) / 86400000
        )
      : null;
    const provenanceSources = [...new Set(records.map((r) => r.data_source).filter(Boolean))];
    const provenanceConfidence = [
      ...new Set(records.map((r) => r.data_confidence).filter(Boolean)),
    ];
    return {
      isDemoFarm,
      openPlanned,
      awaiting,
      needsReview,
      hasDocumentedSkip,
      riskFlags,
      harvestDays,
      provenanceSources,
      provenanceConfidence,
    };
  }, [sprays, observations, planned, compliance, farm]);

  if (error)
    return (
      <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
        {error} — is the backend running on <code>http://localhost:8000</code>?
      </div>
    );
  if (!farm) return <p className="text-sm text-gray-500">Loading…</p>;

  const status = deriveStatus(compliance, derived.openPlanned);
  // The decision queue: open checks first (review needed, then awaiting outcome),
  // then the most recent resolved ones.
  const queue = [
    ...derived.openPlanned,
    ...planned.filter((p) => p.outcome !== "planned"),
  ].slice(0, 3);

  return (
    <div className="space-y-5">
      {/* Farm header */}
      <div>
        <Link
          href="/"
          className="inline-flex items-center gap-1 text-xs text-gray-500 hover:text-gray-900"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Farms
        </Link>
        <div className="mt-1.5 flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-lg font-semibold text-gray-900">{farm.name}</h1>
              {derived.isDemoFarm && (
                <Badge variant="outline">
                  <FlaskConical />
                  Simulated demo data
                </Badge>
              )}
              <Badge variant={status.variant}>{status.label}</Badge>
            </div>
            <p className="mt-0.5 flex items-center gap-1 text-xs text-gray-500">
              <MapPin className="h-3.5 w-3.5" />
              {farm.location || "—"} · {farm.crop_type?.replace(/_/g, " ")}
              {farm.greenhouse_area != null &&
                ` · ${formatArea(farm.greenhouse_area, farm.country)}`}
            </p>
          </div>
          <PreSpraySheet farmId={farmId} onChanged={load} />
        </div>
      </div>

      {/* KPI row */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi
          icon={CalendarClock}
          label="Upcoming harvest"
          value={formatDate(farm.expected_harvest_date)}
          hint={
            derived.harvestDays == null
              ? null
              : derived.harvestDays >= 0
              ? `in ${derived.harvestDays} day${derived.harvestDays === 1 ? "" : "s"}`
              : `${-derived.harvestDays} days ago`
          }
        />
        <Kpi
          icon={ClipboardCheck}
          label="Decisions needing PCA review"
          value={derived.needsReview}
          tone={derived.needsReview > 0 ? "amber" : "neutral"}
        />
        <Kpi
          icon={ListChecks}
          label="Checked sprays awaiting outcome"
          value={derived.awaiting}
          tone={derived.awaiting > 0 ? "amber" : "neutral"}
        />
        <Kpi
          icon={TriangleAlert}
          label="Risk flags"
          value={derived.riskFlags}
          tone={derived.riskFlags > 0 ? "amber" : "neutral"}
          hint="PHI · REI · rotation · scouting"
        />
      </div>

      {/* Tabs */}
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="planned">
            Planned sprays
            {derived.awaiting > 0 && (
              <span className="rounded-full bg-amber-100 px-1.5 text-[11px] font-semibold text-amber-800">
                {derived.awaiting}
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
                      className="text-xs font-medium text-gray-500 hover:text-gray-900"
                    >
                      View all ({planned.length})
                    </button>
                  )
                }
              >
                <PlannedSprayList
                  planned={queue}
                  onChanged={load}
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
              <SectionCard
                title="Pre-spray risk snapshot"
                icon={<ClipboardCheck />}
                description="From user-entered PHI/REI values — not label-verified."
              >
                <ComplianceCard data={compliance} />
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
                  {derived.isDemoFarm && (
                    <p className="rounded bg-gray-50 px-2 py-1 text-[11px] text-gray-500">
                      Seeded demo farm — all records are simulated.
                    </p>
                  )}
                </div>
              </SectionCard>

              <SectionCard title="Weather (demo)" icon={<Eye />}>
                <WeatherCard farmId={farmId} />
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
            <PlannedSprayList planned={planned} onChanged={load} />
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
          <div className="space-y-4">
            {derived.isDemoFarm && (
              <div className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
                <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" />
                <div>
                  <div className="font-semibold">SIMULATED DEMO DATA — NOT A CUSTOMER RESULT</div>
                  <p className="text-xs">
                    Every record on this farm is seeded for demonstration. Numbers below are
                    illustrative of the workflow, not evidence from a real operation.
                  </p>
                </div>
              </div>
            )}

            <SectionCard
              title="Decision evidence"
              icon={<ListChecks />}
              description="What the pre-spray decision workflow documented — counts and entered estimates, demo data excluded."
            >
              <DecisionEvidenceCard
                farmId={farmId}
                country={farm.country}
                refreshKey={`${planned.length}-${planned.filter((p) => p.outcome !== "planned").length}`}
              />
            </SectionCard>

            <SectionCard
              title="Measured spray reduction"
              icon={<ListChecks />}
              description="Sprays vs. a grower/PCA-declared baseline. No baseline, no number."
            >
              <ReductionCard farmId={farmId} refreshKey={sprays.length} />
            </SectionCard>

            <SectionCard title="Pilot evidence" icon={<ClipboardCheck />}>
              <PilotEvidenceCard
                farmId={farmId}
                country={farm.country}
                hasDocumentedSkip={derived.hasDocumentedSkip}
                refreshKey={`${sprays.length}-${observations.length}-${recommendations.length}-${latest?.agronomist_status || ""}`}
              />
            </SectionCard>

            <SectionCard title="Cost analytics" icon={<Download />}>
              <AnalyticsCard
                farmId={farmId}
                country={farm.country}
                hasDocumentedSkip={derived.hasDocumentedSkip}
                refreshKey={sprays.length}
              />
            </SectionCard>

            <SectionCard
              title="Weekly risk review"
              icon={<ClipboardCheck />}
              description="Farm-wide review of current records; only PCA-approved or edited guidance reaches the weekly report below."
            >
              <RecommendationPanel farmId={farmId} latest={latest} onChanged={load} />
            </SectionCard>

            <SectionCard
              title="Weekly report"
              icon={<ClipboardCheck />}
              description="Copy-pasteable summary for the grower (WhatsApp / text)."
            >
              <WeeklyReport farmId={farmId} />
            </SectionCard>

            <SectionCard title="Exports" icon={<Download />}>
              <div className="flex flex-wrap gap-2">
                <a
                  href={`${API_BASE_URL}/farms/${farmId}/export/spray-events.csv`}
                  className="inline-flex h-8 items-center gap-1.5 rounded-md border border-gray-300 bg-white px-3 text-xs font-medium text-gray-700 shadow-sm hover:bg-gray-50"
                >
                  <Download className="h-3.5 w-3.5" />
                  Spray events CSV
                </a>
                <a
                  href={`${API_BASE_URL}/farms/${farmId}/export/recommendations.csv`}
                  className="inline-flex h-8 items-center gap-1.5 rounded-md border border-gray-300 bg-white px-3 text-xs font-medium text-gray-700 shadow-sm hover:bg-gray-50"
                >
                  <Download className="h-3.5 w-3.5" />
                  Recommendations CSV
                </a>
                <a
                  href={`${API_BASE_URL}/farms/${farmId}/audit-packet`}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex h-8 items-center gap-1.5 rounded-md border border-gray-300 bg-white px-3 text-xs font-medium text-gray-700 shadow-sm hover:bg-gray-50"
                >
                  <Download className="h-3.5 w-3.5" />
                  Audit packet (JSON)
                </a>
              </div>
            </SectionCard>
          </div>
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
