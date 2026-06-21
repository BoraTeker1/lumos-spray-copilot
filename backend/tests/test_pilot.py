"""Tests for pilot feedback capture, pilot-farm intake, and CSV export."""


# ----------------------------------------------------------- Pilot feedback
def test_create_and_list_pilot_feedback(client):
    payload = {
        "person_type": "PCA",
        "crop": "strawberry",
        "region": "Watsonville, CA",
        "current_records_method": "spreadsheet",
        "biggest_pain": "REI",
        "would_use_real_data": "yes",
        "would_pay": "maybe",
        "requested_pilot": True,
        "notes": "Wants REI alerts for crews.",
    }
    resp = client.post("/pilot-feedback", json=payload)
    assert resp.status_code == 201
    created = resp.json()
    assert created["id"] and created["person_type"] == "PCA"
    assert created["requested_pilot"] is True

    listing = client.get("/pilot-feedback").json()
    assert len(listing) == 1
    assert listing[0]["biggest_pain"] == "REI"


def test_pilot_feedback_requires_person_type(client):
    resp = client.post("/pilot-feedback", json={"crop": "tomato"})
    assert resp.status_code == 422


def test_minimal_pilot_feedback_is_accepted(client):
    resp = client.post("/pilot-feedback", json={"person_type": "grower"})
    assert resp.status_code == 201


# ------------------------------------------------------------- Pilot intake
def test_pilot_farm_intake_creates_farm_sprays_and_scouting(client):
    payload = {
        "name": "Test Pilot Ranch",
        "location": "Salinas, California",
        "country": "US",
        "crop_type": "strawberry",
        "greenhouse_area": 25,
        "expected_harvest_date": "2026-07-01",
        "advisor_involved": True,
        "spray_events": [
            {"product_name": "Captan 80 WDG", "active_ingredient": "captan",
             "application_date": "2026-06-20", "cost": 120,
             "pre_harvest_interval_days": 4, "re_entry_interval_hours": 24},
            {"product_name": "Brigade WSB", "active_ingredient": "bifenthrin",
             "application_date": "2026-06-15", "cost": 180},
        ],
        "scouting_concern": "gray mold on fruit",
        "scouting_severity_1_to_5": 4,
    }
    resp = client.post("/pilot/farms", json=payload)
    assert resp.status_code == 201
    farm = resp.json()
    assert farm["advisor_involved"] is True
    fid = farm["id"]

    sprays = client.get(f"/farms/{fid}/spray-events").json()
    assert len(sprays) == 2
    obs = client.get(f"/farms/{fid}/scout-observations").json()
    assert len(obs) == 1 and obs[0]["severity_1_to_5"] == 4


def test_pilot_farm_intake_without_extras(client):
    resp = client.post("/pilot/farms", json={"name": "Bare Farm", "country": "US"})
    assert resp.status_code == 201
    fid = resp.json()["id"]
    assert client.get(f"/farms/{fid}/spray-events").json() == []


# ------------------------------------------------------------------ Exports
def _make_farm_with_spray(client):
    fid = client.post("/farms", json={"name": "Export Farm", "country": "US"}).json()["id"]
    client.post(f"/farms/{fid}/spray-events", json={
        "product_name": "Captan 80 WDG", "active_ingredient": "captan",
        "application_date": "2026-06-20", "cost": 120,
        "pre_harvest_interval_days": 4, "re_entry_interval_hours": 24,
    })
    return fid


def test_export_spray_events_csv(client):
    fid = _make_farm_with_spray(client)
    resp = client.get(f"/farms/{fid}/export/spray-events.csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]
    body = resp.text
    assert "re_entry_interval_hours" in body.splitlines()[0]  # header
    assert "Captan 80 WDG" in body


def test_export_recommendations_csv(client):
    fid = _make_farm_with_spray(client)
    client.post(f"/farms/{fid}/recommendations")
    resp = client.get(f"/farms/{fid}/export/recommendations.csv")
    assert resp.status_code == 200
    assert "risk_level" in resp.text.splitlines()[0]
    assert "next_action" in resp.text.splitlines()[0]


def test_export_pilot_feedback_csv(client):
    client.post("/pilot-feedback", json={"person_type": "exporter", "biggest_pain": "audits"})
    resp = client.get("/export/pilot-feedback.csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "person_type" in resp.text.splitlines()[0]
    assert "exporter" in resp.text
