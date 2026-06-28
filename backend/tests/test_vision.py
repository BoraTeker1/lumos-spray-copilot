"""Tests for the photo-analysis (vision) module — pure helpers + endpoint wiring.

No network/API key: the default service falls back to MockVisionService, so these run offline.
"""
from datetime import date

import pytest

from app.vision import (
    MockVisionService,
    build_analysis_result,
    build_observation_suggestion,
)

TODAY = date(2026, 6, 28)


@pytest.fixture(autouse=True)
def _force_mock_vision(monkeypatch):
    """Keep the endpoint hermetic even if a real ANTHROPIC_API_KEY is in the environment."""
    import app.main as main

    monkeypatch.setattr(main, "default_vision_service", MockVisionService())


# --------------------------------------------------------- pure: suggestion mapping
def test_build_observation_suggestion_maps_fields():
    finding = {
        "detected_issue": "Botrytis-like gray mold",
        "suggested_severity": 4,
        "confidence": "medium",
        "observations": ["Gray fuzzy growth on fruit."],
        "model": "claude-opus-4-8",
    }
    sug = build_observation_suggestion(finding, today=TODAY)
    assert sug["observation_date"] == "2026-06-28"
    assert sug["visible_issue"] == "Botrytis-like gray mold"
    assert sug["severity_1_to_5"] == 4
    assert sug["data_source"] == "photo_ai"
    assert "AI photo analysis" in sug["notes"]
    assert "confirm with a pca" in sug["notes"].lower()


def test_suggestion_clamps_severity_and_normalises_confidence():
    sug = build_observation_suggestion(
        {"detected_issue": "x", "suggested_severity": 9, "confidence": "definitely"},
        today=TODAY,
    )
    assert sug["severity_1_to_5"] == 5  # clamped into 1..5
    # bad confidence -> low (shown via the analysis-result wrapper)
    res = build_analysis_result({"confidence": "definitely"}, today=TODAY)
    assert res["confidence"] == "low"


def test_build_analysis_result_always_has_disclaimer_and_caveat():
    res = build_analysis_result({"detected_issue": "spots", "caveats": []}, today=TODAY)
    assert res["is_ai_generated"] is True
    assert res["disclaimer"]
    assert any("misread" in c for c in res["caveats"])  # standing caveat injected
    assert res["suggested_observation"]["visible_issue"] == "spots"


def test_null_issue_passes_through_as_none():
    res = build_analysis_result({"detected_issue": "  ", "suggested_severity": None}, today=TODAY)
    assert res["detected_issue"] is None
    assert res["suggested_severity"] is None


# --------------------------------------------------------- mock service + default
def test_mock_service_is_deterministic_and_flagged():
    svc = MockVisionService()
    a = svc.analyze(b"abc", "image/jpeg", crop_type="strawberry")
    b = svc.analyze(b"different-bytes", "image/jpeg", crop_type="strawberry")
    assert a == b  # deterministic, ignores pixels
    assert a["is_mock"] is True
    assert a["confidence"] == "low"


def test_default_service_is_mock_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from app.vision import _build_default_service

    assert isinstance(_build_default_service(), MockVisionService)


# --------------------------------------------------------------- endpoint wiring
_PNG_1x1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _make_farm(client):
    return client.post(
        "/farms",
        json={"name": "Photo Ranch", "country": "US", "crop_type": "strawberry"},
    ).json()["id"]


def test_photo_analysis_endpoint_returns_suggestion(client):
    fid = _make_farm(client)
    res = client.post(
        f"/farms/{fid}/photo-analysis",
        files={"file": ("leaf.png", _PNG_1x1, "image/png")},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["is_ai_generated"] is True
    assert body["is_mock"] is True  # no API key in tests -> mock
    assert body["disclaimer"]
    assert body["suggested_observation"]["data_source"] == "photo_ai"


def test_photo_analysis_rejects_non_image(client):
    fid = _make_farm(client)
    res = client.post(
        f"/farms/{fid}/photo-analysis",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert res.status_code == 400


def test_photo_analysis_404_for_missing_farm(client):
    res = client.post(
        "/farms/99999/photo-analysis",
        files={"file": ("leaf.png", _PNG_1x1, "image/png")},
    )
    assert res.status_code == 404


def test_suggested_observation_can_be_saved_as_scouting_note(client):
    fid = _make_farm(client)
    res = client.post(
        f"/farms/{fid}/photo-analysis",
        files={"file": ("leaf.png", _PNG_1x1, "image/png")},
    ).json()
    # The grower/PCA confirms it: the suggestion is valid input to the scouting endpoint.
    created = client.post(f"/farms/{fid}/scout-observations", json=res["suggested_observation"])
    assert created.status_code == 201
    assert created.json()["data_source"] == "photo_ai"
