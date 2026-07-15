"use client";

import { ClipboardCheck, Download, ListChecks, TriangleAlert } from "lucide-react";
import { API_BASE_URL } from "@/lib/api";
import SectionCard from "@/components/SectionCard";
import AnalyticsCard from "@/components/AnalyticsCard";
import DecisionEvidenceCard from "@/components/DecisionEvidenceCard";
import PilotEvidenceCard from "@/components/PilotEvidenceCard";
import RecommendationPanel from "@/components/RecommendationPanel";
import ReductionCard from "@/components/ReductionCard";
import WeeklyReport from "@/components/WeeklyReport";

// The farm's full evidence surface — extracted from the farm page's Evidence
// tab so the /evidence page can reuse it without duplicating anything. All
// numbers/caveats come from the composed cards (demo data excluded there).
export default function EvidencePanel({
  farmId,
  farm,
  isDemoFarm,
  hasDocumentedSkip,
  latest,
  planned = [],
  sprays = [],
  observations = [],
  recommendations = [],
  onChanged,
}) {
  return (
    <div className="space-y-4">
      {isDemoFarm && (
        <div className="flex items-start gap-2 rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
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
          area={farm.greenhouse_area}
          refreshKey={`${planned.length}-${planned.filter((p) => !p.is_open).length}`}
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
          hasDocumentedSkip={hasDocumentedSkip}
          refreshKey={`${sprays.length}-${observations.length}-${recommendations.length}-${latest?.agronomist_status || ""}`}
        />
      </SectionCard>

      <SectionCard title="Cost analytics" icon={<Download />}>
        <AnalyticsCard
          farmId={farmId}
          country={farm.country}
          hasDocumentedSkip={hasDocumentedSkip}
          refreshKey={sprays.length}
        />
      </SectionCard>

      <SectionCard
        title="Weekly risk review"
        icon={<ClipboardCheck />}
        description="Farm-wide review of current records; only PCA-approved or edited guidance reaches the weekly report below."
      >
        <RecommendationPanel farmId={farmId} latest={latest} onChanged={onChanged} />
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
            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 text-xs font-medium text-gray-700 shadow-sm hover:bg-gray-50"
          >
            <Download className="h-3.5 w-3.5" />
            Spray events CSV
          </a>
          <a
            href={`${API_BASE_URL}/farms/${farmId}/export/recommendations.csv`}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 text-xs font-medium text-gray-700 shadow-sm hover:bg-gray-50"
          >
            <Download className="h-3.5 w-3.5" />
            Recommendations CSV
          </a>
          <a
            href={`${API_BASE_URL}/farms/${farmId}/audit-packet`}
            target="_blank"
            rel="noreferrer"
            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 text-xs font-medium text-gray-700 shadow-sm hover:bg-gray-50"
          >
            <Download className="h-3.5 w-3.5" />
            Audit packet (JSON)
          </a>
        </div>
      </SectionCard>
    </div>
  );
}
