"""The /internal surface must not be open once real pilot data exists.

These routes mint PCA credentials and grant farm authorizations. Unprotected, the
entire authorization chain is decorative: anyone who can reach the API issues
themselves a credential and then signs recommendations as an authorized PCA. Every
guarantee tested elsewhere in this suite about who may record a disposition rests on
this file.

This is a deployment interlock, not auth infrastructure — no login, no session, no
password, no user table.
"""
import re
from pathlib import Path

import pytest

from app import operator_key
from app.main import app

KEY = "test-operator-secret"
HEADER = operator_key.KEY_HEADER


def _internal_paths() -> list[str]:
    """Every registered /internal path, discovered from the app itself.

    Enumerating rather than listing by hand is the point: a route added later is
    covered by this test automatically, and cannot quietly ship unprotected.
    """
    paths = {
        route.path for route in app.routes
        if getattr(route, "path", "").startswith("/internal")
    }
    assert paths, "no /internal routes found — the enumeration is broken, not empty"
    return sorted(paths)


@pytest.fixture()
def enforced(monkeypatch):
    monkeypatch.setenv(operator_key.ENV_VAR, KEY)
    return KEY


# ------------------------------------------------------------------- enforcement
def test_every_internal_route_is_gated(client, enforced):
    """Parametrized over the live route table, not a hand-maintained list."""
    for path in _internal_paths():
        # Substitute any path params; the guard runs before routing resolves them.
        concrete = path.replace("{credential_id}", "1").replace("{farm_id}", "1")
        concrete = concrete.replace("{plan_id}", "1").replace("{quote_id}", "1")
        concrete = concrete.replace("{order_id}", "1")
        concrete = concrete.replace("{product_id}", "1")

        res = client.get(concrete)
        assert res.status_code == 403, (
            f"{concrete} was reachable without an operator key (got {res.status_code})"
        )
        assert "operator" in res.json()["detail"].lower()


def test_a_wrong_key_is_refused(client, enforced):
    res = client.get("/internal/instrumentation", headers={HEADER: "not-the-key"})
    assert res.status_code == 403
    assert res.json()["detail"] == operator_key.DENIAL_MESSAGES[operator_key.DENY_BAD_KEY]


def test_a_missing_key_is_refused(client, enforced):
    res = client.get("/internal/instrumentation")
    assert res.status_code == 403
    assert res.json()["detail"] == operator_key.DENIAL_MESSAGES[operator_key.DENY_NO_KEY]


def test_the_correct_key_is_accepted(client, enforced):
    res = client.get("/internal/instrumentation", headers={HEADER: KEY})
    assert res.status_code == 200


def test_non_internal_routes_are_untouched(client, enforced):
    """The gate is scoped to /internal and must not lock out the grower-facing API."""
    assert client.get("/health").status_code == 200
    assert client.get("/farms").status_code == 200


def test_credential_minting_specifically_is_gated(client, enforced):
    """The route that makes the whole PCA authorization chain meaningful."""
    res = client.post("/internal/pca-credentials", json={
        "display_name": "Attacker PCA", "license_identifier": "PCA-00000",
        "issued_by": "self",
    })
    assert res.status_code == 403


# ---------------------------------------------------------------------- unset key
def test_unset_key_leaves_internal_open_for_demo_use(client):
    """Local development and the demo must keep working with no configuration."""
    assert operator_key.is_enforced() is False
    assert client.get("/internal/instrumentation").status_code == 200


def test_denial_reason_is_none_when_unenforced(monkeypatch):
    monkeypatch.delenv(operator_key.ENV_VAR, raising=False)
    assert operator_key.denial_reason(None) is None
    assert operator_key.denial_reason("anything") is None


# ------------------------------------------------------------- startup interlock
def test_startup_refuses_an_open_operator_surface_with_real_data(monkeypatch):
    """The unsafe combination must be unable to boot, not merely discouraged."""
    monkeypatch.delenv(operator_key.ENV_VAR, raising=False)
    with pytest.raises(RuntimeError) as exc:
        operator_key.assert_safe_for_serving(has_real_records=True)

    message = str(exc.value)
    assert operator_key.ENV_VAR in message
    assert "PCA credentials" in message


def test_startup_allows_a_demo_only_database(monkeypatch):
    monkeypatch.delenv(operator_key.ENV_VAR, raising=False)
    operator_key.assert_safe_for_serving(has_real_records=False)  # must not raise


def test_startup_allows_real_data_once_a_key_is_configured(monkeypatch):
    monkeypatch.setenv(operator_key.ENV_VAR, KEY)
    operator_key.assert_safe_for_serving(has_real_records=True)  # must not raise


def test_key_comparison_is_constant_time():
    """A timing oracle on a shared secret is unglamorous but real."""
    import inspect

    source = inspect.getsource(operator_key.denial_reason)
    assert "compare_digest" in source


# ------------------------------------------------------- frontend header wiring
# A Python test reading a JavaScript file, deliberately: pytest is the only test
# harness in this repo, and the gap this covers is invisible to every other test
# here. `test_every_internal_route_is_gated` enumerates routes from the app, so it
# passes whether or not any client remembers to send the header — the backend is
# correct and the caller is broken. That is exactly how eight /internal calls in
# lib/api.js shipped without operatorHeaders(): concierge pilot import, the usage
# funnel, AI calibration and the whole procurement concierge UI 403'd on any
# deployment holding real data, which is precisely the deployment where the key is
# mandatory to boot (`assert_safe_for_serving`). The demo worked, so nobody saw it.
API_CLIENT = Path(__file__).resolve().parents[2] / "frontend" / "lib" / "api.js"


def _call_expressions(source: str) -> list[str]:
    """Every `request(...)` / `fetch(...)` expression, by paren balancing.

    Balancing is naive about parens inside strings — acceptable here because no URL
    or literal in this file contains one, and the sanity assertion below fails loudly
    if that ever stops being true rather than silently scanning nothing.
    """
    spans: list[str] = []
    for match in re.finditer(r"\b(?:request|fetch)\(", source):
        depth = 0
        for i in range(match.end() - 1, len(source)):
            if source[i] == "(":
                depth += 1
            elif source[i] == ")":
                depth -= 1
                if depth == 0:
                    spans.append(source[match.start(): i + 1])
                    break
    return spans


def test_every_internal_call_in_the_api_client_sends_the_operator_key():
    source = API_CLIENT.read_text()
    calls = _call_expressions(source)
    assert len(calls) > 50, (
        f"only parsed {len(calls)} call expressions from {API_CLIENT.name} — the "
        "extraction is broken, not the client"
    )

    internal = [c for c in calls if "/internal" in c]
    assert len(internal) >= 20, (
        f"only found {len(internal)} /internal calls — extraction is broken"
    )

    missing = [c for c in internal if "operatorHeaders()" not in c]
    assert not missing, (
        "these /internal calls in frontend/lib/api.js do not send "
        f"{operator_key.KEY_HEADER}, so they 403 on any deployment holding real "
        "data:\n\n" + "\n\n".join(missing)
    )
