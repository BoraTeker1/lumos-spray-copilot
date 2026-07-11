"use client";

import { useState } from "react";
import { FileDown, ShieldCheck, Upload } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";

// CSV pilot import for REAL records (planned spray recommendations + scouting).
// Server-side dry-run first: column mapping (correctable), per-row errors/warnings,
// duplicate detection — nothing is written until the operator confirms the import.
// Imported values are stored as imported_unverified provenance: the decision check
// flags them and they can never produce an automatic approve.

const RECORD_TYPES = [
  { value: "planned_sprays", label: "Planned sprays (recommendations)" },
  { value: "scout_observations", label: "Scouting observations" },
];

// Canonical fields per record type (mirrors backend csv_import.py) for the
// mapping-correction dropdowns.
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
};

export default function PilotImportCard({ farmId, onImported }) {
  const [recordType, setRecordType] = useState("planned_sprays");
  const [text, setText] = useState("");
  const [filename, setFilename] = useState(null);
  const [mapping, setMapping] = useState(null); // header -> field overrides
  const [report, setReport] = useState(null);
  const [busy, setBusy] = useState(false);
  const [committed, setCommitted] = useState(null);
  const [error, setError] = useState(null);

  function reset(keepText = false) {
    setReport(null);
    setCommitted(null);
    setError(null);
    setMapping(null);
    if (!keepText) {
      setText("");
      setFilename(null);
    }
  }

  async function onFile(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    reset();
    setText(await file.text());
    setFilename(file.name);
    e.target.value = "";
  }

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

  const importable = report?.importable_count ?? 0;

  return (
    <div className="space-y-2">
      <p className="text-xs text-gray-500">
        Import real pilot records from a CSV. Everything is validated in a{" "}
        <span className="font-medium text-gray-700">dry run first</span> — fix the
        column mapping below if a header was not recognized, then confirm. Imported
        values are stored as <span className="font-medium">imported, unverified</span>:
        the pre-spray check flags them and they can never auto-approve.
      </p>

      <div className="flex flex-wrap items-center gap-2">
        <select
          className="rounded-md border border-gray-300 px-2 py-1.5 text-xs"
          value={recordType}
          onChange={(e) => {
            setRecordType(e.target.value);
            reset(true);
          }}
        >
          {RECORD_TYPES.map((t) => (
            <option key={t.value} value={t.value}>{t.label}</option>
          ))}
        </select>
        <a
          className="inline-flex items-center gap-1 text-xs font-medium text-gray-500 underline-offset-2 hover:text-gray-900 hover:underline"
          href={api.exportUrl(`/import/templates/${recordType}.csv`)}
        >
          <FileDown className="h-3.5 w-3.5" /> Download template
        </a>
      </div>

      <textarea
        className="w-full rounded-md border border-gray-300 px-2.5 py-1.5 font-mono text-xs"
        rows={5}
        placeholder="Paste CSV rows here (header row first), or upload a file below."
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          reset(true);
        }}
      />

      <div className="flex flex-wrap items-center gap-2">
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
          <input
            type="file"
            accept=".csv,text/csv,text/plain"
            className="hidden"
            onChange={onFile}
          />
        </label>
        {filename && <span className="text-[11px] text-gray-400">{filename}</span>}
      </div>

      {error && <p className="text-xs text-red-600">{error}</p>}

      {committed && (
        <p className="rounded bg-green-50 px-3 py-2 text-sm text-green-700">
          Imported {committed.created_record_ids?.length ?? 0} record(s) (batch #
          {committed.batch?.id}), tagged spreadsheet / imported-unverified.
          {report?.duplicate_count > 0 &&
            ` ${report.duplicate_count} duplicate row(s) were skipped and are listed below.`}
        </p>
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
