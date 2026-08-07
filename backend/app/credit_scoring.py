"""Credit scoring (pure, framework-free).

Executes a lender's transcribed scorecard against a farm's computed features, or refuses
and says why. **It does not design a scorecard**, and with `scorecard_table.TRANSCRIBED`
empty it cannot produce a score at all.

Three properties, in descending order of how badly getting them wrong would hurt:

**1. All-or-nothing on inputs.** A feature that abstains abstains the whole score. This
is the same rule as `pest.active_ingredient_kg_per_ha` and for the same reason, but the
consequence here is sharper: a scorecard is a weighted sum, so a missing factor
contributes zero points and the total comes out *lower*. A partial score does not read
as incomplete — it reads as a worse borrower. Someone would be declined credit because a
soil test was never uploaded. So a single abstention refuses the score.

**2. Inputs are `FeatureResult`s, not raw rows.** Scoring reads the same abstaining
values the readiness cards read, so "we cannot see this" propagates by construction
rather than by each caller remembering to check for None.

**3. The score is not a decision.** `Score` carries no `approved`, `tier`, `decline` or
`recommendation` field. Whether a score clears a bar is `underwriting.assess()`'s job,
against a transcribed policy — kept separate because the scorecard and the credit policy
are different documents from the same lender, and conflating them means a policy change
looks like a scoring change.

The point-in-time discipline matters more here than anywhere else in the codebase: a
score must be reproducible for the `as_of` it was computed at, because "what did you
know when you declined me" is a question with legal weight. `FeatureResult` already
carries `as_of`, and `Score` records the digest of the inputs it used.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime

from app import scorecard_table
from app.refusal import NO_DATA_FOR_FARM, NO_SOURCE_TRANSCRIBED, OUTSIDE_SOURCE_SCOPE, Refusal

MODEL_VERSION = "scorecard_execution_v1"

# Refusal codes specific to this module.
NO_SCORECARD_SUPPLIED = NO_SOURCE_TRANSCRIBED
INPUT_ABSTAINED = "scorecard_input_abstained"
INPUT_MISSING = "scorecard_input_missing"


@dataclass(frozen=True)
class FactorScore:
    """One factor's contribution, with the band it landed in."""

    feature_name: str
    value: float
    points: float
    weight: float
    weighted_points: float

    def as_payload(self) -> dict:
        return {
            "feature_name": self.feature_name,
            "value": self.value,
            "points": self.points,
            "weight": self.weight,
            "weighted_points": round(self.weighted_points, 4),
        }


@dataclass(frozen=True)
class Score:
    """An executed scorecard. Carries no decision — see the module docstring."""

    lender: str
    scorecard_name: str
    scorecard_version: str
    total: float
    minimum_score: float
    maximum_score: float
    as_of: datetime
    inputs_digest: str
    model_version: str = MODEL_VERSION
    factors: tuple[FactorScore, ...] = field(default_factory=tuple)

    def as_payload(self) -> dict:
        return {
            "model_version": self.model_version,
            "lender": self.lender,
            "scorecard_name": self.scorecard_name,
            "scorecard_version": self.scorecard_version,
            "total": round(self.total, 4),
            "minimum_score": self.minimum_score,
            "maximum_score": self.maximum_score,
            "as_of": self.as_of.isoformat(),
            "inputs_digest": self.inputs_digest,
            "factors": [f.as_payload() for f in self.factors],
            "not_calculated": {
                "decision": (
                    "A score is not a lending decision. Whether it clears a bar is "
                    "evaluated against the lender's transcribed credit policy, "
                    "separately — see app/underwriting.py."
                ),
            },
        }


def _digest(pairs) -> str:
    """Content hash over the exact inputs used, for reproducibility at a fixed as_of.

    Canonical JSON with sorted keys, matching `risk_snapshot`'s approach: the same
    inputs must produce the same digest forever, so a digest that moves is evidence an
    input changed underneath a decision someone already acted on.
    """
    canonical = json.dumps(dict(sorted(pairs)), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def score(*, features, as_of: datetime):
    """Execute the transcribed scorecard. Returns Score | Refusal.

    `features` maps feature name -> FeatureResult (anything with `.abstained` and
    `.value`).
    """
    card = scorecard_table.TRANSCRIBED
    if card is None:
        return Refusal(
            NO_SCORECARD_SUPPLIED,
            "No credit scorecard has been transcribed, so no score can be produced. A "
            "scorecard comes from the lending partner in writing — Lumos executes one, "
            "it does not design one. See app/scorecard_table.py.",
            {"model_version": MODEL_VERSION},
        )

    features = dict(features or {})
    scored: list[FactorScore] = []
    digest_pairs: list[tuple[str, object]] = []

    for factor in card.factors:
        result = features.get(factor.feature_name)
        if result is None:
            return Refusal(
                INPUT_MISSING,
                f"The scorecard requires {factor.feature_name!r}, which was not "
                "supplied. Scoring without it would silently contribute zero points "
                "and understate the total.",
                {"feature_name": factor.feature_name},
            )
        if getattr(result, "abstained", False) or getattr(result, "value", None) is None:
            reasons = list(getattr(result, "reasons", ()) or ())
            return Refusal(
                INPUT_ABSTAINED,
                f"{factor.feature_name!r} could not be computed for this farm, so the "
                "whole score is withheld. A scorecard is a weighted sum: a missing "
                "factor contributes zero and the total reads as a worse borrower rather "
                "than an incomplete assessment.",
                {"feature_name": factor.feature_name, "reasons": reasons},
            )

        value = float(result.value)
        band = next((b for b in factor.bands if b.contains(value)), None)
        if band is None:
            return Refusal(
                OUTSIDE_SOURCE_SCOPE,
                f"{value} for {factor.feature_name!r} falls outside every band the "
                "transcribed scorecard defines. Reading past the end of the card is "
                "extrapolation, not scoring.",
                {"feature_name": factor.feature_name, "value": value},
            )

        scored.append(FactorScore(
            feature_name=factor.feature_name, value=value, points=band.points,
            weight=factor.weight, weighted_points=band.points * factor.weight,
        ))
        digest_pairs.append((factor.feature_name, value))

    if not scored:
        return Refusal(
            NO_DATA_FOR_FARM,
            "The transcribed scorecard produced no scored factors.",
            {},
        )

    return Score(
        lender=card.lender,
        scorecard_name=card.name,
        scorecard_version=card.version,
        total=sum(f.weighted_points for f in scored),
        minimum_score=card.minimum_score,
        maximum_score=card.maximum_score,
        as_of=as_of,
        inputs_digest=_digest(digest_pairs),
        factors=tuple(scored),
    )
