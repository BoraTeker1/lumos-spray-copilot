"""Lightweight weather-risk module for spray decisions.

Design
------
* `compute_disease_pressure(...)` is the pure, testable core: it maps temperature /
  humidity / rain-probability to a cautious disease-pressure assessment for greenhouse
  tomatoes (fungal disease loves warm + humid; rain/humidity spikes mean "inspect leaves
  before spraying").
* `WeatherService` is a small abstraction so a real API (e.g. Open-Meteo) can be dropped
  in later. For the MVP we ship `MockWeatherService` with demo readings for the seed farm
  locations (Antalya, Mersin), so the demo works offline and instantly.

Nothing here tells a farmer to spray. It raises cautious flags only.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

# Thresholds (kept obvious and adjustable).
WARM_TEMP_C = 20          # at/above this is "warm" for fungal pressure
HIGH_HUMIDITY_PCT = 80    # at/above this is "high" humidity
HUMIDITY_SPIKE_PCT = 85   # at/above this, inspect leaves before spraying
HIGH_RAIN_PCT = 60        # at/above this rain probability, inspect leaves before spraying

RISK_LOW = "low"
RISK_MODERATE = "moderate"
RISK_ELEVATED = "elevated"


def compute_disease_pressure(
    temperature_c: float, humidity_pct: float, rain_probability_pct: float
) -> dict:
    """Return a cautious disease-pressure assessment from current conditions."""
    factors: list[str] = []
    advisories: list[str] = []
    risk = RISK_LOW

    warm = temperature_c >= WARM_TEMP_C
    humid = humidity_pct >= HIGH_HUMIDITY_PCT

    # Warm + humid -> elevated fungal disease risk (e.g. late/early blight, botrytis).
    if warm and humid:
        risk = RISK_ELEVATED
        factors.append(
            f"Warm ({temperature_c:.0f}°C) and humid ({humidity_pct:.0f}%) conditions favour "
            f"fungal disease — risk appears elevated."
        )
        advisories.append("Consider scouting leaves closely and reviewing options with your agronomist.")
    elif humid or warm:
        risk = RISK_MODERATE
        factors.append(
            f"Conditions are {'humid' if humid else 'warm'} "
            f"({humidity_pct:.0f}% RH, {temperature_c:.0f}°C) — keep an eye on disease pressure."
        )

    # Rain / humidity spike -> inspect leaves before any spray.
    if rain_probability_pct >= HIGH_RAIN_PCT or humidity_pct >= HUMIDITY_SPIKE_PCT:
        if risk == RISK_LOW:
            risk = RISK_MODERATE
        advisories.append(
            f"Rain/humidity spike (rain {rain_probability_pct:.0f}%, RH {humidity_pct:.0f}%) — "
            f"inspect leaves before spraying; spray may wash off or splash disease."
        )

    if not factors:
        factors.append("Conditions are not currently favourable for rapid disease spread.")

    summary = " ".join(factors + advisories)
    return {
        "risk_level": risk,
        "summary": summary,
        "factors": factors,
        "advisories": advisories,
    }


class WeatherService(ABC):
    """Abstraction so a real weather API can replace the mock later."""

    @abstractmethod
    def get_reading(self, location: str | None) -> dict:
        """Return raw conditions: temperature_c, humidity_pct, rain_probability_pct."""

    def get_weather_risk(self, location: str | None) -> dict:
        """Combine a reading with the disease-pressure assessment."""
        reading = self.get_reading(location)
        assessment = compute_disease_pressure(
            reading["temperature_c"],
            reading["humidity_pct"],
            reading["rain_probability_pct"],
        )
        return {"location": location, **reading, **assessment}


class MockWeatherService(WeatherService):
    """Deterministic demo readings keyed by the seed-farm locations."""

    # Antalya is hot & humid (elevated fungal pressure); Mersin is milder.
    _BY_CITY = {
        "antalya": {"temperature_c": 28.0, "humidity_pct": 85.0, "rain_probability_pct": 30.0},
        "mersin": {"temperature_c": 24.0, "humidity_pct": 60.0, "rain_probability_pct": 10.0},
    }
    _DEFAULT = {"temperature_c": 22.0, "humidity_pct": 65.0, "rain_probability_pct": 20.0}

    def get_reading(self, location: str | None) -> dict:
        loc = (location or "").lower()
        for city, reading in self._BY_CITY.items():
            if city in loc:
                return dict(reading)
        return dict(self._DEFAULT)


# Default service used by the API. Swap for a real implementation later.
default_weather_service: WeatherService = MockWeatherService()
