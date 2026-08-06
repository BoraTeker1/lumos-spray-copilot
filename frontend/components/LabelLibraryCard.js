"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

// Operator tooling for the label library. Three separate acts, deliberately shown
// as three steps rather than one form, because they are three different levels of
// trust and collapsing them is exactly the mistake this layer exists to prevent:
//
//   1. EXTRACT — a model proposes values. Writes nothing.
//   2. COMMIT  — a human corrects them. Lands as ai_extracted_unverified: on file,
//                not in force. Still cannot back any decision.
//   3. VERIFY  — a licensed PCA attests, for one farm, against the document. Only
//                now can a decision use the value.
//
// The UI never lets step 3 be implied by step 2. A record's tier is shown verbatim
// on every row so an operator can see what is still unverified.

const TIER_LABELS = {
  transcribed_unverified: "transcribed — unverified",
  ai_extracted_unverified: "AI-extracted — unverified",
  pca_verified_transcription: "PCA-verified",
  registrant_provider_feed: "registrant feed",
};

// The fields a reviewer edits before committing. Regulatory values are blank
// unless the label states them — a blank stays blank and the check stays unrun.
const EMPTY_ROW = {
  epa_reg_no: "",
  product_name: "",
  registrant: "",
  registered_crop: "",
  target_pest_or_disease: "",
  pre_harvest_interval_days: "",
  re_entry_interval_hours: "",
  max_applications_per_season: "",
  min_retreatment_interval_days: "",
  max_seasonal_rate_amount: "",
  max_seasonal_rate_unit: "",
  active_ingredient: "",
  moa_group: "",
  label_version: "",
  label_effective_date: "",
  source_document_reference: "",
  source_section_or_page: "",
  source_snippet: "",
  reviewed_by: "",
};

// Draft strings -> the commit payload. Empty means "the label is silent", so it is
// omitted rather than sent as 0 — the difference between a missing check and a
// fabricated clearance.
function toPayload(draft) {
  const numeric = [
    "pre_harvest_interval_days",
    "re_entry_interval_hours",
    "max_applications_per_season",
    "min_retreatment_interval_days",
    "max_seasonal_rate_amount",
  ];
  const payload = {};
  Object.entries(draft).forEach(([key, value]) => {
    const text = String(value ?? "").trim();
    if (!text) return;
    payload[key] = numeric.includes(key) ? Number(text) : text;
  });
  return payload;
}

// Extracted rows are strings as printed on the label. Carry them across verbatim —
// never parse or convert here, or the operator reviews a number the label never had.
function draftFromExtraction(row) {
  const draft = { ...EMPTY_ROW };
  Object.keys(EMPTY_ROW).forEach((key) => {
    if (row[key] != null) draft[key] = String(row[key]);
  });
  return draft;
}

export default function LabelLibraryCard({ farmId }) {
  const [products, setProducts] = useState([]);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  const [text, setText] = useState("");
  const [file, setFile] = useState(null);
  const [extraction, setExtraction] = useState(null);
  const [busy, setBusy] = useState(false);

  const [draft, setDraft] = useState(null);
  const [verifying, setVerifying] = useState(null);
  const [attestation, setAttestation] = useState("");

  const load = useCallback(() => {
    api
      .listPesticideProducts()
      .then(setProducts)
      .catch((err) => setError(err.message));
  }, []);

  useEffect(load, [load]);

  async function run(action, onDone) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      onDone(await action());
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const extract = () =>
    run(
      () => api.extractLabel({ text, file }),
      (result) => {
        setExtraction(result.extraction);
        setDraft(null);
      }
    );

  const sync = () =>
    run(api.syncTranscribedLabels, (result) => {
      load();
      setNotice(
        result.transcribed_entries === 0
          ? "app/label_table.py is empty, so nothing was loaded. That is the intended state until a value is transcribed from a primary label document with its citation."
          : `Loaded ${result.records_created} record(s); ${result.unchanged} unchanged.`
      );
    });

  const commit = () =>
    run(
      () => api.createLabelRecord(toPayload(draft)),
      () => {
        setDraft(null);
        setExtraction(null);
        load();
        setNotice(
          "Committed as AI-extracted — UNVERIFIED. It cannot back any decision until a licensed PCA verifies it for a farm."
        );
      }
    );

  const verify = () =>
    run(
      () =>
        api.createLabelVerification(farmId, {
          product_label_record_id: verifying,
          attestation,
        }),
      (result) => {
        setVerifying(null);
        setAttestation("");
        load();
        setNotice(`Verified by ${result.verified_by} for this farm.`);
      }
    );

  return (
    <div className="space-y-4">
      {error && (
        <p className="rounded-control border border-risk-line bg-risk-bg p-2 text-xs text-risk-fg">
          {error}
        </p>
      )}
      {notice && (
        <p className="rounded-control border border-ok-line bg-ok-bg p-2 text-xs text-ok-fg">
          {notice}
        </p>
      )}

      {/* ---------------------------------------------------- 1. extract */}
      <div className="rounded-control border border-line p-3">
        <h3 className="text-sm font-semibold text-ink">
          1. Extract from a label document
        </h3>
        <p className="mt-0.5 text-[11px] text-muted">
          Real AI. Copies only what the label literally states — never converts units
          and never infers a value the label omits. Writes nothing: every row below is
          a draft for you to correct.
        </p>
        <textarea
          className="mt-2 w-full rounded border px-2 py-1.5 text-xs"
          rows={3}
          placeholder="Paste label text, or choose a PDF/photo below"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <input
            type="file"
            accept="application/pdf,image/*"
            className="text-xs"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
          />
          <button
            type="button"
            onClick={extract}
            disabled={busy || (!text.trim() && !file)}
            className="rounded bg-ink px-3 py-1.5 text-xs font-medium text-white disabled:opacity-40"
          >
            {busy ? "Working…" : "Extract draft rows"}
          </button>
          <button
            type="button"
            onClick={sync}
            disabled={busy}
            className="rounded border px-3 py-1.5 text-xs font-medium disabled:opacity-40"
          >
            Load transcribed labels
          </button>
        </div>
      </div>

      {/* ---------------------------------------------------- 2. review */}
      {extraction && (
        <div className="rounded-control border border-warn-line bg-warn-bg p-3">
          <h3 className="text-sm font-semibold text-warn-fg">
            2. Review every value against the document
          </h3>
          <p className="mt-0.5 text-[11px] text-warn-fg">{extraction.disclaimer}</p>
          {extraction.is_mock && (
            <p className="mt-1 text-[11px] font-medium text-warn-fg">
              Mock extraction (no ANTHROPIC_API_KEY) — these values are fictional and
              are not model output.
            </p>
          )}
          {extraction.abstained ? (
            <p className="mt-2 text-xs text-warn-fg">
              The model abstained: {extraction.abstain_reason}
            </p>
          ) : (
            <ul className="mt-2 space-y-1.5">
              {extraction.rows.map((row, i) => (
                <li key={i} className="rounded bg-surface/70 p-2 text-xs text-ink">
                  <div className="font-medium">
                    {row.registered_crop || "(no crop)"} · {row.product_name || "(no product)"}
                  </div>
                  {row.source_snippet && (
                    <p className="mt-0.5 text-[11px] italic text-muted">
                      “{row.source_snippet}”
                      {row.source_section_or_page ? ` — ${row.source_section_or_page}` : ""}
                    </p>
                  )}
                  <button
                    type="button"
                    onClick={() => setDraft(draftFromExtraction(row))}
                    className="mt-1.5 rounded border border-warn-line bg-surface px-2 py-1 text-[11px] font-medium"
                  >
                    Correct &amp; commit this row
                  </button>
                </li>
              ))}
            </ul>
          )}
          {extraction.caveats?.length > 0 && (
            <ul className="mt-2 list-disc pl-4 text-[11px] text-warn-fg">
              {extraction.caveats.map((c, i) => (
                <li key={i}>{c}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {draft && (
        <div className="rounded-control border border-line p-3">
          <h3 className="text-sm font-semibold text-ink">Commit one label use</h3>
          <p className="mt-0.5 text-[11px] text-muted">
            Leave a value blank when the label does not state it — blank means the
            label is silent, and the matching check correctly keeps reporting that it
            did not run. It never means &ldquo;no limit&rdquo;.
          </p>
          <div className="mt-2 grid gap-2 sm:grid-cols-2">
            {Object.keys(EMPTY_ROW).map((key) => (
              <label key={key} className="text-[11px] font-medium text-muted">
                {key.replace(/_/g, " ")}
                <input
                  className="mt-0.5 w-full rounded border px-2 py-1 text-xs"
                  value={draft[key]}
                  onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}
                />
              </label>
            ))}
          </div>
          <div className="mt-2 flex gap-2">
            <button
              type="button"
              onClick={commit}
              disabled={busy}
              className="rounded bg-ink px-3 py-1.5 text-xs font-medium text-white disabled:opacity-40"
            >
              Commit as unverified
            </button>
            <button
              type="button"
              onClick={() => setDraft(null)}
              className="rounded border px-3 py-1.5 text-xs font-medium"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* ---------------------------------------------------- 3. library */}
      <div className="rounded-control border border-line p-3">
        <h3 className="text-sm font-semibold text-ink">Label library</h3>
        {products.length === 0 ? (
          <p className="mt-1 text-xs text-muted">
            No products on file. Every label-dependent check reports that it did not
            run, with the reason, on every decision.
          </p>
        ) : (
          <ul className="mt-2 space-y-2">
            {products.map((product) => (
              <li key={product.id} className="rounded border border-line p-2">
                <div className="text-xs font-medium text-ink">
                  {product.product_name}{" "}
                  <span className="font-normal text-muted">
                    · EPA Reg. No. {product.epa_reg_no}
                  </span>
                </div>
                {!product.registered_crops_transcription_complete && (
                  <p className="mt-0.5 text-[11px] text-muted">
                    Registered-crop list not marked complete — the crop/use
                    registration check stays unevaluated for this product.
                  </p>
                )}
                <ul className="mt-1 space-y-1">
                  {product.label_records.map((record) => (
                    <li key={record.id} className="text-[11px] text-ink">
                      <span className="font-medium">{record.registered_crop}</span>
                      {" · "}
                      <span className="text-muted">
                        {TIER_LABELS[record.source_tier] || record.source_tier}
                      </span>
                      {record.supersedes_label_record_id && (
                        <span className="text-muted">
                          {" "}
                          · supersedes #{record.supersedes_label_record_id}
                        </span>
                      )}
                      {record.verifications?.length > 0 && (
                        <span className="text-ok-fg">
                          {" "}
                          · verified for {record.verifications.length} farm(s)
                        </span>
                      )}
                      {farmId && (
                        <button
                          type="button"
                          onClick={() => {
                            setVerifying(record.id);
                            setAttestation("");
                          }}
                          className="ml-1.5 rounded border px-1.5 py-0.5 text-[10px] font-medium"
                        >
                          Verify for this farm
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* ---------------------------------------------------- 4. verify */}
      {verifying && (
        <div className="rounded-control border border-ok-line bg-ok-bg p-3">
          <h3 className="text-sm font-semibold text-ok-fg">
            3. PCA verification (record #{verifying})
          </h3>
          <p className="mt-0.5 text-[11px] text-ok-fg">
            This is a professional act by the farm&apos;s licensed PCA, attributed to
            their credential — not to a name typed here. It requires their token, and
            it applies to THIS farm only. After it, decisions on this farm may rely on
            these values.
          </p>
          <textarea
            className="mt-2 w-full rounded border px-2 py-1.5 text-xs"
            rows={2}
            placeholder="What you checked, against which revision and page"
            value={attestation}
            onChange={(e) => setAttestation(e.target.value)}
          />
          <div className="mt-2 flex gap-2">
            <button
              type="button"
              onClick={verify}
              disabled={busy || attestation.trim().length < 10}
              className="rounded bg-leaf-700 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-40"
            >
              Record verification
            </button>
            <button
              type="button"
              onClick={() => setVerifying(null)}
              className="rounded border px-3 py-1.5 text-xs font-medium"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
