"""The finance decision layer: scoring, underwriting, collateral, insurance, monitoring.

Every module here ships with an EMPTY source, so on today's data every entry point
refuses. These tests pin three things, in descending order of how much damage their
absence would do:

1. **The refusals happen at all** — no model defaults, guesses, or partially answers.
2. **The claim vocabulary stays out of the payloads** — a payload-walking guard, in the
   spirit of `backtest.FORBIDDEN_KEY_SUBSTRINGS`, so `approved` / `funded` / `premium`
   cannot be added to a finance payload without a test failing.
3. **The directional rules hold** — a partial score refuses (it would read as a worse
   borrower), an unchecked covenant is not compliance, an unevaluated policy rule is not
   a pass.

Populated cases run against SYNTHETIC sources built here. No invented number is ever
left in a shipped module.
"""
from datetime import date, datetime

import pytest

from app import (
    collateral,
    collateral_valuation,
    credit_scoring,
    insurance,
    insurance_products,
    monitoring,
    monitoring_covenants,
    scorecard_table,
    underwriting,
    underwriting_rules,
)
from app.refusal import Refusal
from app.transcription import Citation

AS_OF = datetime(2026, 8, 7, 12, 0)

CITATION = Citation(
    document="SYNTHETIC — test fixture, not a lender document",
    publisher="tests/test_finance_layer.py",
    section="fixture",
    snippet="values invented for arithmetic testing only",
    transcribed_by="test suite",
    transcribed_on=date(2026, 8, 7),
)


class FakeFeature:
    """Stands in for a FeatureResult: abstained iff no value."""

    def __init__(self, value=None, reasons=()):
        self.value = value
        self.abstained = value is None
        self.reasons = list(reasons)


# ------------------------------------------------------------- shipped state
def test_every_finance_source_ships_empty():
    """The single most important assertion in this file.

    If any of these is populated, either someone transcribed a real lender document
    (confirm every row carries a Citation, then update this test deliberately) or
    someone invented numbers — which would pass every other test here.
    """
    assert scorecard_table.TRANSCRIBED is None
    assert underwriting_rules.TRANSCRIBED is None
    assert monitoring_covenants.TRANSCRIBED is None
    assert collateral_valuation.TRANSCRIBED == ()
    assert insurance_products.TRANSCRIBED == ()


def test_every_finance_entry_point_refuses_on_todays_data():
    assert isinstance(credit_scoring.score(features={}, as_of=AS_OF), Refusal)
    assert isinstance(underwriting.assess(as_of=AS_OF), Refusal)
    assert isinstance(monitoring.evaluate(features={}, as_of=AS_OF), Refusal)
    assert isinstance(collateral.value_assets([], currency="USD"), Refusal)
    assert isinstance(
        insurance.assess_coverage(crop="strawberry", peril="frost"), Refusal
    )


# --------------------------------------------------------------- credit score
def _scorecard(*factors, minimum=0.0, maximum=100.0):
    return scorecard_table.Scorecard(
        lender="SYNTHETIC Lender", name="Test card", version="1",
        minimum_score=minimum, maximum_score=maximum,
        factors=tuple(factors), citation=CITATION,
    )


def _factor(feature_name, weight=1.0):
    return scorecard_table.ScorecardFactor(
        feature_name=feature_name, weight=weight, citation=CITATION,
        bands=(
            scorecard_table.ScorecardBand(
                lower_inclusive=None, upper_exclusive=10.0, points=10.0),
            scorecard_table.ScorecardBand(
                lower_inclusive=10.0, upper_exclusive=None, points=50.0),
        ),
    )


def test_a_transcribed_scorecard_executes(monkeypatch):
    monkeypatch.setattr(scorecard_table, "TRANSCRIBED", _scorecard(_factor("f1")))
    result = credit_scoring.score(features={"f1": FakeFeature(25.0)}, as_of=AS_OF)

    assert not isinstance(result, Refusal)
    assert result.total == 50.0
    assert result.factors[0].feature_name == "f1"


def test_one_abstaining_input_refuses_the_whole_score(monkeypatch):
    """The load-bearing rule.

    A scorecard is a weighted sum, so a missing factor contributes zero points and the
    total comes out LOWER — a partial score reads as a worse borrower, not as an
    incomplete assessment. Someone would be declined because a soil test was never
    uploaded.
    """
    monkeypatch.setattr(
        scorecard_table, "TRANSCRIBED", _scorecard(_factor("f1"), _factor("f2"))
    )
    result = credit_scoring.score(
        features={"f1": FakeFeature(25.0), "f2": FakeFeature(None, ["no_soil_test"])},
        as_of=AS_OF,
    )
    assert isinstance(result, Refusal)
    assert result.code == credit_scoring.INPUT_ABSTAINED
    assert result.context["feature_name"] == "f2"
    assert "no_soil_test" in result.context["reasons"]


def test_a_missing_input_refuses_rather_than_scoring_zero(monkeypatch):
    monkeypatch.setattr(scorecard_table, "TRANSCRIBED", _scorecard(_factor("f1")))
    result = credit_scoring.score(features={}, as_of=AS_OF)
    assert isinstance(result, Refusal)
    assert result.code == credit_scoring.INPUT_MISSING


def test_the_same_inputs_reproduce_the_same_digest(monkeypatch):
    """A score must be reproducible for its as_of — 'what did you know when you
    declined me' is a question with legal weight."""
    monkeypatch.setattr(scorecard_table, "TRANSCRIBED", _scorecard(_factor("f1")))
    first = credit_scoring.score(features={"f1": FakeFeature(25.0)}, as_of=AS_OF)
    second = credit_scoring.score(features={"f1": FakeFeature(25.0)}, as_of=AS_OF)
    assert first.inputs_digest == second.inputs_digest

    changed = credit_scoring.score(features={"f1": FakeFeature(26.0)}, as_of=AS_OF)
    assert changed.inputs_digest != first.inputs_digest


def test_a_scorecard_with_overlapping_bands_is_refused_at_import_time():
    with pytest.raises(ValueError, match="overlap"):
        scorecard_table.ScorecardFactor(
            feature_name="f1", weight=1.0, citation=CITATION,
            bands=(
                scorecard_table.ScorecardBand(
                    lower_inclusive=0.0, upper_exclusive=20.0, points=1.0),
                scorecard_table.ScorecardBand(
                    lower_inclusive=10.0, upper_exclusive=30.0, points=2.0),
            ),
        )


# --------------------------------------------------------------- underwriting
def _policy(*rules):
    return underwriting_rules.UnderwritingPolicy(
        lender="SYNTHETIC Lender", version="1", effective_from="2026-01-01",
        rules=tuple(rules), citation=CITATION,
    )


def _rule(rule_id, kind, **kw):
    return underwriting_rules.UnderwritingRule(
        rule_id=rule_id, description=f"{kind} rule", kind=kind, citation=CITATION, **kw
    )


def test_conditions_met_when_every_rule_passes(monkeypatch):
    monkeypatch.setattr(underwriting_rules, "TRANSCRIBED",
                        _policy(_rule("R1", "minimum_score", threshold=50.0)))
    result = underwriting.assess(as_of=AS_OF, score_total=70.0)
    assert result.outcome == underwriting.CONDITIONS_MET


def test_a_failed_rule_yields_conditions_not_met(monkeypatch):
    monkeypatch.setattr(underwriting_rules, "TRANSCRIBED",
                        _policy(_rule("R1", "minimum_score", threshold=50.0)))
    result = underwriting.assess(as_of=AS_OF, score_total=30.0)
    assert result.outcome == underwriting.CONDITIONS_NOT_MET
    assert [r.rule_id for r in result.failed] == ["R1"]


def test_an_unevaluated_rule_is_never_folded_into_a_pass(monkeypatch):
    """A policy where a rule could not be checked must not read as a clean result."""
    monkeypatch.setattr(underwriting_rules, "TRANSCRIBED", _policy(
        _rule("R1", "minimum_score", threshold=50.0),
        _rule("R2", "maximum_exposure", threshold=100000.0),
    ))
    result = underwriting.assess(as_of=AS_OF, score_total=70.0, exposure_amount=None)

    assert result.outcome == underwriting.REFERRED_TO_HUMAN
    assert [r.rule_id for r in result.not_evaluated] == ["R2"]


def test_an_exclusion_with_an_unavailable_feature_does_not_pass(monkeypatch):
    """Defaulting to 'not excluded' silently passes the check the lender wrote."""
    monkeypatch.setattr(underwriting_rules, "TRANSCRIBED", _policy(
        _rule("R1", "exclusion", threshold=5.0, feature_name="risk_metric"),
    ))
    result = underwriting.assess(as_of=AS_OF, features={"risk_metric": FakeFeature(None)})
    assert result.outcome == underwriting.REFERRED_TO_HUMAN
    assert result.rules[0].passed is None


def test_a_threshold_rule_without_a_threshold_is_refused_at_import_time():
    with pytest.raises(ValueError, match="without a threshold cannot be evaluated"):
        _rule("R1", "minimum_score")


# ----------------------------------------------------------------- collateral
def _advance(collateral_type, pct):
    return collateral_valuation.AdvanceRate(
        collateral_type=collateral_type, advance_rate_pct=pct,
        valuation_basis="SYNTHETIC basis", citation=CITATION,
    )


def test_advance_rate_is_applied(monkeypatch):
    monkeypatch.setattr(collateral_valuation, "TRANSCRIBED", (_advance("equipment", 60.0),))
    position = collateral.value_assets(
        [collateral.Asset(collateral_type="equipment", assessed_value=100000.0,
                          currency="USD")],
        currency="USD",
    )
    assert position.total_advanced_value == pytest.approx(60000.0)


def test_an_unrated_asset_type_refuses_rather_than_defaulting(monkeypatch):
    """No safe default: 100% understates exposure, 0% denies held collateral."""
    monkeypatch.setattr(collateral_valuation, "TRANSCRIBED", (_advance("equipment", 60.0),))
    result = collateral.value_assets(
        [collateral.Asset(collateral_type="standing_crop", assessed_value=50000.0,
                          currency="USD")],
        currency="USD",
    )
    assert isinstance(result, Refusal)
    assert "no safe default" in result.detail


def test_an_unvalued_asset_refuses_and_names_the_basis_required(monkeypatch):
    monkeypatch.setattr(collateral_valuation, "TRANSCRIBED", (_advance("equipment", 60.0),))
    result = collateral.value_assets(
        [collateral.Asset(collateral_type="equipment", assessed_value=None,
                          currency="USD")],
        currency="USD",
    )
    assert result.code == collateral.ASSET_NOT_VALUED
    assert result.context["required_basis"] == "SYNTHETIC basis"


def test_loan_to_value_refuses_without_an_exposure_figure(monkeypatch):
    monkeypatch.setattr(collateral_valuation, "TRANSCRIBED", (_advance("equipment", 60.0),))
    position = collateral.value_assets(
        [collateral.Asset(collateral_type="equipment", assessed_value=100000.0,
                          currency="USD")],
        currency="USD",
    )
    assert isinstance(position.loan_to_value(None), Refusal)
    assert position.loan_to_value(30000.0) == pytest.approx(0.5)


# ------------------------------------------------------------------ insurance
def test_missing_evidence_is_reported_not_assumed_present(monkeypatch):
    monkeypatch.setattr(insurance_products, "TRANSCRIBED", (
        insurance_products.CoverageProduct(
            product_code="P1", insurer="SYNTHETIC Insurer", perils=("frost",),
            eligible_crops=("strawberry",), coverage_basis="actual production history",
            required_evidence=("spray_log", "harvest_record"), citation=CITATION,
        ),
    ))
    result = insurance.assess_coverage(
        crop="strawberry", peril="frost", available_evidence=("spray_log",)
    )
    match = result.matches[0]
    assert match.terms_match is True
    assert match.evidence_complete is False
    assert match.missing_evidence == ("harvest_record",)


# ----------------------------------------------------------------- monitoring
def _schedule(*covenants):
    return monitoring_covenants.CovenantSchedule(
        lender="SYNTHETIC Lender", facility_reference="F1", version="1",
        covenants=tuple(covenants), citation=CITATION,
    )


def _covenant(cid, feature_name, comparator, threshold):
    return monitoring_covenants.Covenant(
        covenant_id=cid, description=f"{cid} covenant", feature_name=feature_name,
        comparator=comparator, threshold=threshold, breach_severity="reportable",
        citation=CITATION,
    )


def test_a_covenant_within_threshold_is_good_standing(monkeypatch):
    monkeypatch.setattr(monitoring_covenants, "TRANSCRIBED",
                        _schedule(_covenant("C1", "recency", "at_most", 14.0)))
    snapshot = monitoring.evaluate(features={"recency": FakeFeature(7.0)}, as_of=AS_OF)
    assert snapshot.standing == monitoring.STANDING_GOOD


def test_an_unevaluated_covenant_is_never_good_standing(monkeypatch):
    """'Nothing checked' must not render as 'compliant'."""
    monkeypatch.setattr(monitoring_covenants, "TRANSCRIBED",
                        _schedule(_covenant("C1", "recency", "at_most", 14.0)))
    snapshot = monitoring.evaluate(features={"recency": FakeFeature(None)}, as_of=AS_OF)

    assert snapshot.standing == monitoring.STANDING_UNKNOWN
    assert snapshot.covenants[0].status == monitoring.NOT_EVALUATED


def test_a_breach_outranks_an_unknown(monkeypatch):
    monkeypatch.setattr(monitoring_covenants, "TRANSCRIBED", _schedule(
        _covenant("C1", "recency", "at_most", 14.0),
        _covenant("C2", "other", "at_least", 1.0),
    ))
    snapshot = monitoring.evaluate(
        features={"recency": FakeFeature(30.0), "other": FakeFeature(None)}, as_of=AS_OF
    )
    assert snapshot.standing == monitoring.STANDING_BREACH


# ------------------------------------------------------- the claim guard
# Same technique as backtest.FORBIDDEN_KEY_SUBSTRINGS: a payload-walking test, so a key
# implying an unearned claim cannot be added to a finance payload without failing CI.
FORBIDDEN_KEY_SUBSTRINGS = (
    "approved", "approval_granted", "funded", "disbursed", "repaid",
    "guaranteed", "prequalified", "pre_qualified", "premium", "apr",
    "interest_rate", "credit_limit_granted",
)


def _walk_keys(payload, seen=None):
    """Every key that could carry a VALUE, skipping `not_calculated` subtrees.

    `not_calculated` is the disclosure block: its keys name the things this layer
    deliberately does not compute, so `{"not_calculated": {"premium": "...why not..."}}`
    is the guard working, not failing. Excluding the subtree is only safe because
    `test_not_calculated_entries_are_prose_not_values` below proves every value under it
    is a string — so nobody can smuggle a real number in by nesting it there.
    """
    seen = seen if seen is not None else set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            seen.add(str(key))
            if key == "not_calculated":
                continue
            _walk_keys(value, seen)
    elif isinstance(payload, (list, tuple)):
        for item in payload:
            _walk_keys(item, seen)
    return seen


def _not_calculated_blocks(payload, found=None):
    found = found if found is not None else []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key == "not_calculated":
                found.append(value)
            else:
                _not_calculated_blocks(value, found)
    elif isinstance(payload, (list, tuple)):
        for item in payload:
            _not_calculated_blocks(item, found)
    return found


def _all_finance_payloads(monkeypatch):
    """Every finance payload, with SYNTHETIC sources installed so they all compute."""
    monkeypatch.setattr(scorecard_table, "TRANSCRIBED", _scorecard(_factor("f1")))
    monkeypatch.setattr(underwriting_rules, "TRANSCRIBED",
                        _policy(_rule("R1", "minimum_score", threshold=50.0)))
    monkeypatch.setattr(monitoring_covenants, "TRANSCRIBED",
                        _schedule(_covenant("C1", "recency", "at_most", 14.0)))
    monkeypatch.setattr(collateral_valuation, "TRANSCRIBED", (_advance("equipment", 60.0),))
    monkeypatch.setattr(insurance_products, "TRANSCRIBED", (
        insurance_products.CoverageProduct(
            product_code="P1", insurer="SYNTHETIC Insurer", perils=("frost",),
            eligible_crops=("strawberry",), coverage_basis="APH",
            required_evidence=("spray_log",), citation=CITATION,
        ),
    ))

    return [
        credit_scoring.score(features={"f1": FakeFeature(25.0)}, as_of=AS_OF).as_payload(),
        underwriting.assess(as_of=AS_OF, score_total=70.0).as_payload(),
        monitoring.evaluate(features={"recency": FakeFeature(7.0)}, as_of=AS_OF).as_payload(),
        collateral.value_assets(
            [collateral.Asset(collateral_type="equipment", assessed_value=1000.0,
                              currency="USD")],
            currency="USD",
        ).as_payload(),
        insurance.assess_coverage(
            crop="strawberry", peril="frost", available_evidence=("spray_log",)
        ).as_payload(),
    ]


def test_no_finance_payload_key_claims_something_unearned(monkeypatch):
    for payload in _all_finance_payloads(monkeypatch):
        for key in _walk_keys(payload):
            for forbidden in FORBIDDEN_KEY_SUBSTRINGS:
                assert forbidden not in key.lower(), (
                    f"payload key {key!r} contains {forbidden!r}. This layer reports "
                    "what a transcribed document says about a farm; it does not approve, "
                    "fund, price or guarantee anything."
                )


def test_not_calculated_entries_are_prose_not_values(monkeypatch):
    """Closes the loophole the `not_calculated` exemption would otherwise open.

    The key walker skips this subtree so a disclosure named "premium" does not trip the
    guard. That is only safe if nothing under it can be a number — otherwise the way to
    ship a fabricated premium would be to nest it one level deeper.
    """
    blocks = [b for p in _all_finance_payloads(monkeypatch) for b in _not_calculated_blocks(p)]
    assert blocks, "no not_calculated blocks found — the exemption is untested"

    for block in blocks:
        assert isinstance(block, dict)
        for key, value in block.items():
            assert isinstance(value, str), (
                f"not_calculated[{key!r}] is {type(value).__name__}, not prose. Every "
                "entry here must be a SENTENCE explaining why the thing is not "
                "computed — a number under this key would be a fabricated claim hidden "
                "behind a disclosure."
            )
            assert len(value) > 20, f"not_calculated[{key!r}] is too terse to explain anything"


def test_the_claim_guard_would_actually_catch_a_forbidden_key():
    """Guards the guard: a walker that missed nested keys would pass vacuously."""
    keys = _walk_keys({"a": {"b": [{"approved": True}]}})
    assert "approved" in keys


def test_underwriting_has_no_approved_outcome():
    """The vocabulary itself, not just the payload keys."""
    outcomes = {
        underwriting.CONDITIONS_MET,
        underwriting.CONDITIONS_NOT_MET,
        underwriting.REFERRED_TO_HUMAN,
    }
    assert not any("approv" in o for o in outcomes)
    assert set(underwriting_rules.Outcome.__args__) == outcomes
