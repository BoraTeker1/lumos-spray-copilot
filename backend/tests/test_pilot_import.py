"""CSV import of the pilot record types (weather readings, scouting samples).

Reuses the existing dry-run/validate/commit path, so what is tested here is the
behaviour specific to these types: a dry run predicts the commit exactly, a re-import
is reported rather than silently written, provenance survives, and nothing about a
reading is inferred — not its hour, not its wetness provenance, not its block.
"""
from datetime import date, timedelta

import pytest


def _farm(client, name="Import Farm"):
    res = client.post("/farms", json={
        "name": name, "country": "US", "crop_type": "strawberry",
        "expected_harvest_date": (date.today() + timedelta(days=30)).isoformat(),
    })
    assert res.status_code == 201
    return res.json()


def _block(client, farm_id, name="North 1"):
    res = client.post(f"/farms/{farm_id}/blocks", json={"name": name})
    assert res.status_code == 201
    return res.json()


def _import(client, farm_id, record_type, csv_text, dry_run=True, **extra):
    payload = {
        "record_type": record_type, "csv_text": csv_text, "dry_run": dry_run,
        "source_filename": "pilot.csv", "imported_by": "ops",
    }
    payload.update(extra)
    return client.post(f"/farms/{farm_id}/import/csv", json=payload)


WEATHER_CSV = (
    "station,timestamp,temp c,rh,leaf wetness,wetness measured,distance km\n"
    "CIMIS-111,2026-07-18 05:00,13.9,95,60,measured,3.2\n"
    "CIMIS-111,2026-07-18 06:00,14.6,93,60,measured,3.2\n"
)

SAMPLE_CSV = (
    "record id,block,date,method,pest,inspected,affected,scout\n"
    "S-1,North 1,2026-07-18 08:30,fruit_count,botrytis,100,4,Sam\n"
    "S-2,North 1,2026-07-19 08:30,fruit_count,botrytis,100,9,Sam\n"
)


# ------------------------------------------------------------- templates
@pytest.mark.parametrize("record_type", ["weather_observations", "scouting_samples"])
def test_template_downloads_and_its_example_row_can_never_import(client, record_type):
    farm = _farm(client)
    template = client.get(f"/import/templates/{record_type}.csv")
    assert template.status_code == 200

    res = _import(client, farm["id"], record_type, template.text)
    assert res.status_code == 200
    report = res.json()["report"]
    assert report["importable_count"] == 0
    assert any("example row" in e for r in report["rows"] for e in r["errors"])


# --------------------------------------------------------------- dry run
def test_dry_run_writes_nothing(client):
    farm = _farm(client)
    res = _import(client, farm["id"], "weather_observations", WEATHER_CSV)
    assert res.status_code == 200
    body = res.json()
    assert body["dry_run"] is True and body["committed"] is False
    assert body["report"]["importable_count"] == 2
    assert client.get(f"/farms/{farm['id']}/weather-observations").json() == []


def test_commit_writes_rows_with_import_provenance(client):
    farm = _farm(client)
    res = _import(client, farm["id"], "weather_observations", WEATHER_CSV, dry_run=False)
    assert res.status_code == 200
    body = res.json()
    assert body["committed"] is True
    assert body["batch"]["weather_observation_count"] == 2

    rows = client.get(f"/farms/{farm['id']}/weather-observations").json()
    assert len(rows) == 2
    assert all(r["source_type"] == "imported_unverified" for r in rows), (
        "imported readings are never silently treated as verified"
    )
    assert all(r["data_source"] == "spreadsheet" for r in rows)
    assert rows[0]["observed_at"].startswith("2026-07-18T05:00")


# ------------------------------------------------------------ duplicates
def test_reimporting_the_same_file_reports_duplicates_and_writes_nothing_new(client):
    farm = _farm(client)
    _import(client, farm["id"], "weather_observations", WEATHER_CSV, dry_run=False)

    again = _import(client, farm["id"], "weather_observations", WEATHER_CSV, dry_run=False)
    report = again.json()["report"]
    assert report["duplicate_count"] == 2
    assert report["importable_count"] == 0
    assert len(client.get(f"/farms/{farm['id']}/weather-observations").json()) == 2


def test_duplicate_hour_inside_one_file_is_reported(client):
    farm = _farm(client)
    doubled = WEATHER_CSV + "CIMIS-111,2026-07-18 06:00,14.6,93,60,measured,3.2\n"
    report = _import(client, farm["id"], "weather_observations", doubled).json()["report"]
    assert report["duplicate_count"] == 1
    assert any("in this file" in (r["duplicate_of"] or "") for r in report["rows"])


# -------------------------------------------------- nothing is inferred
def test_a_date_without_an_hour_is_refused_for_an_hourly_reading(client):
    """Collapsing a reading to midnight would put it in the wrong wetness hour."""
    farm = _farm(client)
    csv_text = "station,timestamp,temp c\nCIMIS-111,2026-07-18,13.9\n"
    report = _import(client, farm["id"], "weather_observations", csv_text).json()["report"]
    assert report["importable_count"] == 0
    assert any("needs its hour" in e for r in report["rows"] for e in r["errors"])


def test_unrecognised_wetness_provenance_is_an_error_not_a_false(client):
    """Silently reading False would present a derived value as a measurement."""
    farm = _farm(client)
    csv_text = (
        "station,timestamp,leaf wetness,wetness measured\n"
        "CIMIS-111,2026-07-18 05:00,60,probably\n"
    )
    report = _import(client, farm["id"], "weather_observations", csv_text).json()["report"]
    assert report["importable_count"] == 0
    assert any("yes/no value" in e for r in report["rows"] for e in r["errors"])


def test_missing_wetness_warns_that_the_assessment_will_abstain(client):
    farm = _farm(client)
    csv_text = "station,timestamp,temp c\nCIMIS-111,2026-07-18 05:00,13.9\n"
    report = _import(client, farm["id"], "weather_observations", csv_text).json()["report"]
    warnings = [w for r in report["rows"] for w in r["warnings"]]
    assert any("abstain" in w for w in warnings)
    assert any("distance cannot be assumed" in w for w in warnings)


# ------------------------------------------------------- scouting samples
def test_sample_import_derives_incidence_and_links_the_named_block(client):
    farm = _farm(client)
    block = _block(client, farm["id"], "North 1")

    res = _import(client, farm["id"], "scouting_samples", SAMPLE_CSV, dry_run=False)
    assert res.status_code == 200
    assert res.json()["batch"]["scouting_sample_count"] == 2

    rows = client.get(f"/farms/{farm['id']}/scouting-samples").json()
    assert [r["incidence_pct"] for r in rows] == [4.0, 9.0]
    assert all(r["block_id"] == block["id"] for r in rows)


def test_sample_naming_an_unknown_block_fails_in_the_dry_run(client):
    """A dry run that says 'importable' and then fails at commit is worse than none."""
    farm = _farm(client)  # no blocks created
    report = _import(client, farm["id"], "scouting_samples", SAMPLE_CSV).json()["report"]
    assert report["importable_count"] == 0
    assert any("does not exist on this farm" in e
               for r in report["rows"] for e in r["errors"])


def test_sample_with_more_affected_than_inspected_is_refused(client):
    farm = _farm(client)
    _block(client, farm["id"], "North 1")
    bad = (
        "record id,block,date,method,pest,inspected,affected\n"
        "S-9,North 1,2026-07-18 08:30,fruit_count,botrytis,10,11\n"
    )
    report = _import(client, farm["id"], "scouting_samples", bad).json()["report"]
    assert report["importable_count"] == 0
    assert any("exceeds units_inspected" in e for r in report["rows"] for e in r["errors"])


def test_unknown_sampling_method_is_refused_not_coerced(client):
    farm = _farm(client)
    _block(client, farm["id"], "North 1")
    bad = (
        "record id,block,date,method,pest,inspected,affected\n"
        "S-9,North 1,2026-07-18 08:30,eyeballing,botrytis,100,4\n"
    )
    report = _import(client, farm["id"], "scouting_samples", bad).json()["report"]
    assert report["importable_count"] == 0
    assert any("not a recognised sampling method" in e
               for r in report["rows"] for e in r["errors"])


def test_severity_index_without_a_scale_is_dropped_not_stored_as_comparable(client):
    farm = _farm(client)
    _block(client, farm["id"], "North 1")
    csv_text = (
        "record id,block,date,method,pest,inspected,affected,severity\n"
        "S-7,North 1,2026-07-18 08:30,fruit_count,botrytis,100,4,3\n"
    )
    res = _import(client, farm["id"], "scouting_samples", csv_text, dry_run=False)
    assert res.status_code == 200
    row = client.get(f"/farms/{farm['id']}/scouting-samples").json()[0]
    assert row["severity_index"] is None, (
        "a severity with no scale cannot be compared to anything, so it is not stored "
        "as if it could be"
    )


# ------------------------------------------------------------ AI extraction
@pytest.mark.parametrize("record_type", ["weather_observations", "scouting_samples"])
def test_ai_document_extraction_is_not_offered_for_pilot_types(client, record_type):
    """A mis-extracted hour or denominator would corrupt a snapshot silently."""
    farm = _farm(client)
    res = client.post(
        f"/farms/{farm['id']}/import/document",
        data={"record_type": record_type, "pasted_text": "some text"},
    )
    assert res.status_code == 422
