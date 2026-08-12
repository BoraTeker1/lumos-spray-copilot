"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { formatCost } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Field, FormError } from "@/components/ui/field";
import { fieldClass } from "@/components/ui/input";

const DATA_SOURCES = [
  "grower_interview",
  "spreadsheet",
  "whatsapp",
  "email",
  "manual_entry",
  "demo",
  "unknown",
];
const DATA_CONFIDENCES = ["user_provided", "pca_reviewed", "incomplete", "simulated"];

const EXAMPLE = `{
  "spray_events": [
    {"product_name": "Captan 80 WDG", "active_ingredient": "captan",
     "application_date": "2026-06-20", "cost": 120,
     "pre_harvest_interval_days": 4, "re_entry_interval_hours": 24}
  ],
  "scouting_observations": [
    {"observation_date": "2026-06-20", "visible_issue": "gray mold on fruit",
     "severity_1_to_5": 4}
  ]
}`;

// One-page case study, rendered founder/demo friendly.
function CaseStudy({ cs, country }) {
  const Line = ({ label, value }) => (
    <div className="flex justify-between gap-3 border-b py-1 last:border-0">
      <span className="text-muted">{label}</span>
      <span className="text-right font-medium">{value}</span>
    </div>
  );
  return (
    <div className="mt-4 rounded-control border bg-canvas p-4">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="font-semibold">Pilot case study — {cs.farm_name}</h3>
        <span className="text-xs text-muted">
          {cs.crop} · {cs.location || "—"}
        </span>
      </div>
      <div className="text-xs text-muted">
        Data source: {cs.pilot_data_source.join(", ")} · Confidence:{" "}
        {cs.data_confidence_levels.join(", ")}
      </div>
      {cs.pilot_import_batches_count > 0 && (
        <div className="text-xs text-muted">
          {cs.pilot_import_batches_count} import batch(es) · latest:{" "}
          {cs.latest_import_source_label || "—"}
          {cs.latest_imported_by && ` (by ${cs.latest_imported_by})`}
        </div>
      )}

      <div className="mt-3 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
        <Line label="Spray events analyzed" value={cs.spray_events_analyzed} />
        <Line label="Scouting observations" value={cs.scouting_observations_analyzed} />
        <Line label="Scouting-backed sprays" value={cs.scouting_backed_sprays} />
        <Line label="Sprays w/o recent scouting" value={cs.sprays_without_recent_scouting} />
        <Line label="PHI / REI flags" value={cs.phi_rei_flags} />
        <Line label="Resistance flags" value={cs.resistance_flags} />
        <Line label="Weather risk flags" value={cs.weather_risk_flags} />
        <Line
          label="Potential avoidable cost"
          value={
            cs.estimated_avoidable_cost_usd != null
              ? formatCost(cs.estimated_avoidable_cost_usd, country)
              : "—"
          }
        />
      </div>
      <div className="mt-2 text-sm">
        <span className="text-muted">PCA review: </span>
        {cs.pca_review_status_summary}
      </div>

      <div className="mt-3 grid gap-4 sm:grid-cols-2">
        <div>
          <div className="text-xs font-semibold text-ink">What Lumos helped surface</div>
          <ul className="mt-1 space-y-1 text-sm text-ink">
            {cs.what_lumos_helped_surface.map((b, i) => (
              <li key={i}>• {b}</li>
            ))}
          </ul>
        </div>
        <div>
          <div className="text-xs font-semibold text-ink">What is still unknown</div>
          <ul className="mt-1 space-y-1 text-sm text-ink">
            {cs.what_is_still_unknown.map((b, i) => (
              <li key={i}>• {b}</li>
            ))}
          </ul>
        </div>
      </div>

      <p className="mt-3 italic text-muted">{cs.quote_placeholder}</p>
      <p className="mt-2 rounded bg-warn-bg px-3 py-2 text-xs text-warn-fg">{cs.disclaimer}</p>
    </div>
  );
}

// Concierge Pilot: manual import of pilot data + a one-page case study.
export default function ConciergePilotCard({ farmId, country, onImported }) {
  const [sourceLabel, setSourceLabel] = useState("");
  const [dataSource, setDataSource] = useState("grower_interview");
  const [dataConfidence, setDataConfidence] = useState("user_provided");
  const [importedBy, setImportedBy] = useState("");
  const [notes, setNotes] = useState("");
  const [json, setJson] = useState("");
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);
  const [caseStudy, setCaseStudy] = useState(null);

  async function submit(e) {
    e.preventDefault();
    setError(null);
    setStatus(null);
    let records = {};
    if (json.trim()) {
      try {
        records = JSON.parse(json);
      } catch {
        setError("Records box is not valid JSON. Use the example structure.");
        return;
      }
    }
    try {
      const res = await api.importPilotData(farmId, {
        source_label: sourceLabel || "Manual concierge import",
        data_source: dataSource,
        data_confidence: dataConfidence,
        imported_by: importedBy || null,
        notes: notes || null,
        spray_events: records.spray_events || [],
        scouting_observations: records.scouting_observations || [],
      });
      setStatus(
        `Imported ${res.imported_spray_events} spray(s) and ${res.imported_scouting_observations} scouting note(s).`
      );
      setJson("");
      onImported?.();
    } catch (err) {
      setError(err.message);
    }
  }

  async function viewCaseStudy() {
    setError(null);
    try {
      setCaseStudy(await api.getPilotCaseStudy(farmId));
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <div>
      <p className="mb-3 text-xs text-muted">
        Use this for manually collected pilot data from grower/PCA conversations. This is not an
        automated recommendation or compliance guarantee.
      </p>

      <form onSubmit={submit} className="space-y-3">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="Source label">
            <input
              value={sourceLabel}
              onChange={(e) => setSourceLabel(e.target.value)}
              placeholder="Call with PCA Maria, 20 Jun"
              className={fieldClass}
            />
          </Field>
          <Field label="Imported by (optional)">
            <input
              value={importedBy}
              onChange={(e) => setImportedBy(e.target.value)}
              placeholder="you@founder"
              className={fieldClass}
            />
          </Field>
          <Field label="Data source">
            <select
              value={dataSource}
              onChange={(e) => setDataSource(e.target.value)}
              className={fieldClass}
            >
              {DATA_SOURCES.map((s) => (
                <option key={s} value={s}>
                  {s.replace(/_/g, " ")}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Data confidence">
            <select
              value={dataConfidence}
              onChange={(e) => setDataConfidence(e.target.value)}
              className={fieldClass}
            >
              {DATA_CONFIDENCES.map((c) => (
                <option key={c} value={c}>
                  {c.replace(/_/g, " ")}
                </option>
              ))}
            </select>
          </Field>
        </div>

        <Field label="Notes (optional)">
          <input
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Costs are rough; transcribed from a call."
            className={fieldClass}
          />
        </Field>

        <Field label="Records (JSON: spray_events + scouting_observations)">
          <textarea
            value={json}
            onChange={(e) => setJson(e.target.value)}
            placeholder={EXAMPLE}
            rows={9}
            className={`${fieldClass} h-auto p-2 font-mono text-xs`}
          />
        </Field>

        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit">Import pilot data</Button>
          <Button type="button" variant="outline" onClick={viewCaseStudy}>
            View pilot case study
          </Button>
        </div>
      </form>

      {/* A successful import is announced too: this form's only confirmation is
          this line, and it sits below a long textarea that is likely offscreen. */}
      {status && (
        <p role="status" className="mt-2 text-sm text-ok-fg">
          {status}
        </p>
      )}
      <FormError className="mt-2">{error}</FormError>

      {caseStudy && <CaseStudy cs={caseStudy} country={country} />}
    </div>
  );
}
