"""CSV pilot import: mapping, validation, duplicates, dry-run vs. commit, provenance.

Covers the pure module (app/csv_import.py) and the endpoints
(GET /import/templates/{type}.csv, POST /farms/{id}/import/csv).
"""
from app import csv_import

PLANNED_HEADER = (
    "Record ID,Field,Product,AI,Target,Date,Rate,Rate Unit,Cost,PHI,REI,"
    "Harvest Date,Acres,FRAC"
)


def _farm(client, **overrides):
    payload = {
        "name": "CSV Test Farm",
        "location": "Watsonville, CA",
        "country": "US",
        "crop_type": "strawberry",
        "greenhouse_area": 12.0,
        "expected_harvest_date": "2026-08-15",
    }
    payload.update(overrides)
    return client.post("/farms", json=payload).json()


def _import(client, farm_id, csv_text, record_type="planned_sprays", **kwargs):
    body = {"record_type": record_type, "csv_text": csv_text, **kwargs}
    resp = client.post(f"/farms/{farm_id}/import/csv", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ------------------------------------------------------------------ pure module
def test_header_alias_mapping():
    report = csv_import.parse_csv(
        "planned_sprays",
        PLANNED_HEADER + "\nR1,Block 2,Switch 62.5 WG,cyprodinil,gray mold,"
        "2026-07-20,14,oz/acre,210,0,12,2026-07-24,6,FRAC 9",
    )
    assert report.mapping["Product"] == "product_name"
    assert report.mapping["AI"] == "active_ingredient"
    assert report.mapping["PHI"] == "pre_harvest_interval_days"
    assert report.mapping["REI"] == "re_entry_interval_hours"
    assert report.mapping["FRAC"] == "moa_group"
    assert report.unmapped_headers == []
    assert report.missing_required_columns == []
    (row,) = report.rows
    assert row.importable
    assert row.values["intended_date"].isoformat() == "2026-07-20"
    assert row.values["rate_amount"] == 14.0


def test_mapping_override_and_ignore():
    csv_text = "Produkt,When,Mystery\nSwitch,2026-07-20,x"
    report = csv_import.parse_csv(
        "planned_sprays", csv_text,
        mapping_overrides={"Produkt": "product_name", "When": "intended_date",
                           "Mystery": "ignore"},
    )
    assert report.missing_required_columns == []
    (row,) = report.rows
    assert row.importable
    assert row.values["product_name"] == "Switch"


def test_unmapped_headers_and_missing_required_columns_are_reported():
    report = csv_import.parse_csv("planned_sprays", "Whatever,Stuff\na,b")
    assert set(report.unmapped_headers) == {"Whatever", "Stuff"}
    assert "product_name" in report.missing_required_columns
    assert "intended_date" in report.missing_required_columns
    assert not report.rows[0].importable


def test_invalid_values_error_and_regulatory_gaps_warn():
    csv_text = (
        "Product,Date,PHI\n"
        "Switch,not-a-date,0\n"          # bad date -> error
        "Captan,2026-07-20,-1\n"          # negative PHI -> error
        "Rally,2026-07-21,\n"             # missing PHI/REI -> warnings, still importable
    )
    report = csv_import.parse_csv("planned_sprays", csv_text)
    bad_date, bad_phi, ok = report.rows
    assert any("unrecognized date" in e for e in bad_date.errors)
    assert any("must be >= 0" in e for e in bad_phi.errors)
    assert ok.importable
    assert any("PHI missing" in w for w in ok.warnings)
    assert any("REI missing" in w for w in ok.warnings)
    assert any("product identity is ambiguous" in w for w in ok.warnings)


def test_incomplete_rate_pair_warns():
    report = csv_import.parse_csv(
        "planned_sprays", "Product,Date,Rate\nSwitch,2026-07-20,14"
    )
    (row,) = report.rows
    assert any("incomplete application rate" in w for w in row.warnings)


def test_in_file_duplicates_flagged():
    csv_text = (
        "Record ID,Product,Date\n"
        "R1,Switch,2026-07-20\n"
        "R1,Switch,2026-07-20\n"          # same external id -> duplicate
        ",Captan,2026-07-21\n"
        ",Captan,2026-07-21\n"            # same product+date -> duplicate
    )
    report = csv_import.parse_csv("planned_sprays", csv_text)
    assert report.rows[0].importable
    assert report.rows[1].duplicate_of == "row 1 in this file"
    assert report.rows[3].duplicate_of == "row 3 in this file"


def test_scouting_severity_needs_scale_outside_1_5():
    csv_text = (
        "Date,Pest,Severity,Scale\n"
        "2026-07-20,gray mold,7,\n"       # 7 with no scale -> error
        "2026-07-20,gray mold,7,1-10\n"   # scale stated -> importable
    )
    report = csv_import.parse_csv("scout_observations", csv_text)
    assert any("state the scale" in e for e in report.rows[0].errors)
    assert report.rows[1].importable


def test_template_example_row_is_never_importable():
    report = csv_import.parse_csv(
        "planned_sprays", csv_import.template_csv("planned_sprays")
    )
    (row,) = report.rows
    assert not row.importable
    assert any("example row" in e for e in row.errors)


# ------------------------------------------------------------------- endpoints
def test_template_download(client):
    resp = client.get("/import/templates/planned_sprays.csv")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    assert resp.text.splitlines()[0].startswith("external_record_id,")
    assert csv_import.TEMPLATE_EXAMPLE_MARKER in resp.text
    assert client.get("/import/templates/scout_observations.csv").status_code == 200
    assert client.get("/import/templates/nope.csv").status_code == 404


def test_dry_run_writes_nothing(client):
    farm = _farm(client)
    result = _import(
        client, farm["id"],
        "Product,Date\nSwitch,2026-07-20",
    )
    assert result["dry_run"] is True
    assert result["batch"] is None
    assert result["report"]["importable_count"] == 1
    assert client.get(f"/farms/{farm['id']}/planned-sprays").json() == []


def test_commit_creates_planned_sprays_with_full_provenance(client):
    farm = _farm(client)
    csv_text = (
        PLANNED_HEADER + "\n"
        "R1,Block 2,Switch 62.5 WG,cyprodinil + fludioxonil,gray mold,2026-07-20,"
        "14,oz/acre,210,0,12,2026-07-24,6,FRAC 9 + 12"
    )
    result = _import(
        client, farm["id"], csv_text, dry_run=False,
        source_filename="pca_recs.csv", imported_by="Operator",
    )
    assert result["committed"] is True
    assert result["batch"]["record_type"] == "planned_sprays"
    assert result["batch"]["planned_spray_count"] == 1

    (planned,) = client.get(f"/farms/{farm['id']}/planned-sprays").json()
    assert planned["data_source"] == "spreadsheet"
    assert planned["values_source"] == "imported_unverified"
    assert planned["source_filename"] == "pca_recs.csv"
    assert planned["external_record_id"] == "R1"
    assert planned["moa_group"] == "FRAC 9 + 12"
    assert planned["pilot_import_batch_id"] == result["batch"]["id"]

    # Imported values can NEVER auto-approve: the unverified rule escalates.
    assert planned["decision_outcome"] == "pca_review_required"
    assert planned["review_required"] is True
    assert planned["decision_authority"] == "provisional"
    rule = next(
        r for r in planned["decision_payload"]["rules"]
        if r["rule_id"] == "unverified_imported_values"
    )
    assert rule["triggered"] is True
    assert rule["source_authority"] == "imported_unverified"

    values = client.get(f"/planned-sprays/{planned['id']}/input-values").json()
    assert values, "field-level provenance rows must exist"
    assert all(v["source_type"] == "imported_unverified" for v in values)
    assert all(v["verified_by"] is None for v in values)
    reference = {v["source_reference"] for v in values}
    assert reference == {"pca_recs.csv row 1"}


def test_commit_skips_duplicates_against_existing_records(client):
    farm = _farm(client)
    csv_text = "Record ID,Product,Date\nR1,Switch,2026-07-20"
    first = _import(client, farm["id"], csv_text, dry_run=False)
    assert first["batch"]["planned_spray_count"] == 1
    second = _import(client, farm["id"], csv_text, dry_run=False)
    assert second["batch"]["planned_spray_count"] == 0
    assert second["report"]["duplicate_count"] == 1
    assert "already imported" in second["report"]["rows"][0]["duplicate_of"]
    assert len(client.get(f"/farms/{farm['id']}/planned-sprays").json()) == 1


def test_scouting_csv_commit(client):
    farm = _farm(client)
    csv_text = (
        "Date,Pest,Severity,Field,Observer\n"
        "2026-07-18,gray mold,3,Block 2,Sam Scout"
    )
    result = _import(
        client, farm["id"], csv_text, record_type="scout_observations",
        dry_run=False, source_filename="scouting.csv",
    )
    assert result["batch"]["scouting_observation_count"] == 1
    (obs,) = client.get(f"/farms/{farm['id']}/scout-observations").json()
    assert obs["visible_issue"] == "gray mold"
    assert obs["severity_1_to_5"] == 3
    assert obs["field_block"] == "Block 2"
    assert obs["observer"] == "Sam Scout"
    assert obs["data_source"] == "spreadsheet"
    assert obs["source_filename"] == "scouting.csv"
