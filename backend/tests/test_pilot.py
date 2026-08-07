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


# --------------------------------------------- Intake captures the baseline
# Reduction is unmeasurable without a baseline, and until intake asked for one no
# real farm in this system had ever had one — so `compute_reduction` had never
# returned a number for anybody. These three tests pin the cold-start path.
def test_intake_without_a_baseline_still_creates_the_farm(client):
    """A baseline is optional: a farm without one is valid, it just cannot measure."""
    resp = client.post("/pilot/farms", json={"name": "No Baseline Ranch"})
    assert resp.status_code == 201
    fid = resp.json()["id"]

    assert client.get(f"/farms/{fid}/spray-baseline").json() is None
    reduction = client.get(f"/farms/{fid}/reduction").json()
    assert reduction["baseline_expected_sprays"] is None
    assert reduction["reduction_pct"] is None


def test_intake_captures_the_spray_baseline(client):
    resp = client.post("/pilot/farms", json={
        "name": "Baseline Ranch",
        "spray_baseline": {
            "method": "stated_cadence",
            "cadence_days": 7,
            "declared_by": "Grower, at intake",
        },
    })
    assert resp.status_code == 201
    fid = resp.json()["id"]

    baseline = client.get(f"/farms/{fid}/spray-baseline").json()
    assert baseline["method"] == "stated_cadence"
    assert baseline["cadence_days"] == 7
    assert baseline["declared_by"] == "Grower, at intake"


def test_an_intake_baseline_carries_real_provenance_not_demo(client):
    """The load-bearing assertion.

    `SprayBaseline` is one of the models `ensure_demo_real_separation` reads to decide
    whether a farm is a demo farm, so a baseline defaulting to "demo"/"simulated"
    would silently mistag a real pilot farm — the same class of bug §8 records for
    the spray/scouting create schemas. It would also fail reduction's
    `_TRUSTED_CONFIDENCE` gate, making the figure permanently "illustrative".
    """
    resp = client.post("/pilot/farms", json={
        "name": "Provenance Ranch",
        "spray_baseline": {"method": "stated_cadence", "cadence_days": 10},
    })
    baseline = client.get(f"/farms/{resp.json()['id']}/spray-baseline").json()

    assert baseline["data_source"] == "grower_interview"
    assert baseline["data_confidence"] == "user_provided"

    from app import reduction
    assert baseline["data_confidence"] in reduction._TRUSTED_CONFIDENCE


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
