"""AI calibration report: insufficient-data gating, predicted-vs-realized join."""
from datetime import date
from types import SimpleNamespace

import pytest

from app.pilot_evidence import CALIBRATION_MIN_N, build_ai_calibration


def _judgment(kind="risk_note", planned_spray_id=None, level="high", abstained=False,
              is_mock=True):
    return SimpleNamespace(
        kind=kind, planned_spray_id=planned_spray_id,
        output={"rescue_risk": level} if kind == "risk_note" else {},
        abstained=abstained, is_mock=is_mock,
    )


def _decision(pid, demo=False):
    return SimpleNamespace(
        id=pid, outcome="delayed", intended_date=date(2026, 7, 1),
        spray_event_id=None,
        data_source="demo" if demo else "manual_entry",
        data_confidence="simulated" if demo else "user_provided",
    )


def _rescue_event(pid):
    return SimpleNamespace(
        event_type="rescue_application", observed_at=date(2026, 7, 5), id=1,
        severity=None, cost=260.0, rescue_required=True,
        rejected_or_downgraded=None, yield_impact=None, quality_impact=None,
    )


def test_empty_report_is_honest():
    report = build_ai_calibration([], {}, {})
    assert report["risk_notes_total"] == 0
    assert report["abstention_rate_pct"] is None
    for level in ("low", "medium", "high"):
        block = report["predictions_by_level"][level]
        assert block["predictions"] == 0
        assert block["realized_rescue_rate_pct"] is None
        assert "insufficient data" in block["note"]


def test_counts_join_predictions_to_realized_rescues():
    decisions = {1: _decision(1), 2: _decision(2)}
    follow_ups = {1: [_rescue_event(1)], 2: []}
    judgments = [
        _judgment(planned_spray_id=1, level="high"),   # follow-up: rescue happened
        _judgment(planned_spray_id=2, level="high"),   # no follow-up yet
        _judgment(planned_spray_id=1, level="low", abstained=True),  # abstention
        _judgment(kind="extraction"),
    ]
    report = build_ai_calibration(judgments, decisions, follow_ups)
    high = report["predictions_by_level"]["high"]
    assert high["predictions"] == 2
    assert high["with_follow_up"] == 1
    assert high["realized_rescues"] == 1
    assert high["realized_rescue_rate_pct"] is None  # below the n gate
    assert report["risk_notes_abstained"] == 1
    assert report["extraction_judgments"] == 1
    assert report["mock_judgments"] == 4


def test_rate_appears_only_at_min_n():
    n = CALIBRATION_MIN_N
    decisions = {i: _decision(i) for i in range(1, n + 1)}
    follow_ups = {i: [_rescue_event(i)] if i <= 3 else [
        SimpleNamespace(event_type="scouting_observation", observed_at=date(2026, 7, 5),
                        id=i, severity=2, cost=None, rescue_required=False,
                        rejected_or_downgraded=None, yield_impact=None,
                        quality_impact=None)
    ] for i in range(1, n + 1)}
    judgments = [_judgment(planned_spray_id=i, level="medium") for i in range(1, n + 1)]
    report = build_ai_calibration(judgments, decisions, follow_ups)
    medium = report["predictions_by_level"]["medium"]
    assert medium["with_follow_up"] == n
    assert medium["realized_rescue_rate_pct"] == round(100.0 * 3 / n, 1)
    assert medium["note"] is None


def test_demo_parents_are_excluded():
    decisions = {1: _decision(1, demo=True)}
    judgments = [_judgment(planned_spray_id=1, level="high")]
    report = build_ai_calibration(judgments, decisions, {1: [_rescue_event(1)]})
    assert report["risk_notes_total"] == 0


def test_endpoint_smoke(client):
    report = client.get("/internal/ai-calibration").json()
    assert report["risk_notes_total"] == 0
    assert report["calibration_min_n"] == CALIBRATION_MIN_N
    assert any("append-only" in n for n in report["notes"])
