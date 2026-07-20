"""PCA credential logic: token handling and the active/authorized predicates.

Framework-free (duck-typed plain objects, stdlib only), like `decision_status` and
`decision_engine`, so the authorization rules unit-test without a database or a
request. `crud` does the lookups; this module decides what "active" and "authorized"
mean, in one place.

What this is NOT
----------------
This is not authentication. There is no login, session, password, user model, or role
hierarchy, and none is planned for the pilot. It answers exactly one question: *may
this bearer record a professional decision on this farm?* — because a PCA disposition
that anyone can post is not a professional decision, it is an anonymous form field.

Token handling
--------------
Tokens are generated server-side, shown once, and stored only as a sha256 digest. A
database leak therefore yields no usable tokens. There is no recovery path: a lost
token is revoked and reissued.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import date, datetime

# The header a PCA's client presents. Deliberately not `Authorization`: this is a
# farm-scoped capability for one workflow, not an app-wide identity.
TOKEN_HEADER = "X-Lumos-Pca-Token"

# Length of the stored, non-secret token fragment used to tell tokens apart in
# operator UI. Short enough to be useless for replay.
PREFIX_LENGTH = 8

# Denial reasons. Returned verbatim to the caller: an authorized PCA who is being
# refused needs to know whether their token is unknown, expired, revoked, or simply
# not granted this farm — "403 Forbidden" alone turns into a support call.
DENY_NO_TOKEN = "no_token"
DENY_UNKNOWN_TOKEN = "unknown_token"
DENY_REVOKED = "revoked"
DENY_NOT_YET_ACTIVE = "not_yet_active"
DENY_EXPIRED = "expired"
DENY_FARM_NOT_AUTHORIZED = "farm_not_authorized"

DENY_MESSAGES = {
    DENY_NO_TOKEN: (
        f"a PCA credential token is required — present it in the {TOKEN_HEADER} header"
    ),
    DENY_UNKNOWN_TOKEN: "this PCA credential token is not recognised",
    DENY_REVOKED: "this PCA credential has been revoked",
    DENY_NOT_YET_ACTIVE: "this PCA credential is not active yet",
    DENY_EXPIRED: "this PCA credential has expired",
    DENY_FARM_NOT_AUTHORIZED: (
        "this PCA credential is not authorized for this farm — authorization is "
        "granted per farm and is never inferred"
    ),
}


def generate_token() -> str:
    """A new opaque bearer token. Shown once; only its digest is ever stored."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def token_prefix(token: str) -> str:
    return token[:PREFIX_LENGTH]


def credential_denial_reason(credential, today: date | None = None) -> str | None:
    """Why this credential cannot act right now, or None when it is active.

    Checked in the order an operator would explain it: revoked beats expired beats
    not-yet-active, because a revoked credential is a decision someone made and the
    date windows are incidental to it.
    """
    if credential is None:
        return DENY_UNKNOWN_TOKEN
    if getattr(credential, "revoked_at", None) is not None:
        return DENY_REVOKED
    today = today or date.today()
    active_from = getattr(credential, "active_from", None)
    active_to = getattr(credential, "active_to", None)
    if active_from is not None and today < active_from:
        return DENY_NOT_YET_ACTIVE
    if active_to is not None and today > active_to:
        return DENY_EXPIRED
    return None


def credential_is_active(credential, today: date | None = None) -> bool:
    return credential_denial_reason(credential, today) is None


def authorization_is_active(authorization, today: date | None = None) -> bool:
    """An authorization grant is live: not revoked and already granted.

    A grant dated in the future is not yet an authorization — backdating one to "now"
    would silently widen access nobody approved for today.
    """
    if authorization is None:
        return False
    if getattr(authorization, "revoked_at", None) is not None:
        return False
    granted_on = getattr(authorization, "granted_on", None)
    if granted_on is not None and (today or date.today()) < granted_on:
        return False
    return True


def authorize(credential, authorizations, farm_id: int, today: date | None = None) -> str | None:
    """The single authorization decision: None when allowed, else a denial reason.

    `authorizations` is every grant on record for this credential — active or not —
    so the caller cannot accidentally pre-filter the check into always passing.
    """
    reason = credential_denial_reason(credential, today)
    if reason is not None:
        return reason
    for auth in authorizations or []:
        if getattr(auth, "farm_id", None) == farm_id and authorization_is_active(auth, today):
            return None
    return DENY_FARM_NOT_AUTHORIZED


def denial_message(reason: str) -> str:
    return DENY_MESSAGES.get(reason, "PCA authorization denied")


def attribution(credential) -> dict:
    """How a credential is recorded on an audit trail or export.

    The licence identifier travels with the name because "who decided this" is the
    whole point of the record; the token never appears anywhere.
    """
    if credential is None:
        return {}
    return {
        "pca_credential_id": getattr(credential, "id", None),
        "pca_display_name": getattr(credential, "display_name", None),
        "pca_license_identifier": getattr(credential, "license_identifier", None),
        "pca_license_state": getattr(credential, "license_state", None),
        "license_verified_by_lumos": False,  # never verified against any registry
    }


def issued_at(now: datetime | None = None) -> datetime:
    return now or datetime.now()
