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
  getFarm: (id) => request(`/farms/${id}`),
  createFarm: (data) =>
    request("/farms", { method: "POST", body: JSON.stringify(data) }),

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

  // Concierge pilot mode
  importPilotData: (farmId, data) =>
    request(`/farms/${farmId}/pilot-import`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  getPilotCaseStudy: (farmId) => request(`/farms/${farmId}/pilot-case-study`),

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
