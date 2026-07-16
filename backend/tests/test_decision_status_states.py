"""Tests for the composed decision states (workflow / evidence / current next action).

Pure-function tests over duck-typed objects (decision_status imports nothing), plus
API-level assertions that the seeded demo scenarios expose coherent composed states —
the exact contradictions the UI used to show (a resolved decision presented as open,
a stale "inspect first" action after the inspection already happened) must be
impossible to re-derive from these fields.
"""
from types import SimpleNamespace

import pytest

from app import decision_status as ds
from app import seed

PINNED = "2026-07-10"


@pytest.fixture()
def seeded(client, monkeypatch):
    monkeypatch.setenv("LUMOS_DEMO_TODAY", PINNED)
    seed.run()
    return client


def _planned(**kwargs):
    defaults = dict(
        outcome="planned",
        review_required=False,
        review_status=None,
        decision_severity="none",
        decision_outcome="approve",
        spray_event_id=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _event(event_type, **kwargs):
    return SimpleNamespace(event_type=event_type, **kwargs)


# ------------------------------------------------------------- workflow_state
def test_workflow_open_without_required_review_needs_action():
    assert ds.workflow_state(_planned()) == ds.WORKFLOW_NEEDS_ACTION


def test_workflow_open_with_outstanding_review_awaits_pca():
    p = _planned(review_required=True)
    assert ds.workflow_state(p) == ds.WORKFLOW_AWAITING_PCA


def test_workflow_reviewed_but_open_needs_action():
    # The PCA answered; the grower still owes an outcome.
    p = _planned(review_required=True, review_status="edited")
    assert ds.workflow_state(p) == ds.WORKFLOW_NEEDS_ACTION


def test_workflow_any_recorded_outcome_is_resolved():
    for outcome in ("sprayed_as_planned", "changed_product", "delayed", "avoided",
                    "inspected_first"):
        assert ds.workflow_state(_planned(outcome=outcome)) == ds.WORKFLOW_RESOLVED


# ------------------------------------------------------------- evidence_state
def test_evidence_open_decision_is_missing_documentation():
    assert ds.evidence_state(_planned(), []) == ds.EVIDENCE_MISSING_DOCUMENTATION


def test_evidence_clean_as_planned_is_complete():
    p = _planned(outcome="sprayed_as_planned", decision_severity="none")
    assert ds.evidence_state(p, []) == ds.EVIDENCE_COMPLETE


def test_evidence_follow_up_outcome_without_events_is_required():
    p = _planned(outcome="avoided")
    assert ds.evidence_state(p, []) == ds.EVIDENCE_FOLLOW_UP_REQUIRED


def test_evidence_avoided_with_scouting_and_no_application_is_verified():
    p = _planned(outcome="avoided")
    events = [_event("scouting_observation")]
    assert ds.evidence_state(p, events) == ds.EVIDENCE_VERIFIED


def test_evidence_avoided_but_later_applied_is_in_progress_not_verified():
    # The events contradict the recorded outcome — never "verified".
    p = _planned(outcome="avoided")
    events = [_event("scouting_observation"), _event("actual_application")]
    assert ds.evidence_state(p, events) == ds.EVIDENCE_FOLLOW_UP_IN_PROGRESS


def test_evidence_changed_product_confirmed_by_application_or_link():
    p = _planned(outcome="changed_product")
    assert ds.evidence_state(p, [_event("actual_application")]) == ds.EVIDENCE_VERIFIED
    linked = _planned(outcome="changed_product", spray_event_id=7)
    assert ds.evidence_state(linked, [_event("note")]) == ds.EVIDENCE_VERIFIED


def test_evidence_delayed_confirmed_only_once_an_application_is_on_record():
    p = _planned(outcome="delayed")
    scout_only = [_event("scouting_observation")]
    assert ds.evidence_state(p, scout_only) == ds.EVIDENCE_FOLLOW_UP_IN_PROGRESS
    with_rescue = scout_only + [_event("rescue_application")]
    assert ds.evidence_state(p, with_rescue) == ds.EVIDENCE_VERIFIED


def test_evidence_approved_despite_warning_requires_follow_up():
    p = _planned(outcome="sprayed_as_planned", decision_severity="caution")
    assert ds.evidence_state(p, []) == ds.EVIDENCE_FOLLOW_UP_REQUIRED
    assert ds.evidence_state(p, [_event("note")]) == ds.EVIDENCE_VERIFIED


# ------------------------------------------------------- current_next_action
def test_next_action_outstanding_review_comes_first():
    p = _planned(review_required=True, decision_severity="critical",
                 decision_outcome="block")
    assert ds.current_next_action(p, []) == ds.NEXT_AWAIT_PCA_REVIEW


def test_next_action_open_conflict_after_review_is_resolve_conflict():
    p = _planned(review_required=True, review_status="edited",
                 decision_severity="critical", decision_outcome="block")
    assert ds.current_next_action(p, []) == ds.NEXT_RESOLVE_CONFLICT


def test_next_action_open_inspect_first_is_inspect():
    p = _planned(decision_outcome="inspect_first")
    assert ds.current_next_action(p, []) == ds.NEXT_INSPECT


def test_next_action_resolved_with_missing_follow_up_is_record_follow_up():
    # THE fixed contradiction: INSPECT FIRST + recorded AVOIDED must never
    # keep saying "inspect" — the current action is recording follow-up.
    p = _planned(outcome="avoided", decision_outcome="inspect_first")
    assert ds.workflow_state(p) == ds.WORKFLOW_RESOLVED
    assert ds.current_next_action(p, []) == ds.NEXT_RECORD_FOLLOW_UP


def test_next_action_fully_documented_decision_has_none():
    p = _planned(outcome="avoided", decision_outcome="inspect_first")
    events = [_event("scouting_observation")]
    assert ds.evidence_state(p, events) == ds.EVIDENCE_VERIFIED
    assert ds.current_next_action(p, events) == ds.NEXT_NONE


# ------------------------------------------------- seeded demo scenarios (API)
def test_seeded_scenarios_expose_coherent_composed_states(seeded):
    farms = seeded.get("/farms").json()
    us = next(f for f in farms if f["country"] == "US")
    planned = seeded.get(f"/farms/{us['id']}/planned-sprays").json()
    by_product = {p["product_name"]: p for p in planned}

    # All three demo decisions are resolved; verdicts stay visible as history.
    for p in planned:
        assert p["workflow_state"] == "resolved"
        assert p["decision_outcome"] in ("block", "inspect_first")

    # Scenario 1: BLOCK + changed product, replacement application on record.
    captan = by_product["Captan 80 WDG"]
    assert captan["outcome"] == "changed_product"
    assert captan["evidence_state"] == "verified"
    assert captan["current_next_action"] == "none"

    # Scenario 2: INSPECT FIRST + avoided, follow-up inspection recorded.
    pyganic = by_product["PyGanic EC 5.0"]
    assert pyganic["outcome"] == "avoided"
    assert pyganic["evidence_state"] == "verified"
    assert pyganic["current_next_action"] == "none"

    # Scenario 3: honest failure — delayed, rescue application recorded.
    agrimek = by_product["Agri-Mek SC"]
    assert agrimek["outcome"] == "delayed"
    assert agrimek["evidence_state"] == "verified"
    assert agrimek["current_next_action"] == "none"


def test_api_open_decision_states(client):
    farm = client.post("/farms", json={
        "name": "State Farm", "country": "US", "crop_type": "strawberry",
        "expected_harvest_date": "2030-01-01",
    }).json()
    p = client.post(f"/farms/{farm['id']}/planned-sprays", json={
        "intended_date": "2029-12-01", "product_name": "TestProd",
        "pre_harvest_interval_days": 1, "re_entry_interval_hours": 4,
        "values_source": "grower_entered",
    }).json()
    assert p["is_open"] is True
    assert p["workflow_state"] in ("needs_action", "awaiting_pca")
    assert p["evidence_state"] == "missing_documentation"
    assert p["current_next_action"] in (
        "await_pca_review", "resolve_conflict", "inspect", "record_outcome"
    )
