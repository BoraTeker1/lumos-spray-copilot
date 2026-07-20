"""PCA credential authority: who may claim PCA authority, and on which farm.

The property under test is that a *professional decision* cannot be recorded by an
anonymous caller. Everywhere else in this system a PCA is a free-text string; on an
enrolled farm, claiming PCA-entered values or recording an approve/edit review must be
backed by a credential token that resolves, is active, and is granted THIS farm.

Farms with no credentials enrolled keep the original free-text behaviour — enrolling a
farm is what turns enforcement on. That is deliberate: it keeps the demo and every
pre-pilot workflow working while making the pilot path strict.
"""
from datetime import date, timedelta

import pytest

from app import pca_authority

HEADER = pca_authority.TOKEN_HEADER


# ----------------------------------------------------------------- pure module
def test_credential_denial_reasons_are_ordered_revoked_first():
    """A revoked credential reports revocation even if its window also expired —
    revocation is a decision someone made; the dates are incidental to it."""
    today = date(2026, 7, 19)
    revoked_and_expired = _cred(revoked_at=object(), active_to=date(2026, 1, 1))
    assert pca_authority.credential_denial_reason(revoked_and_expired, today) == (
        pca_authority.DENY_REVOKED
    )


def test_unknown_credential_is_denied_not_crashed():
    assert pca_authority.credential_denial_reason(None) == pca_authority.DENY_UNKNOWN_TOKEN


def test_future_grant_is_not_yet_an_authorization():
    """Backdating a grant to 'now' would widen access nobody approved for today."""
    today = date(2026, 7, 19)
    future = _auth(farm_id=1, granted_on=date(2026, 8, 1))
    assert pca_authority.authorization_is_active(future, today) is False
    assert pca_authority.authorize(_cred(), [future], 1, today) == (
        pca_authority.DENY_FARM_NOT_AUTHORIZED
    )


def test_authorize_checks_every_grant_not_a_prefiltered_list():
    today = date(2026, 7, 19)
    grants = [_auth(farm_id=1), _auth(farm_id=2, revoked_at=object())]
    assert pca_authority.authorize(_cred(), grants, 1, today) is None
    # Revoked grant on farm 2 does not authorize farm 2.
    assert pca_authority.authorize(_cred(), grants, 2, today) == (
        pca_authority.DENY_FARM_NOT_AUTHORIZED
    )


def test_attribution_never_contains_the_token_and_never_claims_verification():
    cred = _cred()
    cred.id, cred.display_name = 7, "A. Reyes"
    cred.license_identifier, cred.license_state = "PCA-12345", "CA"
    cred.token_hash = "deadbeef"
    attribution = pca_authority.attribution(cred)
    assert attribution["pca_license_identifier"] == "PCA-12345"
    assert attribution["license_verified_by_lumos"] is False
    assert "deadbeef" not in str(attribution)
    assert not any("token" in k for k in attribution)


class _Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _cred(**kw):
    base = {"revoked_at": None, "active_from": None, "active_to": None}
    base.update(kw)
    return _Obj(**base)


def _auth(**kw):
    base = {"farm_id": 1, "granted_on": None, "revoked_at": None}
    base.update(kw)
    return _Obj(**base)


# ------------------------------------------------------------------- fixtures
def _farm(client, name="Pilot Farm"):
    res = client.post("/farms", json={
        "name": name, "country": "US", "crop_type": "strawberry",
        "expected_harvest_date": (date.today() + timedelta(days=30)).isoformat(),
    })
    assert res.status_code == 201
    return res.json()


def _issue(client, name="A. Reyes", **overrides):
    payload = {"display_name": name, "license_identifier": "PCA-12345", "issued_by": "ops"}
    payload.update(overrides)
    res = client.post("/internal/pca-credentials", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def _grant(client, credential_id, farm_id, **overrides):
    payload = {"farm_id": farm_id}
    payload.update(overrides)
    res = client.post(
        f"/internal/pca-credentials/{credential_id}/farm-authorizations", json=payload
    )
    assert res.status_code == 201, res.text
    return res.json()


def _planned(client, farm_id, headers=None, **overrides):
    payload = {
        "intended_date": date.today().isoformat(),
        "product_name": "Switch 62.5 WG",
        "active_ingredient": "cyprodinil",
        "target_pest_or_disease": "botrytis",
        "pre_harvest_interval_days": 1,
        "re_entry_interval_hours": 12,
    }
    payload.update(overrides)
    return client.post(
        f"/farms/{farm_id}/planned-sprays", json=payload, headers=headers or {}
    )


# ------------------------------------------------------------ token issuance
def test_token_is_returned_once_and_never_stored_in_plaintext(client):
    issued = _issue(client)
    token = issued["token"]
    assert token and len(token) > 20
    assert issued["token_prefix"] == token[: pca_authority.PREFIX_LENGTH]

    # The listing never carries the token back.
    listed = client.get("/internal/pca-credentials").json()
    assert "token" not in listed[0]
    assert token not in str(listed)


def test_issued_credential_never_claims_license_verification(client):
    assert _issue(client)["license_verified_by_lumos"] is False


# ------------------------------------------------------- enforcement is opt-in
def test_farm_without_credentials_keeps_free_text_behaviour(client):
    """The demo and every pre-pilot workflow must keep working untouched."""
    farm = _farm(client)
    created = _planned(client, farm["id"], values_source="pca_entered",
                       values_entered_by="Demo PCA")
    assert created.status_code == 201

    res = client.patch(
        f"/planned-sprays/{created.json()['id']}/review",
        json={"action": "approved", "reviewed_by": "Demo PCA"},
    )
    assert res.status_code == 200


def test_a_bad_token_is_never_silently_ignored_even_when_not_required(client):
    """A PCA whose token was mistyped or revoked must not be quietly downgraded to
    the anonymous path while believing they acted with authority."""
    farm = _farm(client)  # not enrolled: no credential is required here at all
    res = _planned(client, farm["id"], headers={HEADER: "wrong-token"})
    assert res.status_code == 403
    assert res.json()["reason"] == pca_authority.DENY_UNKNOWN_TOKEN

    revoked = _issue(client)
    client.post(f"/internal/pca-credentials/{revoked['id']}/revoke")
    planned = _planned(client, farm["id"]).json()
    denied = client.patch(
        f"/planned-sprays/{planned['id']}/review",
        json={"action": "approved"}, headers={HEADER: revoked["token"]},
    )
    assert denied.status_code == 403
    assert denied.json()["reason"] == pca_authority.DENY_REVOKED


# ------------------------------------------------------------- 403 conditions
@pytest.mark.parametrize(
    "header_factory,expected_reason",
    [
        (lambda t: {}, pca_authority.DENY_NO_TOKEN),
        (lambda t: {HEADER: "not-a-real-token"}, pca_authority.DENY_UNKNOWN_TOKEN),
    ],
)
def test_missing_and_unknown_tokens_are_refused(client, header_factory, expected_reason):
    farm = _farm(client)
    issued = _issue(client)
    _grant(client, issued["id"], farm["id"])  # enrollment turns enforcement on

    res = _planned(client, farm["id"], headers=header_factory(issued["token"]),
                   values_source="pca_entered")
    assert res.status_code == 403, res.text
    assert res.json()["reason"] == expected_reason


def test_revoked_credential_is_refused(client):
    farm = _farm(client)
    issued = _issue(client)
    _grant(client, issued["id"], farm["id"])
    client.post(f"/internal/pca-credentials/{issued['id']}/revoke")

    res = _planned(client, farm["id"], headers={HEADER: issued["token"]},
                   values_source="pca_entered")
    assert res.status_code == 403
    assert res.json()["reason"] == pca_authority.DENY_REVOKED


def test_expired_and_not_yet_active_credentials_are_refused(client):
    farm = _farm(client)
    expired = _issue(client, name="Expired", active_to=(date.today() - timedelta(days=1)).isoformat())
    future = _issue(client, name="Future", active_from=(date.today() + timedelta(days=1)).isoformat())
    _grant(client, expired["id"], farm["id"])
    _grant(client, future["id"], farm["id"])

    r1 = _planned(client, farm["id"], headers={HEADER: expired["token"]},
                  values_source="pca_entered")
    assert r1.status_code == 403 and r1.json()["reason"] == pca_authority.DENY_EXPIRED

    r2 = _planned(client, farm["id"], headers={HEADER: future["token"]},
                  values_source="pca_entered")
    assert r2.status_code == 403 and r2.json()["reason"] == pca_authority.DENY_NOT_YET_ACTIVE


# --------------------------------------------------------- farm scoping (tenancy)
def test_credential_for_one_farm_is_refused_on_another(client):
    """Farm scoping IS the tenant boundary — there is no other isolation in the system."""
    farm_a = _farm(client, "Farm A")
    farm_b = _farm(client, "Farm B")
    issued = _issue(client)
    _grant(client, issued["id"], farm_a["id"])
    _grant(client, _issue(client, name="B's PCA")["id"], farm_b["id"])  # enroll B too

    ok = _planned(client, farm_a["id"], headers={HEADER: issued["token"]},
                  values_source="pca_entered")
    assert ok.status_code == 201

    denied = _planned(client, farm_b["id"], headers={HEADER: issued["token"]},
                      values_source="pca_entered")
    assert denied.status_code == 403
    assert denied.json()["reason"] == pca_authority.DENY_FARM_NOT_AUTHORIZED


# ------------------------------------------------------------- review gating
def test_approve_and_edit_require_a_credential_but_reject_does_not(client):
    """Refusing a spray must never be harder than authorizing one."""
    farm = _farm(client)
    issued = _issue(client)
    _grant(client, issued["id"], farm["id"])
    auth = {HEADER: issued["token"]}

    rejected = _planned(client, farm["id"]).json()
    res = client.patch(f"/planned-sprays/{rejected['id']}/review",
                       json={"action": "rejected", "review_comment": "Inputs look wrong."})
    assert res.status_code == 200, "a rejection must not require a credential"

    approved = _planned(client, farm["id"]).json()
    denied = client.patch(f"/planned-sprays/{approved['id']}/review",
                          json={"action": "approved", "reviewed_by": "Whoever"})
    assert denied.status_code == 403
    assert denied.json()["reason"] == pca_authority.DENY_NO_TOKEN

    allowed = client.patch(f"/planned-sprays/{approved['id']}/review",
                           json={"action": "approved", "reviewed_by": "Whoever"},
                           headers=auth)
    assert allowed.status_code == 200


def test_review_attribution_comes_from_the_credential_not_the_client_string(client):
    """Attribution must name what was actually verified, not what someone typed."""
    farm = _farm(client)
    issued = _issue(client, name="A. Reyes")
    _grant(client, issued["id"], farm["id"])

    planned = _planned(client, farm["id"]).json()
    reviewed = client.patch(
        f"/planned-sprays/{planned['id']}/review",
        json={"action": "approved", "reviewed_by": "Somebody Else"},
        headers={HEADER: issued["token"]},
    ).json()

    assert reviewed["reviewed_by"] == "A. Reyes"
    assert reviewed["reviewed_by_credential_id"] == issued["id"]


def test_revoking_a_grant_stops_further_authority_but_keeps_past_reviews(client):
    farm = _farm(client)
    issued = _issue(client)
    _grant(client, issued["id"], farm["id"])
    auth = {HEADER: issued["token"]}

    planned = _planned(client, farm["id"]).json()
    approved = client.patch(f"/planned-sprays/{planned['id']}/review",
                            json={"action": "approved"}, headers=auth)
    assert approved.status_code == 200

    client.post(f"/internal/pca-credentials/{issued['id']}/revoke")

    later = _planned(client, farm["id"]).json()
    denied = client.patch(f"/planned-sprays/{later['id']}/review",
                          json={"action": "approved"}, headers=auth)
    assert denied.status_code == 403

    # The already-signed review survives revocation, still attributed.
    still = client.get(f"/planned-sprays/{planned['id']}").json()
    assert still["review_status"] == "approved"
    assert still["reviewed_by_credential_id"] == issued["id"]
