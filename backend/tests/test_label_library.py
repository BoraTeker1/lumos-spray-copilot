"""The label library: loading transcriptions, append-only revisions, and resolution.

Two guarantees matter more than the routes themselves. The first is that every shipped
transcription carries a citation back to a primary document, and that the table is
loaded ONLY by an explicit operator act — never by seeding or startup. (This test file
used to assert the table was empty. It is no longer empty: two real EPA labels were
transcribed on 2026-07-28. The empty assertion was always a proxy for the real rule —
"transcribed from a primary document with its citation, or not there" — so the proxy
was replaced with the rule, not deleted.) The second is that the loader never issues an
UPDATE: a corrected transcription appends a superseding row, so the value a decision
relied on last month is still readable.
"""
from datetime import date, timedelta

import pytest

from app import crud, label_data, label_table, models
from app.database import SessionLocal


def _use(**overrides):
    """A syntactically valid transcription. The VALUES are fictional on purpose.

    Nothing here is a real label. These tests exercise the loader's mechanics, and a
    realistic-looking PHI in a test file is exactly how an uncited number gets copied
    into `label_table.py` by someone who assumes it was checked.
    """
    row = {
        "epa_reg_no": "99999-1",
        "product_name": "Test Fungicide 50WG",
        "registrant": "Fictional Crop Science",
        "registered_crop": "Strawberries",
        "target_pest_or_disease": "botrytis_fruit_rot",
        "pre_harvest_interval_days": 1,
        "re_entry_interval_hours": 12,
        "max_applications_per_season": 2,
        "min_retreatment_interval_days": 7,
        "active_ingredient": "test-ai",
        "moa_group": "TEST-1",
        "label_version": "test-rev-1",
        "label_effective_date": date(2025, 1, 1),
        "source_document_reference": "fictional test label, not a real document",
        "source_section_or_page": "Directions for Use, p. 1",
        "source_snippet": "Fictional directions used only to exercise the loader.",
        "transcribed_by": "test suite",
    }
    row.update(overrides)
    return label_table.TranscribedLabelUse(**row)


def _load(monkeypatch, entries):
    monkeypatch.setattr(label_table, "TRANSCRIBED_LABEL_USES", tuple(entries))
    with SessionLocal() as db:
        return crud.sync_transcribed_labels(db)


def _farm(client, name="Label Farm"):
    return client.post("/farms", json={
        "name": name, "country": "US", "crop_type": "strawberry", "area_unit": "acres",
        "expected_harvest_date": (date.today() + timedelta(days=30)).isoformat(),
    }).json()


# ------------------------------------------------------- the shipped transcriptions
def test_every_shipped_transcription_cites_a_primary_document():
    """Load-bearing. See label_table.py's docstring before ever changing this.

    A value in this table ends up in a record a licensed PCA is entitled to trust and an
    auditor may read. It is transcribed from a primary document with its citation, or it
    is not there. Construction already refuses a blank citation; this asserts the
    citation is substantive enough for a second person to re-find the document and check
    the transcription, which is the only thing that makes it verifiable.
    """
    for use in label_table.TRANSCRIBED_LABEL_USES:
        where = f"{use.product_name} ({use.epa_reg_no}) / {use.registered_crop}"
        # A locator someone can act on, not just a non-empty string.
        assert len(use.source_document_reference) >= 40, where
        assert use.epa_reg_no in use.source_document_reference, where
        # Which part of the document — a reader must not have to search 47 pages.
        assert len(use.source_section_or_page) >= 10, where
        # The words the values were read from, so a checker compares text to text.
        assert len(use.source_snippet) >= 40, where
        assert isinstance(use.label_effective_date, date), where
        assert use.transcribed_by.strip(), where


def test_no_shipped_transcription_claims_to_be_verified():
    """A transcription is on file, never in force — whoever typed it, however carefully.

    `sync_transcribed_labels` sets the tier itself, so this asserts the property that
    would actually break: nothing in the shipped table can describe itself as verified,
    because promotion is a licensed PCA's act against a specific farm.
    """
    for use in label_table.TRANSCRIBED_LABEL_USES:
        assert not hasattr(use, "source_tier")
        assert "verified" not in use.transcribed_by.lower().replace("unverified", "")


def test_seeding_never_loads_the_transcription_table(monkeypatch):
    """The guard that matters most now that the table is NOT empty.

    Seeded label data would make demo decisions look label-grounded — a fabricated
    regulatory claim, which is ENGINEERING_GUIDELINES.md §9 applied to the one kind of value where it
    matters most. `seed.run()` and `init_db()` must never reach the loader.
    """
    from app import database, seed

    calls = []
    monkeypatch.setattr(
        crud, "sync_transcribed_labels", lambda *a, **k: calls.append(1)
    )
    seed.run()
    database.init_db()

    assert calls == [], "seeding or init_db loaded the label table"
    with SessionLocal() as db:
        assert crud.list_pesticide_products(db) == []


def test_sync_on_an_empty_table_creates_nothing_and_says_so(client, monkeypatch):
    monkeypatch.setattr(label_table, "TRANSCRIBED_LABEL_USES", ())

    res = client.post("/internal/labels/sync")

    assert res.status_code == 200
    assert res.json() == {
        "transcribed_entries": 0, "products_created": 0, "records_created": 0,
        "records_superseded": 0, "unchanged": 0, "notes": [],
    }
    assert client.get("/internal/labels/products").json() == []


# ---------------------------------------------------------------- transcription
def test_a_transcription_becomes_a_product_and_an_unverified_record(client, monkeypatch):
    result = _load(monkeypatch, [_use()])

    assert (result.products_created, result.records_created) == (1, 1)
    products = client.get("/internal/labels/products").json()
    assert len(products) == 1
    record = products[0]["label_records"][0]
    # However careful the transcriber, this is unverified until a PCA attests to it.
    assert record["source_tier"] == label_data.TIER_TRANSCRIBED
    assert record["registered_crop_normalized"] == "strawberries"
    assert record["transcription_digest"]


def test_reloading_an_unchanged_transcription_is_a_no_op(client, monkeypatch):
    _load(monkeypatch, [_use()])
    result = _load(monkeypatch, [_use()])

    assert (result.records_created, result.unchanged) == (0, 1)
    assert len(client.get("/internal/labels/products").json()[0]["label_records"]) == 1


def test_a_corrected_transcription_appends_a_superseding_row(client, monkeypatch):
    """The original stays readable — that is what makes a correction auditable."""
    _load(monkeypatch, [_use(pre_harvest_interval_days=1)])
    result = _load(monkeypatch, [_use(pre_harvest_interval_days=3)])

    assert (result.records_created, result.records_superseded) == (1, 1)
    records = client.get("/internal/labels/products").json()[0]["label_records"]
    assert len(records) == 2
    original = next(r for r in records if r["supersedes_label_record_id"] is None)
    revision = next(r for r in records if r["supersedes_label_record_id"] is not None)
    assert original["pre_harvest_interval_days"] == 1
    assert revision["pre_harvest_interval_days"] == 3
    assert revision["supersedes_label_record_id"] == original["id"]


def test_conflicting_product_metadata_is_reported_never_silently_overwritten(
    client, monkeypatch
):
    """Whoever synced last must not get to resolve a factual disagreement."""
    _load(monkeypatch, [_use(active_ingredient="test-ai")])
    result = _load(monkeypatch, [
        _use(active_ingredient="something-else", registered_crop="Tomatoes"),
    ])

    assert any("active_ingredient" in note for note in result.notes)
    product = client.get("/internal/labels/products").json()[0]
    assert product["active_ingredient"] == "test-ai"


def test_two_crops_on_one_product_are_two_records(client, monkeypatch):
    result = _load(monkeypatch, [_use(), _use(registered_crop="Tomatoes")])

    assert (result.products_created, result.records_created) == (1, 2)


# ------------------------------------------------------------------- resolution
def test_resolution_without_a_registration_number_says_so(client):
    res = client.get("/internal/labels/resolution", params={"crop": "strawberry"})

    body = res.json()
    assert body["label_record"] is None
    assert "no EPA registration number" in body["unresolved_reason"]


def test_a_base_registration_match_is_refused_with_the_reason(client, monkeypatch):
    """`99999-1` and `99999-1-2222` are different labels. Guessing applies the wrong PHI."""
    _load(monkeypatch, [_use(epa_reg_no="99999-1")])

    body = client.get("/internal/labels/resolution", params={
        "epa_reg_no": "99999-1-2222", "crop": "strawberry",
    }).json()

    assert body["label_record"] is None
    assert "supplemental registration is a different label" in body["unresolved_reason"]


def test_a_resolved_record_is_still_not_promotable_without_a_pca_verification(
    client, monkeypatch
):
    """The state a fresh transcription sits in: values on file, nobody has checked them."""
    farm = _farm(client)
    _load(monkeypatch, [_use()])

    body = client.get("/internal/labels/resolution", params={
        "epa_reg_no": "99999-1", "crop": "strawberry", "farm_id": farm["id"],
    }).json()

    assert body["label_record"] is not None
    assert body["promotable"] is False
    assert "no licensed PCA has verified" in body["promotion_blocked_reason"]


def test_a_verification_promotes_only_the_farm_it_was_recorded_for(client, monkeypatch):
    """A PCA authorized for one farm must not vouch for another farm's decisions."""
    verified_farm = _farm(client, "Verified Farm")
    other_farm = _farm(client, "Other Farm")
    _load(monkeypatch, [_use()])
    credential = client.post("/internal/pca-credentials", json={
        "display_name": "Dana PCA", "license_identifier": "PCA-12345",
        "license_state": "CA", "issued_by": "pilot-operator",
    }).json()

    with SessionLocal() as db:
        record = db.query(models.ProductLabelRecord).one()
        db.add(models.ProductLabelVerification(
            product_label_record_id=record.id,
            farm_id=verified_farm["id"],
            verified_by_credential_id=credential["id"],
            verified_by="Dana PCA",
            attestation="Checked against the fictional test label, p. 1.",
            data_source="manual_entry",
            data_confidence="user_provided",
        ))
        db.commit()

    params = {"epa_reg_no": "99999-1", "crop": "strawberry"}
    verified = client.get("/internal/labels/resolution", params={
        **params, "farm_id": verified_farm["id"],
    }).json()
    other = client.get("/internal/labels/resolution", params={
        **params, "farm_id": other_farm["id"],
    }).json()

    assert verified["promotable"] is True
    assert verified["promotion_blocked_reason"] is None
    assert other["promotable"] is False
    assert "no licensed PCA has verified" in other["promotion_blocked_reason"]


def test_resolution_with_no_farm_never_reports_promotable(client, monkeypatch):
    """An unscoped query must not become the global "verified" flag the design rejected."""
    _load(monkeypatch, [_use()])

    body = client.get("/internal/labels/resolution", params={
        "epa_reg_no": "99999-1", "crop": "strawberry",
    }).json()

    assert body["label_record"] is not None
    assert body["promotable"] is False


def test_an_unknown_farm_is_404(client):
    res = client.get("/internal/labels/resolution", params={"farm_id": 999})
    assert res.status_code == 404


def test_an_unknown_product_is_404(client):
    assert client.get("/internal/labels/products/999").status_code == 404


# ------------------------------------------------------------------ append-only
def test_there_is_no_route_that_edits_or_deletes_a_label_record():
    """Corrections go through the supersede chain, not through an UPDATE."""
    from app.main import app

    for route in app.routes:
        path = getattr(route, "path", "")
        if "label" not in path:
            continue
        assert not (set(getattr(route, "methods", set())) & {"PATCH", "PUT", "DELETE"}), (
            f"{path} exposes a mutating method on append-only label data"
        )


def test_no_request_schema_can_set_a_verified_source_tier():
    """Promotion to label-verified is an attributed PCA act, never a request field."""
    from app import schemas

    for name in dir(schemas):
        model = getattr(schemas, name)
        fields = getattr(model, "model_fields", None)
        if not fields or name in {"ProductLabelRecord", "LabelResolution"}:
            continue
        assert "source_tier" not in fields, (
            f"schemas.{name} exposes source_tier — a client could claim a verified label"
        )


@pytest.mark.parametrize("entry_kwargs", [
    {"source_snippet": ""},
    {"label_version": " "},
    {"transcribed_by": ""},
])
def test_a_transcription_missing_its_citation_cannot_be_constructed(entry_kwargs):
    """Construction is the check, so it is not a validation step anyone can skip."""
    with pytest.raises(ValueError):
        _use(**entry_kwargs)


def test_a_transcription_stating_no_regulatory_value_is_refused():
    with pytest.raises(ValueError):
        _use(
            pre_harvest_interval_days=None, re_entry_interval_hours=None,
            max_applications_per_season=None, min_retreatment_interval_days=None,
        )


def test_a_seasonal_rate_without_its_unit_is_refused():
    with pytest.raises(ValueError):
        _use(max_seasonal_rate_amount=4.0, max_seasonal_rate_unit=None)
