"""Pilot protocol, arm assignment, block outcomes — and the unblinding gate.

The properties that matter: an assignment cannot be quietly changed (that would
invalidate the comparison), a block outcome is per-block rather than per-decision, a
measurement always carries its unit, and shadow mode lifts ONLY through a recorded,
protocol-versioned unblinding.
"""
from datetime import date, datetime, timedelta

import pytest

TOKEN_HEADER = "X-Lumos-Pca-Token"


def _farm(client, name="Protocol Farm"):
    return client.post("/farms", json={
        "name": name, "country": "US", "crop_type": "strawberry", "area_unit": "acres",
        "expected_harvest_date": (date.today() + timedelta(days=30)).isoformat(),
    }).json()


def _block(client, farm_id, name="North 1"):
    return client.post(f"/farms/{farm_id}/blocks", json={
        "name": name, "crop": "strawberry",
    }).json()


def _protocol(client, farm_id, **overrides):
    payload = {
        "version": "v1",
        "name": "Botrytis deferral shadow pilot",
        "document_reference": "https://example.invalid/protocol-v1.pdf",
        "assignment_method": "matched",
        "target": "botrytis_fruit_rot",
        "primary_metric": "botrytis_incidence_pct_at_harvest",
        "secondary_metrics": ["applications_per_block", "marketable_packout"],
        "effective_from": date.today().isoformat(),
    }
    payload.update(overrides)
    return client.post(f"/farms/{farm_id}/pilot-protocols", json=payload)


# ------------------------------------------------------------------------ protocol
def test_a_protocol_records_the_rules_a_result_must_be_read_under(client):
    farm = _farm(client)
    res = _protocol(client, farm["id"])
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["assignment_method"] == "matched"
    assert body["primary_metric"] == "botrytis_incidence_pct_at_harvest"
    # Not unblinded until explicitly recorded.
    assert body["unblinded_at"] is None


def test_an_invalid_assignment_method_is_refused(client):
    farm = _farm(client)
    assert _protocol(client, farm["id"], assignment_method="vibes").status_code == 422


def test_an_inverted_effective_range_is_refused(client):
    farm = _farm(client)
    res = _protocol(
        client, farm["id"],
        effective_from=date.today().isoformat(),
        effective_to=(date.today() - timedelta(days=5)).isoformat(),
    )
    assert res.status_code == 422


def test_only_randomized_and_matched_can_support_a_comparison():
    """Guards the vocabulary the future reporting module will branch on."""
    from app import decision_status

    assert set(decision_status.COMPARABLE_ASSIGNMENT_METHODS) == {"randomized", "matched"}
    assert "observational" in decision_status.ASSIGNMENT_METHODS
    assert "observational" not in decision_status.COMPARABLE_ASSIGNMENT_METHODS


# ---------------------------------------------------------------------- assignment
def test_an_assignment_records_its_offline_seed(client):
    farm = _farm(client)
    block = _block(client, farm["id"])
    protocol = _protocol(client, farm["id"]).json()

    res = client.post(f"/pilot-protocols/{protocol['id']}/assignments", json={
        "block_id": block["id"], "arm": "intervention",
        "matched_pair_key": "pair-a", "assigned_on": date.today().isoformat(),
        "assigned_by": "Dana PCA", "assignment_seed": "seed-20260720-a",
    })
    assert res.status_code == 201, res.text
    assert res.json()["assignment_seed"] == "seed-20260720-a"


def test_a_block_cannot_be_reassigned_under_one_protocol_version(client):
    """Moving a block mid-pilot invalidates the comparison."""
    farm = _farm(client)
    block = _block(client, farm["id"])
    protocol = _protocol(client, farm["id"]).json()
    payload = {
        "block_id": block["id"], "arm": "control",
        "assigned_on": date.today().isoformat(),
    }
    assert client.post(
        f"/pilot-protocols/{protocol['id']}/assignments", json=payload
    ).status_code == 201

    second = client.post(
        f"/pilot-protocols/{protocol['id']}/assignments",
        json={**payload, "arm": "intervention"},
    )
    assert second.status_code == 409
    assert "new protocol version" in second.text


def test_an_invalid_arm_is_refused(client):
    farm = _farm(client)
    block = _block(client, farm["id"])
    protocol = _protocol(client, farm["id"]).json()
    res = client.post(f"/pilot-protocols/{protocol['id']}/assignments", json={
        "block_id": block["id"], "arm": "maybe", "assigned_on": date.today().isoformat(),
    })
    assert res.status_code == 422


def test_a_block_from_another_farm_cannot_be_assigned(client):
    farm = _farm(client)
    other = _farm(client, "Other Farm")
    foreign_block = _block(client, other["id"], name="Their Block")
    protocol = _protocol(client, farm["id"]).json()

    res = client.post(f"/pilot-protocols/{protocol['id']}/assignments", json={
        "block_id": foreign_block["id"], "arm": "control",
        "assigned_on": date.today().isoformat(),
    })
    assert res.status_code == 422


def test_assignments_have_no_update_or_delete_path(client):
    farm = _farm(client)
    block = _block(client, farm["id"])
    protocol = _protocol(client, farm["id"]).json()
    client.post(f"/pilot-protocols/{protocol['id']}/assignments", json={
        "block_id": block["id"], "arm": "control",
        "assigned_on": date.today().isoformat(),
    })
    assert client.patch(
        f"/pilot-protocols/{protocol['id']}/assignments", json={}
    ).status_code in (404, 405)
    assert client.delete(
        f"/pilot-protocols/{protocol['id']}/assignments"
    ).status_code in (404, 405)


# ------------------------------------------------------------------ block outcomes
def test_a_block_outcome_is_recorded_per_block_not_per_decision(client):
    """Packout is evidence for many decisions and for none in particular."""
    farm = _farm(client)
    block = _block(client, farm["id"])
    res = client.post(f"/farms/{farm['id']}/block-outcomes", json={
        "block_id": block["id"], "observed_on": date.today().isoformat(),
        "outcome_type": "marketable_packout", "value": 82.5, "unit": "pct",
        "denominator": 1200.0, "method": "packhouse tally",
    })
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["outcome_type"] == "marketable_packout"
    assert "planned_spray_id" not in body


def test_a_value_without_a_unit_is_refused(client):
    """An unlabelled number is not a measurement, and nothing here converts units."""
    farm = _farm(client)
    block = _block(client, farm["id"])
    res = client.post(f"/farms/{farm['id']}/block-outcomes", json={
        "block_id": block["id"], "observed_on": date.today().isoformat(),
        "outcome_type": "yield", "value": 900.0,
    })
    assert res.status_code == 422
    assert "unit is required" in res.text

    # A qualitative outcome with no value needs no unit.
    ok = client.post(f"/farms/{farm['id']}/block-outcomes", json={
        "block_id": block["id"], "observed_on": date.today().isoformat(),
        "outcome_type": "adverse_event", "notes": "phytotoxicity on row ends",
    })
    assert ok.status_code == 201


def test_an_invalid_outcome_type_is_refused(client):
    farm = _farm(client)
    block = _block(client, farm["id"])
    res = client.post(f"/farms/{farm['id']}/block-outcomes", json={
        "block_id": block["id"], "observed_on": date.today().isoformat(),
        "outcome_type": "vibes", "value": 1.0, "unit": "x",
    })
    assert res.status_code == 422


def test_block_outcomes_are_append_only(client):
    farm = _farm(client)
    block = _block(client, farm["id"])
    first = client.post(f"/farms/{farm['id']}/block-outcomes", json={
        "block_id": block["id"], "observed_on": date.today().isoformat(),
        "outcome_type": "disease_incidence", "value": 4.0, "unit": "pct",
    }).json()

    assert client.patch(f"/farms/{farm['id']}/block-outcomes", json={}).status_code in (404, 405)
    assert client.delete(f"/farms/{farm['id']}/block-outcomes").status_code in (404, 405)

    corrected = client.post(f"/farms/{farm['id']}/block-outcomes", json={
        "block_id": block["id"], "observed_on": date.today().isoformat(),
        "outcome_type": "disease_incidence", "value": 6.0, "unit": "pct",
        "supersedes_id": first["id"],
    })
    assert corrected.status_code == 201

    rows = client.get(f"/farms/{farm['id']}/block-outcomes").json()
    assert len(rows) == 2
    assert any(r["value"] == 4.0 for r in rows), "a correction must not hide the original"


def test_a_block_from_another_farm_cannot_receive_an_outcome(client):
    farm = _farm(client)
    other = _farm(client, "Other Farm 2")
    foreign_block = _block(client, other["id"], name="Their Block")

    res = client.post(f"/farms/{farm['id']}/block-outcomes", json={
        "block_id": foreign_block["id"], "observed_on": date.today().isoformat(),
        "outcome_type": "cull", "value": 3.0, "unit": "pct",
    })
    assert res.status_code == 422


# --------------------------------------------------------------- unblinding gate
def _pilot_chain(client, farm):
    block = _block(client, farm["id"])
    planned = client.post(f"/farms/{farm['id']}/planned-sprays", json={
        "intended_date": (date.today() + timedelta(days=2)).isoformat(),
        "product_name": "Switch 62.5 WG", "block_id": block["id"],
        "target_pest_or_disease": "botrytis_fruit_rot",
    }).json()
    client.post(f"/planned-sprays/{planned['id']}/risk-snapshot", json={})
    return planned


def test_assessments_stay_shadow_while_the_protocol_is_blinded(client):
    farm = _farm(client, "Blinded Farm")
    _protocol(client, farm["id"])
    planned = _pilot_chain(client, farm)

    row = client.post(f"/planned-sprays/{planned['id']}/risk-assessment", json={}).json()
    assert row["is_shadow"] is True


def test_a_farm_with_no_protocol_can_never_drift_out_of_shadow(client):
    """No protocol means no unblinding — not "unblinded by default"."""
    from app import crud
    from app.database import SessionLocal

    farm = _farm(client, "No Protocol Farm")
    planned = _pilot_chain(client, farm)
    row = client.post(f"/planned-sprays/{planned['id']}/risk-assessment", json={}).json()
    assert row["is_shadow"] is True

    db = SessionLocal()
    try:
        assert crud.active_pilot_protocol(db, farm["id"]) is None
        assert crud.farm_is_unblinded(db, farm["id"]) is False
    finally:
        db.close()


def test_unblinding_requires_a_recorded_protocol_event_not_a_flag(client):
    """The only lever is PilotProtocol.unblinded_at, and it is a dated record."""
    from app import crud, models
    from app.database import SessionLocal

    farm = _farm(client, "Unblinding Farm")
    protocol = _protocol(client, farm["id"]).json()
    planned = _pilot_chain(client, farm)

    shadow = client.post(
        f"/planned-sprays/{planned['id']}/risk-assessment", json={}
    ).json()
    assert shadow["is_shadow"] is True

    db = SessionLocal()
    try:
        row = db.get(models.PilotProtocol, protocol["id"])
        row.unblinded_at = datetime.now() - timedelta(hours=1)
        db.commit()
        assert crud.farm_is_unblinded(db, farm["id"]) is True
    finally:
        db.close()

    after = client.post(
        f"/planned-sprays/{planned['id']}/risk-assessment", json={}
    ).json()
    assert after["is_shadow"] is False

    # The earlier assessment stays shadow — history is not rewritten by unblinding.
    rows = client.get("/internal/pilot/assessments").json()
    assert any(r["id"] == shadow["id"] and r["is_shadow"] is True for r in rows)


def test_a_future_unblinding_date_does_not_unblind_yet(client):
    from app import crud, models
    from app.database import SessionLocal

    farm = _farm(client, "Future Unblind Farm")
    protocol = _protocol(client, farm["id"]).json()

    db = SessionLocal()
    try:
        row = db.get(models.PilotProtocol, protocol["id"])
        row.unblinded_at = datetime.now() + timedelta(days=30)
        db.commit()
        assert crud.farm_is_unblinded(db, farm["id"]) is False
    finally:
        db.close()
