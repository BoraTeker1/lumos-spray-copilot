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


# ------------------------------------------------------------- CORS preflight
# A browser NEVER sends custom headers on an OPTIONS preflight — the CORS spec forbids
# it. So a preflight for any request carrying X-Lumos-Operator-Key arrives with no key.
# The gate used to refuse it 403, the browser then never sent the real request, and
# every /internal call from the UI died with an opaque "Failed to fetch".
#
# That made the entire operator surface unusable from a browser on exactly the
# deployments where the key is mandatory. It survived the whole test suite because
# TestClient does not perform preflight, and the route-enumeration test above issues
# plain GETs with no Origin — nothing here spoke CORS until this block.
PREFLIGHT_HEADERS = {
    "Origin": "http://localhost:3000",
    "Access-Control-Request-Method": "POST",
    "Access-Control-Request-Headers": f"{HEADER},content-type",
}


def test_a_preflight_to_an_internal_route_is_not_refused(client, enforced):
    """The bug: a 403 here means the browser never sends the real request at all."""
    res = client.options("/internal/instrumentation", headers=PREFLIGHT_HEADERS)

    assert res.status_code != 403, (
        "the operator gate refused a CORS preflight. A browser cannot attach the key "
        "to a preflight, so this makes every /internal call from the UI fail with "
        "'Failed to fetch' on any deployment where the key is set."
    )
    assert res.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_a_preflight_is_answered_but_the_real_request_still_needs_the_key(client, enforced):
    """Exempting preflight must not open the gate.

    The pair of assertions is the whole argument for the exemption: the preflight is
    answered (so the browser proceeds), and the request that follows is still refused
    without a valid key (so nothing was weakened).
    """
    assert client.options(
        "/internal/instrumentation", headers=PREFLIGHT_HEADERS
    ).status_code != 403

    # The real request, which a browser sends only after a successful preflight.
    assert client.get("/internal/instrumentation").status_code == 403
    assert client.get(
        "/internal/instrumentation", headers={HEADER: "wrong"}
    ).status_code == 403
    assert client.get(
        "/internal/instrumentation", headers={HEADER: KEY}
    ).status_code == 200


def test_a_denied_internal_request_still_carries_cors_headers(client, enforced):
    """The other half of the same bug.

    The gate short-circuits with a 403. If it ran OUTSIDE CORSMiddleware, that response
    would carry no `access-control-allow-origin`, a browser would discard it, and the
    operator would see "Failed to fetch" instead of "this route requires the
    X-Lumos-Operator-Key header" — the one message that tells them what is wrong.

    Middleware ORDER is what fixes this (CORS registered last => outermost), so this
    test is really pinning the registration order in main.py.
    """
    res = client.get(
        "/internal/instrumentation", headers={"Origin": "http://localhost:3000"}
    )

    assert res.status_code == 403
    assert res.headers.get("access-control-allow-origin") == "http://localhost:3000", (
        "the 403 from the operator gate carries no CORS headers, so a browser discards "
        "it and shows an opaque network error instead of the reason"
    )
    assert "operator" in res.json()["detail"].lower()


def test_preflight_is_exempt_across_the_whole_internal_surface(client, enforced):
    """Enumerated from the live route table, like the gate test above."""
    for path in _internal_paths():
        concrete = path.replace("{credential_id}", "1").replace("{farm_id}", "1")
        concrete = concrete.replace("{plan_id}", "1").replace("{quote_id}", "1")
        concrete = concrete.replace("{order_id}", "1").replace("{product_id}", "1")
        concrete = concrete.replace("{supplier_id}", "1").replace("{source_key}", "x")

        res = client.options(concrete, headers=PREFLIGHT_HEADERS)
        assert res.status_code != 403, f"{concrete} refuses CORS preflight"


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
