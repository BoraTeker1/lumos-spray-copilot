"use client";

import { useState } from "react";
import { Upload } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";

// Customer-facing spray-history import: paste rows from a spreadsheet (or upload a
// CSV) — no JSON anywhere. Columns, in order:
//   product, active ingredient, date (YYYY-MM-DD), cost, PHI days, REI hours
// Every imported row is tagged data_source="spreadsheet" so provenance stays honest.
const EXPECTED_COLUMNS = ["product", "active ingredient", "date (YYYY-MM-DD)", "cost", "PHI days", "REI hours"];

const PLACEHOLDER =
  "Captan 80 WDG, captan, 2026-07-01, 120, 4, 24\n" +
  "Brigade WSB, bifenthrin, 2026-07-05, 180, 3, 12";

function parseRows(text) {
  const rows = [];
  const errors = [];
  const lines = text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  lines.forEach((line, i) => {
    // Tab-separated (spreadsheet paste) or comma-separated both work.
    const cells = (line.includes("\t") ? line.split("\t") : line.split(",")).map((c) =>
      c.trim()
    );
    const [product, ai, dateStr, cost, phi, rei] = cells;
    // Skip a pasted header row instead of failing on it.
    if (i === 0 && product && product.toLowerCase().startsWith("product")) return;
    if (!product) {
      errors.push(`Line ${i + 1}: missing product name.`);
      return;
    }
    if (!dateStr || !/^\d{4}-\d{2}-\d{2}$/.test(dateStr)) {
      errors.push(`Line ${i + 1}: date must be YYYY-MM-DD (got "${dateStr || ""}").`);
      return;
    }
    const num = (v) => (v === undefined || v === "" ? null : Number(v));
    if ([cost, phi, rei].some((v) => v !== undefined && v !== "" && Number.isNaN(Number(v)))) {
      errors.push(`Line ${i + 1}: cost / PHI / REI must be numbers.`);
      return;
    }
    rows.push({
      product_name: product,
      active_ingredient: ai || null,
      application_date: dateStr,
      cost: num(cost),
      pre_harvest_interval_days: num(phi) === null ? null : Math.round(num(phi)),
      re_entry_interval_hours: num(rei) === null ? null : Math.round(num(rei)),
      data_source: "spreadsheet",
      data_confidence: "user_provided",
    });
  });
  return { rows, errors };
}

export default function SprayImportCard({ farmId, onImported }) {
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState(null);
  const [errors, setErrors] = useState([]);

  async function onFile(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    setText(await file.text());
    e.target.value = "";
  }

  async function importRows() {
    const { rows, errors: parseErrors } = parseRows(text);
    setErrors(parseErrors);
    setResult(null);
    if (rows.length === 0) {
      if (parseErrors.length === 0) setErrors(["Nothing to import — paste at least one row."]);
      return;
    }
    setSaving(true);
    try {
      for (const row of rows) {
        await api.createSprayEvent(farmId, row);
      }
      api.trackEvent({
        event_type: "import_used",
        farm_id: Number(farmId),
        entry_source: "csv_paste",
        meta: { rows_imported: rows.length, parse_errors: parseErrors.length },
      });
      setResult(`Imported ${rows.length} spray record(s), tagged as spreadsheet data.`);
      setText("");
      onImported && (await onImported());
    } catch (err) {
      setErrors([err.message]);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-2">
      <p className="text-xs text-muted">
        Paste rows straight from a spreadsheet (or upload a CSV). Column order:{" "}
        <span className="font-medium text-ink">{EXPECTED_COLUMNS.join(" · ")}</span>.
        Only product and date are required.
      </p>
      <textarea
        className="w-full rounded-control border border-line px-2.5 py-1.5 font-mono text-xs"
        rows={4}
        placeholder={PLACEHOLDER}
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" size="sm" disabled={saving || !text.trim()} onClick={importRows}>
          <Upload />
          {saving ? "Importing…" : "Import rows"}
        </Button>
        <label className="cursor-pointer text-xs font-medium text-muted underline-offset-2 hover:text-ink hover:underline">
          …or upload a CSV file
          <input type="file" accept=".csv,text/csv,text/plain" className="hidden" onChange={onFile} />
        </label>
      </div>
      {result && <p className="text-sm text-ok-fg">{result}</p>}
      {errors.length > 0 && (
        <ul className="space-y-0.5 text-xs text-risk-fg">
          {errors.map((e, i) => (
            <li key={i}>{e}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
