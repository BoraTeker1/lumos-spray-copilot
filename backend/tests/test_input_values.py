"""Field-level provenance (DecisionInputValue): supersede chain, verification, re-run."""


def _farm(client, harvest="2026-07-12"):
    return client.post("/farms", json={
        "name": "Provenance Farm", "location": "Watsonville, CA", "country": "US",
        "crop_type": "strawberry", "expected_harvest_date": harvest,
    }).json()


def _planned(client, farm_id, **overrides):
    payload = {
        "intended_date": "2026-07-10",
        "product_name": "Captan 80 WDG",
        "active_ingredient": "captan",
        "target_pest_or_disease": "gray mold",
        "pre_harvest_interval_days": 4,
        "re_entry_interval_hours": 24,
        "estimated_cost": 120.0,
    }
    payload.update(overrides)
    resp = client.post(f"/farms/{farm_id}/planned-sprays", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_manual_create_writes_user_entered_input_values(client):
    farm = _farm(client)
    p = _planned(client, farm["id"])
    values = client.get(f"/planned-sprays/{p['id']}/input-values").json()
    by_field = {v["field_name"]: v for v in values}
    assert by_field["pre_harvest_interval_days"]["source_type"] == "user_entered"
    assert by_field["pre_harvest_interval_days"]["unit"] == "days"
    assert by_field["re_entry_interval_hours"]["unit"] == "hours"
    assert by_field["product_name"]["normalized_value"] == "captan 80 wdg"
    # The farm-level harvest date is NOT a per-decision provenance row (the farm
    # field stays authoritative so later edits correctly stale the snapshot).
    assert "expected_harvest_date" not in by_field
    assert all(v["verified_by"] is None for v in values)


def test_pca_entered_create_writes_verified_rows(client):
    farm = _farm(client)
    p = _planned(
        client, farm["id"],
        values_source="pca_entered", values_entered_by="Jane PCA",
    )
    values = client.get(f"/planned-sprays/{p['id']}/input-values").json()
    assert values
    assert all(v["source_type"] == "pca_verified" for v in values)
    assert all(v["verified_by"] == "Jane PCA" for v in values)
    assert all(v["verified_at"] is not None for v in values)


def test_review_edit_supersedes_and_reruns_decision(client):
    farm = _farm(client)  # harvest 2026-07-12
    # PHI 4 from 2026-07-10 clears 2026-07-14, after harvest -> BLOCK.
    p = _planned(client, farm["id"])
    assert p["decision_outcome"] == "block"
    old_values = client.get(f"/planned-sprays/{p['id']}/input-values").json()
    old_phi = next(
        v for v in old_values if v["field_name"] == "pre_harvest_interval_days"
    )

    resp = client.patch(f"/planned-sprays/{p['id']}/review", json={
        "action": "edited",
        "reviewed_by": "Jane PCA",
        "review_comment": "Label PHI for this use is 0 days — corrected.",
        "pca_next_action": "Proceed with the corrected PHI after re-check.",
        "proposed_pre_harvest_interval_days": 0,
    })
    assert resp.status_code == 200, resp.text
    updated = resp.json()

    # Denormalized column follows the verified value and the decision was re-run:
    # with PHI 0 the block clears (repeated-AI etc. don't apply here).
    assert updated["pre_harvest_interval_days"] == 0
    assert updated["decision_outcome"] != "block"

    # Supersede chain: the OLD row still exists, unchanged, and is superseded by a
    # new pca_verified row. History is never overwritten.
    chain = client.get(f"/planned-sprays/{p['id']}/input-values").json()
    phi_rows = [v for v in chain if v["field_name"] == "pre_harvest_interval_days"]
    assert len(phi_rows) == 2
    original, superseding = phi_rows
    assert original["id"] == old_phi["id"]
    assert original["raw_value"] == "4"
    assert original["source_type"] == "user_entered"
    assert superseding["raw_value"] == "0"
    assert superseding["source_type"] == "pca_verified"
    assert superseding["verified_by"] == "Jane PCA"
    assert superseding["supersedes_input_value_id"] == original["id"]

    # The pre-review decision snapshot is preserved in the audit event's `before`.
    events = client.get(f"/planned-sprays/{p['id']}/audit-events").json()
    reviewed = next(e for e in events if e["event_type"] == "reviewed")
    assert reviewed["before"]["decision_outcome"] == "block"
    assert reviewed["after"]["decision_outcome"] == updated["decision_outcome"]
    assert reviewed["before"]["decision_payload"]["outcome"] == "block"
    superseded = [e for e in events if e["event_type"] == "input_value_superseded"]
    assert any(
        e["after"]["field"] == "pre_harvest_interval_days" and e["after"]["to"] == 0
        for e in superseded
    )


def test_imported_values_never_silently_verified(client):
    farm = _farm(client)
    result = client.post(f"/farms/{farm['id']}/import/csv", json={
        "record_type": "planned_sprays",
        "csv_text": "Product,Date,PHI,AI\nCaptan 80 WDG,2026-07-10,4,captan",
        "dry_run": False,
        "source_filename": "recs.csv",
    }).json()
    (pid,) = result["created_record_ids"]

    values = client.get(f"/planned-sprays/{pid}/input-values").json()
    assert all(v["source_type"] == "imported_unverified" for v in values)

    # Only an attributed PCA action creates a verified row — and the imported row
    # survives, superseded, still marked imported_unverified.
    client.patch(f"/planned-sprays/{pid}/review", json={
        "action": "edited", "reviewed_by": "Jane PCA",
        "pca_next_action": "PHI confirmed against the label by the PCA.",
        "proposed_pre_harvest_interval_days": 4,
    })
    chain = client.get(f"/planned-sprays/{pid}/input-values").json()
    phi_rows = [v for v in chain if v["field_name"] == "pre_harvest_interval_days"]
    assert [r["source_type"] for r in phi_rows] == [
        "imported_unverified", "pca_verified"
    ]
    assert phi_rows[0]["verified_by"] is None  # untouched, only superseded
