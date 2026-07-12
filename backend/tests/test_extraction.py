"""AI document extraction: dry-run only, judgment logging, abstention, commit path.

Runs entirely on the deterministic MockLlmService (no API key in tests)."""
import pytest


@pytest.fixture(autouse=True)
def pinned_clock_and_mock(monkeypatch):
    monkeypatch.setenv("LUMOS_DEMO_TODAY", "2026-07-15")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # Force the mock regardless of the developer machine's env.
    from app import llm, main
    monkeypatch.setattr(main.llm, "default_llm_service", llm.MockLlmService())


def _farm(client):
    return client.post("/farms", json={
        "name": "Extraction Farm", "country": "US", "crop_type": "strawberry",
        "expected_harvest_date": "2026-08-20", "greenhouse_area": 10.0,
    }).json()


def _extract(client, farm_id, text="Apply Switch per PCA rec", record_type="planned_sprays"):
    resp = client.post(
        f"/farms/{farm_id}/import/document",
        data={"record_type": record_type, "text": text},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_extraction_returns_dry_run_and_writes_nothing(client):
    farm = _farm(client)
    result = _extract(client, farm["id"])

    assert result["extraction"]["is_mock"] is True
    assert result["extraction"]["disclaimer"].startswith("AI-extracted draft rows")
    (row,) = result["extraction"]["rows"]
    assert row["source_snippet"]  # verbatim snippet travels with every row
    assert result["report"]["importable_count"] == 1
    # The same regulatory honesty as CSV: nothing written yet.
    assert client.get(f"/farms/{farm['id']}/planned-sprays").json() == []


def test_extraction_logs_an_append_only_judgment(client):
    farm = _farm(client)
    result = _extract(client, farm["id"])
    jid = result["judgment_id"]
    assert isinstance(jid, int)
    # No mutation endpoints exist for judgments.
    for method in ("patch", "put", "delete"):
        resp = getattr(client, method)(f"/ai-judgments/{jid}")
        assert resp.status_code in (404, 405)


def test_abstention_path(client):
    farm = _farm(client)
    result = _extract(client, farm["id"], text="This is an invoice MOCK-ABSTAIN")
    assert result["extraction"]["abstained"] is True
    assert result["extraction"]["abstain_reason"]
    assert result["extraction"]["rows"] == []
    assert result["report"]["total_rows"] == 0


def test_rejects_missing_input_and_bad_record_type(client):
    farm = _farm(client)
    resp = client.post(
        f"/farms/{farm['id']}/import/document", data={"record_type": "planned_sprays"}
    )
    assert resp.status_code == 422
    resp = client.post(
        f"/farms/{farm['id']}/import/document",
        data={"record_type": "nope", "text": "x"},
    )
    assert resp.status_code == 422


def test_commit_via_import_rows_full_provenance(client):
    farm = _farm(client)
    result = _extract(client, farm["id"])
    rows = [
        {k: v for k, v in row.items()
         if k not in ("source_snippet", "row_confidence") and v is not None}
        for row in result["extraction"]["rows"]
    ]
    commit = client.post(f"/farms/{farm['id']}/import/rows", json={
        "record_type": "planned_sprays",
        "rows": rows,
        "dry_run": False,
        "source_label": "PCA email (AI-extracted)",
        "imported_by": "Operator",
        "ai_judgment_id": result["judgment_id"],
    }).json()
    assert commit["committed"] is True
    assert commit["batch"]["ai_judgment_id"] == result["judgment_id"]

    (planned,) = client.get(f"/farms/{farm['id']}/planned-sprays").json()
    assert planned["data_source"] == "ai_extracted"
    assert planned["values_source"] == "imported_unverified"
    # AI-extracted values can NEVER auto-approve: unverified rule escalates.
    assert planned["decision_outcome"] == "pca_review_required"
    assert planned["review_required"] is True
    assert planned["decision_authority"] == "provisional"
    values = client.get(f"/planned-sprays/{planned['id']}/input-values").json()
    assert values and all(v["source_type"] == "imported_unverified" for v in values)


def test_import_rows_revalidates_bad_and_duplicate_rows(client):
    farm = _farm(client)
    # Bad date: rejected by the same validator as CSV, even if the client "fixed" rows.
    result = client.post(f"/farms/{farm['id']}/import/rows", json={
        "record_type": "planned_sprays",
        "rows": [{"product_name": "Switch", "intended_date": "someday"}],
        "dry_run": False,
    }).json()
    assert result["report"]["error_count"] == 1
    assert result["created_record_ids"] == []

    ok_row = {"product_name": "Switch", "intended_date": "2026-07-20"}
    first = client.post(f"/farms/{farm['id']}/import/rows", json={
        "record_type": "planned_sprays", "rows": [ok_row], "dry_run": False,
    }).json()
    assert len(first["created_record_ids"]) == 1
    second = client.post(f"/farms/{farm['id']}/import/rows", json={
        "record_type": "planned_sprays", "rows": [ok_row], "dry_run": False,
    }).json()
    assert second["report"]["duplicate_count"] == 1
    assert second["created_record_ids"] == []


def test_row_validation_matches_csv_validation():
    """Same rows through validate_rows and parse_csv produce the same verdicts."""
    from app import csv_import

    csv_text = (
        "Product,Date,PHI\n"
        "Switch,2026-07-20,0\n"
        "Rally,not-a-date,1\n"
    )
    via_csv = csv_import.parse_csv("planned_sprays", csv_text)
    via_rows = csv_import.validate_rows("planned_sprays", [
        {"product_name": "Switch", "intended_date": "2026-07-20",
         "pre_harvest_interval_days": "0"},
        {"product_name": "Rally", "intended_date": "not-a-date",
         "pre_harvest_interval_days": "1"},
    ])
    for a, b in zip(via_csv.rows, via_rows.rows):
        assert a.importable == b.importable
        assert a.errors == b.errors
        assert a.warnings == b.warnings


def test_scouting_extraction_commit(client):
    farm = _farm(client)
    result = _extract(client, farm["id"], record_type="scout_observations")
    rows = [
        {k: v for k, v in row.items()
         if k not in ("source_snippet", "row_confidence") and v is not None}
        for row in result["extraction"]["rows"]
    ]
    commit = client.post(f"/farms/{farm['id']}/import/rows", json={
        "record_type": "scout_observations", "rows": rows, "dry_run": False,
        "ai_judgment_id": result["judgment_id"],
    }).json()
    assert commit["batch"]["scouting_observation_count"] == 1
    (obs,) = client.get(f"/farms/{farm['id']}/scout-observations").json()
    assert obs["data_source"] == "ai_extracted"
    assert obs["visible_issue"] == "gray mold"
