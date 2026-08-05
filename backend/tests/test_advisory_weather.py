"""Tests for the SIMULATED advisory weather module and its isolation from the pilot.

Two things are guarded here. First, the advisory's own arithmetic (it must stay cautious
and must never say "spray"). Second — and this is the reason for the rename — that no
module on the real pilot path can reach it. `low|moderate|elevated` from a hand-tuned
heuristic over three constants must never be mistaken for `low|moderate|high|abstain`
from a cited disease rule over admissible measured inputs.
"""
import ast
from pathlib import Path

from app.advisory_weather import (
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


# --------------------------------------------------------------------------- #
# The boundary.                                                               #
# --------------------------------------------------------------------------- #

APP = Path(__file__).resolve().parents[1] / "app"

# Everything that participates in producing or consuming a real disease-risk
# assessment. A simulated advisory reaching any of these would put a hand-tuned
# constant where the pilot's evidence chain is supposed to be.
PILOT_PATH_MODULES = (
    "crud.py", "disease_risk.py", "risk_snapshot.py", "pit.py",
)
PILOT_PATH_PACKAGES = ("ingest", "features")


def _imported_modules(path: Path) -> set[str]:
    """Every module name this file imports, from the AST rather than by regex.

    Parsing means a mention inside a docstring or a comment does not count — only a
    real import does. The docstrings in this repo discuss the boundary constantly.
    """
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module)
            names.update(f"{node.module}.{a.name}" for a in node.names if node.module)
    return names


def _pilot_path_files():
    for name in PILOT_PATH_MODULES:
        yield APP / name
    for package in PILOT_PATH_PACKAGES:
        directory = APP / package
        if directory.is_dir():
            yield from sorted(directory.glob("*.py"))


def test_advisory_weather_is_unreachable_from_the_pilot_path():
    """No module that feeds a disease-risk assessment may import the advisory.

    The pilot path is `ingest -> WeatherObservation -> risk_snapshot -> disease_risk`.
    This module is a simulated advisory with a different, incomparable band vocabulary.
    Wiring the two together would be invisible in review and would silently make a
    demo number look like measured evidence — so it is a test, not a convention.
    """
    for path in _pilot_path_files():
        imports = _imported_modules(path)
        offending = {
            name for name in imports
            if name == "app.advisory_weather"
            or name.startswith("app.advisory_weather.")
            or name.endswith(".advisory_weather")
        }
        assert not offending, (
            f"{path.name} imports the SIMULATED advisory weather module ({offending}). "
            f"Real weather reaches a decision through the ingest pipeline, where the "
            f"point-in-time rule, station distance and quality flags apply."
        )


def test_the_advisory_module_never_reads_a_weather_observation():
    """It has no path to the real observation table, and must not grow one."""
    source = (APP / "advisory_weather.py").read_text()
    code = "\n".join(
        line for line in source.splitlines() if not line.strip().startswith("#")
    )
    # Strip the module docstring, which discusses WeatherObservation deliberately.
    body = ast.parse(source).body
    docstring_end = body[0].end_lineno if isinstance(body[0], ast.Expr) else 0
    code = "\n".join(code.splitlines()[docstring_end:])
    for forbidden in ("WeatherObservation", "models", "sqlalchemy", "crud"):
        assert forbidden not in code, (
            f"advisory_weather.py references {forbidden!r} outside its docstring — "
            f"it is a simulated advisory and must stay disconnected from real data"
        )
