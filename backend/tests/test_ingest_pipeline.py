"""The eight stages, driven by a FakeAdapter. No network anywhere in this file.

The properties here are the ones that decide whether a weather feed can be trusted as
evidence, rather than merely trusted to run:

  * Re-running a window changes nothing. Without this, a scheduler blip double-counts
    wetness inside a risk window and silently changes a snapshot digest.
  * A row we cannot place in space is dropped, not written with a NULL distance.
    `disease_risk` reads a NULL distance as in-range AND as close, so a null here would
    quietly earn a better evidence grade than the data supports.
  * A unit refusal drops the row and records no number. A reading that silently stayed
    in Fahrenheit is worse than a missing reading.
  * Ingestion onto a demo farm produces demo rows, and both guards that check for that
    read DIFFERENT columns — so the test checks both.
"""
from datetime import datetime, timedelta

import pytest

from app import clock, crud, disease_risk, models, pit, storage
from app.database import SessionLocal
from app.ingest import base, pipeline
from app.ingest.base import (
    FetchResult,
    IngestContext,
    Issue,
    SourceDescriptor,
)

STATION = "CIMIS-111"
# Watsonville-ish field, station ~3 km away.
FIELD_LAT, FIELD_LON = 36.9102, -121.7569
STATION_LAT, STATION_LON = 36.9300, -121.7700

BASE_HOUR = datetime(2026, 7, 1, 6, 0, 0)


@pytest.fixture()
def db(client):
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def store(tmp_path):
    """A file-backed object store rooted in the test's tmp dir."""
    return storage.LocalFileStore(str(tmp_path / "objects"))


class FakeAdapter:
    """A source adapter with no network and total control over what it returns."""

    def __init__(self, rows, *, status=base.SOURCE_IMPLEMENTED, parse_issues=None,
                 blocker=None, raise_on_fetch=None):
        self._rows = rows
        self._status = status
        self._parse_issues = parse_issues or []
        self._blocker = blocker
        self._raise_on_fetch = raise_on_fetch
        self.fetch_calls = 0

    def describe(self):
        return SourceDescriptor(
            source_key="fake_weather", domain="climate", title="Fake weather",
            provider="test", status=self._status, adapter_version="1",
            blocker=self._blocker,
        )

    def fetch(self, ctx):
        self.fetch_calls += 1
        if self._raise_on_fetch:
            raise self._raise_on_fetch
        return FetchResult(raw=b'{"fake":true}', content_type="application/json",
                           filename="fake.json")

    def parse(self, raw, ctx):
        return list(self._rows), list(self._parse_issues)


def rows_for(hours=3, **overrides):
    """Canonical-field rows, the shape `csv_import.validate_rows` expects."""
    out = []
    for i in range(hours):
        row = {
            "station_id": STATION,
            "station_name": "Watsonville West",
            "observed_at": (BASE_HOUR + timedelta(hours=i)).isoformat(),
            "temperature_c": "15.0",
            "relative_humidity_pct": "92.0",
            "rainfall_mm": "0.0",
        }
        row.update(overrides)
        out.append(row)
    return out


def ctx_for(farm_id, field_id=None, **kw):
    defaults = dict(
        farm_id=farm_id, field_id=field_id, station_id=STATION,
        window_start=BASE_HOUR, window_end=BASE_HOUR + timedelta(hours=24),
        station_lat=STATION_LAT, station_lon=STATION_LON,
        field_lat=FIELD_LAT, field_lon=FIELD_LON,
    )
    defaults.update(kw)
    return IngestContext(**defaults)


def make_farm(client, **kw):
    payload = {
        "name": "Ingest Test Ranch", "location": "Watsonville, CA", "country": "US",
        "crop_type": "strawberry", "area": 40.0,
    }
    payload.update(kw)
    return client.post("/farms", json=payload).json()


# --------------------------------------------------------------------------
# The credential gate.
# --------------------------------------------------------------------------


def test_an_adapter_without_a_credential_is_never_asked_to_fetch(db, client, store):
    """Inert by construction: the pipeline checks `describe()` before anything else.

    If this regresses, a deployment with no API key starts making network calls — and
    the "no credential, no traffic" claim in DATA_PLATFORM.md becomes false.
    """
    farm = make_farm(client)
    adapter = FakeAdapter(
        rows_for(), status=base.SOURCE_REQUIRES_CREDENTIAL,
        blocker="Set LUMOS_FAKE_KEY to enable this source.",
    )

    run = pipeline.run_source(db, adapter, ctx_for(farm["id"]), store=store)

    assert adapter.fetch_calls == 0
    assert run.status == base.RUN_SKIPPED_NO_CREDENTIAL
    assert run.admitted_count == 0
    assert db.query(models.WeatherObservation).count() == 0
    (issue,) = run.issues
    assert issue.code == base.ISSUE_NO_CREDENTIAL
    assert "LUMOS_FAKE_KEY" in issue.message


def test_a_skipped_run_is_not_recorded_as_a_failure(db, client, store):
    """A correctly-configured deployment that cannot fetch is not broken.

    Recording it as `failed` would make the operator's dead/failed count permanently
    non-zero and train them to ignore the one column that matters.
    """
    farm = make_farm(client)
    adapter = FakeAdapter([], status=base.SOURCE_REQUIRES_CREDENTIAL, blocker="no key")
    run = pipeline.run_source(db, adapter, ctx_for(farm["id"]), store=store)
    assert run.status != base.RUN_FAILED
    assert run.error is None


# --------------------------------------------------------------------------
# The happy path, and the idempotency property.
# --------------------------------------------------------------------------


def test_a_successful_run_stores_the_raw_response_and_writes_placed_rows(db, client, store):
    farm = make_farm(client)
    adapter = FakeAdapter(rows_for(hours=3))

    run = pipeline.run_source(db, adapter, ctx_for(farm["id"]), store=store)

    assert run.status == base.RUN_SUCCEEDED
    assert run.admitted_count == 3
    observations = crud.list_weather_observations(db, farm["id"])
    assert len(observations) == 3

    obs = observations[0]
    assert obs.source_type == "station_export"
    assert obs.data_source == "provider_api"
    assert obs.data_confidence == "provider_reported"
    assert obs.ingestion_run_id == run.id
    # Haversine, not a guess and not a zero.
    assert 2.0 < obs.station_distance_km < 4.0

    # The raw bytes are retained, subject-linked to the run.
    document = db.get(models.Document, run.document_id)
    assert document.kind == storage.KIND_RAW_INGESTION
    assert document.subject_type == "ingestion_run"
    assert document.subject_id == run.id
    assert store.get(document.storage_key) == b'{"fake":true}'


def test_rerunning_the_same_window_persists_nothing_new(db, client, store):
    """The definition-of-done property for the whole ingestion layer.

    A scheduler that fires twice, a retried job, an operator clicking run again — all
    of them must be free. If this fails, wetness inside a risk window is double-counted
    and every snapshot digest built over that window silently changes.
    """
    farm = make_farm(client)
    ctx = ctx_for(farm["id"])

    first = pipeline.run_source(db, FakeAdapter(rows_for(hours=5)), ctx, store=store)
    assert first.admitted_count == 5
    after_first = crud.list_weather_observations(db, farm["id"])

    second = pipeline.run_source(db, FakeAdapter(rows_for(hours=5)), ctx, store=store)

    assert second.status == base.RUN_SUCCEEDED
    assert second.admitted_count == 0
    assert second.duplicate_count == 5
    after_second = crud.list_weather_observations(db, farm["id"])
    assert [o.id for o in after_first] == [o.id for o in after_second]


def test_a_changed_value_appends_a_correction_rather_than_editing(db, client, store):
    """A station revising an hour is a new row pointing back at the old one.

    Editing in place would rewrite history a stored snapshot may already have used.
    """
    farm = make_farm(client)
    ctx = ctx_for(farm["id"])

    pipeline.run_source(db, FakeAdapter(rows_for(hours=1)), ctx, store=store)
    revised = pipeline.run_source(
        db, FakeAdapter(rows_for(hours=1, temperature_c="17.5")), ctx, store=store
    )

    assert revised.superseded_count == 1
    rows = crud.list_weather_observations(db, farm["id"])
    assert len(rows) == 2
    correction = [r for r in rows if r.supersedes_id is not None][0]
    assert correction.temperature_c == 17.5
    # And the old reading is excluded from any point-in-time view.
    live = crud.live_weather_by_station_hour(db, farm["id"])
    assert list(live.values())[0].id == correction.id


def test_an_identical_refetch_is_not_treated_as_a_correction(db, client, store):
    """Only a changed VALUE supersedes. The clock moving is not a change."""
    farm = make_farm(client)
    ctx = ctx_for(farm["id"])
    pipeline.run_source(db, FakeAdapter(rows_for(hours=2)), ctx, store=store)
    run = pipeline.run_source(db, FakeAdapter(rows_for(hours=2)), ctx, store=store)
    assert run.superseded_count == 0
    assert crud.list_weather_observations(db, farm["id"]).__len__() == 2


# --------------------------------------------------------------------------
# Dropping rows: geolocation, units, stations.
# --------------------------------------------------------------------------


def test_a_row_that_cannot_be_placed_is_dropped_rather_than_written_with_a_null(
    db, client, store
):
    """No centroid, no row.

    This is the load-bearing one. `disease_risk._weather_problems` treats
    `station_distance_km is None` as IN RANGE, and `evidence_grade` filters Nones out of
    the distance list and then treats an empty list as CLOSE. A machine writing 24 rows
    a day with a null distance would therefore look like a station sitting on the field.
    A human leaving one cell blank is a different risk; that path is untouched.
    """
    farm = make_farm(client)
    ctx = ctx_for(farm["id"], field_lat=None, field_lon=None)

    run = pipeline.run_source(db, FakeAdapter(rows_for(hours=3)), ctx, store=store)

    assert run.admitted_count == 0
    assert db.query(models.WeatherObservation).count() == 0
    codes = {i.code for i in run.issues}
    assert base.ISSUE_NO_FIELD_GEOLOCATION in codes
    assert all(
        "dropped" in i.message for i in run.issues
        if i.code == base.ISSUE_NO_FIELD_GEOLOCATION
    )


def test_a_unit_refusal_drops_the_row_and_records_an_issue_with_no_number(
    db, client, store
):
    """A refusal carries a reason and never a value — and neither does its record.

    If a number leaked into the issue detail, someone would eventually read it back as
    data. `units.Refusal` has exactly one field for exactly this reason.
    """
    farm = make_farm(client)
    # A temperature in a unit the canonical vocabulary does not contain.
    rows = rows_for(hours=1, temperature_c="59.0")
    rows[0]["temperature_unit"] = "rankine"

    run = pipeline.run_source(db, FakeAdapter(rows), ctx_for(farm["id"]), store=store)

    assert run.admitted_count == 0
    (issue,) = [i for i in run.issues if i.code == base.ISSUE_UNIT_REFUSAL]
    assert "temperature_c" in issue.message
    assert issue.detail == {"refusal": issue.message}
    # No numeric value anywhere in the recorded issue.
    assert "59" not in issue.message
    assert "59" not in str(issue.detail)


def test_a_known_unit_is_converted_rather_than_refused(db, client, store):
    """The other half: `units` is reused, so Fahrenheit becomes Celsius, cited."""
    farm = make_farm(client)
    rows = rows_for(hours=1, temperature_c="59.0")
    rows[0]["temperature_unit"] = "F"

    run = pipeline.run_source(db, FakeAdapter(rows), ctx_for(farm["id"]), store=store)

    assert run.admitted_count == 1
    (obs,) = crud.list_weather_observations(db, farm["id"])
    assert obs.temperature_c == pytest.approx(15.0)


def test_a_reading_from_an_unrequested_station_is_an_issue_not_a_silent_join(
    db, client, store
):
    """Resolution is deterministic from the context the operator stated.

    A provider returning a neighbouring station's data must never be joined to this
    field just because it arrived in the same response.
    """
    farm = make_farm(client)
    rows = rows_for(hours=2) + rows_for(hours=1, station_id="CIMIS-999")

    run = pipeline.run_source(db, FakeAdapter(rows), ctx_for(farm["id"]), store=store)

    assert run.admitted_count == 2
    (issue,) = [i for i in run.issues if i.code == base.ISSUE_UNREQUESTED_STATION]
    assert "CIMIS-999" in issue.message


def test_an_invalid_row_is_recorded_and_the_rest_of_the_batch_still_lands(
    db, client, store
):
    """Issues are recorded, never raised. One bad hour must not lose a backfill."""
    farm = make_farm(client)
    rows = rows_for(hours=2) + [
        {"station_id": STATION, "observed_at": "not-a-timestamp", "temperature_c": "15"}
    ]

    run = pipeline.run_source(db, FakeAdapter(rows), ctx_for(farm["id"]), store=store)

    assert run.status == base.RUN_SUCCEEDED
    assert run.admitted_count == 2
    assert any(i.code == base.ISSUE_ROW_INVALID for i in run.issues)


def test_a_negative_temperature_survives_the_validator(db, client, store):
    """The frost night reaches the table. Guards the FieldSpec.signed fix end to end."""
    farm = make_farm(client)
    run = pipeline.run_source(
        db, FakeAdapter(rows_for(hours=1, temperature_c="-2.5")),
        ctx_for(farm["id"]), store=store,
    )
    assert run.admitted_count == 1
    (obs,) = crud.list_weather_observations(db, farm["id"])
    assert obs.temperature_c == -2.5


# --------------------------------------------------------------------------
# Demo separation — two guards, two different columns.
# --------------------------------------------------------------------------


def test_ingestion_onto_a_demo_farm_writes_demo_rows_excluded_by_both_guards(
    db, client, store
):
    """A simulated reading must be unable to reach a real number.

    Two independent guards check for this and they read DIFFERENT fields:
    `pit.admissible` reads `data_source`/`data_confidence`, while
    `disease_risk._weather_problems` reads `source_type`. A writer that set only one
    would pass one guard and fail the other, so this test checks both.
    """
    farm = make_farm(client)
    # Make the farm demo the way the rest of the system does: via a demo record.
    client.post(
        f"/farms/{farm['id']}/spray-events",
        json={
            "product_name": "Captan 80 WDG", "application_date": "2026-06-01",
            "data_source": "demo", "data_confidence": "simulated",
        },
    )

    ctx = ctx_for(farm["id"], is_demo=True)
    run = pipeline.run_source(db, FakeAdapter(rows_for(hours=2)), ctx, store=store)

    assert run.admitted_count == 2
    rows = crud.list_weather_observations(db, farm["id"])
    # `as_of` well after ingest, so the ONLY reason left to exclude is the demo tag.
    # (An earlier `as_of` would return `recorded_after_as_of` and the test would pass
    # while proving nothing about demo separation.)
    as_of = clock.current_datetime() + timedelta(days=1)
    for obs in rows:
        assert obs.data_source == "demo"
        assert obs.data_confidence == "simulated"
        assert obs.source_type == "demo"
        # Guard 1: point-in-time admissibility.
        assert pit.admissible(obs, as_of, set()) == pit.EXCLUDED_DEMO_OR_MOCK

    # Guard 2: the disease model, which reads source_type instead.
    payload = {
        "as_of": as_of.isoformat(),
        "weather": [
            {"observed_at": o.observed_at.isoformat(), "station_id": o.station_id,
             "station_distance_km": o.station_distance_km,
             "leaf_wetness_minutes": o.leaf_wetness_minutes,
             "source_type": o.source_type}
            for o in rows
        ],
    }
    assert disease_risk.ABSTAIN_DEMO_INPUT in disease_risk._weather_problems(payload)


def test_a_real_run_onto_a_demo_farm_is_refused(db, client, store):
    """The mixing guard still applies to a batch write."""
    farm = make_farm(client)
    client.post(
        f"/farms/{farm['id']}/spray-events",
        json={
            "product_name": "Captan 80 WDG", "application_date": "2026-06-01",
            "data_source": "demo", "data_confidence": "simulated",
        },
    )

    run = pipeline.run_source(
        db, FakeAdapter(rows_for(hours=2)), ctx_for(farm["id"], is_demo=False), store=store
    )

    assert run.status == base.RUN_FAILED
    assert "demo" in (run.error or "").lower()
    assert db.query(models.WeatherObservation).count() == 0


# --------------------------------------------------------------------------
# The two-timestamp rule, at the point of writing.
# --------------------------------------------------------------------------


def test_recorded_at_is_ingest_time_and_is_never_backdated_to_observed_at(
    db, client, store
):
    """Backfilling history must not fabricate knowledge of it.

    Stamping `recorded_at = observed_at` on a 30-day backfill would assert we knew a
    month ago what we learned today — the exact hindsight leak `app/pit.py` exists to
    prevent. The uncomfortable and correct consequence is asserted below: a backtest
    whose `as_of` precedes the backfill finds NO admissible weather.
    """
    farm = make_farm(client)
    # A window well in the past.
    old_rows = rows_for(hours=3)
    run = pipeline.run_source(db, FakeAdapter(old_rows), ctx_for(farm["id"]), store=store)
    assert run.admitted_count == 3

    for obs in crud.list_weather_observations(db, farm["id"]):
        assert obs.recorded_at > obs.observed_at
        # As_of one day after the observation but before ingest: inadmissible.
        assert pit.admissible(obs, BASE_HOUR + timedelta(days=1), set()) == (
            pit.EXCLUDED_RECORDED_LATE
        )


def test_the_ingestion_link_does_not_change_the_snapshot_payload(db, client, store):
    """Adding `ingestion_run_id` must leave every stored snapshot digest untouched.

    `risk_snapshot._weather_payload` serializes nine named fields. If someone adds the
    run link to it, every previously stored digest becomes unreproducible and every
    calibration join silently breaks.
    """
    from app import risk_snapshot

    farm = make_farm(client)
    pipeline.run_source(db, FakeAdapter(rows_for(hours=1)), ctx_for(farm["id"]), store=store)
    (obs,) = crud.list_weather_observations(db, farm["id"])

    payload = risk_snapshot._weather_payload(obs)
    assert "ingestion_run_id" not in payload
    assert set(payload) == {
        "observed_at", "station_id", "station_distance_km", "temperature_c",
        "relative_humidity_pct", "rainfall_mm", "leaf_wetness_minutes",
        "wetness_is_measured", "source_type",
    }


# --------------------------------------------------------------------------
# Failure handling.
# --------------------------------------------------------------------------


def test_an_adapter_that_raises_records_a_failed_run_rather_than_exploding(
    db, client, store
):
    farm = make_farm(client)
    adapter = FakeAdapter([], raise_on_fetch=RuntimeError("provider timeout"))

    run = pipeline.run_source(db, adapter, ctx_for(farm["id"]), store=store)

    assert run.status == base.RUN_FAILED
    assert "provider timeout" in run.error
    assert db.query(models.WeatherObservation).count() == 0


def test_the_request_digest_is_built_from_the_redacted_context_only(db, client, store):
    """A credential must never reach a digest, because a digest is stored."""
    farm = make_farm(client)
    ctx = ctx_for(farm["id"])
    assert "appKey" not in str(ctx.as_request_payload())
    assert set(ctx.as_request_payload()) == {
        "farm_id", "field_id", "station_id", "window_start", "window_end"
    }
    run = pipeline.run_source(db, FakeAdapter(rows_for(hours=1)), ctx, store=store)
    assert len(run.request_digest) == 64


# --------------------------------------------------------------------------
# The job layer: scheduling, idempotency, dead-lettering.
# --------------------------------------------------------------------------


def test_the_weather_fanout_is_idempotent_within_an_hourly_bucket(db, client):
    """A schedule that fires twice in one hour must enqueue one job per subscription.

    The queue's live idempotency key does the work; this pins that the key we build is
    actually distinct per (source, farm, station, bucket) and stable within the bucket.
    """
    from app.ingest import tasks as ingest_tasks

    farm = make_farm(client)
    payload = {
        "subscriptions": [
            {"farm_id": farm["id"], "field_id": None, "station_id": STATION}
        ]
    }
    first = ingest_tasks.enqueue_due_weather(db, payload)
    second = ingest_tasks.enqueue_due_weather(db, payload)

    assert len(first["enqueued"]) == 1
    assert first["enqueued"] == second["enqueued"], "the second call created a new job"


def test_a_malformed_subscription_is_skipped_rather_than_guessed_at(db):
    from app.ingest import tasks as ingest_tasks

    parsed = ingest_tasks.parse_subscriptions("1:2:CIMIS-111,garbage,,3::CIMIS-222")
    assert parsed == [
        {"farm_id": 1, "field_id": 2, "station_id": "CIMIS-111"},
        {"farm_id": 3, "field_id": None, "station_id": "CIMIS-222"},
    ]


def test_no_subscriptions_configured_enqueues_nothing(db):
    from app.ingest import tasks as ingest_tasks

    assert ingest_tasks.parse_subscriptions(None) == []
    assert ingest_tasks.enqueue_due_weather(db, {"subscriptions": []})["enqueued"] == []


def test_both_ingest_tasks_are_registered_for_the_worker():
    """The worker imports app.ingest.tasks; if that import is dropped, a claimed job
    dead-letters after five attempts with 'unknown task'."""
    from app.jobs import registry as job_registry

    registered = job_registry.registered()
    assert "ingest.run_source" in registered
    assert "ingest.enqueue_due_weather" in registered
    assert registered["ingest.run_source"].queue == "ingest"


def test_the_hourly_weather_schedule_is_on_the_schedules_tuple():
    from app.jobs import schedule as job_schedule

    names = {s.task_name for s in job_schedule.SCHEDULES}
    assert "ingest.enqueue_due_weather" in names
