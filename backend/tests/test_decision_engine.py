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
    # "botrytis on fruit" != "botrytis": still NOT treated as linked evidence.
    # Since the ambiguity milestone, a partial name overlap escalates to PCA review
    # with the ambiguity recorded — never silently inferred as equivalent.
    d = evaluate_planned_spray(
        farm(harvest_offset_days=30), planned(target="botrytis"),
        [], [obs("botrytis on fruit", days_ago=3)], today=TODAY,
    )
    assert d.outcome == "pca_review_required"
    ambiguity = next(r for r in d.rules if r.rule_id == "scouting_target_ambiguity")
    assert ambiguity.triggered
    assert "botrytis on fruit" in ambiguity.detail
    # The scouting-evidence rule itself still reports no confirmed link.
    scouting = next(r for r in d.rules if r.rule_id == "scouting_evidence")
    assert scouting.triggered


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


def test_block_from_pca_entered_values_is_pca_authorized():
    d = evaluate_planned_spray(
        farm(harvest_offset_days=3),
        planned(phi=7, values_source="pca_entered", values_entered_by="Jane Doe, PCA"),
        [], [obs("botrytis", days_ago=3)], today=TODAY,
    )
    assert d.outcome == "block"
    assert d.authority_level == "pca_authorized"
    assert "PCA-authorized" in d.authority_basis
    assert "PROVISIONAL" not in d.narrative
    phi_rule = next(r for r in d.rules if r.rule_id == "phi_harvest_conflict")
    assert phi_rule.source_authority == "pca_entered"
    assert phi_rule.entered_by == "Jane Doe, PCA"
    assert phi_rule.verification_status == "unverified"  # still not a verified label


def test_engine_output_never_contains_definitive_string():
    # The old binary "definitive" vocabulary must be gone from every output surface.
    import json
    d = evaluate_planned_spray(
        farm(harvest_offset_days=3),
        planned(phi=7, values_source="pca_entered", values_entered_by="Jane Doe, PCA"),
        [], [obs("botrytis", days_ago=3)], today=TODAY,
    )
    assert "definitive" not in json.dumps(d.as_payload()).lower()
    assert "definitive" not in d.narrative.lower()


def test_approve_is_never_pca_authorized_even_with_pca_values():
    # Rotation and scouting checks are heuristics, so the "all clear" claim can never
    # be fully backed by PCA-entered or verified sources today.
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
    assert payload["authority_level"] in (
        "verified_label_grounded", "pca_authorized", "provisional"
    )
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


# ------------------------------------------------- PCA-entered action thresholds
def policy(target="lygus bug", threshold=3, entered_by="Jane Doe, PCA"):
    return SimpleNamespace(
        target_pest_or_disease=target,
        min_severity_to_treat=threshold,
        entered_by=entered_by,
    )


def test_policy_below_threshold_triggers_inspect_first_with_pca_citation():
    # Linked scouting exists but pressure is below the PCA-entered threshold.
    d = evaluate_planned_spray(
        farm(harvest_offset_days=30),
        planned(ai="pyrethrins", target="lygus bug", phi=0, rei=12),
        [], [obs("lygus bug", days_ago=1, severity=2)],
        pca_policies=[policy(threshold=3)], today=TODAY,
    )
    assert d.outcome == "inspect_first"
    assert d.authority_level == "provisional"  # inspect_first is a human decision
    rule = next(r for r in d.rules if r.rule_id == "scouting_evidence")
    assert rule.triggered is True
    assert rule.source_authority == "pca_entered"
    assert rule.entered_by == "Jane Doe, PCA"
    assert "PCA-entered action threshold" in rule.detail
    assert ">= 3" in rule.detail
    assert rule.inputs["pca_entered_threshold"] == 3
    assert rule.inputs["max_linked_severity"] == 2


def test_off_scale_severity_is_never_compared_to_a_threshold():
    """A 3 on a 1-10 scale is not a 3 on a 1-5 scale.

    Before this guard the engine read `severity_1_to_5` straight out of an imported
    record and compared it to the PCA threshold regardless of the scale stated
    alongside it — reading "threshold met" off a number that meant something else.
    The reading is reported and excluded, never converted.
    """
    off_scale = obs("lygus bug", days_ago=1, severity=3)
    off_scale.severity_scale = "1-10"

    d = evaluate_planned_spray(
        farm(harvest_offset_days=30),
        planned(ai="pyrethrins", target="lygus bug", phi=0, rei=12),
        [], [off_scale],
        pca_policies=[policy(threshold=3)], today=TODAY,
    )

    rule = next(r for r in d.rules if r.rule_id == "scouting_evidence")
    assert rule.triggered is True, "an incomparable severity must not satisfy a threshold"
    assert d.outcome != "approve"
    assert rule.inputs["max_linked_severity"] is None
    assert rule.inputs["excluded_off_scale_severities"] == [
        {"severity": 3, "severity_scale": "1-10"}
    ]
    assert "not comparable" in rule.detail.lower()
    assert rule.inputs["threshold_severity_scale"] == "1-5"


def test_unstated_severity_scale_is_treated_as_the_default_scale():
    """Every pre-existing record has no scale stated; they stay comparable."""
    d = evaluate_planned_spray(
        farm(harvest_offset_days=30),
        planned(ai="pyrethrins", target="lygus bug", phi=0, rei=12),
        [], [obs("lygus bug", days_ago=1, severity=4)],
        pca_policies=[policy(threshold=3)], today=TODAY,
    )
    rule = next(r for r in d.rules if r.rule_id == "scouting_evidence")
    assert rule.inputs["max_linked_severity"] == 4
    assert rule.inputs["excluded_off_scale_severities"] == []
    assert rule.triggered is False


def test_policy_no_scouting_at_all_triggers_inspect_first():
    d = evaluate_planned_spray(
        farm(harvest_offset_days=30),
        planned(ai="pyrethrins", target="lygus bug", phi=0, rei=12),
        [], [], pca_policies=[policy(threshold=3)], today=TODAY,
    )
    assert d.outcome == "inspect_first"
    rule = next(r for r in d.rules if r.rule_id == "scouting_evidence")
    assert "no scouting observation" in rule.detail.lower()
    assert rule.source_authority == "pca_entered"


def test_policy_met_threshold_does_not_trigger():
    d = evaluate_planned_spray(
        farm(harvest_offset_days=30),
        planned(ai="pyrethrins", target="lygus bug", phi=0, rei=12),
        [], [obs("lygus bug", days_ago=1, severity=4)],
        pca_policies=[policy(threshold=3)], today=TODAY,
    )
    rule = next(r for r in d.rules if r.rule_id == "scouting_evidence")
    assert rule.triggered is False
    assert d.outcome == "approve"
    # The policy-backed scouting check is pca_entered, but rotation/missing-data stay
    # heuristics, so an approve can still never be PCA-authorized.
    assert d.authority_level == "provisional"


def test_no_policy_keeps_heuristic_scouting_behavior():
    # Without a policy nothing may invent a threshold: exact-match evidence passes,
    # regardless of severity, and the rule stays a heuristic.
    d = evaluate_planned_spray(
        farm(harvest_offset_days=30),
        planned(ai="pyrethrins", target="lygus bug", phi=0, rei=12),
        [], [obs("lygus bug", days_ago=1, severity=1)], today=TODAY,
    )
    rule = next(r for r in d.rules if r.rule_id == "scouting_evidence")
    assert rule.triggered is False
    assert rule.source_authority == "heuristic"
    assert "threshold" not in rule.detail.lower()
    assert d.outcome == "approve"


def test_policy_for_other_target_is_ignored():
    d = evaluate_planned_spray(
        farm(harvest_offset_days=30),
        planned(target="botrytis"),
        [], [obs("botrytis", days_ago=1, severity=1)],
        pca_policies=[policy(target="lygus bug", threshold=3)], today=TODAY,
    )
    rule = next(r for r in d.rules if r.rule_id == "scouting_evidence")
    assert rule.source_authority == "heuristic"
    assert rule.triggered is False


# ---------------------------------------------------------------- PHI/REI zero
def test_phi_zero_is_a_value_not_missing_data():
    # PHI 0 days is a real label value (e.g. Switch on strawberries): the check RUNS
    # and passes when it clears by harvest — it must not escalate as missing data.
    d = evaluate_planned_spray(
        farm(harvest_offset_days=30),
        planned(phi=0, rei=0),
        [], [obs("botrytis", days_ago=3)], today=TODAY,
    )
    assert d.missing_information == []
    assert d.outcome == "approve"
    assert d.confidence == "high"
    phi_rule = next(r for r in d.rules if r.rule_id == "phi_harvest_conflict")
    assert phi_rule.triggered is False
    assert "+ 0 days" in phi_rule.calculation


# ------------------------------------------- alias matching / new import checks
def planned_full(**overrides):
    """A planned spray carrying the import-era fields (rate, MoA, EPA reg no)."""
    base = planned()
    for key, value in dict(
        epa_reg_no=None, moa_group=None, rate_amount=None, rate_unit=None,
    ).items():
        setattr(base, key, value)
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def test_alias_dictionary_links_scouting_evidence():
    # "gray mold" and "botrytis" are equivalent ONLY via the explicit alias
    # dictionary — this is a match, not an inference.
    d = evaluate_planned_spray(
        farm(harvest_offset_days=30), planned(target="gray mold"),
        [], [obs("botrytis", days_ago=3)], today=TODAY,
    )
    assert d.outcome == "approve"
    rule = next(r for r in d.rules if r.rule_id == "scouting_evidence")
    assert rule.triggered is False


def test_stale_matching_scouting_is_reported_as_stale():
    d = evaluate_planned_spray(
        farm(harvest_offset_days=30), planned(target="botrytis"),
        [], [obs("botrytis", days_ago=45)], today=TODAY,
    )
    assert d.outcome == "inspect_first"
    rule = next(r for r in d.rules if r.rule_id == "scouting_evidence")
    assert "stale evidence" in rule.detail
    assert "45 days ago" in rule.detail


def test_repeated_moa_group_escalates_only_with_structured_data():
    def moa_spray(days_ago):
        s = spray(ai=f"ai-{days_ago}", days_ago=days_ago)
        s.moa_group = "FRAC 9"
        return s

    sprays = [moa_spray(3), moa_spray(9)]
    d = evaluate_planned_spray(
        farm(harvest_offset_days=30),
        planned_full(ai="fresh-ai", moa_group="FRAC 9"),
        sprays, [obs("botrytis", days_ago=3)], today=TODAY,
    )
    assert d.outcome == "pca_review_required"
    rule = next(r for r in d.rules if r.rule_id == "repeated_moa_group")
    assert rule.triggered is True
    assert "frac 9" in rule.detail.lower()

    # Without a MoA group on the plan, the rule does not exist — never inferred
    # from the product or ingredient name.
    d2 = evaluate_planned_spray(
        farm(harvest_offset_days=30), planned_full(ai="fresh-ai"),
        sprays, [obs("botrytis", days_ago=3)], today=TODAY,
    )
    assert not [r for r in d2.rules if r.rule_id == "repeated_moa_group"]


def test_incomplete_rate_pair_requires_review():
    d = evaluate_planned_spray(
        farm(harvest_offset_days=30), planned_full(rate_amount=14.0),
        [], [obs("botrytis", days_ago=3)], today=TODAY,
    )
    assert d.outcome == "pca_review_required"
    rule = next(r for r in d.rules if r.rule_id == "rate_completeness")
    assert rule.triggered is True
    # A complete pair passes.
    d2 = evaluate_planned_spray(
        farm(harvest_offset_days=30),
        planned_full(rate_amount=14.0, rate_unit="oz/acre"),
        [], [obs("botrytis", days_ago=3)], today=TODAY,
    )
    assert d2.outcome == "approve"


def test_imported_values_can_never_auto_approve():
    # A clean scenario that WOULD approve with user-entered values...
    sources = {
        name: {"source_type": "imported_unverified", "entered_by": None}
        for name in ("product_name", "active_ingredient", "target_pest_or_disease",
                     "intended_date", "pre_harvest_interval_days",
                     "re_entry_interval_hours")
    }
    d = evaluate_planned_spray(
        farm(harvest_offset_days=30), planned(),
        [], [obs("botrytis", days_ago=3)], today=TODAY,
        input_sources=sources,
    )
    # ...escalates to PCA review when the values are imported and unverified.
    assert d.outcome == "pca_review_required"
    assert d.review_required is True
    assert d.authority_level == "provisional"
    rule = next(r for r in d.rules if r.rule_id == "unverified_imported_values")
    assert rule.triggered is True
    assert rule.source_authority == "imported_unverified"
    assert "never produce an automatic approve" in rule.detail


def test_label_dependent_checks_are_disclosed_not_simulated():
    from app import decision_engine as de

    d = evaluate_planned_spray(
        farm(harvest_offset_days=30), planned(),
        [], [obs("botrytis", days_ago=3)], today=TODAY,
    )
    payload = d.as_payload()
    checks = {c["check"] for c in payload["not_evaluated"]}
    assert "maximum seasonal rate" in checks
    assert "minimum retreatment interval" in checks
    # Each undisclosed check says why it did not run. Asserted against the constant
    # rather than a phrase: the wording changed on 2026-07-28 (a label table now
    # exists, so "no label database exists" became false), and a test that pins
    # prose re-fails every time honesty copy is corrected.
    assert all(
        c["reason"] == de.REASON_NO_LABEL_DATA for c in payload["not_evaluated"]
    )
    # And it must still name what is missing, not just assert emptiness.
    assert "authoritative label value" in de.REASON_NO_LABEL_DATA
    # No rule pretends to have run these.
    rule_ids = {r["rule_id"] for r in payload["rules"]}
    assert "max_seasonal_rate" not in rule_ids


# ------------------------------------------- the label-gap disclosure is computed
def test_every_label_dependent_check_is_disclosed_with_a_stable_id_and_a_reason():
    """The four checks carry an id as well as prose, so a rule can retire its own entry.

    Matching on the human name would make the disclosure impossible to narrow safely —
    a reworded check would silently stop being retired, or retire the wrong one.
    """
    from app import decision_engine as de

    d = evaluate_planned_spray(
        farm(harvest_offset_days=30), planned(),
        [], [obs("botrytis", days_ago=3)], today=TODAY,
    )
    entries = d.as_payload()["not_evaluated"]
    assert {e["check_id"] for e in entries} == {
        de.CHECK_MAX_SEASONAL_RATE,
        de.CHECK_MAX_APPLICATIONS,
        de.CHECK_RETREATMENT_INTERVAL,
        de.CHECK_CROP_REGISTRATION,
    }
    assert all(e["check"] and e["reason"] for e in entries)
    # The reason travels per check, so the narrative can print each one.
    assert de.REASON_NO_LABEL_DATA in d.narrative
    assert de.LABEL_DEPENDENT_CHECK_NAMES[de.CHECK_RETREATMENT_INTERVAL] in d.narrative


def test_a_check_that_runs_drops_out_of_the_disclosure():
    """The whole point of computing the list: a check that runs must stop being listed."""
    from app import decision_engine as de

    all_four = de.label_checks_not_evaluated()
    assert len(all_four) == 4

    narrowed = de.label_checks_not_evaluated({de.CHECK_RETREATMENT_INTERVAL})
    assert de.CHECK_RETREATMENT_INTERVAL not in {e["check_id"] for e in narrowed}
    assert len(narrowed) == 3

    assert de.label_checks_not_evaluated(set(de.LABEL_DEPENDENT_CHECK_NAMES)) == []


def test_an_unknown_check_id_never_silently_retires_a_real_check():
    """Fail-safe direction: only an exact id match removes a disclosure."""
    from app import decision_engine as de

    assert len(de.label_checks_not_evaluated({"max_seasonal_rate_v2"})) == 4


def test_the_disclosure_is_a_copy_so_one_decision_cannot_mutate_another():
    from app import decision_engine as de

    first = de.label_checks_not_evaluated()
    first[0]["reason"] = "tampered"
    assert de.label_checks_not_evaluated()[0]["reason"] == de.REASON_NO_LABEL_DATA
    assert de.NOT_EVALUATED_CHECKS[0]["reason"] == de.REASON_NO_LABEL_DATA
