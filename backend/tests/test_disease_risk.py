"""Versioned risk rules: abstention, structural limits, and shadow-mode enforcement.

The load-bearing tests here are the ones asserting what the code CANNOT do — express a
pesticide recommendation, run a rule on thin evidence, or leak a shadow assessment into
a PCA-facing payload. Those are guarantees; the rest are behaviour.
"""
from dataclasses import fields
from datetime import datetime, timedelta

import pytest

from app import disease_risk

AS_OF = datetime(2026, 7, 20, 6, 0)


def _weather(hours_before, **overrides):
    row = {
        "observed_at": (AS_OF - timedelta(hours=hours_before)).isoformat(),
        "station_id": "CIMIS-111",
        "station_distance_km": 3.0,
        "temperature_c": 17.0,
        "relative_humidity_pct": 88.0,
        "rainfall_mm": 0.0,
        "leaf_wetness_minutes": 240,
        "wetness_is_measured": True,
        "source_type": "authoritative_provider",
    }
    row.update(overrides)
    return row


def _sample(days_before=1, **overrides):
    row = {
        "observed_at": (AS_OF - timedelta(days=days_before)).isoformat(),
        "method": "quadrat",
        "target": "botrytis_fruit_rot",
        "units_inspected": 100,
        "units_affected": 3,
        "incidence_pct": 3.0,
        "severity_index": 2.0,
        "severity_scale": "0-5",
        "source_type": "user_entered",
    }
    row.update(overrides)
    return row


def _payload(**overrides):
    """A payload with NO data-quality problems, so a single defect can be isolated."""
    payload = {
        "snapshot_version": "risk-snapshot-v1",
        "as_of": AS_OF.isoformat(),
        "horizon_hours": 72,
        "lookback_hours": 168,
        "target": "botrytis_fruit_rot",
        "block": {"block_id": 1, "crop": "strawberry", "area": 4.0, "area_unit": "acres"},
        # Continuous hourly-ish coverage, no gap wider than MAX_GAP_HOURS.
        "weather": [_weather(h) for h in range(24, -1, -2)],
        "scouting_samples": [_sample()],
    }
    payload.update(overrides)
    return payload


# ----------------------------------------------------------- structural guarantees
def test_assessment_cannot_express_a_pesticide_recommendation():
    """Not "must not emit" — has no field to emit it in. The stronger guarantee."""
    names = {f.name for f in fields(disease_risk.RiskAssessment)}
    forbidden = {
        "product", "product_name", "active_ingredient", "rate", "rate_amount",
        "rate_unit", "tank_mix", "action", "recommended_action", "recommendation",
        "next_action", "spray", "should_spray", "dose", "application",
    }
    assert names.isdisjoint(forbidden), f"recommendation-shaped field: {names & forbidden}"

    # And the serialized payload cannot smuggle one in either.
    payload = disease_risk.assess(_payload()).as_payload()
    assert set(payload).isdisjoint(forbidden)


def test_no_band_means_safe():
    """Lumos never declares a deferral safe. There is no vocabulary for it."""
    assert "safe" not in disease_risk.RISK_BANDS
    assert set(disease_risk.RISK_BANDS) == {"low", "moderate", "high", "abstain"}


def test_every_assessment_records_model_version_and_input_digest():
    result = disease_risk.assess(_payload(), input_digest="abc123")
    assert result.model_version == "botrytis_wetness_v1"
    assert result.model_family == "botrytis_wetness"
    assert result.input_digest == "abc123"
    assert result.as_payload()["assessment_version"] == disease_risk.ASSESSMENT_VERSION


def test_calibration_and_local_validation_are_honest_by_construction():
    result = disease_risk.assess(_payload())
    assert result.calibration_status == "not_calibrated"
    assert "NOT validated for California Central Coast" in result.local_validation_status


# --------------------------------------------------------------- the missing table
def test_botrytis_v1_abstains_because_thresholds_were_never_supplied():
    """The registered rule is complete plumbing with no numbers, and says so.

    Deliberately asserts the ABSENCE of coefficients. No test in this file asserts a
    numeric threshold, because a recalled or invented cut point would pass such a test
    and then be trusted by a PCA.
    """
    model = disease_risk.RISK_MODELS["botrytis_wetness_v1"]
    assert model.is_ready() is False
    assert model.thresholds is None
    assert model.citation is None
    # The source's own scope is absent too, and is required before the rule can run.
    assert model.source_crop is None
    assert model.source_region is None
    assert model.source_validation_conditions is None

    result = disease_risk.assess(_payload())
    assert result.abstained is True
    assert result.risk_band == "abstain"
    assert disease_risk.ABSTAIN_THRESHOLDS_NOT_SUPPLIED in result.missing_or_unreliable_inputs
    assert result.probability_or_index is None
    assert result.calculation == {}


def test_an_unready_model_can_never_be_evaluated():
    """Even directly, the rule refuses to produce a number it has no basis for."""
    model = disease_risk.RISK_MODELS["botrytis_wetness_v1"]
    with pytest.raises(NotImplementedError):
        model.evaluate(_payload())


def _transcribed_model():
    """A structurally complete transcription. The `thresholds` value is a placeholder,
    NOT a threshold: these tests assert that provenance is required and deliberately
    assert nothing whatsoever about any coefficient."""

    class _Transcribed(disease_risk.BotrytisWetnessV1):
        thresholds = {"placeholder": True}
        citation = "Author (Year), Publication"
        source_crop = "strawberry"
        source_region = "the source's stated region"
        source_validation_conditions = "the source's stated validation conditions"

    return _Transcribed


@pytest.mark.parametrize(
    "missing",
    ["thresholds", "citation", "source_crop", "source_region",
     "source_validation_conditions"],
)
def test_a_threshold_table_without_its_full_provenance_is_not_ready(missing):
    """Coefficients alone must never make the rule live.

    A transcriber who pastes the table and forgets the citation would otherwise ship an
    uncited rule inside a cited, versioned module a PCA is entitled to trust — and no
    test of the arithmetic could catch it, because such tests check the arithmetic
    *against* the constants rather than the constants themselves.
    """
    model = _transcribed_model()
    setattr(model, missing, None)
    assert model().is_ready() is False


@pytest.mark.parametrize("blank", ["", "   "])
def test_whitespace_is_not_a_citation(blank):
    model = _transcribed_model()
    model.citation = blank
    assert model().is_ready() is False


def test_the_gate_opens_only_with_the_table_and_all_of_its_provenance():
    assert _transcribed_model()().is_ready() is True


def test_unknown_model_version_abstains():
    result = disease_risk.assess(_payload(), model_version="nonexistent_v9")
    assert result.abstained is True
    assert result.abstain_reason == disease_risk.ABSTAIN_UNKNOWN_MODEL


# ------------------------------------------------------------ abstention conditions
@pytest.mark.parametrize(
    "mutate, expected",
    [
        # Scope
        (lambda p: p.update(target="powdery_mildew"), disease_risk.ABSTAIN_OUT_OF_SCOPE),
        (lambda p: p["block"].update(crop="lettuce"), disease_risk.ABSTAIN_OUT_OF_SCOPE),
        # Weather availability and quality
        (lambda p: p.update(weather=[]), disease_risk.ABSTAIN_NO_WEATHER),
        (
            lambda p: p.update(weather=[_weather(2, station_distance_km=90.0)]),
            disease_risk.ABSTAIN_NO_NEARBY_STATION,
        ),
        (
            lambda p: p.update(weather=[_weather(h, leaf_wetness_minutes=None)
                                        for h in range(24, -1, -2)]),
            disease_risk.ABSTAIN_NO_LEAF_WETNESS,
        ),
        (
            lambda p: p.update(weather=[_weather(48), _weather(2)]),
            disease_risk.ABSTAIN_WEATHER_GAP,
        ),
        (
            lambda p: p.update(weather=[_weather(2), _weather(2, station_id="B",
                                                             temperature_c=30.0)]),
            disease_risk.ABSTAIN_CONFLICTING_READINGS,
        ),
        (
            lambda p: p.update(weather=[_weather(2, source_type="demo")]),
            disease_risk.ABSTAIN_DEMO_INPUT,
        ),
        (
            lambda p: p["weather"].append(_weather(-5)),  # observed AFTER as_of
            disease_risk.ABSTAIN_HINDSIGHT_LEAK,
        ),
        # Scouting
        (lambda p: p.update(scouting_samples=[]), disease_risk.ABSTAIN_NO_SCOUTING),
        (
            lambda p: p.update(scouting_samples=[_sample(days_before=40)]),
            disease_risk.ABSTAIN_SCOUTING_STALE,
        ),
        (
            lambda p: p.update(scouting_samples=[_sample(source_type="demo")]),
            disease_risk.ABSTAIN_DEMO_INPUT,
        ),
    ],
)
def test_each_abstention_condition_abstains_with_its_own_reason(mutate, expected):
    payload = _payload()
    mutate(payload)
    reasons = disease_risk.abstention_reasons(payload)
    assert expected in reasons, f"expected {expected}, got {reasons}"

    result = disease_risk.assess(payload)
    assert result.abstained is True
    assert expected in result.missing_or_unreliable_inputs


def test_empty_payload_abstains_rather_than_assuming():
    assert disease_risk.abstention_reasons({}) == [disease_risk.ABSTAIN_NO_SNAPSHOT]
    assert disease_risk.assess({}).abstained is True


def test_all_abstention_reasons_are_reported_not_just_the_first():
    """The full evidence gap is the useful artifact for a pilot, not the first defect."""
    payload = _payload(weather=[], scouting_samples=[], target="powdery_mildew")
    reasons = disease_risk.assess(payload).missing_or_unreliable_inputs
    assert disease_risk.ABSTAIN_OUT_OF_SCOPE in reasons
    assert disease_risk.ABSTAIN_NO_WEATHER in reasons
    assert disease_risk.ABSTAIN_NO_SCOUTING in reasons
    # ...and the model's own unreadiness, on top of the data gaps.
    assert disease_risk.ABSTAIN_THRESHOLDS_NOT_SUPPLIED in reasons


def test_reasons_are_deduplicated_but_order_is_stable():
    payload = _payload(
        weather=[_weather(2, source_type="demo")],
        scouting_samples=[_sample(source_type="demo")],
    )
    reasons = disease_risk.abstention_reasons(payload)
    assert reasons.count(disease_risk.ABSTAIN_DEMO_INPUT) == 1
    assert reasons == disease_risk.abstention_reasons(payload)


def test_a_clean_payload_has_no_data_quality_objection():
    """Isolates the missing thresholds as the ONLY thing standing in the way.

    If this ever fails, a data-quality gate has become over-strict and would silently
    suppress every real assessment once the table lands.
    """
    reasons = disease_risk.abstention_reasons(_payload())
    assert reasons == [], f"clean payload objected: {reasons}"


# ----------------------------------------------------------------- evidence grading
def test_evidence_grade_reflects_inputs_not_confidence():
    measured_close = _payload()
    assert disease_risk.evidence_grade(measured_close) == "A"

    derived = _payload(weather=[_weather(h, wetness_is_measured=False)
                                for h in range(24, -1, -2)])
    assert disease_risk.evidence_grade(derived) == "B"

    far_and_derived = _payload(weather=[
        _weather(h, wetness_is_measured=False, station_distance_km=12.0)
        for h in range(24, -1, -2)
    ])
    assert disease_risk.evidence_grade(far_and_derived) == "C"
