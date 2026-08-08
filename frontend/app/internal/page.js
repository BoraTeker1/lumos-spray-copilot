"use client";

import { LoadingState } from "@/components/SystemState";
import Callout from "@/components/Callout";
import PageHeader from "@/components/PageHeader";
import SectionCard from "@/components/SectionCard";
import { Badge } from "@/components/ui/badge";
import { Wrench } from "lucide-react";
import { useEffect, useState } from "react";
import ConciergePilotCard from "@/components/ConciergePilotCard";
import ConciergeQuoteCard from "@/components/ConciergeQuoteCard";
import DomainRegistryTable from "@/components/DomainRegistryTable";
import IngestionCard from "@/components/IngestionCard";
import TranscriptionStatusCard from "@/components/TranscriptionStatusCard";
import OpportunityScanCard from "@/components/OpportunityScanCard";
import LabelLibraryCard from "@/components/LabelLibraryCard";
import PilotOperatorCard from "@/components/PilotOperatorCard";
import { api } from "@/lib/api";

// INTERNAL tooling — deliberately not linked from the app navigation.
// Concierge import: a team member manually transcribes pilot data collected from
// calls / WhatsApp / spreadsheets / email into an existing farm, with provenance tags.
// The customer-facing workflow is the pre-spray decision check on the farm page.
function InstrumentationSummary() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.getInstrumentation().then(setData).catch((err) => setError(err.message));
  }, []);

  if (error) return <Callout tone="risk">{error}</Callout>;
  if (!data) return <LoadingState message="Loading telemetry…" />;

  const rows = [
    ["Checks started (client-reported)", data.checks_started],
    ["Checks completed", data.checks_completed],
    ["Checks abandoned", data.checks_abandoned],
    ["Abandonment rate", data.abandonment_rate_pct != null ? `${data.abandonment_rate_pct}%` : "—"],
    [
      "Median time to PCA review",
      data.median_seconds_to_pca_review != null
        ? `${Math.round(data.median_seconds_to_pca_review / 60)} min`
        : "—",
    ],
    ["Outcomes recorded", data.outcomes_recorded],
    ["Decisions changed (not sprayed as planned)", data.decisions_changed],
    [
      "Entry sources",
      Object.entries(data.entry_source_breakdown || {})
        .map(([k, n]) => `${k.replace(/_/g, " ")}: ${n}`)
        .join(" · ") || "—",
    ],
  ];

  return (
    <div>
      <dl className="divide-y divide-line text-sm">
        {rows.map(([label, value]) => (
          <div key={label} className="flex justify-between gap-3 py-1.5">
            <dt className="text-muted">{label}</dt>
            <dd className="text-right font-medium text-ink">{value}</dd>
          </div>
        ))}
      </dl>
      <ul className="mt-2 space-y-0.5 text-[11px] text-muted">
        {(data.notes || []).map((n, i) => (
          <li key={i}>• {n}</li>
        ))}
      </ul>
    </div>
  );
}

function AiCalibrationSummary() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.getAiCalibration().then(setData).catch((err) => setError(err.message));
  }, []);

  if (error) return <Callout tone="risk">{error}</Callout>;
  if (!data) return <LoadingState message="Loading AI calibration…" />;

  const rows = [
    ["Risk notes logged", data.risk_notes_total],
    ["Risk notes abstained", data.risk_notes_abstained],
    [
      "Abstention rate",
      data.abstention_rate_pct != null ? `${data.abstention_rate_pct}%` : "—",
    ],
    ["Extraction judgments", data.extraction_judgments],
    ["Extraction abstained", data.extraction_abstained],
    ["Mock vs real-model judgments", `${data.mock_judgments} mock · ${data.real_model_judgments} real`],
  ];

  return (
    <div>
      <dl className="divide-y divide-line text-sm">
        {rows.map(([label, value]) => (
          <div key={label} className="flex justify-between gap-3 py-1.5">
            <dt className="text-muted">{label}</dt>
            <dd className="text-right font-medium text-ink">{value}</dd>
          </div>
        ))}
      </dl>
      <table className="mt-3 w-full text-left text-xs">
        <thead>
          <tr className="text-muted">
            <th className="py-1 pr-3 font-medium">Predicted risk</th>
            <th className="py-1 pr-3 font-medium">Predictions</th>
            <th className="py-1 pr-3 font-medium">With follow-up</th>
            <th className="py-1 pr-3 font-medium">Realized rescues</th>
            <th className="py-1 font-medium">Realized rate</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(data.predictions_by_level || {}).map(([level, block]) => (
            <tr key={level} className="border-t border-line">
              <td className="py-1 pr-3 font-medium uppercase">{level}</td>
              <td className="py-1 pr-3">{block.predictions}</td>
              <td className="py-1 pr-3">{block.with_follow_up}</td>
              <td className="py-1 pr-3">{block.realized_rescues}</td>
              <td className="py-1">
                {block.realized_rescue_rate_pct != null
                  ? `${block.realized_rescue_rate_pct}%`
                  : `— (${block.note})`}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <ul className="mt-2 space-y-0.5 text-[11px] text-muted">
        {(data.notes || []).map((n, i) => (
          <li key={i}>• {n}</li>
        ))}
      </ul>
    </div>
  );
}

export default function InternalToolsPage() {
  const [farms, setFarms] = useState([]);
  const [farmId, setFarmId] = useState("");
  const [error, setError] = useState(null);

  useEffect(() => {
    api
      .listFarms()
      .then((list) => {
        setFarms(list);
        if (list.length > 0) setFarmId(String(list[0].id));
      })
      .catch((err) => setError(err.message));
  }, []);

  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumbs={[{ label: "Internal tools" }]}
        title="Internal tools"
        meta={
          <span>
            Operator-only concierge tooling. Not part of the customer-facing
            workflow and not linked from the navigation.
          </span>
        }
        actions={
          <Badge variant="amber">
            <Wrench />
            Operator only
          </Badge>
        }
      />

      {error && (
        <Callout tone="risk">
          {error} — is the backend running on <code>http://localhost:8000</code>?
        </Callout>
      )}

      <SectionCard
        title="Pilot instrumentation"
        size="section"
        description={
          <>
            Workflow telemetry for running a real pilot: the check funnel, review latency, changed decisions, and how data gets entered. Never customer-facing.
          </>
        }
      >
        <InstrumentationSummary />
      </SectionCard>

      <SectionCard
        title="AI calibration"
        size="section"
        description={
          <>
            Every AI output (extraction, risk note, evidence action) is logged append-only; this compares predicted rescue risk against realized rescues from follow-up records. Rates are published only past the minimum-n gate — counts until then.
          </>
        }
      >
        <AiCalibrationSummary />
      </SectionCard>

      <SectionCard
        title="Concierge import"
        size="section"
        description={
          <>
            Manually transcribe pilot data (calls, WhatsApp, spreadsheets, email) into an existing farm, with provenance tags on every row.
          </>
        }
      >
        {farms.length === 0 ? (
          <p className="text-sm text-muted">No farms yet — create one first.</p>
        ) : (
          <>
            <label className="mb-4 block text-xs font-medium text-muted">
              Target farm
              <select
                className="mt-1 w-full max-w-sm rounded border px-2 py-1.5 text-sm"
                value={farmId}
                onChange={(e) => setFarmId(e.target.value)}
              >
                {farms.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.name}
                  </option>
                ))}
              </select>
            </label>
            {farmId && (
              <ConciergePilotCard
                key={farmId}
                farmId={farmId}
                country={farms.find((f) => String(f.id) === farmId)?.country || "US"}
              />
            )}
          </>
        )}
      </SectionCard>

      <SectionCard
        title="Botrytis shadow pilot"
        size="section"
        description={
          <>
            Issue and authorize PCA credentials, review the protocol, and read shadow risk assessments. Assessments are operator-only by construction — they are absent from the PCA-facing decision payload, not merely hidden in their UI.
          </>
        }
      >
        <PilotOperatorCard farmId={farmId} />
      </SectionCard>

      <SectionCard
        title="Pesticide label library"
        size="section"
        description={
          <>
            Extract label directions with AI, correct every value against the document, and commit them as UNVERIFIED. A committed value is on file, not in force: only a licensed PCA verifying it for a specific farm lets a decision rely on it. Nothing here shortens that chain.
          </>
        }
      >
        <LabelLibraryCard farmId={farmId} />
      </SectionCard>

      <SectionCard
        title="Data ingestion"
        size="section"
        description={
          <>
            Enqueue and inspect ingestion runs. The counts matter more than the status: a run that fetched 24 rows and admitted 3 is not a healthy run, and each of the 21 dropped rows is explained individually rather than summarised away. Without a provider credential the adapter is inert by construction — it records <span className="font-mono"> skipped_no_credential</span> and makes no network call.
          </>
        }
      >
        <IngestionCard />
      </SectionCard>

      {/* The most actionable card on this page: every finance, market and agronomy
          model refuses for one reason, and it is a reading task, not a build task. */}
      <TranscriptionStatusCard />

      <SectionCard
        title="Data domains"
        size="section"
        description={
          <>
            Seventeen domains are declared. Eight were deferred until 2026-08-07, when an explicit instruction admitted them — each now names the EMPTY transcription source that governs it and the constraint admission did not lift. Declaring is still not building: an admitted domain&apos;s source ships empty, every model over it refuses, and the worklist above says which document would change that.
          </>
        }
      >
        <DomainRegistryTable />
      </SectionCard>

      <SectionCard
        title="Historical opportunity scan"
        size="section"
        description={
          <>
            Pilot ladder Stage 2. Replays a past season&rsquo;s scheduled spray dates and reports what the versioned rule read on each — or, while the threshold table is empty, exactly what stopped each date from being assessable. That reason histogram is a per-farm work list, and it is available before a single coefficient is transcribed. It is <strong>sizing, never evidence</strong>: every historical outcome followed the actual spray, so there is no untreated counterfactual and no date here can be called avoidable.
          </>
        }
      >
        <OpportunityScanCard />
      </SectionCard>

      <SectionCard
        title="Supplier quotes & financing (concierge)"
        size="section"
        description={
          <>
            Enter supplier quotes against open RFQs, indicative financing offers (never approvals), and append-only order lifecycle events. Phase 1 has no supplier portal — Lumos staff transcribe on suppliers&apos; behalf.
          </>
        }
      >
        {farms.length === 0 ? (
          <p className="text-sm text-muted">No farms yet — create one first.</p>
        ) : (
          farmId && (
            <ConciergeQuoteCard
              key={`quotes-${farmId}`}
              farmId={farmId}
              country={farms.find((f) => String(f.id) === farmId)?.country || "US"}
            />
          )
        )}
      </SectionCard>
    </div>
  );
}
