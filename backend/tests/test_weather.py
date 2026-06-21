"""Tests for the weather-risk disease-pressure logic and mock service."""
from app.weather import (
    MockWeatherService,
    RISK_ELEVATED,
    RISK_LOW,
    RISK_MODERATE,
    compute_disease_pressure,
)


def test_warm_and_humid_is_elevated_fungal_risk():
    result = compute_disease_pressure(temperature_c=28, humidity_pct=85, rain_probability_pct=20)
    assert result["risk_level"] == RISK_ELEVATED
    assert "fungal" in result["summary"].lower()


def test_mild_dry_conditions_are_low_risk():
    result = compute_disease_pressure(temperature_c=18, humidity_pct=50, rain_probability_pct=5)
    assert result["risk_level"] == RISK_LOW


def test_rain_spike_advises_inspecting_leaves():
    result = compute_disease_pressure(temperature_c=18, humidity_pct=55, rain_probability_pct=70)
    assert any("inspect leaves" in a.lower() for a in result["advisories"])
    assert result["risk_level"] in (RISK_MODERATE, RISK_ELEVATED)


def test_humidity_spike_advises_inspecting_leaves():
    result = compute_disease_pressure(temperature_c=19, humidity_pct=88, rain_probability_pct=10)
    assert any("inspect leaves" in a.lower() for a in result["advisories"])


def test_never_tells_farmer_to_spray():
    result = compute_disease_pressure(temperature_c=28, humidity_pct=90, rain_probability_pct=80)
    assert "must spray" not in result["summary"].lower()


def test_mock_service_antalya_is_elevated():
    svc = MockWeatherService()
    result = svc.get_weather_risk("Antalya, Türkiye")
    assert result["risk_level"] == RISK_ELEVATED
    assert result["temperature_c"] == 28.0


def test_mock_service_mersin_is_lower_risk():
    svc = MockWeatherService()
    result = svc.get_weather_risk("Mersin, Türkiye")
    assert result["risk_level"] in (RISK_LOW, RISK_MODERATE)


def test_mock_service_unknown_location_uses_default():
    svc = MockWeatherService()
    result = svc.get_weather_risk("Nowhere")
    assert "temperature_c" in result and "risk_level" in result
