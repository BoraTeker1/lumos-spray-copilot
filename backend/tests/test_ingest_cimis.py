"""The CIMIS adapter: credential gating, parsing, and the evidence it must not invent.

No test here reaches the network. Requests are served by `httpx.MockTransport` through
the adapter's `transport` seam, and every fixture states in its own `_provenance` block
that it was hand-authored from the published response shape rather than captured live.

The most important test in this file is
`test_the_recorded_payload_carries_no_leaf_wetness_and_the_adapter_invents_none`.
CIMIS publishes no leaf-wetness item, and the temptation to derive one from relative
humidity is exactly the failure `disease_risk` refuses: a derived number would arrive
wearing `wetness_is_measured` and look like a measurement. Never delete that test.
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest

from app import crud, models, storage
from app.database import SessionLocal
from app.ingest import base, cimis, pipeline, registry
from app.ingest.base import IngestContext

FIXTURES = Path(__file__).parent / "fixtures" / "cimis"
STATION = "111"
BASE_HOUR = datetime(2026, 7, 1, 6, 0, 0)


def fixture(name: str) -> bytes:
    return (FIXTURES / f"{name}.json").read_bytes()


@pytest.fixture()
def db(client):
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def store(tmp_path):
    return storage.LocalFileStore(str(tmp_path / "objects"))


def transport_for(name: str, captured: list | None = None):
    """A MockTransport serving one fixture, optionally recording the request."""

    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured.append(request)
        return httpx.Response(200, content=fixture(name))

    return httpx.MockTransport(handler)


def ctx_for(farm_id, **kw):
    defaults = dict(
        farm_id=farm_id, field_id=None, station_id=STATION,
        window_start=BASE_HOUR, window_end=BASE_HOUR + timedelta(hours=12),
        station_lat=36.93, station_lon=-121.77,
        field_lat=36.9102, field_lon=-121.7569,
    )
    defaults.update(kw)
    return IngestContext(**defaults)


def make_farm(client):
    return client.post(
        "/farms",
        json={"name": "CIMIS Test Ranch", "location": "Watsonville, CA",
              "country": "US", "crop_type": "strawberry", "area": 40.0},
    ).json()


# --------------------------------------------------------------------------
# Credential gating.
# --------------------------------------------------------------------------


def test_without_a_key_the_adapter_reports_requires_credential_and_names_the_variable():
    adapter = cimis.CimisAdapter(api_key=None)
    descriptor = adapter.describe()
    assert descriptor.status == base.SOURCE_REQUIRES_CREDENTIAL
    assert not descriptor.can_fetch
    assert cimis.API_KEY_ENV in descriptor.blocker


def test_with_a_key_the_adapter_reports_implemented():
    descriptor = cimis.CimisAdapter(api_key="secret").describe()
    assert descriptor.status == base.SOURCE_IMPLEMENTED
    assert descriptor.can_fetch
    assert descriptor.blocker is None


def test_the_factory_reads_the_credential_fresh_on_every_call(monkeypatch):
    """An operator who exports the key and restarts must not have to reason about when
    this module was first imported."""
    monkeypatch.delenv(cimis.API_KEY_ENV, raising=False)
    assert not registry.describe(cimis.SOURCE_KEY).can_fetch
    monkeypatch.setenv(cimis.API_KEY_ENV, "secret")
    assert registry.describe(cimis.SOURCE_KEY).can_fetch


def test_the_adapter_is_registered_under_its_source_key():
    assert cimis.SOURCE_KEY in registry.source_keys()
    assert registry.describe(cimis.SOURCE_KEY).domain == "climate"


def test_a_keyless_run_makes_no_request_and_persists_nothing(db, client, store, monkeypatch):
    """End-to-end inertness: the shipping configuration, since no key exists today."""
    monkeypatch.delenv(cimis.API_KEY_ENV, raising=False)
    farm = make_farm(client)

    def explode(request):  # pragma: no cover - must never be reached
        raise AssertionError("the pipeline made a network call without a credential")

    adapter = cimis.CimisAdapter(api_key=None, transport=httpx.MockTransport(explode))
    run = pipeline.run_source(db, adapter, ctx_for(farm["id"]), store=store)

    assert run.status == base.RUN_SKIPPED_NO_CREDENTIAL
    assert db.query(models.WeatherObservation).count() == 0


# --------------------------------------------------------------------------
# The credential must never be stored.
# --------------------------------------------------------------------------


def test_the_credential_never_reaches_the_stored_payload_or_an_issue(db, client, store):
    """A key that reaches durable storage is a leaked key.

    Three places it could land: the request description carried on FetchResult, the
    stored raw document, and any recorded issue. None may contain it.
    """
    farm = make_farm(client)
    captured = []
    adapter = cimis.CimisAdapter(
        api_key="SUPER-SECRET-KEY", transport=transport_for("hourly_metric", captured)
    )

    result = adapter.fetch(ctx_for(farm["id"]))

    # It WAS sent (otherwise the call would fail) ...
    assert "SUPER-SECRET-KEY" in str(captured[0].url)
    # ... and it is NOT in anything we keep.
    assert "SUPER-SECRET-KEY" not in json.dumps(result.request_description)
    assert "appKey" not in json.dumps(result.request_description)
    assert b"SUPER-SECRET-KEY" not in result.raw

    run = pipeline.run_source(db, adapter, ctx_for(farm["id"]), store=store)
    document = db.get(models.Document, run.document_id)
    assert b"SUPER-SECRET-KEY" not in store.get(document.storage_key)
    for issue in run.issues:
        assert "SUPER-SECRET-KEY" not in (issue.message or "")
        assert "SUPER-SECRET-KEY" not in json.dumps(issue.detail or {})


def test_redact_drops_only_the_key():
    params = {"appKey": "x", "targets": "111", "dataItems": "hly-air-tmp"}
    assert cimis._redact(params) == {"targets": "111", "dataItems": "hly-air-tmp"}


# --------------------------------------------------------------------------
# Parsing.
# --------------------------------------------------------------------------


def test_hourly_records_become_canonical_rows(db, client):
    adapter = cimis.CimisAdapter(api_key="k")
    rows, issues = adapter.parse(fixture("hourly_metric"), ctx_for(1))

    assert issues == []
    assert len(rows) == 3
    assert rows[0]["station_id"] == "111"
    assert rows[0]["observed_at"] == "2026-07-01T06:00:00"
    assert rows[0]["temperature_c"] == "14.8"
    assert rows[0]["relative_humidity_pct"] == "93.0"


def test_the_recorded_payload_carries_no_leaf_wetness_and_the_adapter_invents_none(
    db, client, store
):
    """We do not invent evidence. NEVER DELETE THIS TEST.

    CIMIS publishes no leaf-wetness item (verified 2026-08-05 against the hourly item
    catalog). Deriving wetness from relative humidity would be the same failure as
    guessing the Botrytis coefficients, one layer down — and worse, because a derived
    number arriving with `wetness_is_measured` set would look like a measurement.

    `wetness_is_measured` must be None, not False: False asserts "we have a wetness
    value and it is derived", which is also untrue. None means no wetness datum exists.
    """
    farm = make_farm(client)
    adapter = cimis.CimisAdapter(api_key="k", transport=transport_for("hourly_metric"))

    run = pipeline.run_source(db, adapter, ctx_for(farm["id"]), store=store)

    assert run.admitted_count == 3
    for obs in crud.list_weather_observations(db, farm["id"]):
        assert obs.leaf_wetness_minutes is None
        assert obs.wetness_is_measured is None

    # And nothing in the adapter's own output mentions wetness at all.
    rows, _ = adapter.parse(fixture("hourly_metric"), ctx_for(farm["id"]))
    for row in rows:
        assert "leaf_wetness_minutes" not in row
        assert "wetness_is_measured" not in row


def test_the_assessment_still_abstains_on_leaf_wetness_after_a_successful_ingest(
    db, client, store
):
    """The honest end state, asserted rather than described.

    This slice moves the binding blocker from `no_weather_in_window` (a software gap,
    now closed) to `no_leaf_wetness_or_accepted_proxy` (a sensor purchase). If this
    test ever shows the wetness reason gone without an on-site sensor appearing in the
    data, someone has started deriving it.
    """
    from app import disease_risk

    farm = make_farm(client)
    adapter = cimis.CimisAdapter(api_key="k", transport=transport_for("hourly_metric"))
    pipeline.run_source(db, adapter, ctx_for(farm["id"]), store=store)

    rows = crud.list_weather_observations(db, farm["id"])
    payload = {
        "as_of": (BASE_HOUR + timedelta(hours=6)).isoformat(),
        "weather": [
            {"observed_at": o.observed_at.isoformat(), "station_id": o.station_id,
             "station_distance_km": o.station_distance_km,
             "leaf_wetness_minutes": o.leaf_wetness_minutes,
             "wetness_is_measured": o.wetness_is_measured,
             "source_type": o.source_type}
            for o in rows
        ],
    }
    problems = disease_risk._weather_problems(payload)

    # The gap this slice closed:
    assert disease_risk.ABSTAIN_NO_WEATHER not in problems
    # The gap it deliberately did not:
    assert disease_risk.ABSTAIN_NO_LEAF_WETNESS in problems


def test_a_qc_flagged_reading_is_carried_through_and_then_excluded(db, client, store):
    """A station that doubts its own reading has told us not to average over it."""
    from app import pit

    farm = make_farm(client)
    adapter = cimis.CimisAdapter(api_key="k", transport=transport_for("hourly_qc_flagged"))
    pipeline.run_source(db, adapter, ctx_for(farm["id"]), store=store)

    rows = crud.list_weather_observations(db, farm["id"])
    flagged = [o for o in rows if o.quality_flag]
    assert len(flagged) == 1
    assert flagged[0].quality_flag == "M"
    # And point-in-time admissibility drops it for that reason specifically.
    assert pit.admissible(flagged[0], datetime(2030, 1, 1), set()) == (
        pit.EXCLUDED_QUALITY_FLAG
    )


def test_english_units_are_converted_through_units_rather_than_at_the_edge(
    db, client, store
):
    """The adapter declares the unit; `app/units.py` does the arithmetic, with citations."""
    farm = make_farm(client)
    adapter = cimis.CimisAdapter(
        api_key="k", transport=transport_for("hourly_english_units")
    )
    run = pipeline.run_source(db, adapter, ctx_for(farm["id"]), store=store)

    assert run.admitted_count == 1
    (obs,) = crud.list_weather_observations(db, farm["id"])
    assert obs.temperature_c == pytest.approx(14.8, abs=0.05)


def test_an_unreadable_response_is_an_issue_not_an_exception(db, client):
    adapter = cimis.CimisAdapter(api_key="k")
    rows, issues = adapter.parse(b"<html>gateway timeout</html>", ctx_for(1))
    assert rows == []
    assert issues[0].code == base.ISSUE_PARSE_FAILED


def test_an_empty_window_is_reported_rather_than_looking_successful(db, client):
    adapter = cimis.CimisAdapter(api_key="k")
    empty = json.dumps({"Data": {"Providers": [{"Records": []}]}}).encode()
    rows, issues = adapter.parse(empty, ctx_for(1))
    assert rows == []
    assert any("no records" in i.message for i in issues)


@pytest.mark.parametrize(
    "hour,expected",
    [("0000", (0, 0)), ("0600", (6, 0)), ("1330", (13, 30)), ("2400", (23, 59))],
)
def test_the_cimis_hour_encoding_is_decoded(hour, expected):
    """CIMIS writes hours as HHMM, and midnight-ending-the-day as 2400."""
    parsed = cimis._observed_at({"Date": "2026-07-01", "Hour": hour})
    assert (parsed.hour, parsed.minute) == expected


def test_a_malformed_timestamp_is_an_issue_and_the_rest_of_the_batch_survives():
    adapter = cimis.CimisAdapter(api_key="k")
    payload = json.dumps(
        {"Data": {"Providers": [{"Records": [
            {"Date": "", "Hour": "0600", "Station": "111"},
            {"Date": "2026-07-01", "Hour": "0700", "Station": "111",
             "HlyAirTmp": {"Value": "15.0", "Qc": " "}},
        ]}]}}
    ).encode()
    rows, issues = adapter.parse(payload, ctx_for(1))
    assert len(rows) == 1
    assert any(i.code == base.ISSUE_PARSE_FAILED for i in issues)


def test_only_requested_items_are_asked_for():
    """We do not fetch items we have nowhere to put — an unused column is a future
    temptation to invent a meaning for it."""
    assert cimis.HOURLY_ITEMS == ("hly-air-tmp", "hly-rel-hum", "hly-precip")
    assert not any("wetness" in item for item in cimis.HOURLY_ITEMS)


def test_every_fixture_states_that_it_was_hand_authored():
    """A fabricated fixture presented as a live capture is the ENGINEERING_GUIDELINES.md §9 failure
    one layer down. Each fixture carries its own provenance, and this checks it."""
    files = sorted(FIXTURES.glob("*.json"))
    assert files, "no CIMIS fixtures found"
    for path in files:
        provenance = json.loads(path.read_text()).get("_provenance")
        assert provenance, f"{path.name} has no _provenance block"
        assert "HAND-AUTHORED" in provenance["authored"]
        assert "not_a_capture" in provenance
