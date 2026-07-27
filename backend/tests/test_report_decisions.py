"""The decision workflow must reach the artifacts the customer actually receives.

Until this block existed, the weekly report and the audit packet were built entirely
from the legacy farm-wide recommendation path: a grower's WhatsApp message and an
auditor's packet mentioned zero pre-spray decisions. The product's whole output was
invisible in its own deliverables.

The tests that matter here are the honesty ones — a simulated record must be labelled,
an unreviewed verdict must not read as guidance, and a count must describe what was
documented rather than what was prevented.
"""
from datetime import date, timedelta

from app.pilot_evidence import summarize_decisions_for_report

TODAY = date.today()


def _farm(client, name="Report Farm", **overrides):
    payload = {
        "name": name, "country": "US", "crop_type": "strawberry", "area_unit": "acres",
        "expected_harvest_date": (TODAY + timedelta(days=3)).isoformat(),
    }
    payload.update(overrides)
    return client.post("/farms", json=payload).json()


def _planned(client, farm_id, **overrides):
    payload = {
        "intended_date": (TODAY + timedelta(days=1)).isoformat(),
        "product_name": "Captan 80 WDG",
        "active_ingredient": "captan",
        "target_pest_or_disease": "botrytis_fruit_rot",
        "pre_harvest_interval_days": 14,   # clears after harvest -> BLOCK
        "re_entry_interval_hours": 24,
    }
    payload.update(overrides)
    res = client.post(f"/farms/{farm_id}/planned-sprays", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


# ------------------------------------------------------------------ the block
def test_a_blocked_decision_reaches_the_weekly_report(client):
    farm = _farm(client)
    _planned(client, farm["id"])

    text = client.get(f"/farms/{farm['id']}/weekly-report").json()["text"]

    assert "This week's spray decisions" in text
    assert "Captan 80 WDG" in text
    assert "BLOCKED" in text
    # The REASON, not just the verdict — that is what makes the message useful.
    assert "AFTER the expected harvest" in text
    assert "1 conflict(s) caught before application" in text


def test_the_report_says_nothing_when_there_are_no_decisions(client):
    """A farm with no checks must not grow an empty, confusing section."""
    farm = _farm(client)

    text = client.get(f"/farms/{farm['id']}/weekly-report").json()["text"]

    assert "This week's spray decisions" not in text


def test_a_decision_awaiting_review_is_never_presented_as_guidance(client):
    farm = _farm(client)
    _planned(client, farm["id"])

    text = client.get(f"/farms/{farm['id']}/weekly-report").json()["text"]

    assert "Awaiting review — not yet guidance." in text
    assert "1 awaiting review" in text


def test_a_recorded_outcome_replaces_the_awaiting_review_line(client):
    farm = _farm(client)
    decision = _planned(client, farm["id"])
    client.patch(f"/planned-sprays/{decision['id']}/review", json={
        "action": "approved", "reviewed_by": "Dana PCA",
    })
    client.patch(f"/planned-sprays/{decision['id']}/outcome", json={
        "outcome": "avoided", "outcome_reason": "Scouting pressure stayed below threshold.",
    })

    text = client.get(f"/farms/{farm['id']}/weekly-report").json()["text"]

    assert "Recorded outcome: not applied." in text
    assert "Awaiting review" not in text
    assert "1 application(s) recorded as not applied" in text


# ------------------------------------------------------------------- honesty
def test_simulated_records_are_labelled_in_the_report(client):
    """A demo farm's decisions must never read as real usage."""
    farm = _farm(client, "Demo Report Farm")
    _planned(client, farm["id"], data_source="demo", data_confidence="simulated")

    text = client.get(f"/farms/{farm['id']}/weekly-report").json()["text"]

    assert "SIMULATED demo records — not real usage" in text


def test_the_summary_never_claims_prevention_or_savings(client):
    """ENGINEERING_GUIDELINES.md §10 wording: documented, not prevented; not applied, not saved."""
    farm = _farm(client)
    _planned(client, farm["id"])

    text = client.get(f"/farms/{farm['id']}/weekly-report").json()["text"].lower()

    for forbidden in ("prevented", "saved you", "guaranteed", "we stopped"):
        assert forbidden not in text


def test_the_note_states_documented_not_caused():
    summary = summarize_decisions_for_report([])
    assert "not outcomes it caused" in summary["note"]
    assert "not a confirmed" in summary["note"]


# --------------------------------------------------------------- audit packet
def test_the_audit_packet_carries_the_structured_decision_trail(client):
    farm = _farm(client)
    decision = _planned(client, farm["id"])

    packet = client.get(f"/farms/{farm['id']}/audit-packet").json()

    trail = packet["spray_decisions"]
    assert trail["scope"] == "real"
    assert trail["checked"] == 1
    assert trail["conflicts_caught"] == 1
    row = trail["decisions"][0]
    assert row["product_name"] == "Captan 80 WDG"
    assert row["verdict"] == "block"
    # Dates are serialized for the JSON packet, not left as date objects.
    assert isinstance(row["intended_date"], str)
    assert row["reason"]
    # And the human-readable block is in the packet's report text too.
    assert "BLOCKED" in packet["weekly_report_text"]
    assert decision["id"]


def test_the_audit_packet_marks_a_demo_farm_as_simulated(client):
    farm = _farm(client, "Demo Audit Farm")
    _planned(client, farm["id"], data_source="demo", data_confidence="simulated")

    trail = client.get(f"/farms/{farm['id']}/audit-packet").json()["spray_decisions"]

    assert trail["scope"] == "simulated"
    assert trail["is_simulated"] is True


# ------------------------------------------------------------------ pure unit
def test_real_records_win_when_both_scopes_somehow_exist():
    """A real decision must never be hidden behind a simulated label."""
    from types import SimpleNamespace

    real = SimpleNamespace(
        data_source="manual_entry", data_confidence="user_provided",
        product_name="Real", intended_date=TODAY, decision_outcome="block",
        decision_severity="critical", decision_payload={}, outcome="planned",
        review_required=True, review_status="not_reviewed",
    )
    demo = SimpleNamespace(
        data_source="demo", data_confidence="simulated",
        product_name="Demo", intended_date=TODAY, decision_outcome="approve",
        decision_severity="none", decision_payload={}, outcome="planned",
        review_required=False, review_status="not_reviewed",
    )

    summary = summarize_decisions_for_report([demo, real])

    assert summary["scope"] == "real"
    assert summary["checked"] == 1
    assert summary["decisions"][0]["product_name"] == "Real"
