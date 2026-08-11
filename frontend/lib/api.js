// Single place for all backend calls. Keeps components free of fetch boilerplate
// and makes it easy to add auth headers later.
const BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Session-held credentials. Never persisted to localStorage: a PCA token signs
// professional recommendations, so it lives for one browser session and no longer.
const PCA_TOKEN_KEY = "lumos.pcaToken";
const OPERATOR_KEY_KEY = "lumos.operatorKey";

function sessionValue(key) {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage.getItem(key) || null;
  } catch {
    return null; // private mode / storage disabled
  }
}

export const credentials = {
  getPcaToken: () => sessionValue(PCA_TOKEN_KEY),
  setPcaToken: (token) => window.sessionStorage.setItem(PCA_TOKEN_KEY, token),
  clearPcaToken: () => window.sessionStorage.removeItem(PCA_TOKEN_KEY),
  getOperatorKey: () => sessionValue(OPERATOR_KEY_KEY),
  setOperatorKey: (key) => window.sessionStorage.setItem(OPERATOR_KEY_KEY, key),
  clearOperatorKey: () => window.sessionStorage.removeItem(OPERATOR_KEY_KEY),
};

function pcaHeaders() {
  const token = credentials.getPcaToken();
  return token ? { "X-Lumos-Pca-Token": token } : {};
}

function operatorHeaders() {
  const key = credentials.getOperatorKey();
  return key ? { "X-Lumos-Operator-Key": key } : {};
}

// Query string from defined values only, so an omitted filter is truly omitted.
function qs(params) {
  const pairs = Object.entries(params).filter(
    ([, v]) => v !== undefined && v !== null && v !== ""
  );
  return pairs.length ? `?${new URLSearchParams(pairs)}` : "";
}

// Presentation only: FastAPI returns its message as {"detail": "..."}, and
// printing the raw body put a literal `API 403: {"detail":"…"}` on screen —
// JSON punctuation the reader has to parse past to reach the sentence. The
// status code is kept for anything without a detail string.
async function errorMessage(res) {
  const body = await res.text().catch(() => "");
  try {
    const parsed = JSON.parse(body);
    const detail = parsed?.detail;
    if (typeof detail === "string" && detail) return detail;
    // Pydantic validation errors arrive as a list of {loc, msg}.
    if (Array.isArray(detail) && detail.length) {
      const msgs = detail.map((d) => d?.msg).filter(Boolean);
      if (msgs.length) return msgs.join("; ");
    }
  } catch {
    // Not JSON — fall through to the raw text.
  }
  return body || `${res.status} ${res.statusText}`;
}

async function request(path, options = {}) {
  const res = await fetch(`${BASE_URL}${path}`, {
    cache: "no-store",
    ...options,
    // MERGED, not spread-over. `...options` used to come after `headers`, so any
    // caller passing headers replaced the object wholesale and silently dropped
    // Content-Type — every POST body went up untyped. Merging is what makes the
    // X-Lumos-Pca-Token / X-Lumos-Operator-Key headers possible at all.
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  if (!res.ok) {
    throw new Error(await errorMessage(res));
  }
  if (res.status === 204) return null;
  return res.json();
}

export const api = {
  // Farms
  listFarms: () => request("/farms"),
  listFarmsOverview: () => request("/farms-overview"),
  // The same status entry the dashboard shows, for one farm (single derivation —
  // the farm page must use this instead of re-deriving counts client-side).
  getFarmOverview: (id) => request(`/farms/${id}/overview`),
  getFarm: (id) => request(`/farms/${id}`),
  createFarm: (data) =>
    request("/farms", { method: "POST", body: JSON.stringify(data) }),
  updateFarm: (id, data) =>
    request(`/farms/${id}`, { method: "PUT", body: JSON.stringify(data) }),

  // Spray events
  listSprayEvents: (farmId) => request(`/farms/${farmId}/spray-events`),
  createSprayEvent: (farmId, data) =>
    request(`/farms/${farmId}/spray-events`, {
      method: "POST",
      body: JSON.stringify(data),
    }),

  // Scout observations
  listScoutObservations: (farmId) =>
    request(`/farms/${farmId}/scout-observations`),
  createScoutObservation: (farmId, data) =>
    request(`/farms/${farmId}/scout-observations`, {
      method: "POST",
      body: JSON.stringify(data),
    }),

  // Planned sprays (pre-spray decision check)
  listPlannedSprays: (farmId) => request(`/farms/${farmId}/planned-sprays`),
  getPlannedSpray: (plannedId) => request(`/planned-sprays/${plannedId}`),
  createPlannedSpray: (farmId, data) =>
    request(`/farms/${farmId}/planned-sprays`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  reviewPlannedSpray: (plannedId, data) =>
    request(`/planned-sprays/${plannedId}/review`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }),
  updatePlannedSprayOutcome: (plannedId, data) =>
    request(`/planned-sprays/${plannedId}/outcome`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }),
  deletePlannedSpray: (plannedId) =>
    request(`/planned-sprays/${plannedId}`, { method: "DELETE" }),
  getDecisionEvidence: (farmId) => request(`/farms/${farmId}/decision-evidence`),

  // Decision provenance + immutable audit trail + follow-up timeline
  listAuditEvents: (plannedId) =>
    request(`/planned-sprays/${plannedId}/audit-events`),
  listInputValues: (plannedId) =>
    request(`/planned-sprays/${plannedId}/input-values`),
  listFollowUpEvents: (plannedId) =>
    request(`/planned-sprays/${plannedId}/follow-up-events`),
  addFollowUpEvent: (plannedId, data) =>
    request(`/planned-sprays/${plannedId}/follow-up-events`, {
      method: "POST",
      body: JSON.stringify(data),
    }),

  // CSV pilot import (dry-run by default; commit with dry_run: false)
  importCsv: (farmId, data) =>
    request(`/farms/${farmId}/import/csv`, {
      method: "POST",
      body: JSON.stringify(data),
    }),

  // AI document/message extraction (never writes; returns draft rows + dry-run report).
  // Multipart, so it bypasses the JSON helper.
  extractDocument: async (farmId, { recordType, text, file }) => {
    const body = new FormData();
    body.append("record_type", recordType);
    if (text) body.append("text", text);
    if (file) body.append("file", file);
    const res = await fetch(`${BASE_URL}/farms/${farmId}/import/document`, {
      method: "POST",
      cache: "no-store",
      body, // browser sets the multipart boundary; do NOT set Content-Type
    });
    if (!res.ok) {
      throw new Error(await errorMessage(res));
    }
    return res.json();
  },
  // Commit path for human-reviewed extracted rows (server re-validates everything).
  importRows: (farmId, data) =>
    request(`/farms/${farmId}/import/rows`, {
      method: "POST",
      body: JSON.stringify(data),
    }),

  // AI review brief for one decision (on-demand; never changes the decision).
  generateAiBrief: (plannedId) =>
    request(`/planned-sprays/${plannedId}/ai-brief`, { method: "POST" }),
  getAiCalibration: () =>
    request("/internal/ai-calibration", { headers: operatorHeaders() }),

  // ------------------------------------------------------------ label library
  listPesticideProducts: () =>
    request("/internal/labels/products", { headers: operatorHeaders() }),
  syncTranscribedLabels: () =>
    request("/internal/labels/sync", {
      method: "POST",
      headers: operatorHeaders(),
    }),
  // "Why does this decision still say the label check did not run?" — same
  // resolution the decision path uses, so the answers cannot disagree.
  // Grower-facing, farm-scoped: no operator key. Tells the person entering a spray
  // whether a verified label supplies PHI/REI or whether they still have to type them.
  resolveLabel: ({ epaRegNo, crop, farmId } = {}) =>
    request(
      `/farms/${farmId}/label-resolution${qs({ epa_reg_no: epaRegNo, crop })}`
    ),
  // Operator view of the same resolution, not scoped to a farm.
  resolveLabelInternal: ({ epaRegNo, crop, farmId } = {}) =>
    request(
      `/internal/labels/resolution${qs({
        epa_reg_no: epaRegNo,
        crop,
        farm_id: farmId,
      })}`,
      { headers: operatorHeaders() }
    ),
  // AI label extraction. NEVER writes — returns draft rows for a human to correct.
  // Multipart, so it bypasses the JSON helper (same shape as extractDocument).
  extractLabel: async ({ text, file }) => {
    const body = new FormData();
    if (text) body.append("text", text);
    if (file) body.append("file", file);
    const res = await fetch(`${BASE_URL}/internal/labels/extract`, {
      method: "POST",
      cache: "no-store",
      headers: operatorHeaders(),
      body, // browser sets the multipart boundary; do NOT set Content-Type
    });
    if (!res.ok) {
      throw new Error(await errorMessage(res));
    }
    return res.json();
  },
  // Commit ONE reviewed row. Lands as ai_extracted_unverified — never verified.
  createLabelRecord: (data) =>
    request("/internal/labels/records", {
      method: "POST",
      headers: operatorHeaders(),
      body: JSON.stringify(data),
    }),
  // The act that makes a label value usable. Requires the farm's PCA token.
  createLabelVerification: (farmId, data) =>
    request(`/farms/${farmId}/label-verifications`, {
      method: "POST",
      headers: pcaHeaders(),
      body: JSON.stringify(data),
    }),

  // Anonymized evidence export (JSON; CSV via exportUrl)
  getEvidenceExport: (farmId) => request(`/farms/${farmId}/evidence-export`),

  // Recommendations
  listRecommendations: (farmId) => request(`/farms/${farmId}/recommendations`),
  generateRecommendation: (farmId) =>
    request(`/farms/${farmId}/recommendations`, { method: "POST" }),
  updateRecommendation: (recId, data) =>
    request(`/recommendations/${recId}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }),

  // Analytics, weather & compliance
  getAnalytics: (farmId) => request(`/farms/${farmId}/analytics`),
  getWeatherRisk: (farmId) => request(`/farms/${farmId}/weather-risk`),
  getCompliance: (farmId) => request(`/farms/${farmId}/compliance`),

  // Data readiness (grower-facing, NOT operator-gated). Answers "can this farm's data
  // support a measurement yet" — deliberately carries no risk band and no action.
  getDataReadiness: (farmId) => request(`/farms/${farmId}/data-readiness`),

  // Ingestion (operator only)
  getIngestionSources: () =>
    request("/internal/ingestion/sources", { headers: operatorHeaders() }),
  getIngestionRuns: (params = {}) =>
    request(`/internal/ingestion${qs(params)}`, { headers: operatorHeaders() }),
  runIngestionSource: (sourceKey, data) =>
    request(`/internal/ingestion/${sourceKey}/run`, {
      method: "POST",
      headers: operatorHeaders(),
      body: JSON.stringify(data),
    }),

  // Historical opportunity scan (operator only — pilot ladder Stage 2).
  // Operator-gated for a reason beyond tooling convenience: a risk histogram reaching a
  // PCA enrolled in the blinded shadow study would contaminate the baseline their
  // dispositions exist to provide.
  runOpportunityScan: (farmId, data) =>
    request(`/internal/farms/${farmId}/opportunity-scans`, {
      method: "POST",
      headers: operatorHeaders(),
      body: JSON.stringify(data),
    }),
  getOpportunityScans: (params = {}) =>
    request(`/internal/opportunity-scans${qs(params)}`, { headers: operatorHeaders() }),
  getOpportunityScan: (scanId) =>
    request(`/internal/opportunity-scans/${scanId}`, { headers: operatorHeaders() }),

  // Weekly report
  weeklyReport: (farmId) => request(`/farms/${farmId}/weekly-report`),

  // Field-photo analysis (multimodal CV). Uses multipart, so it bypasses the JSON helper.
  analyzePhoto: async (farmId, file, concern) => {
    const body = new FormData();
    body.append("file", file);
    const qs = concern ? `?concern=${encodeURIComponent(concern)}` : "";
    const res = await fetch(`${BASE_URL}/farms/${farmId}/photo-analysis${qs}`, {
      method: "POST",
      cache: "no-store",
      body, // browser sets the multipart boundary; do NOT set Content-Type
    });
    if (!res.ok) {
      throw new Error(await errorMessage(res));
    }
    return res.json();
  },

  // PCA-entered action thresholds (per farm + target; attributed, never invented)
  listPcaPolicies: (farmId) => request(`/farms/${farmId}/pca-policies`),
  setPcaPolicy: (farmId, data) =>
    request(`/farms/${farmId}/pca-policies`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),

  // Demo reset (refused with 409 unless the whole DB is demo/simulated data)
  resetDemo: () =>
    request("/internal/demo/reset", {
      method: "POST",
      headers: operatorHeaders(),
    }),

  // Reduction measurement
  getReduction: (farmId) => request(`/farms/${farmId}/reduction`),
  getSprayBaseline: (farmId) => request(`/farms/${farmId}/spray-baseline`),
  setSprayBaseline: (farmId, data) =>
    request(`/farms/${farmId}/spray-baseline`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),

  // Pilot evidence & audit packet
  getPilotEvidence: (farmId) => request(`/farms/${farmId}/pilot-evidence`),
  getAuditPacket: (farmId) => request(`/farms/${farmId}/audit-packet`),

  // Concierge pilot mode (internal tooling — not the customer-facing workflow)
  importPilotData: (farmId, data) =>
    request(`/internal/farms/${farmId}/pilot-import`, {
      method: "POST",
      headers: operatorHeaders(),
      body: JSON.stringify(data),
    }),
  getPilotCaseStudy: (farmId) => request(`/farms/${farmId}/pilot-case-study`),

  // Pilot instrumentation (fire-and-forget; failures must never break the UI)
  trackEvent: (data) => {
    request("/pilot-events", { method: "POST", body: JSON.stringify(data) }).catch(() => {});
  },
  getInstrumentation: () =>
    request("/internal/instrumentation", { headers: operatorHeaders() }),

  // Pilot feedback & intake
  listPilotFeedback: () => request("/pilot-feedback"),
  createPilotFeedback: (data) =>
    request("/pilot-feedback", { method: "POST", body: JSON.stringify(data) }),
  createPilotFarm: (data) =>
    request("/pilot/farms", { method: "POST", body: JSON.stringify(data) }),

  // Inputs & finance (Phase 1 procurement: RFQ -> concierge quotes -> optional
  // INDICATIVE financing -> order -> explicit application link; no real money)
  listInputPlans: (farmId) => request(`/farms/${farmId}/input-plans`),
  createInputPlan: (farmId, data) =>
    request(`/farms/${farmId}/input-plans`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  getInputPlan: (planId) => request(`/input-plans/${planId}`),
  addInputPlanItem: (planId, data) =>
    request(`/input-plans/${planId}/items`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  deleteInputPlanItem: (itemId) =>
    request(`/input-plan-items/${itemId}`, { method: "DELETE" }),
  submitInputPlan: (planId, data) =>
    request(`/input-plans/${planId}/submit`, {
      method: "POST",
      body: JSON.stringify(data || {}),
    }),
  cancelInputPlan: (planId, data) =>
    request(`/input-plans/${planId}/cancel`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  listQuotes: (planId) => request(`/input-plans/${planId}/quotes`),
  selectQuote: (planId, data) =>
    request(`/input-plans/${planId}/select-quote`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  decideFinancingOffer: (offerId, data) =>
    request(`/financing-offers/${offerId}/decision`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  createOrder: (planId, data) =>
    request(`/input-plans/${planId}/order`, {
      method: "POST",
      body: JSON.stringify(data || {}),
    }),
  listOrders: (farmId) => request(`/farms/${farmId}/orders`),
  getOrder: (orderId) => request(`/orders/${orderId}`),
  listOrderEvents: (orderId) => request(`/orders/${orderId}/events`),
  reportInputApplied: (orderId, data) =>
    request(`/orders/${orderId}/input-applied`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  // ----------------------------------------------------------------- finance
  // Reading a farm's own assessment history is grower-facing (no operator key):
  // "why was I declined" is their question, and the refusal rows are the part they
  // most need to see. RECORDING an assessment is a consequential act, so it is
  // operator-gated.
  getFarmProfile: (farmId) => request(`/farms/${farmId}/profile`),
  listCreditAssessments: (farmId) =>
    request(`/farms/${farmId}/credit-assessments`),
  recordCreditAssessment: (farmId, assessedBy) =>
    request(
      `/internal/farms/${farmId}/credit-assessments${qs({ assessed_by: assessedBy })}`,
      { method: "POST", headers: operatorHeaders() }
    ),
  listUnderwritingDecisions: (farmId) =>
    request(`/farms/${farmId}/underwriting-decisions`),
  recordUnderwritingDecision: (farmId, data) =>
    request(`/internal/farms/${farmId}/underwriting-decisions`, {
      method: "POST",
      headers: operatorHeaders(),
      body: JSON.stringify(data),
    }),
  listCollateral: (farmId) => request(`/farms/${farmId}/collateral`),
  registerCollateral: (farmId, data) =>
    request(`/internal/farms/${farmId}/collateral`, {
      method: "POST",
      headers: operatorHeaders(),
      body: JSON.stringify(data),
    }),
  listMonitoringSnapshots: (farmId) =>
    request(`/farms/${farmId}/monitoring-snapshots`),
  recordMonitoringSnapshot: (farmId) =>
    request(`/internal/farms/${farmId}/monitoring-snapshots`, {
      method: "POST",
      headers: operatorHeaders(),
    }),
  listCoverageAssessments: (farmId) =>
    request(`/farms/${farmId}/coverage-assessments`),
  recordCoverageAssessment: (farmId, data) =>
    request(`/internal/farms/${farmId}/coverage-assessments`, {
      method: "POST",
      headers: operatorHeaders(),
      body: JSON.stringify(data),
    }),
  // The operator worklist: which empty sources are blocking which layer.
  getTranscriptionStatus: () =>
    request("/internal/transcription-status", { headers: operatorHeaders() }),

  // ------------------------------------------------------------- marketplace
  // Suppliers and the product catalogue. Without these the concierge form can only
  // send free text, every quote line lands unlinked, and price dispersion reports
  // 100% unlinked forever — the catalogue would be decorative.
  listSuppliers: (includeInactive = false) =>
    request(`/internal/suppliers${includeInactive ? "?include_inactive=true" : ""}`, {
      headers: operatorHeaders(),
    }),
  createSupplier: (data) =>
    request("/internal/suppliers", {
      method: "POST",
      headers: operatorHeaders(),
      body: JSON.stringify(data),
    }),
  listInputProducts: () =>
    request("/internal/input-products", { headers: operatorHeaders() }),
  createInputProduct: (data) =>
    request("/internal/input-products", {
      method: "POST",
      headers: operatorHeaders(),
      body: JSON.stringify(data),
    }),
  // Grower-facing: what suppliers quoted, and whether anyone was actually contacted.
  getPriceDispersion: (planId) =>
    request(`/input-plans/${planId}/price-dispersion`),
  getRfqTransport: () => request("/rfq-transport"),
  listRfqTransmissions: (planId) =>
    request(`/input-plans/${planId}/transmissions`),
  transmitRfq: (planId, data) =>
    request(`/input-plans/${planId}/transmit-rfq`, {
      method: "POST",
      body: JSON.stringify(data),
    }),

  // Concierge entry points (internal operator tooling, /internal page only)
  createSupplierQuote: (planId, data) =>
    request(`/internal/input-plans/${planId}/quotes`, {
      method: "POST",
      headers: operatorHeaders(),
      body: JSON.stringify(data),
    }),
  withdrawSupplierQuote: (quoteId) =>
    request(`/internal/supplier-quotes/${quoteId}/withdraw`, {
      method: "POST",
      headers: operatorHeaders(),
    }),
  createFinancingOffer: (quoteId, data) =>
    request(`/internal/supplier-quotes/${quoteId}/financing-offers`, {
      method: "POST",
      headers: operatorHeaders(),
      body: JSON.stringify(data),
    }),
  addOrderEvent: (orderId, data) =>
    request(`/internal/orders/${orderId}/events`, {
      method: "POST",
      headers: operatorHeaders(),
      body: JSON.stringify(data),
    }),

  // ---------------------------------------------------------- Botrytis pilot
  // Blocks — the comparison unit. Never inferred from the legacy `field_block` text.
  listBlocks: (farmId) => request(`/farms/${farmId}/blocks`),
  createBlock: (farmId, data) =>
    request(`/farms/${farmId}/blocks`, { method: "POST", body: JSON.stringify(data) }),

  // Observations. Append-only: a correction posts a new row with `supersedes_id`.
  listWeatherObservations: (farmId, blockId) =>
    request(`/farms/${farmId}/weather-observations${qs({ block_id: blockId })}`),
  createWeatherObservation: (farmId, data) =>
    request(`/farms/${farmId}/weather-observations`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  listScoutingSamples: (farmId, blockId) =>
    request(`/farms/${farmId}/scouting-samples${qs({ block_id: blockId })}`),
  createScoutingSample: (farmId, data) =>
    request(`/farms/${farmId}/scouting-samples`, {
      method: "POST",
      body: JSON.stringify(data),
    }),

  // Risk snapshot — freezes what was knowable. Immutable once written.
  createRiskSnapshot: (plannedId, data = {}) =>
    request(`/planned-sprays/${plannedId}/risk-snapshot`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  listRiskSnapshots: (plannedId) =>
    request(`/planned-sprays/${plannedId}/risk-snapshots`),

  // PCA disposition — ALWAYS requires a credential; there is no anonymous path.
  createPcaDisposition: (plannedId, data) =>
    request(`/planned-sprays/${plannedId}/pca-disposition`, {
      method: "POST",
      body: JSON.stringify(data),
      headers: pcaHeaders(),
    }),
  listPcaDispositions: (plannedId) =>
    request(`/planned-sprays/${plannedId}/pca-dispositions`),

  // Protocol, arms, and block-level outcomes.
  listPilotProtocols: (farmId) => request(`/farms/${farmId}/pilot-protocols`),
  createPilotProtocol: (farmId, data) =>
    request(`/farms/${farmId}/pilot-protocols`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  listBlockAssignments: (protocolId) =>
    request(`/pilot-protocols/${protocolId}/assignments`),
  createBlockAssignment: (protocolId, data) =>
    request(`/pilot-protocols/${protocolId}/assignments`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  listBlockOutcomes: (farmId, blockId) =>
    request(`/farms/${farmId}/block-outcomes${qs({ block_id: blockId })}`),
  createBlockOutcome: (farmId, data) =>
    request(`/farms/${farmId}/block-outcomes`, {
      method: "POST",
      body: JSON.stringify(data),
    }),


  // USDA PDP measured-residue reference. Grower/PCA-facing and deliberately not
  // farm-scoped — PDP measures commodities nationally, so no farm id belongs here.
  residueReference: (crop, activeIngredient) =>
    request(
      `/residue-reference?crop=${encodeURIComponent(crop)}` +
        `&active_ingredient=${encodeURIComponent(activeIngredient)}`
    ),
  residueReferenceCoverage: () =>
    request("/internal/residue-reference-coverage", { headers: operatorHeaders() }),

  // CSV export URLs (used as direct download links)
  exportUrl: (path) => `${BASE_URL}${path}`,
};

// Exposed so components can build absolute download links.
export const API_BASE_URL = BASE_URL;
