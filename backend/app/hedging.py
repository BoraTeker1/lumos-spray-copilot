"""Price-risk coverage (pure, framework-free).

Reports how much of an expected harvest is already priced through positions the grower
took **elsewhere**, and how much remains exposed. Nothing here executes, and nothing here
advises.

**Why the outcome vocabulary is shaped the way it is.** `HedgeCoverage` has no
`recommended_action`, no `suggested_contracts`, and no `should_hedge` field — the same
technique `disease_risk.RiskAssessment` uses to make a spray prescription *inexpressible*
rather than merely forbidden. A recommendation to take, increase or close a market
position is investment advice, which is regulated in every jurisdiction this product
would operate in, and the distance between "you are 40% covered" and "you should cover
more" is one field that a well-meaning later change could add in a minute. It cannot be
added without changing this dataclass, which is the point.

**Positions are records, not orders.** A `Position` here describes something the grower
did with their broker or cooperative. Lumos holds no account, places nothing, and settles
nothing — the ENGINEERING_GUIDELINES.md §4 "money movement of any kind" line, which the 2026-08-07
admission explicitly did not lift.

**Coverage is all-or-nothing on units.** A position quoted per tonne and an expected
harvest quoted in hundredweight cannot be netted without a cited conversion, so this
module refuses rather than converting — mirroring `label_data.convert_rate` refusing
mass↔volume, and `pilot_evidence._sum_treated_area` refusing to total a mixed-unit set.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.refusal import CONVERSION_NOT_CITED, NO_DATA_FOR_FARM, Refusal

MODEL_VERSION = "hedge_coverage_v1"

# What a recorded position does to price exposure. `sold_forward` and `bought_put` both
# reduce downside exposure; they are kept distinct because they are not equivalent
# instruments and collapsing them would misdescribe what the grower actually holds.
POSITION_KINDS = ("sold_forward", "bought_put", "cooperative_pool", "cash_contract")


@dataclass(frozen=True)
class Position:
    """A price-risk position the grower took elsewhere. Never an order."""

    kind: str
    quantity: float
    quantity_unit: str
    commodity: str
    counterparty: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in POSITION_KINDS:
            raise ValueError(
                f"unknown position kind {self.kind!r}; declared kinds are {POSITION_KINDS}"
            )
        if self.quantity <= 0:
            raise ValueError("a recorded position must have a positive quantity")
        if not self.quantity_unit.strip():
            raise ValueError("Position.quantity_unit is blank")


@dataclass(frozen=True)
class HedgeCoverage:
    """How much expected production is priced, and how much is not.

    Deliberately has no action field. See the module docstring.
    """

    commodity: str
    expected_quantity: float
    covered_quantity: float
    quantity_unit: str
    position_count: int
    model_version: str = MODEL_VERSION

    @property
    def covered_fraction(self) -> float:
        if not self.expected_quantity:
            return 0.0
        return self.covered_quantity / self.expected_quantity

    @property
    def exposed_quantity(self) -> float:
        """Never negative: over-hedging is its own condition, not negative exposure."""
        return max(self.expected_quantity - self.covered_quantity, 0.0)

    @property
    def over_covered(self) -> bool:
        """Priced more than expected production — a real and reportable situation."""
        return self.covered_quantity > self.expected_quantity

    def as_payload(self) -> dict:
        return {
            "model_version": self.model_version,
            "commodity": self.commodity,
            "quantity_unit": self.quantity_unit,
            "expected_quantity": round(self.expected_quantity, 3),
            "covered_quantity": round(self.covered_quantity, 3),
            "exposed_quantity": round(self.exposed_quantity, 3),
            "covered_fraction": round(self.covered_fraction, 4),
            "over_covered": self.over_covered,
            "position_count": self.position_count,
            "not_calculated": {
                "recommended_action": (
                    "No hedging advice. Whether to take, increase or close a position "
                    "is investment advice; this reports coverage only."
                ),
                "mark_to_market": (
                    "No profit or loss on positions. That needs settlement prices for "
                    "each position's contract month and the price each was struck at, "
                    "neither of which this system holds."
                ),
            },
        }


def coverage(*, commodity: str, expected_quantity: float | None, quantity_unit: str,
             positions):
    """Coverage of expected production by recorded positions. HedgeCoverage | Refusal."""
    if expected_quantity is None:
        return Refusal(
            NO_DATA_FOR_FARM,
            "No expected production quantity recorded, so there is nothing to measure "
            "coverage against. Assuming a default would invent the denominator of every "
            "percentage on this screen.",
            {"commodity": commodity},
        )
    if expected_quantity <= 0:
        return Refusal(
            NO_DATA_FOR_FARM,
            "Expected production must be positive to compute coverage.",
            {"commodity": commodity, "expected_quantity": expected_quantity},
        )

    commodity_key = commodity.strip().lower()
    relevant = [
        p for p in (positions or ()) if p.commodity.strip().lower() == commodity_key
    ]
    if not relevant:
        # A true zero, not an abstention: the grower has recorded no positions for this
        # commodity, which means none of the crop is priced. That is a real, useful
        # answer and distinct from "we cannot see their positions".
        return HedgeCoverage(
            commodity=commodity, expected_quantity=expected_quantity,
            covered_quantity=0.0, quantity_unit=quantity_unit, position_count=0,
        )

    units = {p.quantity_unit.strip().lower() for p in relevant} | {
        quantity_unit.strip().lower()
    }
    if len(units) > 1:
        return Refusal(
            CONVERSION_NOT_CITED,
            "Positions and expected production are quoted in different units "
            f"({', '.join(sorted(units))}), and netting them needs a cited conversion "
            "this system does not hold. Re-enter them in one unit rather than having "
            "the platform guess at the factor.",
            {"commodity": commodity, "units": sorted(units)},
        )

    return HedgeCoverage(
        commodity=commodity,
        expected_quantity=expected_quantity,
        covered_quantity=sum(p.quantity for p in relevant),
        quantity_unit=quantity_unit,
        position_count=len(relevant),
    )
