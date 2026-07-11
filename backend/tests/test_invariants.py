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
    assert len(planned) == 2
    for p in planned:
        assert p["intended_date"] == PINNED
        assert p["outcome_date"] == PINNED
        assert p["created_at"][:10] == PINNED
        assert p["reviewed_at"][:10] == PINNED
        # Snapshot payload agrees with the stored columns (no drift).
        assert p["decision_payload"]["outcome"] == p["decision_outcome"]
        assert p["decision_payload"]["authority_level"] == p["decision_authority"]
        assert p["decision_payload"]["review_required"] == p["review_required"]


def test_no_invented_threshold_for_targets_without_policy(client, pinned_clock):
    seed.run()
    us = next(f for f in client.get("/farms").json() if f["country"] == "US")
    # A target with no policy on this farm: the scouting rule stays a heuristic.
    p = _planned(
        client, us["id"],
        intended_date=PINNED,
        product_name="Test Product",
        active_ingredient="novel-ai",
        target_pest_or_disease="spider mites",
        pre_harvest_interval_days=0,
        re_entry_interval_hours=4,
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
    us = next(f for f in client.get("/farms").json() if f["country"] == "US")
    # One real spray on a demo farm is enough to block the reset.
    client.post(
        f"/farms/{us['id']}/spray-events",
        json={
            "product_name": "Real Spray",
            "application_date": PINNED,
            "data_source": "manual_entry",
            "data_confidence": "user_provided",
        },
    )
    assert client.post("/internal/demo/reset").status_code == 409


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
