"""Append-only follow-up timeline + confirmed-vs-estimated metric derivation."""
import pytest


@pytest.fixture(autouse=True)
def pinned_clock(monkeypatch):
    """Pin the app clock so the hard-coded story dates are chronologically valid."""
    monkeypatch.setenv("LUMOS_DEMO_TODAY", "2026-07-09")


def _farm(client):
    return client.post("/farms", json={
        "name": "Follow-up Farm", "country": "US", "crop_type": "strawberry",
        "expected_harvest_date": "2026-09-01", "greenhouse_area": 20.0,
        # Declared so treated-area totals carry a real unit; without it the evidence
        # correctly reports the area as unit-unspecified rather than assuming acres.
        "area_unit": "acres",
    }).json()


def _planned(client, farm_id, **overrides):
    payload = {
        "intended_date": "2026-07-10",
        "product_name": "PyGanic EC 5.0",
        "active_ingredient": "pyrethrins",
        "target_pest_or_disease": "lygus bug",
        "pre_harvest_interval_days": 0,
        "re_entry_interval_hours": 12,
        "estimated_cost": 95.0,
        "treated_acres": 10.0,
    }
    payload.update(overrides)
    return client.post(f"/farms/{farm_id}/planned-sprays", json=payload).json()


def _record_outcome(client, pid, outcome, reason="documented", date="2026-07-10"):
    resp = client.patch(f"/planned-sprays/{pid}/outcome", json={
        "outcome": outcome, "outcome_reason": reason, "outcome_date": date,
    })
    assert resp.status_code == 200, resp.text
    return resp.json()


def _add_event(client, pid, expect=201, **payload):
    resp = client.post(f"/planned-sprays/{pid}/follow-up-events", json=payload)
    assert resp.status_code == expect, resp.text
    return resp.json()


def _evidence(client, farm_id):
    return client.get(f"/farms/{farm_id}/decision-evidence").json()


def test_follow_up_requires_recorded_outcome(client):
    farm = _farm(client)
    p = _planned(client, farm["id"])
    _add_event(
        client, p["id"], expect=409,
        event_type="scouting_observation", observed_at="2026-07-12", severity=2,
    )


def test_follow_up_chronology_and_validation(client):
    farm = _farm(client)
    p = _planned(client, farm["id"])
    _record_outcome(client, p["id"], "avoided", "below threshold")
    # Cannot predate the decision check.
    _add_event(
        client, p["id"], expect=409,
        event_type="scouting_observation", observed_at="2020-01-01", severity=2,
    )
    # A rescue application must name the product actually applied.
    _add_event(
        client, p["id"], expect=422,
        event_type="rescue_application", observed_at="2026-07-15",
    )
    # A scouting event must carry a severity.
    _add_event(
        client, p["id"], expect=422,
        event_type="scouting_observation", observed_at="2026-07-15",
    )


def test_avoidance_is_estimated_until_follow_up_confirms_it(client):
    farm = _farm(client)
    p = _planned(client, farm["id"])
    _record_outcome(client, p["id"], "avoided", "held after inspection")

    ev = _evidence(client, farm["id"])
    assert ev["confirmed"]["applications_confirmed_avoided"] == 0
    assert ev["confirmed"]["confirmed_gross_spend_avoided"] == 0.0
    assert ev["estimated"]["avoided_outcomes_without_follow_up"] == 1
    assert ev["estimated"]["potential_gross_savings_unconfirmed"] == 95.0
    assert ev["follow_up"]["follow_up_required"] == 1
    assert ev["follow_up"]["follow_up_with_events"] == 0

    # Follow-up scouting with no application -> NOW it is confirmed.
    _add_event(
        client, p["id"],
        event_type="scouting_observation", observed_at="2026-07-14",
        severity=2, cost=30.0, rescue_required=False,
        evidence_notes="Pressure stayed below threshold.",
        entered_by="Jane PCA",
    )
    ev = _evidence(client, farm["id"])
    assert ev["confirmed"]["applications_confirmed_avoided"] == 1
    assert ev["confirmed"]["treated_area_confirmed_avoided"] == 10.0
    assert ev["confirmed"]["treated_area_confirmed_avoided_unit"] == "acres"
    assert ev["confirmed"]["confirmed_gross_spend_avoided"] == 95.0
    assert ev["confirmed"]["confirmed_additional_scouting_cost"] == 30.0
    assert ev["confirmed"]["confirmed_net_financial_result"] == 65.0
    assert ev["estimated"]["avoided_outcomes_without_follow_up"] == 0
    assert ev["follow_up"]["follow_up_completion_rate_pct"] == 100.0
    # Yield stays unknown until someone records it — never assumed neutral.
    assert ev["confirmed"]["yield_impact_counts"]["unknown"] == 1


def test_failed_delay_counts_as_negative_net_result(client):
    farm = _farm(client)
    p = _planned(client, farm["id"], product_name="Agri-Mek SC",
                 active_ingredient="abamectin",
                 target_pest_or_disease="twospotted spider mite",
                 estimated_cost=190.0)
    _record_outcome(client, p["id"], "delayed", "held to verify pressure")
    _add_event(
        client, p["id"],
        event_type="scouting_observation", observed_at="2026-07-13",
        severity=4, cost=40.0, evidence_notes="Flare-up after the delay.",
    )
    _add_event(
        client, p["id"],
        event_type="rescue_application", observed_at="2026-07-14",
        actual_product="Agri-Mek SC", cost=260.0, rescue_required=True,
        evidence_notes="Rescue required — the delay failed.",
    )
    ev = _evidence(client, farm["id"])
    assert ev["confirmed"]["applications_confirmed_avoided"] == 0
    assert ev["confirmed"]["confirmed_rescue_treatments"] == 1
    assert ev["confirmed"]["confirmed_rescue_cost"] == 260.0
    # Negative net result reported as negative — failures are counted, not hidden.
    assert ev["confirmed"]["confirmed_net_financial_result"] == -300.0


def test_confirmed_delay_duration_from_actual_application(client):
    farm = _farm(client)
    p = _planned(client, farm["id"])
    _record_outcome(client, p["id"], "delayed", "waiting out the REI")
    _add_event(
        client, p["id"],
        event_type="actual_application", observed_at="2026-07-16",
        actual_product="PyGanic EC 5.0", cost=95.0,
    )
    ev = _evidence(client, farm["id"])
    assert ev["confirmed"]["confirmed_delayed_decisions"] == 1
    assert ev["confirmed"]["confirmed_delay_days_total"] == 6  # 07-10 -> 07-16


def test_negative_yield_and_rejection_are_reported(client):
    farm = _farm(client)
    p = _planned(client, farm["id"])
    _record_outcome(client, p["id"], "avoided", "held")
    _add_event(
        client, p["id"],
        event_type="yield_quality_outcome", observed_at="2026-08-30",
        yield_impact="negative", quality_impact="negative",
        rejected_or_downgraded=True,
        evidence_notes="Fruit loss in the untreated block.",
    )
    ev = _evidence(client, farm["id"])
    assert ev["confirmed"]["yield_impact_counts"]["negative"] == 1
    assert ev["confirmed"]["rejected_or_downgraded_count"] == 1


def test_follow_up_events_are_append_only(client):
    farm = _farm(client)
    p = _planned(client, farm["id"])
    _record_outcome(client, p["id"], "avoided", "held")
    event = _add_event(
        client, p["id"],
        event_type="scouting_observation", observed_at="2026-07-12", severity=2,
    )
    # No update or delete surface exists for follow-up events.
    for method in ("patch", "put", "delete"):
        resp = getattr(client, method)(
            f"/planned-sprays/{p['id']}/follow-up-events/{event['id']}"
        )
        assert resp.status_code in (404, 405)
    # Adding another event never touches the first.
    _add_event(
        client, p["id"],
        event_type="note", observed_at="2026-07-13",
        evidence_notes="Still holding.",
    )
    events = client.get(f"/planned-sprays/{p['id']}/follow-up-events").json()
    assert events[0] == event
    assert len(events) == 2
