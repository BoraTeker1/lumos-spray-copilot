"""Tests for the Pilot Evidence summary and the Audit Packet export endpoints."""
from datetime import date, timedelta

TODAY = date.today()


def _us_strawberry_farm(client):
    """Recreate the Golden Coast seed scenario via the API (captan x3 + bifenthrin + scouting)."""
    fid = client.post(
        "/farms",
        json={
            "name": "Evidence Strawberry Ranch",
            "location": "Watsonville, California",
            "country": "US",
            "crop_type": "strawberry",
            "greenhouse_area": 18,
            "expected_harvest_date": (TODAY + timedelta(days=2)).isoformat(),
        },
    ).json()["id"]

    base = {
        "product_name": "Captan 80 WDG",
        "active_ingredient": "captan",
        "pre_harvest_interval_days": 4,
        "re_entry_interval_hours": 24,
        "cost": 120,
    }
    for d in (1, 10, 20):
        client.post(
            f"/farms/{fid}/spray-events",
            json={**base, "application_date": (TODAY - timedelta(days=d)).isoformat()},
        )
    client.post(
        f"/farms/{fid}/spray-events",
        json={
            "product_name": "Brigade WSB",
            "active_ingredient": "bifenthrin",
            "application_date": (TODAY - timedelta(days=6)).isoformat(),
            "cost": 180,
            "pre_harvest_interval_days": 3,
            "re_entry_interval_hours": 12,
        },
    )
    # One recent high-severity scouting note (within 30 days of every spray above).
    client.post(
        f"/farms/{fid}/scout-observations",
        json={
            "observation_date": (TODAY - timedelta(days=2)).isoformat(),
            "visible_issue": "gray mold on fruit",
            "severity_1_to_5": 4,
        },
    )
    return fid


# --------------------------------------------------------------- Pilot evidence
def test_pilot_evidence_returns_required_keys(client):
    fid = _us_strawberry_farm(client)
    ev = client.get(f"/farms/{fid}/pilot-evidence").json()
    required = {
        "farm_id", "farm_name", "crop", "location",
        "pilot_period_start", "pilot_period_end",
        "total_spray_events", "total_scouting_observations", "total_recommendations",
        "total_agronomist_reviews",
        "sprays_with_recent_scouting_count", "sprays_without_recent_scouting_count",
        "phi_rei_risk_flags_count", "resistance_or_repeated_active_ingredient_flags_count",
        "weather_risk_flags_count",
        "pca_pending_count", "pca_approved_count", "pca_changes_requested_count",
        "estimated_avoidable_cost_usd",
        "evidence_summary", "investor_summary", "limitations",
    }
    assert required.issubset(ev.keys())


def test_pilot_evidence_metrics_are_deterministic(client):
    fid = _us_strawberry_farm(client)
    ev = client.get(f"/farms/{fid}/pilot-evidence").json()

    assert ev["farm_name"] == "Evidence Strawberry Ranch"
    assert ev["crop"] == "strawberry"
    assert ev["total_spray_events"] == 4
    assert ev["total_scouting_observations"] == 1
    assert ev["total_recommendations"] == 0
    assert ev["total_agronomist_reviews"] == 0
    # "Scouting-backed" = a scouting note within 30 days *before* the spray. The single note
    # (day-2) precedes only the day-1 spray; the day-6/10/20 sprays were scouting-light.
    assert ev["sprays_with_recent_scouting_count"] == 1
    assert ev["sprays_without_recent_scouting_count"] == 3
    # PHI + REI both fire on the day-1 captan spray -> 2 flags.
    assert ev["phi_rei_risk_flags_count"] == 2
    assert ev["resistance_or_repeated_active_ingredient_flags_count"] == 1
    # Avoidable cost = average spray cost (540 / 4 = 135) for this U.S. farm.
    assert ev["estimated_avoidable_cost_usd"] == 135.0
    # Inferred pilot window spans the oldest spray to the most recent.
    assert ev["pilot_period_start"] == (TODAY - timedelta(days=20)).isoformat()
    assert ev["pilot_period_end"] == (TODAY - timedelta(days=1)).isoformat()


def test_pilot_evidence_review_counts_track_status(client):
    fid = _us_strawberry_farm(client)
    rec = client.post(f"/farms/{fid}/recommendations").json()
    client.patch(f"/recommendations/{rec['id']}", json={"agronomist_status": "approved"})
    ev = client.get(f"/farms/{fid}/pilot-evidence").json()
    assert ev["total_recommendations"] == 1
    assert ev["total_agronomist_reviews"] == 1
    assert ev["pca_approved_count"] == 1
    assert ev["pca_pending_count"] == 0


def test_pilot_evidence_summaries_are_nonempty_and_limited(client):
    fid = _us_strawberry_farm(client)
    ev = client.get(f"/farms/{fid}/pilot-evidence").json()
    assert 3 <= len(ev["evidence_summary"]) <= 6
    assert 2 <= len(ev["investor_summary"]) <= 4
    assert len(ev["limitations"]) >= 1
    # Honest framing: limitations must state we are not proving reduction.
    assert any("not prove" in lim.lower() or "does not prove" in lim.lower()
               for lim in ev["limitations"])


def test_pilot_evidence_has_no_autonomous_prescription_language(client):
    fid = _us_strawberry_farm(client)
    ev = client.get(f"/farms/{fid}/pilot-evidence").json()
    blob = " ".join(
        ev["evidence_summary"] + ev["investor_summary"] + ev["limitations"]
    ).lower()
    assert "must spray" not in blob
    assert "you must" not in blob
    assert "guaranteed" not in blob


def test_pilot_evidence_nonexistent_farm_returns_404(client):
    assert client.get("/farms/9999/pilot-evidence").status_code == 404


def test_pilot_evidence_empty_farm_is_safe(client):
    fid = client.post("/farms", json={"name": "Empty Farm", "country": "US"}).json()["id"]
    ev = client.get(f"/farms/{fid}/pilot-evidence").json()
    assert ev["total_spray_events"] == 0
    assert ev["pilot_period_start"] is None
    assert ev["estimated_avoidable_cost_usd"] is None


# ---------------------------------------------------------------- Audit packet
def test_audit_packet_includes_required_sections(client):
    fid = _us_strawberry_farm(client)
    rec = client.post(f"/farms/{fid}/recommendations").json()
    client.patch(
        f"/recommendations/{rec['id']}",
        json={"agronomist_status": "approved", "agronomist_comment": "Hold harvest 2 days."},
    )
    packet = client.get(f"/farms/{fid}/audit-packet").json()

    for section in (
        "generated_at", "farm_profile", "spray_events", "scout_observations",
        "recommendations", "compliance_flags", "resistance_flags", "review_status",
        "weekly_report_text", "disclaimer",
    ):
        assert section in packet, f"missing section: {section}"

    assert packet["farm_profile"]["name"] == "Evidence Strawberry Ranch"
    assert len(packet["spray_events"]) == 4
    assert len(packet["scout_observations"]) == 1
    assert packet["compliance_flags"]["phi_risk"] is True
    assert packet["compliance_flags"]["rei_risk"] is True
    assert packet["resistance_flags"]["repeated_active_ingredient_risk"] is True
    assert packet["review_status"]["latest_status"] == "approved"
    assert "label" in packet["disclaimer"].lower()


def test_audit_packet_has_no_autonomous_prescription_language(client):
    fid = _us_strawberry_farm(client)
    client.post(f"/farms/{fid}/recommendations")
    packet = client.get(f"/farms/{fid}/audit-packet").json()
    text = (packet["weekly_report_text"] + " " + packet["disclaimer"]).lower()
    for rec in packet["recommendations"]:
        text += " " + (rec["recommendation_text"] or "").lower()
    assert "must spray" not in text
    assert "you must spray" not in text


def test_audit_packet_nonexistent_farm_returns_404(client):
    assert client.get("/farms/9999/audit-packet").status_code == 404
