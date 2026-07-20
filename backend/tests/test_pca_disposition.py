"""PCA disposition: attributed, anchored, append-only, and orthogonal to everything.

The orthogonality tests are the most important in the pilot. A disposition, the
engine's verdict, a completed review, and what actually happened are four different
facts about four different moments. If recording one silently moves another, the pilot
cannot distinguish "the rule said defer" from "the PCA chose to defer" from "the spray
was in fact deferred" — and that distinction is the entire measurement.
"""
from datetime import date, datetime, timedelta

import pytest

TOKEN_HEADER = "X-Lumos-Pca-Token"


def _farm(client, name="Disposition Farm"):
    res = client.post("/farms", json={
        "name": name, "country": "US", "crop_type": "strawberry", "area_unit": "acres",
        "expected_harvest_date": (date.today() + timedelta(days=30)).isoformat(),
    })
    assert res.status_code == 201
    return res.json()


def _block(client, farm_id):
    return client.post(f"/farms/{farm_id}/blocks", json={
        "name": "North 1", "crop": "strawberry",
    }).json()


def _credential(client, farm_id, name="Dana PCA"):
    cred = client.post("/internal/pca-credentials", json={
        "display_name": name, "license_identifier": "PCA-12345", "license_state": "CA",
        "issued_by": "pilot-operator",
    }).json()
    auth = client.post(
        f"/internal/pca-credentials/{cred['id']}/farm-authorizations",
        json={"farm_id": farm_id, "granted_by": "pilot-operator"},
    )
    assert auth.status_code == 201, auth.text
    return cred


def _planned(client, farm_id, block_id, **overrides):
    """A decision that REQUIRES review: PHI/REI are omitted, so missing data escalates.

    That is the realistic pilot shape (no label database exists, so regulatory values
    are routinely absent) and it is the only shape in which "does a disposition unlock
    an applied outcome?" is a meaningful question.
    """
    payload = {
        "intended_date": (date.today() + timedelta(days=2)).isoformat(),
        "product_name": "Switch 62.5 WG",
        "active_ingredient": "cyprodinil + fludioxonil",
        "target_pest_or_disease": "botrytis_fruit_rot",
        "block_id": block_id,
    }
    payload.update(overrides)
    res = client.post(f"/farms/{farm_id}/planned-sprays", json=payload)
    assert res.status_code == 201, res.text
    assert res.json()["review_required"] is True
    return res.json()


@pytest.fixture()
def pilot(client):
    """A farm enrolled with a credentialed PCA, a block, a decision and a snapshot."""
    farm = _farm(client)
    block = _block(client, farm["id"])
    cred = _credential(client, farm["id"])
    planned = _planned(client, farm["id"], block["id"])
    snap = client.post(f"/planned-sprays/{planned['id']}/risk-snapshot", json={
        "horizon_hours": 72,
    })
    assert snap.status_code == 201, snap.text
    return {
        "farm": farm, "block": block, "credential": cred,
        "planned": planned, "snapshot": snap.json(),
        "headers": {TOKEN_HEADER: cred["token"]},
    }


def _record(client, pilot, disposition="defer", rationale="Canopy dry; holding 48h.", **kw):
    return client.post(
        f"/planned-sprays/{pilot['planned']['id']}/pca-disposition",
        json={"disposition": disposition, "rationale": rationale, **kw},
        headers=pilot["headers"],
    )


# ================================================================== ORTHOGONALITY
def test_a_disposition_never_mutates_any_decision_or_review_column(client, pilot):
    before = client.get(f"/planned-sprays/{pilot['planned']['id']}").json()
    assert _record(client, pilot).status_code == 201
    after = client.get(f"/planned-sprays/{pilot['planned']['id']}").json()

    for column in (
        "decision_outcome", "decision_severity", "decision_authority",
        "decision_confidence", "required_next_action", "review_required",
        "review_status", "review_comment", "reviewed_by", "pca_next_action",
        "outcome", "outcome_reason", "outcome_date", "spray_event_id",
    ):
        assert before.get(column) == after.get(column), (
            f"recording a disposition moved {column!r}: "
            f"{before.get(column)!r} -> {after.get(column)!r}"
        )


def test_defer_does_not_unlock_applied_outcomes(client, pilot):
    """Deferring and being cleared to spray are unrelated decisions."""
    planned_id = pilot["planned"]["id"]
    assert client.get(f"/planned-sprays/{planned_id}").json()["review_required"] is True

    assert _record(client, pilot, disposition="defer").status_code == 201

    # Still blocked from recording an applied outcome — the review is untouched.
    res = client.patch(f"/planned-sprays/{planned_id}/outcome", json={
        "outcome": "sprayed_as_planned", "outcome_reason": "changed my mind",
        "outcome_date": date.today().isoformat(),
    })
    assert res.status_code == 409


def test_defer_does_not_satisfy_a_required_review(client, pilot):
    planned_id = pilot["planned"]["id"]
    assert _record(client, pilot, disposition="defer").status_code == 201

    body = client.get(f"/planned-sprays/{planned_id}").json()
    assert body["review_required"] is True
    assert body["review_status"] == "not_reviewed"
    assert body["needs_review"] is True


def test_follow_baseline_does_not_record_that_the_spray_happened(client, pilot):
    """A disposition is an intention. What happened is recorded through /outcome."""
    assert _record(client, pilot, disposition="follow_baseline").status_code == 201
    body = client.get(f"/planned-sprays/{pilot['planned']['id']}").json()
    assert body["outcome"] == "planned"
    assert body["spray_event_id"] is None


# ==================================================================== AUTHORIZATION
def test_a_disposition_always_requires_a_credential(client, pilot):
    res = client.post(
        f"/planned-sprays/{pilot['planned']['id']}/pca-disposition",
        json={"disposition": "defer", "rationale": "no token"},
    )
    assert res.status_code == 403


def test_an_unenrolled_farm_still_requires_a_credential(client):
    """The strict path must not degrade into the permissive one.

    `ensure_pca_authority` deliberately no-ops on a farm with no credentials, so that
    existing non-pilot workflows keep working. A disposition must NOT inherit that
    leniency — it is a licensed professional's attributed decision.
    """
    farm = _farm(client, "Unenrolled Farm")
    block = _block(client, farm["id"])
    planned = _planned(client, farm["id"], block["id"])
    client.post(f"/planned-sprays/{planned['id']}/risk-snapshot", json={})

    res = client.post(f"/planned-sprays/{planned['id']}/pca-disposition",
                      json={"disposition": "defer", "rationale": "anonymous"})
    assert res.status_code == 403


def test_a_pca_authorized_for_another_farm_is_refused(client, pilot):
    other = _farm(client, "Other Farm")
    other_cred = _credential(client, other["id"], name="Sam PCA")

    res = client.post(
        f"/planned-sprays/{pilot['planned']['id']}/pca-disposition",
        json={"disposition": "defer", "rationale": "wrong farm"},
        headers={TOKEN_HEADER: other_cred["token"]},
    )
    assert res.status_code == 403


def test_a_revoked_token_is_refused(client, pilot):
    client.post(f"/internal/pca-credentials/{pilot['credential']['id']}/revoke", json={})
    assert _record(client, pilot).status_code == 403


def test_an_unknown_token_is_refused(client, pilot):
    res = client.post(
        f"/planned-sprays/{pilot['planned']['id']}/pca-disposition",
        json={"disposition": "defer", "rationale": "made up token"},
        headers={TOKEN_HEADER: "not-a-real-token"},
    )
    assert res.status_code == 403


def test_the_disposition_is_attributed_to_the_presenting_credential(client, pilot):
    row = _record(client, pilot).json()
    assert row["pca_credential_id"] == pilot["credential"]["id"]
    assert row["data_source"] == "pca_entered"


# ========================================================================= VALIDITY
def test_an_invalid_disposition_value_is_refused(client, pilot):
    assert _record(client, pilot, disposition="spray_now").status_code == 422
    assert _record(client, pilot, disposition="safe_to_defer").status_code == 422


def test_an_empty_rationale_is_refused(client, pilot):
    """Without a stated reason the record is not usable as pilot evidence."""
    assert _record(client, pilot, rationale="").status_code == 422
    assert _record(client, pilot, rationale="   ").status_code == 422


def test_a_disposition_requires_a_snapshot(client):
    farm = _farm(client, "No Snapshot Farm")
    block = _block(client, farm["id"])
    cred = _credential(client, farm["id"])
    planned = _planned(client, farm["id"], block["id"])

    res = client.post(f"/planned-sprays/{planned['id']}/pca-disposition",
                      json={"disposition": "defer", "rationale": "unanchored"},
                      headers={TOKEN_HEADER: cred["token"]})
    assert res.status_code == 422
    assert "snapshot" in res.text.lower()


def test_the_disposition_is_anchored_to_the_snapshot_digest(client, pilot):
    row = _record(client, pilot).json()
    assert row["snapshot_digest_at_decision"] == pilot["snapshot"]["input_digest"]


def test_the_assessment_is_linked_even_though_the_pca_could_not_see_it(client, pilot):
    """Blinded at decision time, joinable afterwards — that is what makes scoring possible."""
    assessment = client.post(
        f"/planned-sprays/{pilot['planned']['id']}/risk-assessment", json={}
    ).json()
    row = _record(client, pilot).json()
    assert row["assessment_id"] == assessment["id"]


# ====================================================================== APPEND-ONLY
def test_dispositions_have_no_update_or_delete_path(client, pilot):
    row = _record(client, pilot).json()
    planned_id = pilot["planned"]["id"]

    assert client.patch(f"/planned-sprays/{planned_id}/pca-disposition",
                        json={"disposition": "rescout"}).status_code in (404, 405)
    assert client.delete(
        f"/planned-sprays/{planned_id}/pca-disposition"
    ).status_code in (404, 405)
    assert client.delete(f"/pca-dispositions/{row['id']}").status_code in (404, 405)


def test_a_correction_supersedes_and_never_hides_what_it_replaced(client, pilot):
    first = _record(client, pilot, disposition="defer",
                    rationale="Holding 48h on dry canopy.").json()
    second = _record(client, pilot, disposition="follow_baseline",
                     rationale="Rain forecast changed; spraying on schedule.",
                     supersedes_id=first["id"])
    assert second.status_code == 201, second.text

    chain = client.get(
        f"/planned-sprays/{pilot['planned']['id']}/pca-dispositions"
    ).json()
    assert len(chain) == 2
    assert chain[0]["id"] == first["id"]
    assert chain[0]["rationale"] == "Holding 48h on dry canopy."
    assert chain[1]["supersedes_id"] == first["id"]


def test_a_second_live_disposition_is_refused(client, pilot):
    """One live judgement per decision; a change must supersede explicitly."""
    assert _record(client, pilot, disposition="defer").status_code == 201
    second = _record(client, pilot, disposition="rescout")
    assert second.status_code == 409


def test_recording_a_disposition_appends_an_audit_event(client, pilot):
    _record(client, pilot, disposition="defer", rationale="Canopy dry; holding 48h.")
    events = client.get(
        f"/planned-sprays/{pilot['planned']['id']}/audit-events"
    ).json()
    recorded = [e for e in events if e["event_type"] == "pca_disposition_recorded"]
    assert len(recorded) == 1
    assert recorded[0]["rationale"] == "Canopy dry; holding 48h."
    assert recorded[0]["after"]["disposition"] == "defer"


# ================================================================== DELETION GUARD
def test_a_decision_with_a_snapshot_cannot_be_deleted(client, pilot):
    res = client.delete(f"/planned-sprays/{pilot['planned']['id']}")
    assert res.status_code == 409
    assert "snapshot" in res.text.lower()


def test_a_decision_with_a_disposition_cannot_be_deleted(client, pilot):
    _record(client, pilot)
    res = client.delete(f"/planned-sprays/{pilot['planned']['id']}")
    assert res.status_code == 409
    assert "disposition" in res.text.lower()


def test_deleting_a_decision_can_never_destroy_its_audit_trail(client):
    """The cascade on audit_events makes an unguarded DELETE silently destructive."""
    farm = _farm(client, "Audit Trail Farm")
    block = _block(client, farm["id"])
    planned = _planned(client, farm["id"], block["id"])

    # A review is audit history beyond creation.
    review = client.patch(f"/planned-sprays/{planned['id']}/review", json={
        "action": "rejected", "review_comment": "not this week", "reviewed_by": "Dana",
    })
    assert review.status_code == 200, review.text

    res = client.delete(f"/planned-sprays/{planned['id']}")
    assert res.status_code == 409

    # And it is still readable.
    events = client.get(f"/planned-sprays/{planned['id']}/audit-events").json()
    assert any(e["event_type"] == "reviewed" for e in events)


def test_a_freshly_mistyped_decision_is_still_deletable(client):
    """The guard must not break the one legitimate use of DELETE."""
    farm = _farm(client, "Typo Farm")
    block = _block(client, farm["id"])
    planned = _planned(client, farm["id"], block["id"])

    assert client.delete(f"/planned-sprays/{planned['id']}").status_code == 204
    assert client.get(f"/farms/{farm['id']}/planned-sprays").json() == []
