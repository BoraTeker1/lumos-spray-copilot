"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";

const RISK_VARIANTS = { low: "neutral", moderate: "amber", elevated: "red" };

// Compact, provenance-labelled weather info for the right rail. Demo data —
// deliberately not presented as a major compliance signal.
export default function WeatherCard({ farmId }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api
      .getWeatherRisk(farmId)
      .then(setData)
      .catch((err) => setError(err.message));
  }, [farmId]);

  if (error) return <p className="text-xs text-red-600">{error}</p>;
  if (!data) return <p className="text-xs text-gray-500">Loading weather…</p>;

  return (
    <div className="text-xs text-gray-600">
      <div className="flex items-center justify-between gap-2">
        <span>Disease pressure</span>
        <Badge variant={RISK_VARIANTS[data.risk_level] || "neutral"}>{data.risk_level}</Badge>
      </div>
      <div className="mt-1.5 text-gray-500">
        {data.temperature_c}°C · {data.humidity_pct}% RH · {data.rain_probability_pct}% rain
      </div>
      <div className="mt-1.5 rounded bg-gray-50 px-2 py-1 text-[11px] text-gray-500">
        Simulated demo weather — not a live feed.
      </div>
    </div>
  );
}
