"use client";

import { useState } from "react";
import { FileDown, ShieldCheck, Sparkles, Upload } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";

// CSV pilot import for REAL records (planned spray recommendations + scouting).
// Two input modes, one pipeline:
//  - CSV: server-side dry-run (column mapping, per-row errors/warnings, duplicates).
//  - AI extract: a PDF/photo or pasted email/WhatsApp goes through Claude (mock
//    without an API key), producing DRAFT rows with verbatim source snippets that a
//    human reviews/corrects — then the SAME validation runs before anything commits.
// Imported values are stored as imported_unverified provenance either way: the
// decision check flags them and they can never produce an automatic approve.

const RECORD_TYPES = [
  { value: "planned_sprays", label: "Planned sprays (recommendations)" },
  { value: "scout_observations", label: "Scouting observations" },
  // Historical actual applications — the reduction baseline's denominator.
  // CSV-only: there is no AI-extraction model for spray history (yet).
  { value: "spray_events", label: "Spray history (actual applications)", csvOnly: true },
  // Botrytis pilot observation inputs. CSV-only: these are instrument and
  // standardized-count records, not prose a model should be reading.
  { value: "weather_observations", label: "Weather observations (pilot)", csvOnly: true },
  { value: "scouting_samples", label: "Scouting samples (pilot)", csvOnly: true },
];

// How slash dates in the file are read. "auto" refuses ambiguous m/d-vs-d/m rows
// instead of guessing — a wrong guess silently shifts PHI/REI math by months.
const DATE_FORMATS = [
  { value: "auto", label: "Dates: auto (ambiguous rows error)" },
  { value: "iso", label: "Dates: YYYY-MM-DD only" },
  { value: "mdy", label: "Dates: MM/DD/YYYY" },
  { value: "dmy", label: "Dates: DD/MM/YYYY" },
];

// Canonical fields per record type (mirrors backend csv_import.py) for the
// mapping-correction dropdowns and the AI-row editor.
const FIELD_OPTIONS = {
  planned_sprays: [
    "external_record_id", "field_block", "crop", "treated_acres", "intended_date",
    "product_name", "epa_reg_no", "active_ingredient", "moa_group",
    "target_pest_or_disease", "rate_amount", "rate_unit", "estimated_cost",
    "pre_harvest_interval_days", "re_entry_interval_hours", "expected_harvest_date",
    "recommendation_author", "notes",
  ],
  scout_observations: [
    "external_record_id", "field_block", "observation_date", "crop_stage",
    "visible_issue", "severity", "severity_scale", "count_value", "observer", "notes",
  ],
  spray_events: [
    "external_record_id", "field_block", "application_date", "product_name",
    "active_ingredient", "moa_group", "pesticide_class", "target_pest_or_disease",
    "rate_amount", "rate_unit", "treated_acres", "cost",
    "pre_harvest_interval_days", "re_entry_interval_hours", "notes",
  ],
  weather_observations: [
    "station_id", "station_name", "station_distance_km", "observed_at",
    "temperature_c", "relative_humidity_pct", "rainfall_mm",
    "leaf_wetness_minutes", "wetness_is_measured",
  ],
  scouting_samples: [
    "external_record_id", "block_name", "observed_at", "method", "target",
    "units_inspected", "units_affected", "severity_index", "severity_scale",
    "scout_name",
  ],
};

const AI_ROW_METADATA = ["source_snippet", "row_confidence"];

export default function PilotImportCard({ farmId, onImported }) {
  const [mode, setMode] = useState("csv"); // "csv" | "ai"
  const [recordType, setRecordType] = useState("planned_sprays");
  const [dateFormat, setDateFormat] = useState("auto");
  const [text, setText] = useState("");
  const [filename, setFilename] = useState(null);
  const [aiFile, setAiFile] = useState(null);
  const [mapping, setMapping] = useState(null); // header -> field overrides
  const [report, setReport] = useState(null);
  const [extraction, setExtraction] = useState(null);
  const [aiRows, setAiRows] = useState([]);
  const [aiJudgmentId, setAiJudgmentId] = useState(null);
  const [busy, setBusy] = useState(false);
  const [committed, setCommitted] = useState(null);
  const [error, setError] = useState(null);

  function reset(keepText = false) {
    setReport(null);
    setCommitted(null);
    setError(null);
    setMapping(null);
    setExtraction(null);
    setAiRows([]);
    setAiJudgmentId(null);
    setAiFile(null);
    if (!keepText) {
      setText("");
      setFilename(null);
    }
  }

  async function onCsvFile(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    reset();
    setText(await file.text());
    setFilename(file.name);
    e.target.value = "";
  }

  function onAiFile(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    setAiFile(file);
    setFilename(file.name);
    e.target.value = "";
  }

  // ------------------------------------------------------------- CSV pipeline
  async function runImport(dryRun, overrides) {
    setBusy(true);
    setError(null);
    setCommitted(null);
    try {
      const result = await api.importCsv(farmId, {
        record_type: recordType,
        csv_text: text,
        mapping: overrides ?? mapping,
        dry_run: dryRun,
        date_format: dateFormat,
        source_filename: filename,
      });
      setReport(result.report);
      if (!dryRun) {
        setCommitted(result);
        api.trackEvent({
          event_type: "import_used",
          farm_id: Number(farmId),
          entry_source: "csv_paste",
          meta: {
            record_type: recordType,
            rows_imported: result.created_record_ids?.length ?? 0,
            duplicates: result.report?.duplicate_count ?? 0,
          },
        });
        onImported && (await onImported());
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  function remap(header, field) {
    const next = { ...(mapping || report?.mapping || {}), [header]: field };
    setMapping(next);
    runImport(true, next); // re-validate with the corrected mapping
  }

  // -------------------------------------------------------------- AI pipeline
  async function runExtraction() {
    setBusy(true);
    setError(null);
    setCommitted(null);
    try {
      const result = await api.extractDocument(farmId, {
        recordType,
        text: text.trim() || null,
        file: aiFile,
      });
      setExtraction(result.extraction);
      setReport(result.report);
      setAiJudgmentId(result.judgment_id);
      setAiRows(
        (result.extraction.rows || []).map((row) => {
          const clean = {};
          for (const [k, v] of Object.entries(row)) {
            if (!AI_ROW_METADATA.includes(k) && v !== null && v !== "") clean[k] = v;
          }
          return clean;
        })
      );
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function commitAiRows() {
    setBusy(true);
    setError(null);
    try {
      const result = await api.importRows(farmId, {
        record_type: recordType,
        rows: aiRows,
        dry_run: false,
        source_label: `AI-extracted (${filename || "pasted text"})`,
        source_filename: filename,
        ai_judgment_id: aiJudgmentId,
      });
      setReport(result.report);
      setCommitted(result);
      onImported && (await onImported());
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  function editAiRow(index, field, value) {
    setAiRows((rows) =>
      rows.map((row, i) => {
        if (i !== index) return row;
        const next = { ...row };
        if (value === "") delete next[field];
        else next[field] = value;
        return next;
      })
    );
  }

  const importable = report?.importable_count ?? 0;
  const aiFieldColumns = FIELD_OPTIONS[recordType].filter((f) =>
    aiRows.some((row) => row[f] !== undefined)
  );

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <div className="inline-flex overflow-hidden rounded-md border border-gray-300 text-xs">
          <button
            type="button"
            className={`px-2.5 py-1.5 ${mode === "csv" ? "bg-gray-900 text-white" : "bg-white text-gray-600"}`}
            onClick={() => { setMode("csv"); reset(); }}
          >
            CSV / paste rows
          </button>
          <button
            type="button"
            className={`px-2.5 py-1.5 ${mode === "ai" ? "bg-gray-900 text-white" : "bg-white text-gray-600"}`}
            onClick={() => {
              setMode("ai");
              // Spray history is CSV-only — no AI-extraction model exists for it.
              if (recordType === "spray_events") setRecordType("planned_sprays");
              reset();
            }}
          >
            AI extract (PDF / text)
          </button>
        </div>
        <select
          className="rounded-md border border-gray-300 px-2 py-1.5 text-xs"
          value={recordType}
          onChange={(e) => {
            setRecordType(e.target.value);
            reset(true);
          }}
        >
          {RECORD_TYPES.filter((t) => mode === "csv" || !t.csvOnly).map((t) => (
            <option key={t.value} value={t.value}>{t.label}</option>
          ))}
        </select>
        {mode === "csv" && (
          <select
            className="rounded-md border border-gray-300 px-2 py-1.5 text-xs"
            value={dateFormat}
            onChange={(e) => setDateFormat(e.target.value)}
          >
            {DATE_FORMATS.map((f) => (
              <option key={f.value} value={f.value}>{f.label}</option>
            ))}
          </select>
        )}
        {mode === "csv" && (
          <a
            className="inline-flex items-center gap-1 text-xs font-medium text-gray-500 underline-offset-2 hover:text-gray-900 hover:underline"
            href={api.exportUrl(`/import/templates/${recordType}.csv`)}
          >
            <FileDown className="h-3.5 w-3.5" /> Download template
          </a>
        )}
      </div>

      <p className="text-xs text-gray-500">
        {mode === "csv" ? (
          <>
            Import real pilot records from a CSV. Everything is validated in a{" "}
            <span className="font-medium text-gray-700">dry run first</span> — fix the
            column mapping below if a header was not recognized, then confirm.
          </>
        ) : (
          <>
            Paste a PCA email/WhatsApp or upload a PDF/photo of a recommendation.{" "}
            <span className="font-medium text-gray-700">Real AI</span> drafts rows with
            verbatim source snippets — it extracts only what is written and never
            guesses PHI/REI/rates. You review and correct every row before import.
          </>
        )}{" "}
        Imported values are stored as{" "}
        <span className="font-medium">imported, unverified</span>: the pre-spray check
        flags them and they can never auto-approve.
      </p>

      <textarea
        className="w-full rounded-md border border-gray-300 px-2.5 py-1.5 font-mono text-xs"
        rows={5}
        placeholder={
          mode === "csv"
            ? "Paste CSV rows here (header row first), or upload a file below."
            : "Paste the recommendation text here (email / WhatsApp / notes), or upload a PDF/photo below."
        }
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          reset(true);
        }}
      />

      <div className="flex flex-wrap items-center gap-2">
        {mode === "csv" ? (
          <>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={busy || !text.trim()}
              onClick={() => runImport(true)}
            >
              <ShieldCheck />
              {busy ? "Validating…" : "Validate (dry run)"}
            </Button>
            {report && !committed && (
              <Button
                type="button"
                size="sm"
                disabled={busy || importable === 0}
                onClick={() => runImport(false)}
              >
                <Upload />
                {busy ? "Importing…" : `Import ${importable} valid row(s)`}
              </Button>
            )}
            <label className="cursor-pointer text-xs font-medium text-gray-500 underline-offset-2 hover:text-gray-900 hover:underline">
              …or upload a CSV file
              <input type="file" accept=".csv,text/csv,text/plain" className="hidden" onChange={onCsvFile} />
            </label>
          </>
        ) : (
          <>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={busy || (!text.trim() && !aiFile)}
              onClick={runExtraction}
            >
              <Sparkles />
              {busy ? "Extracting…" : "Extract with AI"}
            </Button>
            {extraction && !extraction.abstained && aiRows.length > 0 && !committed && (
              <Button type="button" size="sm" disabled={busy} onClick={commitAiRows}>
                <Upload />
                {busy ? "Importing…" : `Import ${aiRows.length} reviewed row(s)`}
              </Button>
            )}
            <label className="cursor-pointer text-xs font-medium text-gray-500 underline-offset-2 hover:text-gray-900 hover:underline">
              …or upload a PDF / photo
              <input
                type="file"
                accept="application/pdf,image/jpeg,image/png,image/webp,image/gif"
                className="hidden"
                onChange={onAiFile}
              />
            </label>
          </>
        )}
        {filename && <span className="text-[11px] text-gray-400">{filename}</span>}
      </div>

      {error && <p className="text-xs text-red-600">{error}</p>}

      {committed && (
        <p className="rounded bg-green-50 px-3 py-2 text-sm text-green-700">
          Imported {committed.created_record_ids?.length ?? 0} record(s) (batch #
          {committed.batch?.id}), tagged{" "}
          {mode === "ai" ? "AI-extracted / imported-unverified" : "spreadsheet / imported-unverified"}.
          {report?.duplicate_count > 0 &&
            ` ${report.duplicate_count} duplicate row(s) were skipped and are listed below.`}
        </p>
      )}

      {extraction && (
        <div className="space-y-2 rounded-md border border-blue-200 bg-blue-50/50 p-3">
          <p className="text-xs font-medium text-blue-900">
            AI extraction ({extraction.is_mock ? "mock — set ANTHROPIC_API_KEY for real extraction" : extraction.model}
            {" · "}confidence: {extraction.overall_confidence})
          </p>
          {extraction.abstained ? (
            <p className="text-xs text-amber-800">
              The AI abstained: {extraction.abstain_reason || "input not recognized as the requested record type."}
            </p>
          ) : (
            aiRows.length > 0 && (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-[11px]">
                  <thead>
                    <tr className="text-gray-500">
                      {aiFieldColumns.map((f) => (
                        <th key={f} className="py-1 pr-2 font-medium">{f.replace(/_/g, " ")}</th>
                      ))}
                      <th className="py-1 font-medium">source snippet</th>
                    </tr>
                  </thead>
                  <tbody>
                    {aiRows.map((row, i) => (
                      <tr key={i} className="border-t border-blue-100 align-top">
                        {aiFieldColumns.map((f) => (
                          <td key={f} className="py-1 pr-2">
                            <input
                              className="w-full min-w-20 rounded border border-gray-300 bg-white px-1 py-0.5 text-[11px]"
                              value={row[f] ?? ""}
                              onChange={(e) => editAiRow(i, f, e.target.value)}
                            />
                          </td>
                        ))}
                        <td className="py-1 text-gray-500">
                          {extraction.rows[i]?.source_snippet || "—"}
                          {extraction.rows[i]?.row_confidence && (
                            <span className="ml-1 text-gray-400">
                              ({extraction.rows[i].row_confidence})
                            </span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          )}
          {extraction.caveats?.length > 0 && (
            <ul className="space-y-0.5 text-[11px] text-blue-900/70">
              {extraction.caveats.map((c, i) => (
                <li key={i}>• {c}</li>
              ))}
            </ul>
          )}
          <p className="text-[11px] text-gray-500">{extraction.disclaimer}</p>
        </div>
      )}

      {report && (
        <div className="space-y-2 rounded-md border bg-gray-50 p-3">
          <p className="text-xs font-medium text-gray-700">
            Dry-run result: {report.importable_count} importable ·{" "}
            {report.error_count} with errors · {report.duplicate_count} duplicates ·{" "}
            {report.warning_count} with warnings
          </p>

          {report.parse_error && (
            <p className="text-xs text-red-600">{report.parse_error}</p>
          )}

          {report.missing_required_columns?.length > 0 && (
            <p className="text-xs text-red-600">
              Required column(s) not mapped:{" "}
              {report.missing_required_columns.join(", ")} — correct the mapping
              below.
            </p>
          )}

          {report.headers?.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-[11px]">
                <thead>
                  <tr className="text-gray-500">
                    <th className="py-1 pr-3 font-medium">CSV column</th>
                    <th className="py-1 font-medium">Maps to</th>
                  </tr>
                </thead>
                <tbody>
                  {report.headers.map((h) => (
                    <tr key={h} className="border-t border-gray-200">
                      <td className="py-1 pr-3 font-mono">{h}</td>
                      <td className="py-1">
                        <select
                          className="rounded border border-gray-300 px-1 py-0.5 text-[11px]"
                          value={(mapping || report.mapping)[h] || "ignore"}
                          onChange={(e) => remap(h, e.target.value)}
                        >
                          <option value="ignore">— ignore —</option>
                          {FIELD_OPTIONS[recordType].map((f) => (
                            <option key={f} value={f}>{f}</option>
                          ))}
                        </select>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {report.rows?.some((r) => r.errors.length || r.warnings.length || r.duplicate_of) && (
            <ul className="space-y-1 text-[11px]">
              {report.rows.map((r) =>
                r.errors.length || r.warnings.length || r.duplicate_of ? (
                  <li key={r.row_number} className="rounded bg-white px-2 py-1">
                    <span className="font-medium">Row {r.row_number}:</span>{" "}
                    {r.errors.map((e, i) => (
                      <span key={`e${i}`} className="text-red-600">{e}. </span>
                    ))}
                    {r.duplicate_of && (
                      <span className="text-amber-700">
                        Duplicate of {r.duplicate_of} — skipped.{" "}
                      </span>
                    )}
                    {r.warnings.map((w, i) => (
                      <span key={`w${i}`} className="text-gray-500">{w}. </span>
                    ))}
                  </li>
                ) : null
              )}
            </ul>
          )}

          {report.notes?.length > 0 && (
            <ul className="space-y-0.5 text-[11px] text-gray-400">
              {report.notes.map((n, i) => (
                <li key={i}>• {n}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
