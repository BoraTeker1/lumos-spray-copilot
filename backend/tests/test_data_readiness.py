"""The grower-facing readiness surface, and what it must never become.

`/farms/{id}/data-readiness` answers "can this farm's data support a measurement yet".
It is deliberately NOT under `/internal`: the answer to "why does my risk assessment
still say it did not run" belongs to the person whose farm it is.

Two properties are defended here rather than described:

  * An abstention is rendered as `{abstained, reasons}` with NO `value` key. A null in
    a numeric field is precisely what a template turns into `0` or `--`, and `0 kg/ha
    of active ingredient` is not a data gap — it is a pesticide-reduction claim.
  * The payload contains no product, rate, dose or action, at any nesting depth. A
    readiness card that drifted into "conditions look favourable" would be a spray
    prompt wearing a data-quality label, and would break the shadow study's blinding.
"""
import json
from datetime import datetime, timedelta

import pytest

from app import crud, models
from app.database import SessionLocal
from app.features import base, compute

AS_OF = datetime(2026, 7, 8, 6, 0, 0)


@pytest.fixture()
def db(client):
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def make_farm(client, name="Readiness Ranch"):
    return client.post(
        "/farms",
        json={"name": name, "location": "Watsonville, CA", "country": "US",
              "crop_type": "strawberry", "area": 20.0},
    ).json()


def make_field(db, farm_id, **kw):
    field = models.Field(farm_id=farm_id, name="Block A", **kw)
    db.add(field)
    db.commit()
    db.refresh(field)
    return field


# --------------------------------------------------------------------------
# Shape.
# --------------------------------------------------------------------------


def test_an_empty_farm_says_nothing_is_configured_rather_than_showing_zeroes(client):
    farm = make_farm(client)
    body = client.get(f"/farms/{farm['id']}/data-readiness").json()

    assert body["fields"] == []
    assert body["ingestion"]["runs"] == 0
    assert "No outside data source is configured" in body["basis_text"]
    # Not a risk statement, not a recommendation.
    assert "spray" not in body["basis_text"].lower()


def test_a_missing_farm_is_a_404(client):
    assert client.get("/farms/9999/data-readiness").status_code == 404


def test_an_abstained_measure_carries_reasons_and_no_value_key(db, client):
    """The single most important shape in this payload.

    If `value: null` ever appears, some template downstream renders it as 0 or as a
    dash, and a farm with no wetness sensor starts looking like a farm with no wetness.
    """
    farm = make_farm(client)
    field = make_field(db, farm["id"])

    spec = base.get("leaf_wetness_hours")
    result, digest = compute.compute_one(db, spec, field.id, AS_OF)
    assert result.abstained  # no weather at all yet
    compute.persist(db, spec, field.id, AS_OF, result, digest, farm_id=farm["id"])

    body = client.get(f"/farms/{farm['id']}/data-readiness").json()
    (entry,) = body["fields"]
    measure = entry["measures"]["leaf_wetness_hours"]

    assert measure["abstained"] is True
    assert measure["reasons"], "an abstention must say why"
    assert "value" not in measure, (
        "a null value key is what a template turns into 0 or --"
    )


def test_a_computed_measure_carries_a_value_and_unit_and_no_abstention(db, client):
    farm = make_farm(client)
    field = make_field(db, farm["id"], centroid_lat=36.91, centroid_lon=-121.75)

    db.add(models.WeatherObservation(
        farm_id=farm["id"], field_id=field.id, station_id="111",
        station_distance_km=3.0, observed_at=AS_OF - timedelta(hours=2),
        recorded_at=AS_OF - timedelta(hours=2), temperature_c=15.0,
        source_type="station_export", data_source="provider_api",
        data_confidence="provider_reported",
    ))
    db.commit()

    spec = base.get("weather_data_staleness_hours")
    result, digest = compute.compute_one(db, spec, field.id, AS_OF)
    compute.persist(db, spec, field.id, AS_OF, result, digest, farm_id=farm["id"])

    body = client.get(f"/farms/{farm['id']}/data-readiness").json()
    measure = body["fields"][0]["measures"]["weather_data_staleness_hours"]

    assert measure["value"] == pytest.approx(2.0)
    assert measure["unit"] == "h"
    assert "abstained" not in measure


def test_the_latest_as_of_wins_rather_than_the_most_recently_computed(db, client):
    """Backfilling an older `as_of` is legitimate and must not look like the present."""
    farm = make_farm(client)
    field = make_field(db, farm["id"])
    spec = base.get("weather_observation_coverage_pct")

    older = AS_OF - timedelta(days=2)
    for as_of in (AS_OF, older):  # newest computed FIRST, then the backfill
        result, digest = compute.compute_one(db, spec, field.id, as_of)
        compute.persist(db, spec, field.id, as_of, result, digest, farm_id=farm["id"])

    rows = crud.list_feature_values_for_farm(db, farm["id"])
    (row,) = [r for r in rows if r.name == spec.name]
    assert row.as_of == AS_OF


# --------------------------------------------------------------------------
# The structural guarantee.
# --------------------------------------------------------------------------


FORBIDDEN = ("product", "rate", "dose", "apply", "spray", "tank", "mix", "recommend",
             "action")


def _walk_keys(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from _walk_keys(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_keys(item)


def test_a_pesticide_recommendation_stays_structurally_inexpressible(db, client):
    """Recursive key scan, not a spot check.

    `FeatureResult` has no product/rate/action field, so one cannot arrive through a
    measure. This guards the ENVELOPE too — someone adding a helpful "suggested action"
    alongside the measures would be adding a prescription to a grower-facing card.
    """
    farm = make_farm(client)
    field = make_field(db, farm["id"])
    spec = base.get("leaf_wetness_hours")
    result, digest = compute.compute_one(db, spec, field.id, AS_OF)
    compute.persist(db, spec, field.id, AS_OF, result, digest, farm_id=farm["id"])

    body = client.get(f"/farms/{farm['id']}/data-readiness").json()
    for key in _walk_keys(body):
        lowered = str(key).lower()
        assert not any(word in lowered for word in FORBIDDEN), (
            f"readiness payload grew a key named {key!r}"
        )


def test_the_payload_carries_no_risk_band(db, client):
    """Blinding: a risk-shaped field here would leak the shadow study."""
    farm = make_farm(client)
    body = json.dumps(client.get(f"/farms/{farm['id']}/data-readiness").json()).lower()
    for band in ("risk_band", "moderate", "elevated", "favourable", "favorable"):
        assert band not in body


def test_the_basis_text_is_server_owned_and_present(db, client):
    """The card renders this string and writes none of its own.

    Four compliance surfaces once hardcoded their own wording and drifted apart; this
    surface starts on the right side of that lesson.
    """
    farm = make_farm(client)
    body = client.get(f"/farms/{farm['id']}/data-readiness").json()
    assert body["basis_text"]
    assert isinstance(body["basis_text"], str)


def test_a_credential_less_source_is_described_as_such_not_as_a_failure(db, client):
    """An inert deployment is correctly configured, not broken."""
    from app.ingest import base as ingest_base

    farm = make_farm(client)
    db.add(models.IngestionRun(
        source_key="cimis_hourly", domain="climate", farm_id=farm["id"],
        status=ingest_base.RUN_SKIPPED_NO_CREDENTIAL,
    ))
    db.commit()

    body = client.get(f"/farms/{farm['id']}/data-readiness").json()
    assert "no credential" in body["basis_text"].lower()
    assert "hand-entered" in body["basis_text"]


def test_provider_data_is_described_as_unreviewed(db, client):
    """`provider_reported` is real data of a specific, limited kind.

    The sentence must never imply a PCA looked at it — that would be a claim with
    legal weight about a machine-fetched number.
    """
    from app.ingest import base as ingest_base

    farm = make_farm(client)
    db.add(models.IngestionRun(
        source_key="cimis_hourly", domain="climate", farm_id=farm["id"],
        status=ingest_base.RUN_SUCCEEDED, admitted_count=24,
    ))
    db.commit()

    body = client.get(f"/farms/{farm['id']}/data-readiness").json()
    assert "not PCA-verified" in body["basis_text"]


# --------------------------------------------------------------------------
# Operator routes.
# --------------------------------------------------------------------------


def test_the_operator_can_list_runs_with_their_counts_and_issues(db, client):
    from app.ingest import base as ingest_base

    farm = make_farm(client)
    run = models.IngestionRun(
        source_key="cimis_hourly", domain="climate", farm_id=farm["id"],
        status=ingest_base.RUN_SUCCEEDED, fetched_count=24, admitted_count=3,
        duplicate_count=0, issue_count=21,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    db.add(models.IngestionIssue(
        ingestion_run_id=run.id, stage="align", severity="error",
        code=ingest_base.ISSUE_NO_FIELD_GEOLOCATION, message="no centroid",
    ))
    db.commit()

    body = client.get("/internal/ingestion").json()
    (entry,) = body["runs"]
    # The gap between fetched and admitted is the whole point of showing counts.
    assert entry["counts"]["fetched"] == 24
    assert entry["counts"]["admitted"] == 3
    assert entry["issues"][0]["code"] == ingest_base.ISSUE_NO_FIELD_GEOLOCATION


def test_running_a_source_enqueues_rather_than_fetching_inline(db, client):
    """Retries, dead-lettering and stall recovery live in the worker.

    A route that fetched directly would be a second execution path with none of them.
    """
    farm = make_farm(client)
    response = client.post(
        "/internal/ingestion/cimis_hourly/run",
        json={"farm_id": farm["id"], "station_id": "111", "lookback_hours": 6},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending"
    assert body["source"]["source_key"] == "cimis_hourly"

    job = db.get(models.Job, body["job_id"])
    assert job.task_name == "ingest.run_source"
    assert job.queue == "ingest"
    # Nothing was fetched.
    assert db.query(models.IngestionRun).count() == 0


def test_running_an_unknown_source_is_a_404(client):
    farm = make_farm(client)
    response = client.post(
        "/internal/ingestion/no_such_source/run",
        json={"farm_id": farm["id"], "station_id": "111"},
    )
    assert response.status_code == 404


def test_a_deferred_finance_source_cannot_be_run(db, client):
    """It is declared, so it resolves; it has no adapter, so the job cannot execute.

    The route accepting it is fine — the guardrail is that `build_adapter` raises, so
    the work can never actually happen.
    """
    from app.ingest import registry

    farm = make_farm(client)
    response = client.post(
        "/internal/ingestion/credit_bureau/run",
        json={"farm_id": farm["id"], "station_id": "n/a"},
    )
    assert response.status_code == 200
    with pytest.raises(registry.SourceError):
        registry.build_adapter("credit_bureau")
