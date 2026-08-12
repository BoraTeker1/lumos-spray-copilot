"""Underwriting evaluation (pure, framework-free).

Evaluates a lender's transcribed credit policy against a score and a farm's evidence,
and reports **which rules passed, which failed, and which could not be evaluated** — or
refuses and says why. With `underwriting_rules.TRANSCRIBED` empty it produces nothing.

**The outcome vocabulary is the most deliberate thing in this file.** There is no
`approved`. The strongest affirmative outcome is `conditions_met`, and the difference is
not cosmetic:

* "Approved" is a commitment to lend. Only a lender can make it, it binds them, and a
  system that emitted it would be originating credit.
* "The conditions in the policy you gave us were met, and here is which rule was tested
  against which value at which moment" is a statement about a document. It is checkable,
  it is useful, and it is not a commitment.

`promotable_to_authoritative` in `label_data.py` established this shape here: return the
REASON something cannot back a decision, not a boolean. The same instinct applies with
more force to credit.

**A rule that cannot be evaluated is never silently passed.** This is the failure mode
that matters most: a policy with five rules where two cannot be checked must not report
"3 passed" and read as a clean result. `not_evaluated` is reported as its own category,
and `conditions_met` is False whenever anything is in it — the same construction as
`decision_engine`'s per-decision `not_evaluated` list, which exists so a check that did
not run can never look like a check that passed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app import underwriting_rules
from app.refusal import NO_SOURCE_TRANSCRIBED, Refusal

MODEL_VERSION = "policy_evaluation_v1"

NO_POLICY_SUPPLIED = NO_SOURCE_TRANSCRIBED

# Outcomes. Deliberately no "approved" — see the module docstring.
CONDITIONS_MET = "conditions_met"
CONDITIONS_NOT_MET = "conditions_not_met"
REFERRED_TO_HUMAN = "referred_to_human"

# Why a rule could not be evaluated.
NO_SCORE_AVAILABLE = "no_score_available"
EVIDENCE_NOT_PRESENT = "evidence_not_present"
NO_EXPOSURE_FIGURE = "no_exposure_figure"
FEATURE_UNAVAILABLE = "feature_unavailable"


@dataclass(frozen=True)
class RuleOutcome:
    """One rule's result, or the reason it could not be tested."""

    rule_id: str
    description: str
    kind: str
    passed: bool | None = None
    observed_value: float | None = None
    threshold: float | None = None
    not_evaluated_reason: str | None = None

    @property
    def evaluated(self) -> bool:
        return self.passed is not None

    def as_payload(self) -> dict:
        payload = {
            "rule_id": self.rule_id,
            "description": self.description,
            "kind": self.kind,
            "evaluated": self.evaluated,
        }
        if self.passed is not None:
            payload["passed"] = self.passed
        if self.observed_value is not None:
            payload["observed_value"] = self.observed_value
        if self.threshold is not None:
            payload["threshold"] = self.threshold
        if self.not_evaluated_reason:
            payload["not_evaluated_reason"] = self.not_evaluated_reason
        return payload


@dataclass(frozen=True)
class UnderwritingAssessment:
    """Which policy conditions were met. Never an approval."""

    lender: str
    policy_version: str
    outcome: str
    as_of: datetime
    model_version: str = MODEL_VERSION
    rules: tuple[RuleOutcome, ...] = field(default_factory=tuple)

    @property
    def failed(self) -> tuple[RuleOutcome, ...]:
        return tuple(r for r in self.rules if r.passed is False)

    @property
    def not_evaluated(self) -> tuple[RuleOutcome, ...]:
        return tuple(r for r in self.rules if not r.evaluated)

    def as_payload(self) -> dict:
        return {
            "model_version": self.model_version,
            "lender": self.lender,
            "policy_version": self.policy_version,
            "outcome": self.outcome,
            "as_of": self.as_of.isoformat(),
            "rules": [r.as_payload() for r in self.rules],
            "failed_rule_ids": [r.rule_id for r in self.failed],
            # Its own category, never folded into a pass count. A policy where two of
            # five rules could not be checked must not read as "3 passed".
            "not_evaluated_rule_ids": [r.rule_id for r in self.not_evaluated],
            "not_calculated": {
                "approval": (
                    "This is not an approval and not an offer of credit. It reports "
                    "whether the conditions in the lender's own transcribed policy were "
                    "met, against data as it stood at `as_of`. Only the lender approves."
                ),
                "pricing": (
                    "No rate, margin or fee is derived. Pricing credit is not a "
                    "decision this layer makes."
                ),
            },
        }


def _evaluate_rule(rule, *, score_total, exposure_amount, evidence_keys, features):
    """One rule against the available inputs. Never guesses a missing input."""
    if rule.kind == "minimum_score":
        if score_total is None:
            return RuleOutcome(
                rule_id=rule.rule_id, description=rule.description, kind=rule.kind,
                not_evaluated_reason=NO_SCORE_AVAILABLE, threshold=rule.threshold,
            )
        return RuleOutcome(
            rule_id=rule.rule_id, description=rule.description, kind=rule.kind,
            passed=score_total >= rule.threshold,
            observed_value=score_total, threshold=rule.threshold,
        )

    if rule.kind == "maximum_exposure":
        if exposure_amount is None:
            return RuleOutcome(
                rule_id=rule.rule_id, description=rule.description, kind=rule.kind,
                not_evaluated_reason=NO_EXPOSURE_FIGURE, threshold=rule.threshold,
            )
        return RuleOutcome(
            rule_id=rule.rule_id, description=rule.description, kind=rule.kind,
            passed=exposure_amount <= rule.threshold,
            observed_value=exposure_amount, threshold=rule.threshold,
        )

    if rule.kind == "required_evidence":
        present = rule.evidence_key in set(evidence_keys or ())
        if present:
            return RuleOutcome(
                rule_id=rule.rule_id, description=rule.description, kind=rule.kind,
                passed=True,
            )
        # Absent evidence is NOT EVALUATED, not failed. Lumos can see what the farm
        # has recorded; it cannot see the grower's filing cabinet, and a document
        # nobody uploaded is a question for a human rather than grounds for Lumos to
        # decline. Routing it to `referred_to_human` keeps the asymmetry this layer
        # is built on: there is no `approved` outcome, and there should be no
        # automatic rejection on paperwork either.
        return RuleOutcome(
            rule_id=rule.rule_id, description=rule.description, kind=rule.kind,
            not_evaluated_reason=EVIDENCE_NOT_PRESENT,
        )

    if rule.kind == "exclusion":
        # An exclusion tests a feature: if the named feature is unavailable, the
        # exclusion cannot be cleared. It must NOT default to "not excluded" — that
        # would silently pass the check the lender wrote to catch this exact case.
        if not rule.feature_name:
            return RuleOutcome(
                rule_id=rule.rule_id, description=rule.description, kind=rule.kind,
                not_evaluated_reason=FEATURE_UNAVAILABLE,
            )
        result = (features or {}).get(rule.feature_name)
        if result is None or getattr(result, "abstained", False) or getattr(
            result, "value", None
        ) is None:
            return RuleOutcome(
                rule_id=rule.rule_id, description=rule.description, kind=rule.kind,
                not_evaluated_reason=FEATURE_UNAVAILABLE,
            )
        value = float(result.value)
        if rule.threshold is None:
            return RuleOutcome(
                rule_id=rule.rule_id, description=rule.description, kind=rule.kind,
                not_evaluated_reason=FEATURE_UNAVAILABLE, observed_value=value,
            )
        return RuleOutcome(
            rule_id=rule.rule_id, description=rule.description, kind=rule.kind,
            passed=value <= rule.threshold, observed_value=value,
            threshold=rule.threshold,
        )

    return RuleOutcome(
        rule_id=rule.rule_id, description=rule.description, kind=rule.kind,
        not_evaluated_reason=FEATURE_UNAVAILABLE,
    )


def assess(*, as_of: datetime, score_total: float | None = None,
           exposure_amount: float | None = None, evidence_keys=(), features=None,
           policy=None):
    """Evaluate a lender's policy. Returns UnderwritingAssessment | Refusal.

    `policy` lets a caller supply a policy recorded against a specific lender (see
    `models.LenderPolicy`) instead of the module-level transcription. Both routes
    carry the same guarantee and the same reason: the rules come from the lender in
    writing. Lumos evaluates a policy, it never authors one.
    """
    policy = policy if policy is not None else underwriting_rules.TRANSCRIBED
    if policy is None:
        return Refusal(
            NO_POLICY_SUPPLIED,
            "No underwriting policy has been transcribed, so no assessment can be "
            "produced. The policy comes from the lending partner in writing — Lumos "
            "evaluates one, it does not author one. See app/underwriting_rules.py.",
            {"model_version": MODEL_VERSION},
        )

    outcomes = tuple(
        _evaluate_rule(
            rule, score_total=score_total, exposure_amount=exposure_amount,
            evidence_keys=evidence_keys, features=features,
        )
        for rule in policy.rules
    )

    any_failed = any(r.passed is False for r in outcomes)
    any_unevaluated = any(not r.evaluated for r in outcomes)

    if any_failed:
        outcome = CONDITIONS_NOT_MET
    elif any_unevaluated:
        # Not "met with caveats". A rule that could not run is a question for a human,
        # and folding it into a pass is exactly how an unchecked condition ships.
        outcome = REFERRED_TO_HUMAN
    else:
        outcome = CONDITIONS_MET

    return UnderwritingAssessment(
        lender=policy.lender, policy_version=policy.version,
        outcome=outcome, as_of=as_of, rules=outcomes,
    )
