"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

const RISK_STYLES = {
  low: "border-green-200 bg-green-50",
  moderate: "border-amber-200 bg-amber-50",
  elevated: "border-red-200 bg-red-50",
};

// Lightweight weather-based disease-pressure card for the farm location.
export default function WeatherCard({ farmId }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api
      .getWeatherRisk(farmId)
      .then(setData)
      .catch((err) => setError(err.message));
  }, [farmId]);

  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (!data) return <p className="text-sm text-gray-500">Loading weather…</p>;

  const boxCls = RISK_STYLES[data.risk_level] || "border-gray-200 bg-gray-50";

  return (
    <div>
      <h2 className="mb-3 font-semibold">🌦️ Weather risk</h2>
      <div className={`rounded-lg border p-4 ${boxCls}`}>
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium capitalize">
            Disease pressure: {data.risk_level}
          </span>
          <span className="text-xs text-gray-500">{data.location}</span>
        </div>
        <div className="mt-2 flex gap-4 text-sm text-gray-700">
          <span>🌡️ {data.temperature_c}°C</span>
          <span>💧 {data.humidity_pct}% RH</span>
          <span>🌧️ {data.rain_probability_pct}% rain</span>
        </div>
        <p className="mt-2 text-sm text-gray-700">{data.summary}</p>
      </div>
      <p className="mt-2 text-xs text-gray-500">
        Demo weather data. A live weather API can be added behind the same WeatherService.
      </p>
    </div>
  );
}
