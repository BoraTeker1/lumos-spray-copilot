"""Unit tests for the pre-spray decision engine (pure, no DB).

SimpleNamespace stand-ins with a fixed `today`, same style as
test_recommendation_engine.py.
"""
from datetime import date, timedelta
from types import SimpleNamespace

from app.decision_engine import (
    PLANNED_SPRAY_DISCLAIMER,
    evaluate_planned_spray,
)

TODAY = date(2026, 7, 9)


def farm(harvest_offset_days=None):
    harvest = (
        TODAY + timedelta(days=harvest_offset_days)
        if harvest_offset_days is not None
        else None
    )
    return SimpleNamespace(expected_harvest_date=harvest)


def spray(ai="captan", days_ago=1, rei_hours=None):
    return SimpleNamespace(
        active_ingredient=ai,
        application_date=TODAY - timedelta(days=days_ago),
        pre_harvest_interval_days=None,
        re_entry_interval_hours=rei_hours,
        product_name="Test Product",
    )


def obs(issue, days_ago=1, severity=2):
    return SimpleNamespace(
        observation_date=TODAY - timedelta(days=days_ago),
        severity_1_to_5=severity,
        visible_issue=issue,
    )


def planned(
    ai="captan",
    target="botrytis",
    phi=2,
    rei=12,
    intended_offset_days=1,
    values_source="grower_entered",
    values_entered_by=None,
):
    return SimpleNamespace(
        intended_date=TODAY + timedelta(days=intended_offset_days),
        product_name="Captan 80WDG",
        active_ingredient=ai,
        target_pest_or_disease=target,
        pre_harvest_interval_days=phi,
        re_entry_interval_hours=rei,
        values_source=values_source,
        values_entered_by=values_entered_by,
    )


def complete_ok_scenario():
    """All inputs present, no conflicts, linked scouting -> approve."""
    return dict(
        farm=farm(harvest_offset_days=30),
        planned=planned(),
        spray_events=[],
        scout_observations=[obs("botrytis", days_ago=3)],
    )


# ------------------------------------------------------------------- outcomes
def test_approve_when_everything_checks_out():
    s = complete_ok_scenario()
    d = evaluate_planned_spray(s["farm"], s["planned"], s["spray_events"],
                               s["scout_observations"], today=TODAY)
    assert d.outcome == "approve"
    assert d.severity == "none"
    assert d.confidence == "high"
    assert d.missing_information == []
    assert not d.triggered_rules
    # Grower-entered values + heuristic checks -> approve is PROVISIONAL and still
    # needs PCA confirmation. A definitive green light is impossible without a
    # verified label or PCA-entered values behind every determining check.
    assert d.authority_level == "provisional"
    assert d.review_required is True


def test_phi_conflict_blocks():
    # Intended tomorrow + PHI 7 clears day 8; harvest day 3 -> block.
    d = evaluate_planned_spray(
        farm(harvest_offset_days=3), planned(phi=7), [],
        [obs("botrytis", days_ago=3)], today=TODAY,
    )
    assert d.outcome == "block"
    assert d.severity == "critical"
    assert d.review_required is True
    triggered = {r.rule_id for r in d.triggered_rules}
    assert "phi_harvest_conflict" in triggered
    # The arithmetic is shown.
    phi_rule = next(r for r in d.rules if r.rule_id == "phi_harvest_conflict")
    assert "+ 7 days" in phi_rule.calculation


def test_rei_active_at_harvest_blocks():
    # Intended tomorrow, REI 72h -> clears day 4; harvest day 2 -> block.
    d = evaluate_planned_spray(
        farm(harvest_offset_days=2), planned(phi=1, rei=72), [],
        [obs("botrytis", days_ago=1)], today=TODAY,
    )
    assert d.outcome == "block"
    assert any(r.rule_id == "rei_active_at_harvest" for r in d.triggered_rules)


def test_prior_rei_overlap_delays():
    # A spray today with REI 72h clears day 3; intended tomorrow -> delay.
    d = evaluate_planned_spray(
        farm(harvest_offset_days=30),
        planned(ai="azoxystrobin"),
        [spray(days_ago=0, rei_hours=72)],
        [obs("botrytis", days_ago=1)],
        today=TODAY,
    )
    assert d.outcome == "delay"
    assert any(r.rule_id == "prior_rei_overlap" for r in d.triggered_rules)


def test_repeated_ingredient_requires_pca_review():
    # 2 recent captan uses; the planned one would be the 3rd -> over the limit.
    d = evaluate_planned_spray(
        farm(harvest_offset_days=30), planned(),
        [spray(days_ago=5), spray(days_ago=15)],
        [obs("botrytis", days_ago=3)],
        today=TODAY,
    )
    assert d.outcome == "pca_review_required"
    rule = next(r for r in d.rules if r.rule_id == "repeated_active_ingredient")
    assert rule.triggered
    assert "use number 3" in rule.detail


def test_old_sprays_outside_window_do_not_count():
    d = evaluate_planned_spray(
        farm(harvest_offset_days=30), planned(),
        [spray(days_ago=40), spray(days_ago=50)],
        [obs("botrytis", days_ago=3)],
        today=TODAY,
    )
    assert d.outcome == "approve"


def test_no_linked_scouting_means_inspect_first():
    d = evaluate_planned_spray(
        farm(harvest_offset_days=30), planned(), [], [], today=TODAY
    )
    assert d.outcome == "inspect_first"
    rule = next(r for r in d.rules if r.rule_id == "scouting_evidence")
    assert rule.triggered


def test_near_miss_scouting_text_is_not_a_link():
    # "botrytis on fruit" != "botrytis": exact normalized match only.
    d = evaluate_planned_spray(
        farm(harvest_offset_days=30), planned(target="botrytis"),
        [], [obs("botrytis on fruit", days_ago=3)], today=TODAY,
    )
    assert d.outcome == "inspect_first"


def test_exact_normalized_match_links():
    d = evaluate_planned_spray(
        farm(harvest_offset_days=30), planned(target="botrytis"),
        [], [obs("  Botrytis ", days_ago=3)], today=TODAY,
    )
    assert d.outcome == "approve"


# ------------------------------------------------------------- missing data
def test_missing_phi_escalates_to_pca_review_never_approve():
    d = evaluate_planned_spray(
        farm(harvest_offset_days=30), planned(phi=None), [],
        [obs("botrytis", days_ago=3)], today=TODAY,
    )
    assert d.outcome == "pca_review_required"
    assert any("PHI" in m for m in d.missing_information)
    assert d.confidence == "medium"  # exactly one missing input


def test_missing_harvest_date_escalates():
    d = evaluate_planned_spray(
        farm(), planned(), [], [obs("botrytis", days_ago=3)], today=TODAY
    )
    assert d.outcome == "pca_review_required"
    assert any("harvest date" in m.lower() for m in d.missing_information)


def test_multiple_missing_inputs_drop_confidence_to_low():
    d = evaluate_planned_spray(
        farm(), planned(ai="", phi=None, rei=None, target=""), [], [], today=TODAY
    )
    assert d.outcome == "pca_review_required"
    assert d.confidence == "low"
    assert len(d.missing_information) >= 2


# --------------------------------------------------------- precedence + payload
def test_block_takes_precedence_over_everything():
    # PHI conflict + repeated AI + no scouting + prior REI all at once -> block.
    d = evaluate_planned_spray(
        farm(harvest_offset_days=1),
        planned(phi=7),
        [spray(days_ago=0, rei_hours=72), spray(days_ago=5)],
        [],
        today=TODAY,
    )
    assert d.outcome == "block"
    assert d.severity == "critical"


def test_payload_is_complete_and_serializable():
    s = complete_ok_scenario()
    d = evaluate_planned_spray(s["farm"], s["planned"], s["spray_events"],
                               s["scout_observations"], today=TODAY)
    payload = d.as_payload()
    assert payload["outcome"] == "approve"
    assert payload["disclaimer"] == PLANNED_SPRAY_DISCLAIMER
    assert payload["inputs_used"]["intended_date"] == (TODAY + timedelta(days=1)).isoformat()
    rule_ids = {r["rule_id"] for r in payload["rules"]}
    # Every check that ran appears in the audit trail, triggered or not.
    assert {"phi_harvest_conflict", "rei_active_at_harvest", "prior_rei_overlap",
            "repeated_active_ingredient", "scouting_evidence", "missing_data"} <= rule_ids
    import json
    json.dumps(payload)  # must be JSON-serializable for the DB column


# ----------------------------------------------------------- authority gating
def test_block_from_grower_entered_values_is_provisional():
    d = evaluate_planned_spray(
        farm(harvest_offset_days=3), planned(phi=7), [],
        [obs("botrytis", days_ago=3)], today=TODAY,
    )
    assert d.outcome == "block"
    assert d.authority_level == "provisional"
    assert "grower-entered" in d.authority_basis
    assert "PROVISIONAL BLOCK" in d.narrative


def test_block_from_pca_entered_values_is_definitive():
    d = evaluate_planned_spray(
        farm(harvest_offset_days=3),
        planned(phi=7, values_source="pca_entered", values_entered_by="Jane Doe, PCA"),
        [], [obs("botrytis", days_ago=3)], today=TODAY,
    )
    assert d.outcome == "block"
    assert d.authority_level == "definitive"
    assert "PROVISIONAL" not in d.narrative
    phi_rule = next(r for r in d.rules if r.rule_id == "phi_harvest_conflict")
    assert phi_rule.source_authority == "pca_entered"
    assert phi_rule.entered_by == "Jane Doe, PCA"
    assert phi_rule.verification_status == "unverified"  # still not a verified label


def test_approve_is_never_definitive_even_with_pca_values():
    # Rotation and scouting checks are heuristics, so the "all clear" claim can never
    # be fully backed by definitive sources today.
    s = complete_ok_scenario()
    s["planned"].values_source = "pca_entered"
    d = evaluate_planned_spray(s["farm"], s["planned"], s["spray_events"],
                               s["scout_observations"], today=TODAY)
    assert d.outcome == "approve"
    assert d.authority_level == "provisional"
    assert d.review_required is True


def test_every_rule_carries_source_authority_in_payload():
    d = evaluate_planned_spray(
        farm(harvest_offset_days=1), planned(phi=7),
        [spray(days_ago=2), spray(days_ago=4)], [], today=TODAY,
    )
    payload = d.as_payload()
    assert payload["authority_level"] in ("definitive", "provisional")
    assert payload["authority_basis"]
    for r in payload["rules"]:
        assert r["source_authority"] in (
            "verified_label", "pca_entered", "grower_entered", "heuristic"
        )
        assert r["verification_status"] in ("verified", "unverified")
    heuristic_rules = {r["rule_id"] for r in payload["rules"]
                       if r["source_authority"] == "heuristic"}
    assert "repeated_active_ingredient" in heuristic_rules
    assert "missing_data" in heuristic_rules
    # Nothing can claim a verified label until label data actually exists.
    assert all(r["verification_status"] == "unverified" for r in payload["rules"])


def test_engine_never_recommends_a_replacement_product():
    # Replacement products may only come from explicit PCA-entered guidance, never
    # from engine output.
    for scenario in (
        (farm(harvest_offset_days=1), planned(phi=7)),                    # block
        (farm(harvest_offset_days=30), planned(), [spray(days_ago=5),
                                                   spray(days_ago=15)]),  # rotation
        (farm(), planned(phi=None, rei=None)),                            # missing data
    ):
        f, p = scenario[0], scenario[1]
        sprays = scenario[2] if len(scenario) > 2 else []
        d = evaluate_planned_spray(f, p, sprays, [], today=TODAY)
        lower = d.narrative.lower()
        assert "switch to" not in lower
        assert "instead" not in lower
        assert "use product" not in lower


# ------------------------------------------------------------ cautious language
def test_narrative_stays_cautious_and_carries_disclaimer():
    d = evaluate_planned_spray(
        farm(harvest_offset_days=1), planned(phi=7),
        [spray(days_ago=2), spray(days_ago=4)], [], today=TODAY,
    )
    assert PLANNED_SPRAY_DISCLAIMER in d.narrative
    lower = d.narrative.lower()
    assert "must spray" not in lower
    assert "don't spray" not in lower
    assert "do not spray" not in lower
    assert d.required_next_action  # always present
