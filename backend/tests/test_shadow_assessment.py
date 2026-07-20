"""Shadow enforcement: the PCA must not be able to see a risk assessment.

The pilot's whole design depends on this. A PCA who has seen a risk band can no longer
provide an unbiased baseline to score the rule against, so "blinded" has to mean the
field is ABSENT from their payload — not that the UI declines to draw it. These tests
assert on serialized JSON keys for exactly that reason: a frontend that never renders
the field is not a guarantee, it is a habit.
"""
from datetime import date, datetime, timedelta

import pytest

NOW = datetime(2026, 7, 19, 6, 0, 0)


def _farm(client, name="Shadow Farm"):
    res = client.post("/farms", json={
        "name": name, "country": "US", "crop_type": "strawberry", "area_unit": "acres",
        "expected_harvest_date": (date.today() + timedelta(days=30)).isoformat(),
    })
    assert res.status_code == 201
    return res.json()


def _block(client, farm_id):
    res = client.post(f"/farms/{farm_id}/blocks", json={
        "name": "North 1", "crop": "strawberry",
    })
    assert res.status_code == 201
    return res.json()


def _planned(client, farm_id, block_id):
    res = client.post(f"/farms/{farm_id}/planned-sprays", json={
        "intended_date": (date.today() + timedelta(days=2)).isoformat(),
        "product_name": "Switch 62.5 WG",
        "active_ingredient": "cyprodinil + fludioxonil",
        "target_pest_or_disease": "botrytis_fruit_rot",
        "block_id": block_id,
        "pre_harvest_interval_days": 0,
        "re_entry_interval_hours": 12,
    })
    assert res.status_code == 201, res.text
    return res.json()


def _chain(client):
    """farm -> block -> planned spray -> snapshot. The minimum an assessment needs."""
    farm = _farm(client)
    block = _block(client, farm["id"])
    planned = _planned(client, farm["id"], block["id"])
    snap = client.post(f"/planned-sprays/{planned['id']}/risk-snapshot", json={
        "horizon_hours": 72,
    })
    assert snap.status_code == 201, snap.text
    return farm, block, planned, snap.json()


# ------------------------------------------------------------------- shadow absence
def test_shadow_assessment_is_absent_from_the_pca_facing_payload(client):
    farm, _block_, planned, _snap = _chain(client)
    created = client.post(f"/planned-sprays/{planned['id']}/risk-assessment", json={})
    assert created.status_code == 201, created.text
    assert created.json()["is_shadow"] is True

    # The decision as the PCA reads it carries NO risk information of any kind.
    detail = client.get(f"/planned-sprays/{planned['id']}")
    assert detail.status_code == 200
    body = detail.json()
    for key in (
        "risk_band", "assessment", "disease_risk", "risk_assessment", "probability",
        "evidence_grade", "abstained", "model_version",
    ):
        assert key not in body, f"shadow assessment leaked into PCA payload via {key!r}"

    # Nor does the farm's decision list.
    listed = client.get(f"/farms/{farm['id']}/planned-sprays").json()
    assert all("risk_band" not in row for row in listed)


def test_operator_route_is_the_only_place_shadow_rows_are_readable(client):
    _farm_, _block_, planned, _snap = _chain(client)
    client.post(f"/planned-sprays/{planned['id']}/risk-assessment", json={})

    shadow = client.get("/internal/pilot/assessments")
    assert shadow.status_code == 200
    rows = shadow.json()
    assert len(rows) == 1
    assert rows[0]["is_shadow"] is True
    assert rows[0]["risk_band"] == "abstain"


def test_assessments_default_to_shadow(client):
    """Defaulting the other way would let a wiring mistake silently unblind the pilot."""
    from app import crud
    from app.database import SessionLocal

    _farm_, _block_, planned, _snap = _chain(client)
    client.post(f"/planned-sprays/{planned['id']}/risk-assessment", json={})

    db = SessionLocal()
    try:
        # No PilotProtocol exists, so nothing can be unblinded yet.
        rows = crud.list_shadow_assessments(db)
        assert all(r.is_shadow for r in rows)
        assert crud.farm_is_unblinded(db, rows[0].farm_id) is False
    finally:
        db.close()


# ------------------------------------------------------- anchoring and append-only
def test_an_assessment_requires_a_snapshot(client):
    """Unanchored, an assessment is an opinion with a timestamp, not evidence."""
    farm = _farm(client, "No Snapshot Farm")
    block = _block(client, farm["id"])
    planned = _planned(client, farm["id"], block["id"])

    res = client.post(f"/planned-sprays/{planned['id']}/risk-assessment", json={})
    assert res.status_code == 422
    assert "snapshot" in res.text.lower()


def test_assessment_is_anchored_to_the_snapshot_digest(client):
    _farm_, _block_, planned, snap = _chain(client)
    created = client.post(
        f"/planned-sprays/{planned['id']}/risk-assessment", json={}
    ).json()
    assert created["input_digest"] == snap["input_digest"]
    assert created["snapshot_id"] == snap["id"]


def test_reassessing_appends_rather_than_overwriting(client):
    _farm_, _block_, planned, _snap = _chain(client)
    first = client.post(f"/planned-sprays/{planned['id']}/risk-assessment", json={}).json()
    second = client.post(f"/planned-sprays/{planned['id']}/risk-assessment", json={}).json()

    assert first["id"] != second["id"]
    rows = client.get("/internal/pilot/assessments").json()
    assert len(rows) == 2

    # There is no update and no delete path for an assessment.
    assert client.patch(
        f"/planned-sprays/{planned['id']}/risk-assessment", json={}
    ).status_code in (404, 405)
    assert client.delete(
        f"/planned-sprays/{planned['id']}/risk-assessment"
    ).status_code in (404, 405)


def test_assessment_appends_an_audit_event(client):
    _farm_, _block_, planned, _snap = _chain(client)
    client.post(f"/planned-sprays/{planned['id']}/risk-assessment", json={})

    events = client.get(f"/planned-sprays/{planned['id']}/audit-events").json()
    computed = [e for e in events if e["event_type"] == "risk_assessment_computed"]
    assert len(computed) == 1
    assert computed[0]["after"]["is_shadow"] is True
    assert computed[0]["after"]["abstained"] is True


# ------------------------------------------------------------ honesty of the result
def test_the_real_pilot_path_abstains_and_says_exactly_why(client):
    """End-to-end, with no weather or scouting loaded: every gap is reported."""
    _farm_, _block_, planned, _snap = _chain(client)
    row = client.post(f"/planned-sprays/{planned['id']}/risk-assessment", json={}).json()

    assert row["abstained"] is True
    assert row["risk_band"] == "abstain"
    assert row["probability"] is None
    assert row["calibration_status"] == "not_calibrated"
    assert "NOT validated for California Central Coast" in row["local_validation_status"]

    reasons = row["missing_inputs"]
    assert "thresholds_not_supplied" in reasons
    assert "no_weather_in_window" in reasons
    assert "no_scouting_sample_for_target" in reasons


def test_assessment_row_has_no_recommendation_shaped_field(client):
    _farm_, _block_, planned, _snap = _chain(client)
    row = client.post(f"/planned-sprays/{planned['id']}/risk-assessment", json={}).json()
    for key in ("product", "product_name", "rate_amount", "action", "recommendation"):
        assert key not in row
