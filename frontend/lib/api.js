// Single place for all backend calls. Keeps components free of fetch boilerplate
// and makes it easy to add auth headers later.
const BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function request(path, options = {}) {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
    ...options,
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`API ${res.status}: ${detail || res.statusText}`);
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
      const detail = await res.text().catch(() => "");
      throw new Error(`API ${res.status}: ${detail || res.statusText}`);
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
  getAiCalibration: () => request("/internal/ai-calibration"),

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
      const detail = await res.text().catch(() => "");
      throw new Error(`API ${res.status}: ${detail || res.statusText}`);
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
  resetDemo: () => request("/internal/demo/reset", { method: "POST" }),

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
      body: JSON.stringify(data),
    }),
  getPilotCaseStudy: (farmId) => request(`/farms/${farmId}/pilot-case-study`),

  // Pilot instrumentation (fire-and-forget; failures must never break the UI)
  trackEvent: (data) => {
    request("/pilot-events", { method: "POST", body: JSON.stringify(data) }).catch(() => {});
  },
  getInstrumentation: () => request("/internal/instrumentation"),

  // Pilot feedback & intake
  listPilotFeedback: () => request("/pilot-feedback"),
  createPilotFeedback: (data) =>
    request("/pilot-feedback", { method: "POST", body: JSON.stringify(data) }),
  createPilotFarm: (data) =>
    request("/pilot/farms", { method: "POST", body: JSON.stringify(data) }),

  // CSV export URLs (used as direct download links)
  exportUrl: (path) => `${BASE_URL}${path}`,
};

// Exposed so components can build absolute download links.
export const API_BASE_URL = BASE_URL;
