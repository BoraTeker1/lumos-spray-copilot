"""Cross-surface invariant tests: impossible chronology is rejected, harvest edits
flag stale decisions, review state is derived identically everywhere, the pinned demo
clock reproduces the seeded stories live, and the demo reset never touches real data.
"""
from datetime import date, timedelta

import pytest

from app import seed

PINNED = "2026-07-10"


@pytest.fixture()
def pinned_clock(monkeypatch):
    monkeypatch.setenv("LUMOS_DEMO_TODAY", PINNED)
    return date.fromisoformat(PINNED)


def _farm(client, **overrides):
    payload = {
        "name": "Invariant Farm",
        "country": "US",
        "crop_type": "strawberry",
        "expected_harvest_date": (date.today() + timedelta(days=30)).isoformat(),
    }
    payload.update(overrides)
    return client.post("/farms", json=payload).json()


def _planned(client, farm_id, **overrides):
    payload = {
        "intended_date": date.today().isoformat(),
        "product_name": "Captan 80WDG",
        "active_ingredient": "captan",
        "target_pest_or_disease": "botrytis",
        "pre_harvest_interval_days": 2,
        "re_entry_interval_hours": 12,
        "estimated_cost": 100.0,
    }
    payload.update(overrides)
    res = client.post(f"/farms/{farm_id}/planned-sprays", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def _review(client, planned_id, action, **overrides):
    payload = {"action": action, "reviewed_by": "Test PCA"}
    if action == "edited":
        payload["pca_next_action"] = "Adjusted guidance."
    if action == "rejected":
        payload["review_comment"] = "Inputs look wrong."
    payload.update(overrides)
    res = client.patch(f"/planned-sprays/{planned_id}/review", json=payload)
    assert res.status_code == 200, res.text
    return res.json()


# ------------------------------------------------------------------- chronology
def test_applied_outcome_rejects_outcome_date_before_intended(client):
    farm = _farm(client)
    p = _planned(client, farm["id"], intended_date=(date.today()).isoformat())
    _review(client, p["id"], "approved")
    res = client.patch(
        f"/planned-sprays/{p['id']}/outcome",
        json={
            "outcome": "sprayed_as_planned",
            "outcome_date": (date.today() - timedelta(days=2)).isoformat(),
        },
    )
    assert res.status_code == 422
    assert "before" in res.json()["detail"].lower()


def test_applied_outcome_rejects_application_date_before_intended(client):
    farm = _farm(client)
    p = _planned(client, farm["id"])
    _review(client, p["id"], "approved")
    res = client.patch(
        f"/planned-sprays/{p['id']}/outcome",
        json={
            "outcome": "sprayed_as_planned",
            "application_date": (date.today() - timedelta(days=3)).isoformat(),
        },
    )
    assert res.status_code == 422
    assert "application date" in res.json()["detail"].lower()


def test_any_outcome_rejects_date_before_the_check_was_run(client):
    farm = _farm(client)
    p = _planned(client, farm["id"])
    res = client.patch(
        f"/planned-sprays/{p['id']}/outcome",
        json={
            "outcome": "avoided",
            "outcome_reason": "Held off.",
            "outcome_date": (date.today() - timedelta(days=1)).isoformat(),
        },
    )
    assert res.status_code == 422
    assert "predate" in res.json()["detail"].lower()


def test_outcome_date_defaults_to_today_and_explicit_valid_date_is_accepted(client):
    farm = _farm(client)
    p = _planned(client, farm["id"])
    res = client.patch(
        f"/planned-sprays/{p['id']}/outcome",
        json={"outcome": "avoided", "outcome_reason": "No pressure found."},
    )
    assert res.status_code == 200
    assert res.json()["outcome_date"] == date.today().isoformat()

    p2 = _planned(client, farm["id"])
    explicit = (date.today() + timedelta(days=1)).isoformat()
    res = client.patch(
        f"/planned-sprays/{p2['id']}/outcome",
        json={"outcome": "delayed", "outcome_reason": "Waiting.", "outcome_date": explicit},
    )
    assert res.status_code == 200
    assert res.json()["outcome_date"] == explicit


# -------------------------------------------------------------- harvest staleness
def test_harvest_staleness_flag_appears_after_farm_harvest_edit(client):
    farm = _farm(client)
    p = _planned(client, farm["id"])
    assert p["harvest_date_changed_since_check"] is False

    new_harvest = (date.today() + timedelta(days=45)).isoformat()
    client.put(f"/farms/{farm['id']}", json={"expected_harvest_date": new_harvest})

    stale = client.get(f"/planned-sprays/{p['id']}").json()
    assert stale["harvest_date_changed_since_check"] is True

    # A fresh check against the new harvest date is not stale.
    fresh = _planned(client, farm["id"])
    assert fresh["harvest_date_changed_since_check"] is False


# ------------------------------------------------- canonical review-state matrix
def test_review_state_matrix_is_consistent_across_surfaces(client):
    """pending / approved / edited / rejected decisions must be derived identically
    by the planned-spray schema, the farm overview, and the decision evidence."""
    farm = _farm(client, expected_harvest_date=(date.today() + timedelta(days=1)).isoformat())
    # All four checks block (PHI 2 > 1 day to harvest) -> review_required True.
    pending = _planned(client, farm["id"])
    approved = _planned(client, farm["id"])
    _review(client, approved["id"], "approved")
    edited = _planned(client, farm["id"])
    _review(client, edited["id"], "edited")
    rejected = _planned(client, farm["id"])
    _review(client, rejected["id"], "rejected")

    rows = {p["id"]: p for p in client.get(f"/farms/{farm['id']}/planned-sprays").json()}
    assert rows[pending["id"]]["review_state"] == "pending"
    assert rows[pending["id"]]["needs_review"] is True
    assert rows[pending["id"]]["applied_outcome_allowed"] is False
    assert rows[approved["id"]]["review_state"] == "approved"
    assert rows[approved["id"]]["needs_review"] is False
    assert rows[approved["id"]]["applied_outcome_allowed"] is True
    assert rows[edited["id"]]["review_state"] == "edited"
    assert rows[edited["id"]]["applied_outcome_allowed"] is True
    # A rejected review RESOLVES "needs review" but does NOT unlock application.
    assert rows[rejected["id"]]["review_state"] == "rejected"
    assert rows[rejected["id"]]["needs_review"] is False
    assert rows[rejected["id"]]["applied_outcome_allowed"] is False
    # Every row is still open and a critical conflict.
    assert all(r["is_open"] and r["open_conflict"] for r in rows.values())

    # The dashboard entry and the farm-page entry are the SAME derivation.
    card = next(f for f in client.get("/farms-overview").json() if f["id"] == farm["id"])
    page = client.get(f"/farms/{farm['id']}/overview").json()
    for key in ("needs_review_count", "awaiting_outcome_count", "open_conflict_count",
                "flag_count", "urgency"):
        assert card[key] == page[key], key
    assert page["needs_review_count"] == 1   # only the pending one
    assert page["awaiting_outcome_count"] == 4
    assert page["open_conflict_count"] == 4
    assert page["urgency"] == "conflict"

    # Evidence: reviewed = approved + edited + rejected.
    ev = client.get(f"/farms/{farm['id']}/decision-evidence").json()
    assert ev["decisions_checked"] == 4
    assert ev["decisions_reviewed"] == 3
    assert ev["pca_acceptance_rate_pct"] == round(100.0 * 2 / 3, 1)

    # The compliance snapshot's decision_review block agrees.
    comp = client.get(f"/farms/{farm['id']}/compliance").json()
    assert comp["decision_review"]["pending"] == 1
    assert comp["decision_review"]["approved"] == 1
    assert comp["decision_review"]["edited"] == 1
    assert comp["decision_review"]["rejected"] == 1
    assert comp["decision_review"]["needs_review_count"] == 1


def test_days_to_harvest_is_server_computed(client):
    farm = _farm(client, expected_harvest_date=(date.today() + timedelta(days=12)).isoformat())
    page = client.get(f"/farms/{farm['id']}/overview").json()
    assert page["days_to_harvest"] == 12


# --------------------------------------------------- deterministic demo clock
def test_reseeding_under_pinned_clock_is_byte_identical(client, pinned_clock):
    """With LUMOS_DEMO_TODAY pinned, re-seeding must reproduce the exact same
    decisions — the seeded story can never silently drift or go stale.

    (A live RE-check of a seeded spray is deliberately NOT asserted equal: recording
    scenario 1's outcome adds the Switch spray event, and later checks correctly see
    that new record — that is the engine working, not drift.)
    """
    def snapshot():
        seed.run()
        us = next(f for f in client.get("/farms").json() if f["country"] == "US")
        return [
            {k: v for k, v in p.items() if k not in ("id",)}
            for p in client.get(f"/farms/{us['id']}/planned-sprays").json()
        ]

    first = snapshot()
    second = snapshot()
    assert first == second


def test_live_check_is_deterministic_under_pinned_clock(client, pinned_clock):
    """The same check POSTed twice against the same records yields the same decision."""
    seed.run()
    us = next(f for f in client.get("/farms").json() if f["country"] == "US")
    payload = {
        "intended_date": PINNED,
        "product_name": "PyGanic EC 5.0",
        "active_ingredient": "pyrethrins",
        "target_pest_or_disease": "lygus bug",
        "pre_harvest_interval_days": 0,
        "re_entry_interval_hours": 12,
        "estimated_cost": 95.0,
        # Live checks on the demo farm are demo-tagged (mixing guard).
        "data_source": "demo",
        "data_confidence": "simulated",
    }
    a = client.post(f"/farms/{us['id']}/planned-sprays", json=payload).json()
    b = client.post(f"/farms/{us['id']}/planned-sprays", json=payload).json()
    for key in ("decision_outcome", "decision_severity", "decision_confidence",
                "decision_authority", "review_required", "decision_payload"):
        assert a[key] == b[key], key
    # And the pinned clock stamps the check on the anchor day.
    assert a["created_at"][:10] == PINNED
    # NOTE: this live re-check correctly sees the Switch spray recorded by scenario 1
    # (its re-entry interval is still active on the anchor day -> DELAY) — later
    # records changing a later check is the engine working, not nondeterminism.
    assert a["decision_outcome"] == "delay"


def test_seeded_scenarios_share_one_anchor_and_agree_with_engine_columns(
    client, pinned_clock
):
    seed.run()
    us = next(f for f in client.get("/farms").json() if f["country"] == "US")
    planned = client.get(f"/farms/{us['id']}/planned-sprays").json()
    assert len(planned) == 3
    # Scenarios 1 & 2 (captan block, PyGanic avoidance) resolve on the demo day;
    # the captan check/review happen the MORNING BEFORE (its procurement chain —
    # plan, quotes, order, delivery — must fit between review and application),
    # while PyGanic stays a same-day story. The failed-delay story (Agri-Mek)
    # deliberately spans the preceding days.
    captan = next(p for p in planned if p["product_name"] == "Captan 80 WDG")
    assert captan["intended_date"] == PINNED
    assert captan["outcome_date"] == PINNED
    assert captan["created_at"][:10] < PINNED  # checked the day before
    assert captan["reviewed_at"][:10] == captan["created_at"][:10]
    assert captan["created_at"] <= captan["reviewed_at"]
    pyganic = next(p for p in planned if p["product_name"] == "PyGanic EC 5.0")
    assert pyganic["intended_date"] == PINNED
    assert pyganic["outcome_date"] == PINNED
    assert pyganic["created_at"][:10] == PINNED
    assert pyganic["reviewed_at"][:10] == PINNED
    mite = next(p for p in planned if p["product_name"] == "Agri-Mek SC")
    assert mite["created_at"][:10] <= mite["outcome_date"] <= PINNED
    for p in planned:
        # Snapshot payload agrees with the stored columns (no drift).
        assert p["decision_payload"]["outcome"] == p["decision_outcome"]
        assert p["decision_payload"]["authority_level"] == p["decision_authority"]
        assert p["decision_payload"]["review_required"] == p["review_required"]


def test_no_invented_threshold_for_targets_without_policy(client, pinned_clock):
    seed.run()
    us = next(f for f in client.get("/farms").json() if f["country"] == "US")
    # A target with no policy on this farm (and no alias link to one — "spider mites"
    # would now correctly hit the seeded twospotted-spider-mite policy via the
    # explicit alias dictionary): the scouting rule stays a heuristic.
    p = _planned(
        client, us["id"],
        intended_date=PINNED,
        product_name="Test Product",
        active_ingredient="novel-ai",
        target_pest_or_disease="powdery mildew",
        pre_harvest_interval_days=0,
        re_entry_interval_hours=4,
        # Live checks on the demo farm are demo-tagged (mixing guard).
        data_source="demo",
        data_confidence="simulated",
    )
    rule = next(
        r for r in p["decision_payload"]["rules"] if r["rule_id"] == "scouting_evidence"
    )
    assert rule["source_authority"] == "heuristic"
    assert "threshold" not in rule["detail"].lower()


def test_pca_authorized_replaces_definitive_everywhere(client, pinned_clock):
    import json
    seed.run()
    us = next(f for f in client.get("/farms").json() if f["country"] == "US")
    planned = client.get(f"/farms/{us['id']}/planned-sprays").json()
    captan = next(p for p in planned if p["product_name"] == "Captan 80 WDG")
    assert captan["decision_authority"] == "pca_authorized"
    for p in planned:
        assert "definitive" not in json.dumps(p["decision_payload"]).lower()
        assert "definitive" not in p["check_text"].lower()


# ------------------------------------------------------------------- demo reset
def test_demo_reset_refuses_when_real_data_exists(client, pinned_clock):
    seed.run()
    farm = _farm(client)  # a real (non-demo) farm with no records
    res = client.post("/internal/demo/reset")
    assert res.status_code == 409
    assert "refusing" in res.json()["detail"].lower()
    # The real farm survived.
    assert client.get(f"/farms/{farm['id']}").status_code == 200


def test_demo_reset_refuses_on_real_records_too(client, pinned_clock):
    seed.run()
    # A real spray can no longer land on a demo farm at all (mixing guard) — the
    # reset-blocking real record lives on its own real farm instead.
    farm = _farm(client)
    res = client.post(
        f"/farms/{farm['id']}/spray-events",
        json={
            "product_name": "Real Spray",
            "application_date": PINNED,
            "data_source": "manual_entry",
            "data_confidence": "user_provided",
        },
    )
    assert res.status_code == 201, res.text
    assert client.post("/internal/demo/reset").status_code == 409


# ------------------------------------------------------- demo/real mixing guard
def test_real_records_are_rejected_on_a_demo_farm(client, pinned_clock):
    seed.run()
    us = next(f for f in client.get("/farms").json() if f["country"] == "US")
    real_spray = {
        "product_name": "Real Spray",
        "application_date": PINNED,
        "data_source": "manual_entry",
        "data_confidence": "user_provided",
    }
    res = client.post(f"/farms/{us['id']}/spray-events", json=real_spray)
    assert res.status_code == 409
    assert "never mix" in res.json()["detail"]

    res = client.post(
        f"/farms/{us['id']}/scout-observations",
        json={"observation_date": PINNED, "visible_issue": "real issue"},
    )
    assert res.status_code == 409

    res = client.post(
        f"/farms/{us['id']}/planned-sprays",
        json={"intended_date": PINNED, "product_name": "Real Product"},
    )
    assert res.status_code == 409

    res = client.post(
        f"/farms/{us['id']}/input-plans",
        json={
            "requested_by": "Real grower",
            "items": [{
                "product_name": "Real product", "quantity": 1, "unit": "oz",
                "needed_by_date": "2026-07-20",
            }],
        },
    )
    assert res.status_code == 409


def test_demo_records_are_rejected_on_a_real_farm(client, pinned_clock):
    farm = _farm(client)
    _planned(client, farm["id"])  # first (real) record sets the farm's nature
    res = client.post(
        f"/farms/{farm['id']}/spray-events",
        json={
            "product_name": "Simulated Spray",
            "application_date": PINNED,
            "data_source": "demo",
            "data_confidence": "simulated",
        },
    )
    assert res.status_code == 409
    assert "never mix" in res.json()["detail"]


def test_demo_check_run_live_on_a_demo_farm_still_works(client, pinned_clock):
    """The demo walkthrough runs a check on the demo farm — tagged as demo, it lands."""
    seed.run()
    us = next(f for f in client.get("/farms").json() if f["country"] == "US")
    res = client.post(
        f"/farms/{us['id']}/planned-sprays",
        json={
            "intended_date": PINNED,
            "product_name": "Captan 80 WDG",
            "data_source": "demo",
            "data_confidence": "simulated",
        },
    )
    assert res.status_code == 201, res.text


# ------------------------------------------------------------ clock interlock
def test_pinned_clock_requires_explicit_demo_mode(monkeypatch):
    """A leftover LUMOS_DEMO_TODAY must never silently serve a live API."""
    from fastapi.testclient import TestClient

    from app.main import app as main_app

    monkeypatch.setenv("LUMOS_DEMO_TODAY", PINNED)
    monkeypatch.delenv("LUMOS_DEMO_MODE", raising=False)
    with pytest.raises(RuntimeError, match="LUMOS_DEMO_MODE"):
        with TestClient(main_app):
            pass


def test_health_reports_clock_mode(client, pinned_clock):
    body = client.get("/health").json()
    assert body["clock_mode"] == "pinned"
    assert body["pinned_date"] == PINNED


# ----------------------------------------------- missing data can never approve
def test_missing_inputs_never_approve():
    """The core safety rule: a check that could not run can never produce approve."""
    from types import SimpleNamespace

    from app.decision_engine import evaluate_planned_spray

    today = date(2026, 7, 10)
    farm = SimpleNamespace(expected_harvest_date=date(2026, 8, 15))
    complete = dict(
        intended_date=today,
        product_name="Product X",
        active_ingredient="captan",
        target_pest_or_disease="botrytis",
        pre_harvest_interval_days=1,
        re_entry_interval_hours=4,
    )
    scouting = [SimpleNamespace(
        observation_date=today, visible_issue="botrytis", severity_1_to_5=3
    )]

    # Control: with every input present and linked scouting evidence, the engine
    # CAN approve (still provisional, so review is required regardless).
    control = evaluate_planned_spray(
        farm, SimpleNamespace(**complete), [], scouting, today=today
    )
    assert control.outcome == "approve"
    assert control.review_required is True  # provisional approve still needs a PCA

    for missing_field in (
        "pre_harvest_interval_days", "re_entry_interval_hours", "active_ingredient",
    ):
        planned = SimpleNamespace(**{**complete, missing_field: None})
        decision = evaluate_planned_spray(farm, planned, [], scouting, today=today)
        assert decision.outcome != "approve", missing_field
        assert decision.review_required is True, missing_field
        assert decision.missing_information, missing_field

    no_harvest = SimpleNamespace(expected_harvest_date=None)
    decision = evaluate_planned_spray(
        no_harvest, SimpleNamespace(**complete), [], scouting, today=today
    )
    assert decision.outcome != "approve"
    assert decision.review_required is True


def test_imported_unverified_values_never_approve():
    from types import SimpleNamespace

    from app.decision_engine import evaluate_planned_spray

    today = date(2026, 7, 10)
    farm = SimpleNamespace(expected_harvest_date=date(2026, 8, 15))
    planned = SimpleNamespace(
        intended_date=today,
        product_name="Product X",
        active_ingredient="captan",
        target_pest_or_disease="botrytis",
        pre_harvest_interval_days=1,
        re_entry_interval_hours=4,
    )
    scouting = [SimpleNamespace(
        observation_date=today, visible_issue="botrytis", severity_1_to_5=3
    )]
    decision = evaluate_planned_spray(
        farm, planned, [], scouting, today=today,
        input_sources={
            "pre_harvest_interval_days": {"source_type": "imported_unverified"},
        },
    )
    assert decision.outcome != "approve"
    assert decision.outcome == "pca_review_required"
    assert decision.review_required is True


def test_demo_reset_reseeds_an_all_demo_db(client, pinned_clock):
    seed.run()
    res = client.post("/internal/demo/reset")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "reseeded"
    assert body["anchor"] == PINNED
    farms = client.get("/farms").json()
    assert len(farms) == 3
    assert any(f["country"] == "US" for f in farms)


# ---------------------------------------------------------- outcome vocabulary parity
def test_outcome_vocabulary_has_one_source_of_truth():
    """crud, pilot_evidence and schemas must never drift from decision_status.

    The vocabulary used to be restated in four places. Three now derive from
    decision_status; schemas.PlannedSprayOutcome still spells the Literal out because
    a Literal cannot be built from a runtime tuple readably — so this test is the
    thing that keeps it honest.
    """
    import typing

    from app import crud, decision_status, pilot_evidence, schemas

    canonical = decision_status.PLANNED_SPRAY_OUTCOMES

    assert crud.APPLIED_OUTCOMES is decision_status.APPLIED_OUTCOMES
    assert pilot_evidence._PLANNED_OUTCOMES == canonical
    assert set(typing.get_args(schemas.PlannedSprayOutcome)) == set(canonical)

    # "planned" is a starting state, not a recorded decision.
    assert decision_status.OUTCOME_PLANNED not in canonical
    # Applied and non-applied partition the vocabulary with no overlap.
    assert set(decision_status.APPLIED_OUTCOMES).isdisjoint(
        decision_status.NON_APPLIED_OUTCOMES
    )


# ------------------------------------------------- treated area is never unit-blended
def _area_record(acres, unit):
    from types import SimpleNamespace

    return SimpleNamespace(treated_acres=acres, treated_area_unit=unit)


def test_treated_area_totals_carry_their_unit():
    from app.pilot_evidence import _sum_treated_area

    total, unit, note = _sum_treated_area(
        [_area_record(4.0, "acres"), _area_record(6.0, "acres")]
    )
    assert total == 10.0
    assert unit == "acres"
    assert note is None


def test_treated_area_refuses_to_add_acres_to_square_metres():
    """The false-reduction guard: mixed units produce NO number, not a wrong one."""
    from app.pilot_evidence import _sum_treated_area

    total, unit, note = _sum_treated_area(
        [_area_record(4.0, "acres"), _area_record(2000.0, "m2")]
    )
    assert total is None
    assert unit is None
    assert "more than one area unit" in note
    assert "no conversion table exists" in note


def test_treated_area_never_assumes_acres_when_unit_is_missing():
    """An undeclared unit stays undeclared. Silently labelling it acres is the bug."""
    from app.pilot_evidence import _sum_treated_area

    total, unit, note = _sum_treated_area([_area_record(4.0, None)])
    assert total == 4.0
    assert unit is None
    assert "unit unspecified" in note

    # A declared unit mixed with an undeclared one is still a refusal.
    total, unit, note = _sum_treated_area(
        [_area_record(4.0, "acres"), _area_record(1.0, None)]
    )
    assert total is None
    assert "unspecified" in note


def test_no_code_path_claims_a_seasonal_or_active_ingredient_reduction():
    """Three different metrics that must never be read as one another."""
    from app.pilot_evidence import NOT_CALCULATED

    for key in (
        "active_ingredient_quantity_avoided",
        "risk_weighted_pesticide_reduction",
        "seasonal_pesticide_use_reduction",
    ):
        assert key in NOT_CALCULATED
        assert "not calculated" in NOT_CALCULATED[key]


def test_critical_input_fields_and_the_rows_actually_written_cannot_drift():
    """Every field declared compliance-critical really does get a provenance row.

    CRITICAL_INPUT_FIELDS used to be declared and referenced by nothing while
    _planned_input_rows kept a parallel hardcoded dict — so a field added to the
    declaration would silently have had no field-level provenance at all.
    """
    from app.crud import CRITICAL_INPUT_FIELDS, _planned_input_rows

    class _Planned:
        product_name = "Switch 62.5 WG"
        epa_reg_no = "100-953"
        crop = "strawberry"
        target_pest_or_disease = "gray mold"
        rate_amount = 14.0
        rate_unit = "oz/acre"
        pre_harvest_interval_days = 0
        re_entry_interval_hours = 12
        intended_date = date(2026, 7, 20)
        active_ingredient = "cyprodinil + fludioxonil"
        moa_group = "FRAC 9 + 12"

    written = [name for name, _value, _unit in _planned_input_rows(
        _Planned(), date(2026, 7, 24)
    )]
    assert written == list(CRITICAL_INPUT_FIELDS)
