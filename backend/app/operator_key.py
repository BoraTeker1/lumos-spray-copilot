"""Operator-key interlock for the /internal surface (stdlib only).

The /internal routes mint PCA credentials, grant farm authorizations, reset the demo
database, and read shadow assessments. Unauthenticated, they make the entire
authorization chain decorative: anyone who can reach the API can issue themselves a
credential and then sign recommendations as an authorized PCA.

This is deliberately NOT auth infrastructure. There is no login, no session, no
password, no user table, no multi-tenant model — ENGINEERING_GUIDELINES.md section 4 still holds. It
is a deployment interlock in exactly the shape of `clock.assert_safe_for_serving`:
one environment variable that an operator must set, and a startup check that refuses
to serve without it once the database holds anything real.

Behaviour:
  * LUMOS_OPERATOR_KEY set   -> every /internal route requires a matching
                                X-Lumos-Operator-Key header; anything else is 403.
  * LUMOS_OPERATOR_KEY unset -> /internal stays open (demo and local development),
                                but the API refuses to start if any non-demo farm
                                exists, so a real pilot cannot run unprotected.
"""
from __future__ import annotations

import hmac
import os

KEY_HEADER = "X-Lumos-Operator-Key"
ENV_VAR = "LUMOS_OPERATOR_KEY"

DENY_NO_KEY = "operator_key_missing"
DENY_BAD_KEY = "operator_key_invalid"

DENIAL_MESSAGES = {
    DENY_NO_KEY: (
        f"this operator route requires the {KEY_HEADER} header on this deployment"
    ),
    DENY_BAD_KEY: f"the {KEY_HEADER} presented is not valid",
}


def configured_key() -> str | None:
    """The operator key this deployment requires, or None when unprotected."""
    return os.environ.get(ENV_VAR) or None


def is_enforced() -> bool:
    return configured_key() is not None


def denial_reason(presented: str | None) -> str | None:
    """Why this request may not reach /internal, or None when it may."""
    expected = configured_key()
    if expected is None:
        return None
    if not presented:
        return DENY_NO_KEY
    # Constant-time compare: the key is a shared secret, and a timing oracle on a
    # string comparison is a real (if unglamorous) way to recover one.
    if not hmac.compare_digest(presented, expected):
        return DENY_BAD_KEY
    return None


def assert_safe_for_serving(has_real_records: bool) -> None:
    """Refuse to serve real pilot data from an unprotected operator surface.

    Mirrors `clock.assert_safe_for_serving`: rather than trusting an operator to
    remember, the unsafe combination simply cannot boot. Demo-only databases are
    exempt, so the local demo and the test suite are untouched.
    """
    if has_real_records and not is_enforced():
        raise RuntimeError(
            f"{ENV_VAR} is not set but this database contains real (non-demo) "
            "records. The /internal routes issue PCA credentials and farm "
            "authorizations — leaving them open would let anyone who can reach this "
            f"API sign recommendations as an authorized PCA. Set {ENV_VAR} to a "
            "secret value and present it in the "
            f"{KEY_HEADER} header, or run against a demo-only database."
        )
