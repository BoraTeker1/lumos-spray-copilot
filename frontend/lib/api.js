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

  // Analytics & weather
  getAnalytics: (farmId) => request(`/farms/${farmId}/analytics`),
  getWeatherRisk: (farmId) => request(`/farms/${farmId}/weather-risk`),

  // Weekly report
  weeklyReport: (farmId) => request(`/farms/${farmId}/weekly-report`),
};
