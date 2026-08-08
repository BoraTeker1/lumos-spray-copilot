"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { RISK_LEVEL_TONES, tone } from "@/lib/tones";
import { FormError } from "@/components/ui/field";

const RISK_VARIANTS = Object.fromEntries(
  Object.entries(RISK_LEVEL_TONES).map(([k, t]) => [k, tone(t).badge])
);

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

  if (error) return <FormError size="sm">{error}</FormError>;
  if (!data) return <p className="text-xs text-muted">Loading weather…</p>;

  return (
    <div className="text-xs text-muted">
      <div className="flex items-center justify-between gap-2">
        <span>Disease pressure</span>
        <Badge variant={RISK_VARIANTS[data.risk_level] || "neutral"}>{data.risk_level}</Badge>
      </div>
      <div className="mt-1.5 text-muted">
        {data.temperature_c}°C · {data.humidity_pct}% RH · {data.rain_probability_pct}% rain
      </div>
      <div className="mt-1.5 rounded bg-canvas px-2 py-1 text-[11px] text-muted">
        Simulated demo weather — not a live feed.
      </div>
    </div>
  );
}
