"""AI label extraction: the draft path, and what it is structurally unable to do.

The extraction endpoint reads a regulatory document and proposes regulatory values,
which makes it the highest-consequence AI call in the system. The tests that matter
here are the ones asserting it CANNOT shortcut anything: it never writes a record,
a committed row is never verified, and a verification is an attributed act by a
licensed PCA rather than a field anyone can set.

Every value in this file is fictional. Nothing here may be copied into
`app/label_table.py`.
"""
from datetime import date, timedelta

import pytest

from app import label_extraction, label_data, models
from app.database import SessionLocal

TOKEN_HEADER = "X-Lumos-Pca-Token"
TODAY = date.today()


def _row(**overrides):
    row = {
        "epa_reg_no": "99999-1",
        "product_name": "Mock Fungicide 50WG",
        "registrant": "Fictional Crop Science",
        "registered_crop": "Strawberries",
        "target_pest_or_disease": "botrytis_fruit_rot",
        "pre_harvest_interval_days": 0,
        "re_entry_interval_hours": 12,
        "max_applications_per_season": 2,
        "label_version": "mock-rev-1",
        "label_effective_date": "2025-01-01",
        "source_document_reference": "fictional test label, not a real document",
        "source_section_or_page": "Directions for Use, p. 1",
        "source_snippet": "Fictional directions used only to exercise the commit path.",
        "reviewed_by": "Operator",
    }
    row.update(overrides)
    return row


def _farm(client, name="Extraction Farm"):
    return client.post("/farms", json={
        "name": name, "country": "US", "crop_type": "strawberry", "area_unit": "acres",
        "expected_harvest_date": (TODAY + timedelta(days=30)).isoformat(),
    }).json()


def _credentialed_pca(client, farm_id):
    """Issue a credential AND authorize it for the farm — both are required."""
    cred = client.post("/internal/pca-credentials", json={
        "display_name": "Dana PCA", "license_identifier": "PCA-12345",
        "license_state": "CA", "issued_by": "pilot-operator",
    }).json()
    auth = client.post(
        f"/internal/pca-credentials/{cred['id']}/farm-authorizations",
        json={"farm_id": farm_id, "granted_by": "pilot-operator"},
    )
    assert auth.status_code == 201, auth.text
    return cred


# ------------------------------------------------------------- the pure module
def test_the_mock_builder_is_registered_so_tests_never_hit_the_real_api():
    from app import llm

    service = llm.MockLlmService()
    result, model_id = service.parse(
        label_extraction.build_system_prompt(),
        label_extraction.build_content_blocks(text="Directions for use..."),
        label_extraction.LabelExtraction,
    )
    assert model_id == "mock"
    assert result.rows


def test_the_system_prompt_forbids_inference_and_unit_conversion():
    """The two rules whose violation would produce a wrong regulatory value."""
    prompt = label_extraction.build_system_prompt().lower()

    assert "only what is literally printed" in prompt
    assert "do not convert" in prompt
    assert "one row per (crop, use) block" in prompt
    assert "abstained=true" in prompt


def test_upload_guards_are_imported_not_redefined():
    """A second copy of the limits would drift from the one the CSV path enforces."""
    from app import extraction

    assert label_extraction.MAX_DOCUMENT_BYTES is extraction.MAX_DOCUMENT_BYTES
    assert label_extraction.ALLOWED_DOCUMENT_TYPES is extraction.ALLOWED_DOCUMENT_TYPES
    assert label_extraction.build_content_blocks is extraction.build_content_blocks


def test_the_input_digest_covers_the_prompt_version_and_the_input():
    a = label_extraction.input_digest(text="same label text")
    b = label_extraction.input_digest(text="same label text")
    c = label_extraction.input_digest(text="different label text")

    assert a == b
    assert a != c


def test_the_mock_values_are_obviously_fictional():
    """A realistic-looking mock would eventually be mistaken for a real label."""
    payload = label_extraction.extraction_payload(
        label_extraction._mock_label([{"type": "text", "text": "label"}]),
        "mock", is_mock=True,
    )
    row = payload["rows"][0]

    assert "mock" in row["product_name"].lower()
    assert "fictional" in row["source_snippet"].lower()
    assert row["row_confidence"] == "low"
    assert payload["is_mock"] is True


# ---------------------------------------------------------------- extract
def test_extraction_returns_draft_rows_and_writes_nothing(client):
    res = client.post(
        "/internal/labels/extract",
        data={"text": "Directions for use: apply to strawberries..."},
    )

    assert res.status_code == 200
    body = res.json()
    assert body["extraction"]["rows"]
    assert body["extraction"]["disclaimer"]
    # The load-bearing assertion: no record, no product, nothing stored.
    assert client.get("/internal/labels/products").json() == []


def test_extraction_logs_an_append_only_judgment(client):
    res = client.post("/internal/labels/extract", data={"text": "Directions for use..."})

    judgment_id = res.json()["judgment_id"]
    with SessionLocal() as db:
        judgment = db.get(models.AiJudgment, judgment_id)
        assert judgment.kind == "label_extraction"
        assert judgment.prompt_version == label_extraction.PROMPT_VERSION
        assert judgment.is_mock is True
        assert judgment.input_digest


def test_a_non_label_document_abstains(client):
    res = client.post("/internal/labels/extract", data={"text": "mock-abstain: an invoice"})

    extraction = res.json()["extraction"]
    assert extraction["abstained"] is True
    assert extraction["rows"] == []
    assert extraction["abstain_reason"]


def test_an_abstention_is_recorded_as_one(client):
    res = client.post("/internal/labels/extract", data={"text": "mock-abstain"})

    with SessionLocal() as db:
        judgment = db.get(models.AiJudgment, res.json()["judgment_id"])
        assert judgment.abstained is True
        assert judgment.confidence == "none"


def test_extraction_requires_a_file_or_text(client):
    assert client.post("/internal/labels/extract", data={}).status_code == 422
    assert client.post("/internal/labels/extract", data={"text": "   "}).status_code == 422


def test_an_unsupported_file_type_is_refused(client):
    res = client.post(
        "/internal/labels/extract",
        files={"file": ("label.exe", b"binary", "application/x-msdownload")},
    )
    assert res.status_code == 400
    assert "Unsupported file type" in res.json()["detail"]


# ----------------------------------------------------------------- commit
def test_a_committed_row_is_ai_extracted_unverified(client):
    res = client.post("/internal/labels/records", json=_row())

    assert res.status_code == 201, res.text
    record = res.json()
    assert record["source_tier"] == label_data.TIER_AI_EXTRACTED
    assert record["transcribed_by"] == "Operator"


def test_a_client_cannot_declare_its_own_row_verified(client):
    """`source_tier` is server-set; sending one must not change the stored tier."""
    res = client.post("/internal/labels/records", json={
        **_row(), "source_tier": label_data.TIER_PCA_VERIFIED,
    })

    assert res.status_code == 201
    assert res.json()["source_tier"] == label_data.TIER_AI_EXTRACTED


def test_a_committed_row_still_cannot_back_a_decision(client):
    """Committing is on-file, not in-force. This is the whole point of the tier."""
    farm = _farm(client)
    client.post("/internal/labels/records", json=_row())

    body = client.get("/internal/labels/resolution", params={
        "epa_reg_no": "99999-1", "crop": "strawberry", "farm_id": farm["id"],
    }).json()

    assert body["label_record"] is not None
    assert body["promotable"] is False
    assert "no licensed PCA has verified" in body["promotion_blocked_reason"]


def test_committing_a_corrected_row_supersedes_rather_than_edits(client):
    first = client.post("/internal/labels/records", json=_row()).json()
    second = client.post(
        "/internal/labels/records", json=_row(pre_harvest_interval_days=3)
    ).json()

    assert second["supersedes_label_record_id"] == first["id"]
    records = client.get("/internal/labels/products").json()[0]["label_records"]
    assert len(records) == 2  # the original stays readable


@pytest.mark.parametrize("bad", [
    {"source_snippet": ""},
    {"source_document_reference": ""},
    {"label_version": ""},
    {"registered_crop": ""},
    {"reviewed_by": ""},
])
def test_a_row_without_its_citation_is_refused(client, bad):
    """Without these a record could never be promoted — storing it is pointless."""
    assert client.post("/internal/labels/records", json=_row(**bad)).status_code == 422


def test_a_row_stating_no_regulatory_value_is_refused(client):
    res = client.post("/internal/labels/records", json=_row(
        pre_harvest_interval_days=None, re_entry_interval_hours=None,
        max_applications_per_season=None,
    ))
    assert res.status_code == 422


def test_a_seasonal_rate_without_its_unit_is_refused(client):
    res = client.post(
        "/internal/labels/records", json=_row(max_seasonal_rate_amount=4.0)
    )
    assert res.status_code == 422


# ----------------------------------------------------------- verification
def test_a_pca_verification_promotes_the_record(client):
    farm = _farm(client)
    record = client.post("/internal/labels/records", json=_row()).json()
    credential = _credentialed_pca(client, farm["id"])

    res = client.post(
        f"/farms/{farm['id']}/label-verifications",
        json={"product_label_record_id": record["id"],
              "attestation": "Checked against the fictional test label, page 1."},
        headers={TOKEN_HEADER: credential["token"]},
    )

    assert res.status_code == 201, res.text
    assert res.json()["verified_by"] == "Dana PCA"
    body = client.get("/internal/labels/resolution", params={
        "epa_reg_no": "99999-1", "crop": "strawberry", "farm_id": farm["id"],
    }).json()
    assert body["promotable"] is True


def test_verification_without_a_credential_is_refused(client):
    farm = _farm(client)
    record = client.post("/internal/labels/records", json=_row()).json()

    res = client.post(
        f"/farms/{farm['id']}/label-verifications",
        json={"product_label_record_id": record["id"],
              "attestation": "I checked it, honestly."},
    )

    assert res.status_code == 403


def test_a_credential_not_authorized_for_this_farm_is_refused(client):
    """Farm scope is the point of the model — a PCA vouches per farm, not globally."""
    authorized_farm = _farm(client, "Authorized Farm")
    other_farm = _farm(client, "Other Farm")
    record = client.post("/internal/labels/records", json=_row()).json()
    credential = _credentialed_pca(client, authorized_farm["id"])

    res = client.post(
        f"/farms/{other_farm['id']}/label-verifications",
        json={"product_label_record_id": record["id"],
              "attestation": "Checked against the fictional test label, page 1."},
        headers={TOKEN_HEADER: credential["token"]},
    )

    assert res.status_code == 403


def test_attribution_comes_from_the_credential_not_the_request(client):
    farm = _farm(client)
    record = client.post("/internal/labels/records", json=_row()).json()
    credential = _credentialed_pca(client, farm["id"])

    res = client.post(
        f"/farms/{farm['id']}/label-verifications",
        json={
            "product_label_record_id": record["id"],
            "attestation": "Checked against the fictional test label, page 1.",
            "verified_by": "Somebody Else",  # ignored — not a field on the schema
        },
        headers={TOKEN_HEADER: credential["token"]},
    )

    assert res.json()["verified_by"] == "Dana PCA"
    assert res.json()["verified_by_credential_id"] == credential["id"]


def test_a_thin_attestation_is_refused(client):
    farm = _farm(client)
    record = client.post("/internal/labels/records", json=_row()).json()
    credential = _credentialed_pca(client, farm["id"])

    res = client.post(
        f"/farms/{farm['id']}/label-verifications",
        json={"product_label_record_id": record["id"], "attestation": "ok"},
        headers={TOKEN_HEADER: credential["token"]},
    )

    assert res.status_code == 422


def test_verifying_an_unknown_record_is_404(client):
    farm = _farm(client)
    credential = _credentialed_pca(client, farm["id"])

    res = client.post(
        f"/farms/{farm['id']}/label-verifications",
        json={"product_label_record_id": 999,
              "attestation": "Checked against the fictional test label, page 1."},
        headers={TOKEN_HEADER: credential["token"]},
    )

    assert res.status_code == 404


def test_there_is_no_route_that_revokes_by_deleting(client):
    """Revocation is a timestamp — a decision that relied on an attestation stays
    attributable after it is withdrawn (same rule as PcaCredential)."""
    from app.main import app

    for route in app.routes:
        path = getattr(route, "path", "")
        if "label-verification" in path:
            assert "DELETE" not in set(getattr(route, "methods", set()))
