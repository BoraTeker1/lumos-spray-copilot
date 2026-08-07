"""Credit scorecard — EMPTY until a lender's published scorecard is transcribed.

This is the single most tempting file in the repository to fill in from intuition, and
the most dangerous. A scorecard is just weights over farm features; anyone could write
one in ten minutes, it would produce plausible three-digit numbers, and every test
anyone would think to write would pass. It would also be a fabricated assessment of a
real person's creditworthiness, which is a claim with legal weight in most jurisdictions
and is not a thing this codebase gets to invent.

So the structure is real and the numbers are absent. `credit_scoring.score()` reads this
table; while it is `None` it returns `Refusal(NO_SCORECARD_SUPPLIED)` and no credit
assessment can be produced at all. That is the correct behaviour, not a gap to route
around.

**What fills it:** a lending partner's own published or contractually supplied scorecard —
the factors they already use, the weights they already apply, and the bands they already
band on. Lumos does not design the scorecard; it executes one, auditably, against
point-in-time farm data. That division is the whole product thesis for this layer.

`feature_name` on each factor must match a registered feature in `app/features/`, so a
scorecard cannot reference an input this system has no honest way to compute. A feature
that abstains abstains the whole score — see `credit_scoring.py` for why partial scoring
is worse than none.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.transcription import Citation

PRIMARY_SOURCE = (
    "The lending partner's published or contractually supplied credit scorecard: the "
    "factor list, per-factor weights, score bands, and the score range. Must arrive from "
    "the lender in writing — never reconstructed from example decisions, and never "
    "designed by Lumos."
)


@dataclass(frozen=True, kw_only=True)
class ScorecardBand:
    """One band of a factor: a half-open interval and the points it earns.

    Bounds are half-open [lower, upper) so adjacent bands cannot both claim a boundary
    value — an overlap here is a silent scoring difference, not an error anyone would
    notice from the output.
    """

    lower_inclusive: float | None
    upper_exclusive: float | None
    points: float

    def __post_init__(self) -> None:
        if (
            self.lower_inclusive is not None
            and self.upper_exclusive is not None
            and self.lower_inclusive >= self.upper_exclusive
        ):
            raise ValueError(
                f"band [{self.lower_inclusive}, {self.upper_exclusive}) is empty or "
                "inverted"
            )

    def contains(self, value: float) -> bool:
        if self.lower_inclusive is not None and value < self.lower_inclusive:
            return False
        if self.upper_exclusive is not None and value >= self.upper_exclusive:
            return False
        return True


@dataclass(frozen=True, kw_only=True)
class ScorecardFactor:
    """One scored input, tied to a feature this system can actually compute."""

    feature_name: str
    weight: float
    bands: tuple[ScorecardBand, ...]
    citation: Citation

    def __post_init__(self) -> None:
        if not self.feature_name.strip():
            raise ValueError("ScorecardFactor.feature_name is blank")
        if not self.bands:
            raise ValueError(
                f"{self.feature_name}: a factor with no bands can never score; "
                "transcribe the bands or omit the factor"
            )
        # Overlap check, pairwise. A scorecard with overlapping bands scores
        # differently depending on iteration order, which is exactly the kind of bug
        # that surfaces as an unexplainable decline months later.
        ordered = sorted(
            self.bands,
            key=lambda b: (b.lower_inclusive if b.lower_inclusive is not None else float("-inf")),
        )
        for earlier, later in zip(ordered, ordered[1:]):
            upper = earlier.upper_exclusive
            lower = later.lower_inclusive
            if upper is None or lower is None or upper > lower:
                raise ValueError(
                    f"{self.feature_name}: bands overlap or leave an ambiguous "
                    "boundary; every value must fall in exactly one band"
                )


@dataclass(frozen=True, kw_only=True)
class Scorecard:
    """A lender's whole scorecard, transcribed as one coherent artifact.

    Whole-artifact rather than row-by-row on purpose: half a scorecard does not score
    a farm more roughly, it scores it *wrongly* — the weights are calibrated against
    each other and a missing factor silently redistributes them.
    """

    lender: str
    name: str
    version: str
    minimum_score: float
    maximum_score: float
    factors: tuple[ScorecardFactor, ...]
    citation: Citation

    def __post_init__(self) -> None:
        if not self.factors:
            raise ValueError("a Scorecard with no factors cannot score anything")
        if self.minimum_score >= self.maximum_score:
            raise ValueError("minimum_score must be below maximum_score")
        seen = [f.feature_name for f in self.factors]
        if len(seen) != len(set(seen)):
            raise ValueError("a feature appears twice in the scorecard factors")


# EMPTY. See the module docstring — this is the designed state, not an omission.
TRANSCRIBED: Scorecard | None = None
