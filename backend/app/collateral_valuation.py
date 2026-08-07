"""Collateral advance rates — EMPTY until a lender's published schedule is transcribed.

`collateral.value()` reads this table; while it is empty it returns a `Refusal` naming
`NO_ADVANCE_RATE_SUPPLIED`, and no loan-to-value figure exists anywhere in the system.

Why an advance rate must never be defaulted: the failure is asymmetric and silent. A
missing advance rate defaulted to 100% turns an unvalued asset into full coverage and
understates a lender's exposure; defaulted to 0% it denies a borrower collateral they
actually hold. Neither error announces itself, and both look like arithmetic. There is
no safe default, so there is no default.

A standing crop is the hardest case and the one this table exists for: its value depends
on the season completing, which is exactly the risk the collateral is supposed to cover.
Any advance rate against a standing crop encodes a lender's judgment about that circular
risk, and Lumos has no basis to form one.

**What fills it:** the lender's published collateral schedule — asset classes, advance
rates, and the valuation basis each rate assumes.

Note: registering and valuing collateral is a decision-support act. Perfecting a security
interest, filing it, or moving money against it are not in scope and are not modelled.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.transcription import Citation

PRIMARY_SOURCE = (
    "The lending partner's published collateral schedule: eligible asset classes, the "
    "advance rate applied to each, and the valuation basis each rate assumes (e.g. "
    "audited invoice, market survey, insured value). Never estimated from comparables."
)

# Asset classes this system can describe. Adding one is a data question, not a code
# question — but each still needs its own transcribed advance rate before it can be used.
COLLATERAL_TYPES = (
    "standing_crop",
    "harvested_inventory",
    "equipment",
    "land",
    "receivable",
)


@dataclass(frozen=True, kw_only=True)
class AdvanceRate:
    """The share of an asset's assessed value a lender will advance against."""

    collateral_type: str
    advance_rate_pct: float
    valuation_basis: str
    citation: Citation

    def __post_init__(self) -> None:
        if self.collateral_type not in COLLATERAL_TYPES:
            raise ValueError(
                f"unknown collateral_type {self.collateral_type!r}; "
                f"declared types are {COLLATERAL_TYPES}"
            )
        if not 0 < self.advance_rate_pct <= 100:
            raise ValueError(
                f"{self.collateral_type}: advance_rate_pct must be in (0, 100]; "
                f"got {self.advance_rate_pct}"
            )
        if not self.valuation_basis.strip():
            raise ValueError(
                f"{self.collateral_type}: valuation_basis is blank. An advance rate "
                "without the basis it assumes is not applicable to anything — 60% of "
                "an insured value and 60% of a market estimate are different numbers."
            )


# EMPTY. See the module docstring.
TRANSCRIBED: tuple[AdvanceRate, ...] = ()
