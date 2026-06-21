"""Tests for the farmer-facing next-action derivation."""
from datetime import date, timedelta
from types import SimpleNamespace

from app.recommendation_engine import (
    ACTION_CONTINUE_MONITORING,
    ACTION_HARVEST_TIMING,
    ACTION_INSPECT_FIRST,
    ACTION_REVIEW_AGRONOMIST,
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


def test_phi_risk_yields_harvest_timing_action():
    sprays = [spray(days_ago=2, phi=7)]
    result = generate_recommendation(farm(harvest_offset_days=3), sprays, [], today=TODAY)
    assert result.next_action == ACTION_HARVEST_TIMING


def test_high_severity_yields_review_with_agronomist():
    result = generate_recommendation(farm(), [], [obs(severity=5)], today=TODAY)
    assert result.next_action == ACTION_REVIEW_AGRONOMIST


def test_overuse_yields_review_with_agronomist():
    sprays = [spray(days_ago=2), spray(days_ago=10), spray(days_ago=20)]
    result = generate_recommendation(farm(), sprays, [], today=TODAY)
    assert result.next_action == ACTION_REVIEW_AGRONOMIST


def test_recent_low_severity_yields_continue_monitoring():
    result = generate_recommendation(farm(), [], [obs(severity=2)], today=TODAY)
    assert result.next_action == ACTION_CONTINUE_MONITORING


def test_no_records_yields_inspect_first():
    result = generate_recommendation(farm(), [], [], today=TODAY)
    assert result.next_action == ACTION_INSPECT_FIRST


def test_harvest_timing_takes_priority_over_other_concerns():
    # PHI risk + high severity at once -> safety (harvest) action wins.
    sprays = [spray(days_ago=2, phi=7)]
    result = generate_recommendation(
        farm(harvest_offset_days=3), sprays, [obs(severity=5)], today=TODAY
    )
    assert result.next_action == ACTION_HARVEST_TIMING


def test_next_action_appears_in_recommendation_text():
    result = generate_recommendation(farm(), [], [], today=TODAY)
    assert result.next_action in result.recommendation_text
