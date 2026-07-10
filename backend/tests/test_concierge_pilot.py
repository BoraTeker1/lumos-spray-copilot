"""Tests for Concierge Pilot Mode: manual pilot-import and the one-page case study."""
from datetime import date, timedelta

TODAY = date.today()


def _make_us_farm(client, name="Concierge Strawberry Ranch"):
    return client.post(
        "/farms",
        json={
            "name": name,
            "location": "Watsonville, California",
            "country": "US",
            "crop_type": "strawberry",
            "expected_harvest_date": (TODAY + timedelta(days=2)).isoformat(),
        },
    ).json()["id"]


def _import_payload():
    return {
        "source_label": "Call with PCA Maria, 2026-06-20",
        "data_source": "grower_interview",
        "data_confidence": "user_provided",
        "imported_by": "founder",
        "notes": "Transcribed from a 20-min call; costs are rough.",
        "spray_events": [
            {"product_name": "Captan 80 WDG", "active_ingredient": "captan",
             "application_date": (TODAY - timedelta(days=1)).isoformat(), "cost": 120,
             "pre_harvest_interval_days": 4, "re_entry_interval_hours": 24},
            {"product_name": "Captan 80 WDG", "active_ingredient": "captan",
             "application_date": (TODAY - timedelta(days=10)).isoformat(), "cost": 120,
             "pre_harvest_interval_days": 4, "re_entry_interval_hours": 24},
            {"product_name": "Captan 80 WDG", "active_ingredient": "captan",
             "application_date": (TODAY - timedelta(days=20)).isoformat(), "cost": 120,
             "pre_harvest_interval_days": 4, "re_entry_interval_hours": 24},
        ],
        "scouting_observations": [
            {"observation_date": (TODAY - timedelta(days=2)).isoformat(),
             "visible_issue": "gray mold on fruit", "severity_1_to_5": 4},
        ],
    }


# --------------------------------------------------------------- Pilot import
def test_valid_pilot_import(client):
    fid = _make_us_farm(client)
    resp = client.post(f"/internal/farms/{fid}/pilot-import", json=_import_payload())
    assert resp.status_code == 201
    body = resp.json()
    assert body["imported_spray_events"] == 3
    assert body["imported_scouting_observations"] == 1
    assert body["data_source"] == "grower_interview"
    assert body["data_confidence"] == "user_provided"

    # Records are persisted and tagged with provenance.
    sprays = client.get(f"/farms/{fid}/spray-events").json()
    assert len(sprays) == 3
    assert all(s["data_source"] == "grower_interview" for s in sprays)
    assert all(s["data_confidence"] == "user_provided" for s in sprays)


def test_pilot_import_invalid_farm_returns_404(client):
    assert client.post("/internal/farms/9999/pilot-import", json=_import_payload()).status_code == 404


def test_pilot_import_rejects_bad_enum_value(client):
    fid = _make_us_farm(client)
    bad = {**_import_payload(), "data_confidence": "totally_made_up"}
    assert client.post(f"/internal/farms/{fid}/pilot-import", json=bad).status_code == 422


def test_imported_records_affect_pilot_evidence_metrics(client):
    fid = _make_us_farm(client)
    before = client.get(f"/farms/{fid}/pilot-evidence").json()
    assert before["total_spray_events"] == 0

    client.post(f"/internal/farms/{fid}/pilot-import", json=_import_payload())
    after = client.get(f"/farms/{fid}/pilot-evidence").json()
    assert after["total_spray_events"] == 3
    assert after["total_scouting_observations"] == 1
    assert after["resistance_or_repeated_active_ingredient_flags_count"] == 1
    assert after["phi_rei_risk_flags_count"] == 2
    assert after["estimated_avoidable_cost_usd"] == 120.0  # 360 / 3 sprays


# ------------------------------------------------------------- Case study
def test_case_study_includes_required_sections(client):
    fid = _make_us_farm(client)
    client.post(f"/internal/farms/{fid}/pilot-import", json=_import_payload())
    cs = client.get(f"/farms/{fid}/pilot-case-study").json()

    required = {
        "farm_name", "crop", "location", "pilot_data_source",
        "spray_events_analyzed", "scouting_observations_analyzed",
        "scouting_backed_sprays", "sprays_without_recent_scouting",
        "phi_rei_flags", "resistance_flags", "weather_risk_flags",
        "pca_review_status_summary", "estimated_avoidable_cost_usd",
        "what_lumos_helped_surface", "what_is_still_unknown",
        "quote_placeholder", "disclaimer",
    }
    assert required.issubset(cs.keys())
    assert cs["farm_name"] == "Concierge Strawberry Ranch"
    assert cs["spray_events_analyzed"] == 3
    assert cs["pilot_data_source"] == ["grower_interview"]
    assert len(cs["what_lumos_helped_surface"]) >= 1


def test_case_study_includes_limitations_and_disclaimer(client):
    fid = _make_us_farm(client)
    client.post(f"/internal/farms/{fid}/pilot-import", json=_import_payload())
    cs = client.get(f"/farms/{fid}/pilot-case-study").json()
    assert len(cs["what_is_still_unknown"]) >= 1
    assert any("baseline" in u.lower() for u in cs["what_is_still_unknown"])
    disc = cs["disclaimer"].lower()
    assert "not a guarantee" in disc
    assert "decision support" in disc


def test_case_study_has_no_autonomous_prescription_language(client):
    fid = _make_us_farm(client)
    client.post(f"/internal/farms/{fid}/pilot-import", json=_import_payload())
    cs = client.get(f"/farms/{fid}/pilot-case-study").json()
    blob = " ".join(
        cs["what_lumos_helped_surface"]
        + cs["what_is_still_unknown"]
        + [cs["quote_placeholder"], cs["disclaimer"]]
    ).lower()
    assert "must spray" not in blob
    assert "you must" not in blob
    assert "guaranteed" not in blob


def test_case_study_nonexistent_farm_returns_404(client):
    assert client.get("/farms/9999/pilot-case-study").status_code == 404


# ------------------------------------------------ Import batch (audit trail)
def test_pilot_import_creates_persisted_batch(client):
    fid = _make_us_farm(client)
    resp = client.post(f"/internal/farms/{fid}/pilot-import", json=_import_payload()).json()
    assert resp["batch_id"]
    assert resp["imported_at"]
    assert resp["imported_spray_events"] == 3
    assert resp["imported_scouting_observations"] == 1


def test_imported_records_link_to_the_batch(client):
    fid = _make_us_farm(client)
    batch_id = client.post(f"/internal/farms/{fid}/pilot-import", json=_import_payload()).json()["batch_id"]
    sprays = client.get(f"/farms/{fid}/spray-events").json()
    obs = client.get(f"/farms/{fid}/scout-observations").json()
    assert sprays and all(s["pilot_import_batch_id"] == batch_id for s in sprays)
    assert obs and all(o["pilot_import_batch_id"] == batch_id for o in obs)


def test_case_study_includes_latest_import_metadata(client):
    fid = _make_us_farm(client)
    # Two batches from different sources; the second is the "latest".
    client.post(f"/internal/farms/{fid}/pilot-import", json=_import_payload())
    second = {
        **_import_payload(),
        "source_label": "WhatsApp from grower, 2026-06-21",
        "data_source": "whatsapp",
        "imported_by": "founder-2",
        "notes": "Follow-up thread.",
        "scouting_observations": [],
    }
    client.post(f"/internal/farms/{fid}/pilot-import", json=second)

    cs = client.get(f"/farms/{fid}/pilot-case-study").json()
    assert cs["pilot_import_batches_count"] == 2
    assert cs["latest_import_source_label"] == "WhatsApp from grower, 2026-06-21"
    assert cs["latest_imported_by"] == "founder-2"
    assert cs["latest_import_notes"] == "Follow-up thread."
    assert cs["latest_imported_at"]
    assert set(cs["pilot_data_source"]) == {"grower_interview", "whatsapp"}


def test_audit_packet_includes_pilot_import_batches_section(client):
    fid = _make_us_farm(client)
    client.post(f"/internal/farms/{fid}/pilot-import", json=_import_payload())
    packet = client.get(f"/farms/{fid}/audit-packet").json()
    assert "pilot_import_batches" in packet
    assert len(packet["pilot_import_batches"]) == 1
    batch = packet["pilot_import_batches"][0]
    assert batch["source_label"] == "Call with PCA Maria, 2026-06-20"
    assert batch["spray_event_count"] == 3
    assert batch["scouting_observation_count"] == 1
    assert batch["imported_at"]


def test_import_batch_metadata_has_no_autonomous_prescription_language(client):
    fid = _make_us_farm(client)
    client.post(f"/internal/farms/{fid}/pilot-import", json=_import_payload())
    cs = client.get(f"/farms/{fid}/pilot-case-study").json()
    disc = cs["disclaimer"].lower()
    assert "must spray" not in disc
    assert "you must" not in disc
