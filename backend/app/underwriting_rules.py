"""Underwriting policy — EMPTY until a lender's written credit policy is transcribed.

Underwriting is the act of deciding whether to lend. `underwriting.assess()` reads this
policy; while it is `None` it returns a `Refusal` naming `NO_POLICY_SUPPLIED`, and the
system produces no underwriting decision at all — not a provisional one, not an
indicative one, none.

The distinction that matters here, and the reason this module exists rather than a
hard-coded rule set: Lumos can *evaluate* a policy someone else wrote, against
point-in-time farm data, with a full audit trail of which rule fired on which value at
which moment. That is genuinely useful and genuinely defensible. What it must not do is
*author* the policy, because authoring it means deciding who gets credit, and nothing in
this repository — 4 farms, zero lending partners — supports that.

**What fills it:** the lender's written credit policy, rule by rule, each with the
section it came from.

Note what is deliberately absent from `RuleKind`: there is no `price` or `rate` rule.
Setting a price for credit is not a decision this layer makes, and adding a kind for it
would be the first step toward computing a repayment schedule — i.e. money math, which
ENGINEERING_GUIDELINES.md §4 still forbids and this expansion did not lift.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.transcription import Citation

PRIMARY_SOURCE = (
    "The lending partner's written credit policy: eligibility rules, minimum score, "
    "exposure limits, required evidence, and exclusions, each identified by its section "
    "in the policy document. Never inferred from a sample of past decisions."
)

RuleKind = Literal[
    "minimum_score",      # the score floor below which the answer is no
    "maximum_exposure",   # a currency ceiling on total exposure to one borrower
    "required_evidence",  # a document or record that must be present
    "exclusion",          # a condition that disqualifies outright
]

# A decision this layer may reach. There is deliberately no "approved" — see
# `underwriting.py`. The strongest affirmative outcome is that the policy's conditions
# were met, which is a statement about the policy, not a commitment to lend.
Outcome = Literal["conditions_met", "conditions_not_met", "referred_to_human"]


@dataclass(frozen=True, kw_only=True)
class UnderwritingRule:
    """One rule from a written policy, with the section it came from."""

    rule_id: str
    description: str
    kind: RuleKind
    citation: Citation
    threshold: float | None = None
    evidence_key: str | None = None
    feature_name: str | None = None

    def __post_init__(self) -> None:
        if not self.rule_id.strip():
            raise ValueError("UnderwritingRule.rule_id is blank")
        if self.kind in ("minimum_score", "maximum_exposure") and self.threshold is None:
            raise ValueError(
                f"{self.rule_id}: a {self.kind} rule without a threshold cannot be "
                "evaluated. Transcribe the number or omit the rule — a rule that always "
                "passes is worse than an absent one, because it reads as a check."
            )
        if self.kind == "required_evidence" and not (self.evidence_key or "").strip():
            raise ValueError(
                f"{self.rule_id}: a required_evidence rule must name the evidence"
            )


@dataclass(frozen=True, kw_only=True)
class UnderwritingPolicy:
    """A lender's whole policy, transcribed as one artifact."""

    lender: str
    version: str
    effective_from: str
    rules: tuple[UnderwritingRule, ...]
    citation: Citation

    def __post_init__(self) -> None:
        if not self.rules:
            raise ValueError("an UnderwritingPolicy with no rules decides nothing")
        ids = [r.rule_id for r in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate rule_id in policy")


# EMPTY. See the module docstring.
TRANSCRIBED: UnderwritingPolicy | None = None
