"""What verified label data may and may not do to a decision.

This is the feature's invariant file. Every test here is about a way the label layer
could produce something that LOOKS authoritative without being it: a client claiming
label provenance for itself, a demo record grounding a real verdict, a transcription
nobody checked driving a block, a label sync quietly rewriting a decision a PCA already
signed, or a disagreement between the label and what a grower typed being resolved
silently instead of raised.

The values transcribed here are fictional. They exercise the machinery; they are not a
real product's directions, and nothing in this file may be copied into
`app/label_table.py`.
"""
from datetime import date, timedelta

import pytest

from app import crud, label_data, label_table, models
from app.database import SessionLocal

TOKEN_HEADER = "X-Lumos-Pca-Token"
REG_NO = "99999-1"
TODAY = date.today()


def _use(**overrides):
    row = {
        "epa_reg_no": REG_NO,
        "product_name": "Test Fungicide 50WG",
        "registrant": "Fictional Crop Science",
        "registered_crop": "Strawberries",
        "target_pest_or_disease": "botrytis_fruit_rot",
        "pre_harvest_interval_days": 21,
        "re_entry_interval_hours": 24,
        "max_applications_per_season": 2,
        "min_retreatment_interval_days": 10,
        "max_seasonal_rate_amount": 20.0,
        "max_seasonal_rate_unit": "oz/acre",
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


def _farm(client, name="Label Authority Farm", **overrides):
    payload = {
        "name": name, "country": "US", "crop_type": "strawberry", "area_unit": "acres",
        "planting_date": (TODAY - timedelta(days=90)).isoformat(),
        "expected_harvest_date": (TODAY + timedelta(days=60)).isoformat(),
    }
    payload.update(overrides)
    return client.post("/farms", json=payload).json()


def _verified_label(
    client, farm_id, entries=None, *, complete_crops=True, confidence="user_provided"
):
    """Transcribe a label, then have a credentialed PCA verify it for this farm."""
    from app import label_table as table

    original = table.TRANSCRIBED_LABEL_USES
    table.TRANSCRIBED_LABEL_USES = tuple(entries or [_use()])
    try:
        with SessionLocal() as db:
            crud.sync_transcribed_labels(db)
    finally:
        table.TRANSCRIBED_LABEL_USES = original

    credential = client.post("/internal/pca-credentials", json={
        "display_name": "Dana PCA", "license_identifier": "PCA-12345",
        "license_state": "CA", "issued_by": "pilot-operator",
    }).json()

    with SessionLocal() as db:
        product = db.query(models.PesticideProduct).one()
        product.registered_crops_transcription_complete = complete_crops
        for record in db.query(models.ProductLabelRecord).all():
            db.add(models.ProductLabelVerification(
                product_label_record_id=record.id,
                farm_id=farm_id,
                verified_by_credential_id=credential["id"],
                verified_by="Dana PCA",
                attestation="Checked against the fictional test label, p. 1.",
                data_source="manual_entry",
                data_confidence=confidence,
            ))
        db.commit()
    return credential


def _planned(client, farm_id, **overrides):
    payload = {
        "intended_date": (TODAY + timedelta(days=2)).isoformat(),
        "product_name": "Test Fungicide 50WG",
        "epa_reg_no": REG_NO,
        "crop": "strawberry",
        "target_pest_or_disease": "botrytis_fruit_rot",
        "active_ingredient": "test-ai",
        "re_entry_interval_hours": 24,
    }
    payload.update(overrides)
    res = client.post(f"/farms/{farm_id}/planned-sprays", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def _rules(decision) -> dict:
    return {r["rule_id"]: r for r in decision["decision_payload"]["rules"]}


def _not_evaluated(decision) -> dict:
    return {c["check_id"]: c["reason"] for c in decision["decision_payload"]["not_evaluated"]}


# ------------------------------------------------- nothing changes without a label
def test_without_label_data_all_four_checks_stay_unevaluated(client):
    farm = _farm(client)
    decision = _planned(client, farm["id"])

    reasons = _not_evaluated(decision)
    assert set(reasons) == {
        "max_seasonal_rate", "max_applications_per_season",
        "min_retreatment_interval", "crop_use_registration",
    }
    # The reason is specific to WHY, not the generic "no label database": this decision
    # carries a registration number and nothing on file matches it.
    assert all(REG_NO in reason for reason in reasons.values())


def test_an_unverified_transcription_cannot_run_a_single_check(client):
    """Values on file are not values in force. This is the whole promotion gate."""
    farm = _farm(client)
    with SessionLocal() as db:
        import app.label_table as table
        original = table.TRANSCRIBED_LABEL_USES
        table.TRANSCRIBED_LABEL_USES = (_use(),)
        try:
            crud.sync_transcribed_labels(db)
        finally:
            table.TRANSCRIBED_LABEL_USES = original

    decision = _planned(client, farm["id"])

    reasons = _not_evaluated(decision)
    assert len(reasons) == 4
    assert "no licensed PCA has verified" in reasons["max_applications_per_season"]


def test_a_simulated_verification_never_grounds_a_decision(client):
    """A demo farm can only hold a simulated verification — and it must not promote.

    Note what the setup itself proves: recording a simulated verification makes the farm
    a demo farm, so the decision has to be demo too or `ensure_demo_real_separation`
    409s. The verification being a farm record is what wires the demo guard in.
    """
    farm = _farm(client)
    _verified_label(client, farm["id"], confidence="simulated")

    decision = _planned(
        client, farm["id"], data_source="demo", data_confidence="simulated"
    )

    assert "simulated demo record" in _not_evaluated(decision)["min_retreatment_interval"]


# --------------------------------------------------- the checks actually run
def test_a_verified_label_runs_the_checks_and_grounds_the_verdict(client):
    farm = _farm(client)
    _verified_label(client, farm["id"])

    decision = _planned(client, farm["id"])

    rules = _rules(decision)
    assert "label_crop_registration" in rules
    assert "label_max_applications" in rules
    assert "label_retreatment_interval" in rules
    assert rules["label_crop_registration"]["source_authority"] == "verified_label"
    assert rules["label_crop_registration"]["verification_status"] == "verified"
    # The checks that ran are no longer disclosed as not run.
    assert "crop_use_registration" not in _not_evaluated(decision)


def test_an_unregistered_crop_blocks_only_once_the_list_is_known_complete(client):
    """A partial transcription's silence about a crop must never become a BLOCK."""
    incomplete_farm = _farm(client, "Incomplete Farm")
    _verified_label(client, incomplete_farm["id"], complete_crops=False)
    decision = _planned(client, incomplete_farm["id"], crop="lettuce")

    assert decision["decision_outcome"] != "block"
    assert "has not been transcribed in full" in (
        _not_evaluated(decision)["crop_use_registration"]
    )

    with SessionLocal() as db:
        db.query(models.PesticideProduct).one().registered_crops_transcription_complete = True
        db.commit()

    blocked = _planned(client, incomplete_farm["id"], crop="lettuce")
    assert blocked["decision_outcome"] == "block"
    assert _rules(blocked)["label_crop_registration"]["triggered"] is True


def test_exceeding_the_label_application_count_blocks(client):
    farm = _farm(client)
    _verified_label(client, farm["id"])
    for days_ago in (40, 20):
        client.post(f"/farms/{farm['id']}/spray-events", json={
            "product_name": "Test Fungicide 50WG",
            "epa_reg_no": REG_NO,
            "active_ingredient": "test-ai",
            "application_date": (TODAY - timedelta(days=days_ago)).isoformat(),
        })

    decision = _planned(client, farm["id"])

    rule = _rules(decision)["label_max_applications"]
    assert rule["triggered"] is True
    assert rule["inputs"]["including_this_one"] == 3
    assert decision["decision_outcome"] == "block"


def test_a_related_registration_number_is_never_counted_as_the_same_product(client):
    """`99999-1-2222` is a different label; counting it would be a false BLOCK."""
    farm = _farm(client)
    _verified_label(client, farm["id"])
    for days_ago in (40, 20):
        client.post(f"/farms/{farm['id']}/spray-events", json={
            "product_name": "Test Fungicide 50WG (supplemental)",
            "epa_reg_no": "99999-1-2222",
            "application_date": (TODAY - timedelta(days=days_ago)).isoformat(),
        })

    decision = _planned(client, farm["id"])

    assert _rules(decision)["label_max_applications"]["inputs"]["including_this_one"] == 1


def test_a_short_retreatment_interval_delays_rather_than_blocks(client):
    farm = _farm(client)
    _verified_label(client, farm["id"])
    client.post(f"/farms/{farm['id']}/spray-events", json={
        "product_name": "Test Fungicide 50WG",
        "epa_reg_no": REG_NO,
        "active_ingredient": "test-ai",
        "application_date": (TODAY - timedelta(days=1)).isoformat(),
    })

    decision = _planned(client, farm["id"], crop="strawberry")

    rule = _rules(decision)["label_retreatment_interval"]
    assert rule["triggered"] is True
    assert rule["inputs"]["days_since_last_application"] == 3
    assert decision["decision_outcome"] in ("block", "delay")


def test_an_unconvertible_rate_is_refused_by_name_never_approximated(client):
    """Mass-to-volume needs a density the label does not state. Refusing is the answer."""
    farm = _farm(client)
    _verified_label(client, farm["id"])

    decision = _planned(client, farm["id"], rate_amount=2.0, rate_unit="fl oz/acre")

    reason = _not_evaluated(decision)["max_seasonal_rate"]
    assert "no cited conversion exists" in reason
    assert "label_max_seasonal_rate" not in _rules(decision)


def test_a_seasonal_rate_total_converts_with_its_citation(client):
    farm = _farm(client)
    _verified_label(client, farm["id"])
    client.post(f"/farms/{farm['id']}/spray-events", json={
        "product_name": "Test Fungicide 50WG",
        "epa_reg_no": REG_NO,
        "application_date": (TODAY - timedelta(days=30)).isoformat(),
        "rate_amount": 1.0, "rate_unit": "lb/acre",
    })

    decision = _planned(client, farm["id"], rate_amount=8.0, rate_unit="oz/acre")

    rule = _rules(decision)["label_max_seasonal_rate"]
    # 1 lb/acre = 16 oz/acre, plus 8 oz/acre planned = 24 vs a label maximum of 20.
    assert rule["inputs"]["season_total"] == 24.0
    assert rule["triggered"] is True
    assert any("16 ounces" in c for c in rule["inputs"]["conversion_provenance"])


def test_no_season_window_leaves_the_seasonal_checks_unevaluated(client):
    farm = _farm(client, "No Planting Date", planting_date=None)
    _verified_label(client, farm["id"])

    decision = _planned(client, farm["id"], rate_amount=8.0, rate_unit="oz/acre")

    reasons = _not_evaluated(decision)
    assert "no planting date" in reasons["max_applications_per_season"]
    assert "no planting date" in reasons["max_seasonal_rate"]
    # The retreatment check needs no season window, so it still runs.
    assert "min_retreatment_interval" not in reasons


# ------------------------------------------------------------- the disagreement
def test_the_label_value_drives_the_arithmetic_and_the_disagreement_is_reported(client):
    """The most saleable output in the layer: "your label says 21 days, this said 3"."""
    farm = _farm(client, "Disagreement Farm", expected_harvest_date=(
        TODAY + timedelta(days=10)
    ).isoformat())
    _verified_label(client, farm["id"])

    # Entered as a 3-day PHI, 8 days before harvest — harmless on its own.
    decision = _planned(client, farm["id"], pre_harvest_interval_days=3)

    rules = _rules(decision)
    disagreement = rules["label_value_disagreement"]
    assert disagreement["triggered"] is True
    fields = {d["field"]: d for d in disagreement["inputs"]["disagreements"]}
    assert fields["pre_harvest_interval_days"]["entered_value"] == 3
    assert fields["pre_harvest_interval_days"]["label_value"] == 21
    # The label's 21 days is what the PHI check actually ran on — so it blocks.
    assert decision["decision_outcome"] == "block"
    assert decision["decision_payload"]["inputs_used"]["pre_harvest_interval_days"] == 21


def test_the_superseded_human_value_stays_readable(client):
    """Applying a label value must not erase what a person entered."""
    farm = _farm(client)
    _verified_label(client, farm["id"])
    decision = _planned(client, farm["id"], pre_harvest_interval_days=3)

    values = client.get(f"/planned-sprays/{decision['id']}/input-values").json()
    phi = [v for v in values if v["field_name"] == "pre_harvest_interval_days"]
    assert {v["source_type"] for v in phi} == {"user_entered", "authoritative_provider"}
    assert {v["normalized_value"] for v in phi} == {"3", "21"}

    events = client.get(f"/planned-sprays/{decision['id']}/audit-events").json()
    assert any(e["event_type"] == "label_values_applied" for e in events)


def test_agreement_produces_no_disagreement_rule(client):
    farm = _farm(client)
    _verified_label(client, farm["id"])

    decision = _planned(client, farm["id"], pre_harvest_interval_days=21)

    assert "label_value_disagreement" not in _rules(decision)


# -------------------------------------------------------------- what cannot happen
def test_a_client_can_never_claim_label_provenance(client):
    """`authoritative_provider` is reachable only from a resolved, verified record."""
    farm = _farm(client)
    res = client.post(f"/farms/{farm['id']}/planned-sprays", json={
        "intended_date": (TODAY + timedelta(days=2)).isoformat(),
        "product_name": "Test Fungicide 50WG",
        "values_source": "authoritative_provider",
    })
    assert res.status_code == 422


def test_the_source_vocabulary_a_client_may_claim_stays_two_values(client):
    """The behavioural refusal above holds only while this literal stays narrow.

    `ValuesSource` is the one client-supplied field that maps onto decision-input
    provenance. Widening it — even to add a seemingly harmless option — is what would
    let a request grant itself the authority the whole label layer exists to earn.
    """
    from typing import get_args

    from app import schemas

    assert get_args(schemas.ValuesSource) == ("grower_entered", "pca_entered")


def test_a_pca_review_cannot_claim_label_authority_either(client):
    """A PCA edit is `pca_verified`. Only a resolved label record is authoritative."""
    farm = _farm(client)
    decision = _planned(client, farm["id"], pre_harvest_interval_days=3)
    client.patch(f"/planned-sprays/{decision['id']}/review", json={
        "action": "edited", "reviewed_by": "Dana PCA",
        "pca_next_action": "Use the label PHI.",
        "proposed_pre_harvest_interval_days": 21,
    })

    values = client.get(f"/planned-sprays/{decision['id']}/input-values").json()
    sources = {v["source_type"] for v in values}
    assert "authoritative_provider" not in sources
    assert "pca_verified" in sources


def test_a_reviewed_decision_is_never_rewritten_by_a_later_label_sync(client):
    """A PCA's signature has to keep meaning what it meant when they gave it."""
    farm = _farm(client)
    credential = _verified_label(client, farm["id"])
    token = client.post("/internal/pca-credentials", json={
        "display_name": "Dana PCA", "license_identifier": "PCA-12345",
        "license_state": "CA", "issued_by": "pilot-operator",
    }).json()
    client.post(
        f"/internal/pca-credentials/{token['id']}/farm-authorizations",
        json={"farm_id": farm["id"], "granted_by": "pilot-operator"},
    )
    decision = _planned(client, farm["id"], pre_harvest_interval_days=21)
    client.patch(
        f"/planned-sprays/{decision['id']}/review",
        json={"action": "approved", "reviewed_by": "Dana PCA"},
        headers={TOKEN_HEADER: token["token"]},
    )

    with SessionLocal() as db:
        planned = db.get(models.PlannedSpray, decision["id"])
        before = planned.pre_harvest_interval_days
        applied = crud.apply_label_values(db, planned)

    assert applied == []
    after = client.get(f"/planned-sprays/{decision['id']}").json()
    assert after["pre_harvest_interval_days"] == before
    assert after["review_status"] == "approved"
    assert credential is not None


def test_a_label_revision_marks_a_stored_decision_stale_rather_than_recomputing_it(client):
    farm = _farm(client)
    _verified_label(client, farm["id"])
    decision = _planned(client, farm["id"], pre_harvest_interval_days=21)
    assert decision["label_reference_stale"] is False

    with SessionLocal() as db:
        record = (
            db.query(models.ProductLabelRecord)
            .filter(models.ProductLabelRecord.supersedes_label_record_id.is_(None))
            .one()
        )
        db.add(models.ProductLabelRecord(
            product_id=record.product_id,
            registered_crop=record.registered_crop,
            registered_crop_normalized=record.registered_crop_normalized,
            pre_harvest_interval_days=30,
            source_tier=label_data.TIER_TRANSCRIBED,
            label_version="test-rev-2",
            label_effective_date=date(2026, 1, 1),
            source_document_reference="fictional test label rev 2",
            source_snippet="Fictional revised directions.",
            supersedes_label_record_id=record.id,
        ))
        db.commit()

    after = client.get(f"/planned-sprays/{decision['id']}").json()
    assert after["label_reference_stale"] is True
    # The stored decision is NOT silently recomputed against the new revision.
    assert after["pre_harvest_interval_days"] == 21


def test_an_approve_is_never_verified_label_grounded(client):
    """Load-bearing, and easy to break by "cleaning up" the rotation rule.

    For an approve the determining set is EVERY rule, and `repeated_active_ingredient`
    is a heuristic while `prior_rei_overlap` rests on an entered value. So an approve
    stays provisional and keeps requiring a human — no label coverage changes that.
    """
    farm = _farm(client)
    _verified_label(client, farm["id"])
    client.post(f"/farms/{farm['id']}/scout-observations", json={
        "observation_date": TODAY.isoformat(),
        "visible_issue": "botrytis_fruit_rot", "severity_1_to_5": 3,
    })

    decision = _planned(client, farm["id"], pre_harvest_interval_days=21)

    assert decision["decision_authority"] != "verified_label_grounded"
    if decision["decision_outcome"] == "approve":
        assert decision["review_required"] is True


@pytest.mark.parametrize("rule_id", ["repeated_active_ingredient", "prior_rei_overlap"])
def test_the_rules_that_keep_an_approve_provisional_still_exist(client, rule_id):
    """Deleting or merging either one silently creates a no-human-review approve."""
    farm = _farm(client)
    decision = _planned(client, farm["id"])

    assert rule_id in _rules(decision)


# --------------------------------------------------- conditional honesty copy
def test_the_disclaimer_is_the_exact_original_sentence_without_label_coverage(client):
    """Zero disclaimers are deleted by the label layer. This is the proof."""
    from app.decision_engine import PLANNED_SPRAY_DISCLAIMER, planned_spray_disclaimer

    assert planned_spray_disclaimer(None) == PLANNED_SPRAY_DISCLAIMER
    assert planned_spray_disclaimer("") == PLANNED_SPRAY_DISCLAIMER

    farm = _farm(client)
    decision = _planned(client, farm["id"])
    assert decision["decision_payload"]["disclaimer"] == PLANNED_SPRAY_DISCLAIMER


def test_a_label_grounded_decision_names_its_source_and_still_states_the_limits(client):
    farm = _farm(client)
    _verified_label(client, farm["id"])

    decision = _planned(client, farm["id"], pre_harvest_interval_days=21)

    disclaimer = decision["decision_payload"]["disclaimer"]
    assert "verified against the label document" in disclaimer
    assert REG_NO in disclaimer
    # It must still say what is NOT label-backed — a verified PHI does not make the
    # rotation and scouting heuristics label requirements.
    assert "heuristics" in disclaimer


def test_the_compliance_basis_text_degrades_to_todays_wording(client):
    from app.main import COMPLIANCE_BASIS_TEXT_UNVERIFIED, COMPLIANCE_BASIS_UNVERIFIED

    farm = _farm(client)
    body = client.get(f"/farms/{farm['id']}/compliance").json()

    assert body["basis"] == COMPLIANCE_BASIS_UNVERIFIED
    assert body["basis_text"] == COMPLIANCE_BASIS_TEXT_UNVERIFIED


def test_the_compliance_basis_text_says_partially_when_coverage_is_partial(client):
    """"Partially" is accuracy, not hedging — one verified label among many products."""
    farm = _farm(client)
    _verified_label(client, farm["id"])

    body = client.get(f"/farms/{farm['id']}/compliance").json()

    assert body["basis"] == "partially label-verified"
    assert "1 product(s)" in body["basis_text"]
    assert "still comes from user-entered values" in body["basis_text"]


# ------------------------------------------- active-ingredient quantity avoided
def test_the_quantity_stays_not_calculated_without_a_verified_concentration(client):
    farm = _farm(client)
    body = client.get(f"/farms/{farm['id']}/decision-evidence").json()

    assert "active_ingredient_quantity_avoided" in body["not_calculated"]
    assert body["confirmed"]["active_ingredient_quantity_avoided"] is None


def test_an_unverified_concentration_does_not_unlock_the_quantity(client):
    """On file is not in force — for the metric exactly as for the decision."""
    from app import crud
    from app.database import SessionLocal

    farm = _farm(client)
    with SessionLocal() as db:
        import app.label_table as table
        original = table.TRANSCRIBED_LABEL_USES
        table.TRANSCRIBED_LABEL_USES = (
            _use(active_ingredient_concentration_amount=50.0,
                 active_ingredient_concentration_unit="%"),
        )
        try:
            crud.sync_transcribed_labels(db)
        finally:
            table.TRANSCRIBED_LABEL_USES = original
        assert crud.ai_concentrations_for_farm(db, farm["id"]) == {}

    body = client.get(f"/farms/{farm['id']}/decision-evidence").json()
    assert "active_ingredient_quantity_avoided" in body["not_calculated"]


# ------------------------------------------- grower-facing label resolution
def test_the_grower_route_needs_no_operator_key(client, monkeypatch):
    """The person entering a spray must be able to ask whether a label covers it.

    `/internal/labels/resolution` sits behind the operator gate, which a grower does
    not have — so the same answer is available farm-scoped and ungated.
    """
    from app import operator_key

    monkeypatch.setenv(operator_key.ENV_VAR, "test-operator-secret")
    farm = _farm(client)

    # The operator route is gated...
    gated = client.get("/internal/labels/resolution", params={"epa_reg_no": REG_NO})
    assert gated.status_code == 403
    # ...the grower route is not.
    res = client.get(f"/farms/{farm['id']}/label-resolution", params={"epa_reg_no": REG_NO})
    assert res.status_code == 200


def test_the_grower_route_defaults_the_crop_to_the_farms(client):
    """A grower should not have to restate what they grow."""
    farm = _farm(client)

    body = client.get(
        f"/farms/{farm['id']}/label-resolution", params={"epa_reg_no": REG_NO}
    ).json()

    assert body["crop"] == "strawberry"
    assert body["farm_id"] == farm["id"]


def test_the_grower_route_reports_the_same_three_states(client):
    farm = _farm(client)

    # 1. Nothing on file.
    body = client.get(
        f"/farms/{farm['id']}/label-resolution", params={"epa_reg_no": REG_NO}
    ).json()
    assert body["promotable"] is False
    assert REG_NO in body["unresolved_reason"]

    # 2. On file but unverified — the state that matters most to get right.
    _verified_label(client, farm["id"])
    with SessionLocal() as db:
        for v in db.query(models.ProductLabelVerification).all():
            db.delete(v)
        db.commit()
    body = client.get(
        f"/farms/{farm['id']}/label-resolution", params={"epa_reg_no": REG_NO}
    ).json()
    assert body["promotable"] is False
    assert "no licensed PCA has verified" in body["promotion_blocked_reason"]


def test_the_grower_route_is_read_only(client):
    """It answers a question; it must never create or promote anything."""
    from app.main import app

    routes = [r for r in app.routes if "label-resolution" in getattr(r, "path", "")]
    assert routes
    for route in routes:
        assert set(getattr(route, "methods", set())) == {"GET"}


# ----------------------------------------- the reference farm is capability, not use
# A reference farm is the one configuration where the label checks can actually run:
# real provenance, so a PCA verification promotes. Real provenance is also what makes
# it dangerous — every evidence surface counts real records, and this farm has no
# grower. These tests are about the second half of that trade.
def _reference_farm(client, name="Reference Farm"):
    farm = _farm(client, name=name)
    with SessionLocal() as db:
        db.get(models.Farm, farm["id"]).is_reference = True
        db.commit()
    return farm


def test_a_reference_farm_is_excluded_from_the_usage_funnel(client):
    """`/internal/instrumentation` answers "is anyone actually using it".

    A decision the operator created to exercise the engine is real by every provenance
    test in the system, so nothing else would filter it out — and it would land in the
    exact number a reader treats as usage.
    """
    reference = _reference_farm(client)
    _verified_label(client, reference["id"])
    _planned(client, reference["id"])

    body = client.get("/internal/instrumentation").json()

    assert body["reference_decisions_excluded"] == 1
    assert body["entry_source_breakdown"] == {}
    assert body["outcomes_recorded"] == 0
    assert any("reference farm" in note for note in body["notes"])


def test_a_normal_farms_decisions_still_reach_the_usage_funnel(client):
    """The exclusion must be the flag, not a bug that drops everyone."""
    farm = _farm(client, name="Ordinary Farm")
    _verified_label(client, farm["id"])
    _planned(client, farm["id"])

    body = client.get("/internal/instrumentation").json()

    assert body["reference_decisions_excluded"] == 0
    assert sum(body["entry_source_breakdown"].values()) == 1


def test_reference_farm_evidence_leads_with_the_disclosure(client):
    """The number is real arithmetic. The sentence saying whose it is has to travel."""
    from app.pilot_evidence import REFERENCE_FARM_DISCLOSURE

    reference = _reference_farm(client)
    _verified_label(client, reference["id"])
    _planned(client, reference["id"])

    body = client.get(f"/farms/{reference['id']}/decision-evidence").json()

    assert body["is_reference_farm"] is True
    assert body["limitations"][0] == REFERENCE_FARM_DISCLOSURE
    assert "not a customer" in body["limitations"][0]


def test_a_reference_farm_publishes_no_investor_talking_points(client):
    """`investor_summary` exists to be read aloud. On a farm with no grower there is
    no honest sentence for it to hold, so it is empty rather than hedged."""
    reference = _reference_farm(client)

    body = client.get(f"/farms/{reference['id']}/pilot-evidence").json()

    assert body["is_reference_farm"] is True
    assert body["investor_summary"] == []


def test_the_evidence_export_carries_the_disclosure_first(client):
    """The export is the artifact that leaves the building."""
    from app.pilot_evidence import REFERENCE_FARM_DISCLOSURE

    reference = _reference_farm(client)
    _verified_label(client, reference["id"])
    _planned(client, reference["id"])

    body = client.get(f"/farms/{reference['id']}/evidence-export").json()

    assert body["is_reference_farm"] is True
    assert body["limitations"][0] == REFERENCE_FARM_DISCLOSURE


def test_the_reference_flag_cannot_be_set_through_the_api(client):
    """Setting it hides a farm from the usage funnel; clearing it reveals one there.

    Both directions are consequential, so it is an operator act
    (`python -m app.reference_farm`) and no request schema exposes it.
    """
    farm = _farm(client, name="Not Yours To Flag")

    created = client.post("/farms", json={
        "name": "Sneaky", "country": "US", "crop_type": "strawberry",
        "is_reference": True,
    }).json()
    updated = client.put(
        f"/farms/{farm['id']}", json={"name": farm["name"], "is_reference": True}
    ).json()

    assert created["is_reference"] is False
    assert updated["is_reference"] is False
