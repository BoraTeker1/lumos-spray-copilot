"""Unit tests for the rule-based recommendation engine.

The engine reads plain objects via duck typing, so we use lightweight stand-ins
(SimpleNamespace) instead of the SQLAlchemy models. Tests inject a fixed `today`
for determinism.
"""
from datetime import date, timedelta
from types import SimpleNamespace

from app.recommendation_engine import (
    RISK_ELEVATED,
    RISK_LOW,
    RISK_MODERATE,
    generate_recommendation,
)

TODAY = date(2026, 6, 21)


def farm(harvest_offset_days=None):
    harvest = TODAY + timedelta(days=harvest_offset_days) if harvest_offset_days is not None else None
    return SimpleNamespace(expected_harvest_date=harvest)


def spray(ai="mancozeb", days_ago=1, phi=None, product="Test Product"):
    return SimpleNamespace(
        active_ingredient=ai,
        application_date=TODAY - timedelta(days=days_ago),
        pre_harvest_interval_days=phi,
        product_name=product,
    )


def obs(severity, days_ago=1, issue="leaf spots"):
    return SimpleNamespace(
        observation_date=TODAY - timedelta(days=days_ago),
        severity_1_to_5=severity,
        visible_issue=issue,
    )


# --------------------------------------------------------------------- Rule 1
def test_repeated_active_ingredient_is_flagged():
    sprays = [spray(days_ago=2), spray(days_ago=10), spray(days_ago=20)]
    result = generate_recommendation(farm(), sprays, [], today=TODAY)
    assert any("mancozeb" in f.lower() for f in result.flags)
    assert result.risk_level in (RISK_MODERATE, RISK_ELEVATED)


def test_two_uses_of_ingredient_not_flagged_as_overuse():
    sprays = [spray(days_ago=2), spray(days_ago=10)]
    result = generate_recommendation(farm(), sprays, [], today=TODAY)
    assert not any("appears" in f and "times" in f for f in result.flags)


def test_old_sprays_outside_window_not_counted():
    sprays = [spray(days_ago=40), spray(days_ago=50), spray(days_ago=60)]
    result = generate_recommendation(farm(), sprays, [], today=TODAY)
    assert not any("times in the last" in f for f in result.flags)


# --------------------------------------------------------------------- Rule 2
def test_pre_harvest_interval_risk_is_flagged():
    # PHI 7 days, applied 2 days ago -> clears in 5 days; harvest in 3 days -> risk.
    sprays = [spray(days_ago=2, phi=7, product="Mancozeb 80WP")]
    result = generate_recommendation(farm(harvest_offset_days=3), sprays, [], today=TODAY)
    assert any("pre-harvest interval risk" in f.lower() for f in result.flags)
    assert result.risk_level == RISK_ELEVATED


def test_no_phi_risk_when_harvest_is_far_away():
    sprays = [spray(days_ago=2, phi=7)]
    result = generate_recommendation(farm(harvest_offset_days=60), sprays, [], today=TODAY)
    assert not any("pre-harvest interval risk" in f.lower() for f in result.flags)


def test_no_phi_risk_without_harvest_date():
    sprays = [spray(days_ago=1, phi=14)]
    result = generate_recommendation(farm(harvest_offset_days=None), sprays, [], today=TODAY)
    assert not any("pre-harvest interval risk" in f.lower() for f in result.flags)


# --------------------------------------------------------------------- Rule 3
def test_high_severity_observation_is_flagged():
    result = generate_recommendation(farm(), [], [obs(severity=5)], today=TODAY)
    assert any("high-severity" in f.lower() for f in result.flags)
    assert result.risk_level in (RISK_MODERATE, RISK_ELEVATED)


def test_low_severity_observation_not_flagged_as_high():
    result = generate_recommendation(farm(), [], [obs(severity=2)], today=TODAY)
    assert not any("high-severity" in f.lower() for f in result.flags)


# --------------------------------------------------------------------- Rule 4
def test_weak_evidence_suggests_inspect_first():
    result = generate_recommendation(farm(), [], [obs(severity=2)], today=TODAY)
    assert any("inspect" in f.lower() for f in result.flags)
    assert result.risk_level == RISK_LOW


def test_no_records_suggests_scouting_first():
    result = generate_recommendation(farm(), [], [], today=TODAY)
    assert any("scout" in f.lower() for f in result.flags)
    assert result.risk_level == RISK_LOW


# --------------------------------------------------------------- Safety language
def test_never_uses_must_spray_language():
    sprays = [spray(days_ago=2, phi=7), spray(days_ago=10), spray(days_ago=20)]
    result = generate_recommendation(farm(harvest_offset_days=3), sprays, [obs(5)], today=TODAY)
    text = result.recommendation_text.lower()
    assert "must spray" not in text
    assert "you must" not in text
    # Cautious, agronomist-in-the-loop framing is present.
    assert "agronomist" in text


def test_result_text_is_populated_and_risk_levels_are_valid():
    result = generate_recommendation(farm(), [], [], today=TODAY)
    assert result.recommendation_text
    assert result.risk_level in (RISK_LOW, RISK_MODERATE, RISK_ELEVATED)
