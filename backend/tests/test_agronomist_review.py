"""API tests for the agronomist review workflow and report gating.

Uses the shared `client` fixture from conftest.py (throwaway DB, reset per test).
"""


def _make_farm(client):
    resp = client.post(
        "/farms",
        json={
            "name": "Test Greenhouse",
            "location": "Antalya, Türkiye",
            "expected_harvest_date": "2026-06-24",
        },
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def test_generate_recommendation_starts_pending_with_next_action(client):
    farm_id = _make_farm(client)
    rec = client.post(f"/farms/{farm_id}/recommendations").json()
    assert rec["agronomist_status"] == "pending"
    assert rec["next_action"]  # non-empty


def test_approve_updates_status(client):
    farm_id = _make_farm(client)
    rec = client.post(f"/farms/{farm_id}/recommendations").json()
    updated = client.patch(
        f"/recommendations/{rec['id']}",
        json={"agronomist_status": "approved", "agronomist_comment": "Looks fine."},
    ).json()
    assert updated["agronomist_status"] == "approved"
    assert updated["agronomist_comment"] == "Looks fine."


def test_edit_updates_text_and_status(client):
    farm_id = _make_farm(client)
    rec = client.post(f"/farms/{farm_id}/recommendations").json()
    updated = client.patch(
        f"/recommendations/{rec['id']}",
        json={"agronomist_status": "edited", "recommendation_text": "Edited guidance."},
    ).json()
    assert updated["agronomist_status"] == "edited"
    assert updated["recommendation_text"] == "Edited guidance."


def test_pending_recommendation_is_not_shown_as_reviewed_guidance(client):
    farm_id = _make_farm(client)
    client.post(f"/farms/{farm_id}/recommendations")
    report = client.get(f"/farms/{farm_id}/weekly-report").json()["text"]
    assert "awaiting" in report.lower() and "review" in report.lower()
    assert "reviewed guidance" not in report.lower()


def test_approved_recommendation_appears_as_reviewed_guidance(client):
    farm_id = _make_farm(client)
    rec = client.post(f"/farms/{farm_id}/recommendations").json()
    client.patch(
        f"/recommendations/{rec['id']}",
        json={"agronomist_status": "approved", "agronomist_comment": "Confirmed."},
    )
    report = client.get(f"/farms/{farm_id}/weekly-report").json()["text"]
    assert "agronomist-reviewed guidance" in report.lower()
    assert "confirmed." in report.lower()


def test_report_includes_weather_and_disclaimer(client):
    farm_id = _make_farm(client)
    report = client.get(f"/farms/{farm_id}/weekly-report").json()["text"]
    assert "weather risk" in report.lower()
    assert "decision support only" in report.lower()


def test_analytics_and_weather_endpoints_respond(client):
    farm_id = _make_farm(client)
    analytics = client.get(f"/farms/{farm_id}/analytics").json()
    assert "total_spend" in analytics and "potential_avoidable_cost" in analytics
    weather = client.get(f"/farms/{farm_id}/weather-risk").json()
    assert weather["risk_level"] == "elevated"  # Antalya mock
