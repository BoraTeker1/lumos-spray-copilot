"use client";

import { useEffect, useState } from "react";
import { api, API_BASE_URL } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { fieldClass } from "@/components/ui/input";
import PageHeader from "@/components/PageHeader";

const PERSON_TYPES = ["grower", "PCA", "agronomist", "exporter", "input_supplier", "other"];
const RECORDS = ["paper", "spreadsheet", "whatsapp", "software", "none", "other"];
const PAINS = ["cost", "PHI", "REI", "residue", "resistance", "audits", "labor", "other"];
const YNM = ["yes", "no", "maybe"];

const EMPTY = {
  person_type: "grower",
  crop: "",
  region: "",
  current_records_method: "",
  biggest_pain: "",
  would_use_real_data: "",
  would_pay: "",
  requested_pilot: false,
  notes: "",
};

// Capture pilot/discovery feedback after a demo. Stored locally in SQLite.
export default function FeedbackPage() {
  const [form, setForm] = useState(EMPTY);
  const [items, setItems] = useState([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const update = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  async function load() {
    try {
      setItems(await api.listPilotFeedback());
    } catch (err) {
      setError(err.message);
    }
  }
  useEffect(() => {
    load();
  }, []);

  async function submit(e) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await api.createPilotFeedback({
        ...form,
        crop: form.crop || null,
        region: form.region || null,
        current_records_method: form.current_records_method || null,
        biggest_pain: form.biggest_pain || null,
        would_use_real_data: form.would_use_real_data || null,
        would_pay: form.would_pay || null,
      });
      setForm(EMPTY);
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  const input = fieldClass;
  const label = "text-xs font-medium text-muted";

  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumbs={[{ label: "Feedback" }]}
        title="Pilot feedback"
        meta={
          <span>
            Capture what growers, PCAs, and operators say after a demo. Stored
            locally.
          </span>
        }
      />

      <form onSubmit={submit} className="grid gap-3 rounded-card border border-line bg-surface p-5 shadow-sm sm:grid-cols-2">
        <div>
          <span className={label}>Person type *</span>
          <select className={input} value={form.person_type} onChange={(e) => update("person_type", e.target.value)}>
            {PERSON_TYPES.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
        </div>
        <div>
          <span className={label}>Crop</span>
          <input className={input} value={form.crop} onChange={(e) => update("crop", e.target.value)} placeholder="strawberry, tomato…" />
        </div>
        <div>
          <span className={label}>Region</span>
          <input className={input} value={form.region} onChange={(e) => update("region", e.target.value)} placeholder="Watsonville, CA" />
        </div>
        <div>
          <span className={label}>Current spray records method</span>
          <select className={input} value={form.current_records_method} onChange={(e) => update("current_records_method", e.target.value)}>
            <option value="">—</option>
            {RECORDS.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </div>
        <div>
          <span className={label}>Biggest pain</span>
          <select className={input} value={form.biggest_pain} onChange={(e) => update("biggest_pain", e.target.value)}>
            <option value="">—</option>
            {PAINS.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
        </div>
        <div>
          <span className={label}>Would use with real data?</span>
          <select className={input} value={form.would_use_real_data} onChange={(e) => update("would_use_real_data", e.target.value)}>
            <option value="">—</option>
            {YNM.map((y) => <option key={y} value={y}>{y}</option>)}
          </select>
        </div>
        <div>
          <span className={label}>Would pay?</span>
          <select className={input} value={form.would_pay} onChange={(e) => update("would_pay", e.target.value)}>
            <option value="">—</option>
            {YNM.map((y) => <option key={y} value={y}>{y}</option>)}
          </select>
        </div>
        <label className="flex items-center gap-2 self-end text-sm">
          <input type="checkbox" checked={form.requested_pilot} onChange={(e) => update("requested_pilot", e.target.checked)} />
          Requested a pilot
        </label>
        <div className="sm:col-span-2">
          <span className={label}>Notes</span>
          <textarea className={input} rows={2} value={form.notes} onChange={(e) => update("notes", e.target.value)} placeholder="Verbatim quotes, next steps…" />
        </div>
        {error && <p className="text-sm text-risk-fg sm:col-span-2">{error}</p>}
        <div className="sm:col-span-2">
          <Button type="submit" disabled={saving}>
            {saving ? "Saving…" : "Save feedback"}
          </Button>
        </div>
      </form>

      <div className="flex items-center justify-between">
        <h2 className="text-section font-semibold text-ink">Captured feedback ({items.length})</h2>
        {items.length > 0 && (
          <a
            href={`${API_BASE_URL}/export/pilot-feedback.csv`}
            className="rounded-control border border-leaf-600/40 bg-surface px-3 py-1.5 text-sm font-medium text-leaf-700 shadow-sm hover:bg-leaf-50"
          >
            Export CSV
          </a>
        )}
      </div>

      <div className="space-y-2">
        {items.map((it) => (
          <div key={it.id} className="rounded-card border border-line bg-surface p-3 text-sm shadow-sm">
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-full bg-draft-bg px-2 py-0.5 text-xs font-medium">{it.person_type}</span>
              {it.crop && <span className="text-xs text-muted">{it.crop}</span>}
              {it.region && <span className="text-xs text-muted">· {it.region}</span>}
              {it.requested_pilot && <span className="rounded-full bg-ok-bg px-2 py-0.5 text-xs text-ok-fg">requested pilot</span>}
              <span className="ml-auto text-xs text-muted">{formatDate(it.created_at)}</span>
            </div>
            <div className="mt-1 text-xs text-muted">
              pain: {it.biggest_pain || "—"} · records: {it.current_records_method || "—"} ·
              would use: {it.would_use_real_data || "—"} · would pay: {it.would_pay || "—"}
            </div>
            {it.notes && <p className="mt-1 text-ink">{it.notes}</p>}
          </div>
        ))}
        {items.length === 0 && <p className="text-sm text-muted">No feedback captured yet.</p>}
      </div>
    </div>
  );
}
