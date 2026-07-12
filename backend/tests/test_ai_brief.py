"""AI review brief: retrieval, forced abstention, enum-locked actions, judgment log."""
import pytest
from pydantic import ValidationError

from app import ai_brief


@pytest.fixture(autouse=True)
def pinned_clock_and_mock(monkeypatch):
    monkeypatch.setenv("LUMOS_DEMO_TODAY", "2026-07-15")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from app import llm, main
    monkeypatch.setattr(main.llm, "default_llm_service", llm.MockLlmService())


def _farm(client):
    return client.post("/farms", json={
        "name": "Brief Farm", "country": "US", "crop_type": "strawberry",
        "expected_harvest_date": "2026-09-01",
    }).json()


def _planned(client, farm_id, **overrides):
    payload = {
        "intended_date": "2026-07-20",
        "product_name": "PyGanic EC 5.0",
        "active_ingredient": "pyrethrins",
        "target_pest_or_disease": "lygus bug",
        "pre_harvest_interval_days": 0,
        "re_entry_interval_hours": 12,
    }
    payload.update(overrides)
    resp = client.post(f"/farms/{farm_id}/planned-sprays", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _brief(client, planned_id):
    resp = client.post(f"/planned-sprays/{planned_id}/ai-brief")
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_forced_abstention_below_min_comparables(client):
    """The mock always answers 'low' — the server-side guard must overrule it."""
    farm = _farm(client)
    p = _planned(client, farm["id"])
    brief = _brief(client, p["id"])
    assert brief["comparable_count"] == 0
    assert brief["rescue_risk"] == "abstain"
    assert brief["abstained"] is True
    assert "below the minimum" in brief["abstain_reason"]
    assert brief["confidence"] == "none"
    assert brief["is_mock"] is True
    assert brief["disclaimer"].startswith("AI-suggested, not confirmed")


def test_risk_note_stands_with_enough_comparables(client):
    farm = _farm(client)
    # Two prior decisions on the same target (alias-matched: "lygus" ~ "lygus bug").
    _planned(client, farm["id"], intended_date="2026-07-16", target_pest_or_disease="lygus")
    _planned(client, farm["id"], intended_date="2026-07-17",
             product_name="Other", active_ingredient="pyrethrins",
             target_pest_or_disease="lygus bug")
    p = _planned(client, farm["id"], intended_date="2026-07-21")
    brief = _brief(client, p["id"])
    assert brief["comparable_count"] == 2
    assert brief["rescue_risk"] == "low"  # mock verdict allowed to stand
    assert brief["abstained"] is False
    ids = {c["id"] for c in brief["comparables"]}
    assert p["id"] not in ids
    # Every comparable explains WHY it matched and carries follow-up state.
    assert all(c["match_basis"] for c in brief["comparables"])
    assert all("follow_up" in c for c in brief["comparables"])


def test_demo_decisions_never_count_as_comparables(client, monkeypatch):
    from app import seed
    monkeypatch.setenv("LUMOS_DEMO_TODAY", "2026-07-10")
    seed.run()
    us = next(f for f in client.get("/farms").json() if f["country"] == "US")
    # The demo farm has three seeded decision stories — all demo/simulated.
    monkeypatch.setenv("LUMOS_DEMO_TODAY", "2026-07-15")
    p = _planned(client, us["id"], target_pest_or_disease="lygus bug")
    brief = _brief(client, p["id"])
    assert brief["comparable_count"] == 0          # demo excluded from retrieval
    assert brief["rescue_risk"] == "abstain"        # so the guard abstains


def test_actions_are_enum_locked_to_evidence_gathering(client):
    farm = _farm(client)
    p = _planned(client, farm["id"])
    brief = _brief(client, p["id"])
    allowed = {"rescout_target", "verify_phi_rei_from_label",
               "confirm_threshold_with_pca", "record_follow_up",
               "wait_and_recheck", "consult_pca"}
    assert brief["next_evidence_actions"]
    assert all(a["action_type"] in allowed for a in brief["next_evidence_actions"])
    # A product recommendation is not expressible in the schema at all.
    with pytest.raises(ValidationError):
        ai_brief.EvidenceAction(action_type="apply_product", detail="spray X")


def test_brief_logs_two_judgments_and_never_touches_the_decision(client):
    farm = _farm(client)
    p = _planned(client, farm["id"])
    before = client.get(f"/planned-sprays/{p['id']}").json()
    brief = _brief(client, p["id"])
    assert len(brief["judgment_ids"]) == 2

    after = client.get(f"/planned-sprays/{p['id']}").json()
    assert after == before  # decision columns, review, outcome: all untouched

    # Judgments carry the calibration substrate fields.
    from app import crud
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        judgments = crud.list_ai_judgments(db, planned_spray_id=p["id"])
        assert sorted(j.kind for j in judgments) == ["next_evidence_action", "risk_note"]
        assert all(j.is_mock for j in judgments)
        assert all(j.prompt_version == ai_brief.PROMPT_VERSION for j in judgments)
        assert all(len(j.input_digest) == 64 for j in judgments)
        assert all(j.abstained for j in judgments)  # 0 comparables ⇒ abstained
    finally:
        db.close()


def test_post_guard_pure_function():
    happy = ai_brief.AiBrief(rescue_risk="high", confidence="medium", rationale="x")
    guarded = ai_brief.apply_post_guards(happy, comparable_count=1)
    assert guarded.rescue_risk == "abstain" and guarded.abstained
    assert guarded.confidence == "none"
    kept = ai_brief.apply_post_guards(happy, comparable_count=2)
    assert kept.rescue_risk == "high" and not kept.abstained
