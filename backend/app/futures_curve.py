"""Futures quotes — EMPTY until an exchange's published settlements are transcribed.

`hedging.assess()` reads this curve; while it is empty it returns a `Refusal` naming
`NO_CURVE_SUPPLIED`.

Two boundaries are load-bearing in this module and both are easy to erode:

**Nothing here executes.** A hedge position in this system is a *record of a position the
grower took elsewhere*, entered so that the rest of the platform can reason about their
exposure honestly. Lumos does not place orders, does not connect to a broker, and holds
no account. That is the ENGINEERING_GUIDELINES.md §4 "money movement of any kind" line, which this
expansion did not lift.

**Nothing here advises a position.** `hedging.assess()` reports coverage — how much of an
expected harvest is already priced, and what remains exposed — against the grower's own
recorded positions and expected volume. It does not say "hedge more" or "sell now". A
recommendation to take a position is investment advice, which is regulated in every
jurisdiction this product would operate in, and the enum of outcomes is deliberately
shaped so such a recommendation is inexpressible rather than merely discouraged — the
same technique `disease_risk.RiskAssessment` uses to make a spray prescription impossible.

**What fills it:** an exchange's published settlement prices for the relevant contract
months. A broker's indicative quote is not a settlement and is not interchangeable.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.transcription import Citation

PRIMARY_SOURCE = (
    "The exchange's published daily settlement prices for the relevant contract months "
    "(e.g. CME/ICE settlement files). Broker indications and screen quotes are not "
    "settlements and must not be transcribed here."
)


@dataclass(frozen=True, kw_only=True)
class FuturesQuote:
    """One contract month's settlement, on one date."""

    commodity: str
    exchange: str
    contract_month: str  # ISO year-month, e.g. "2026-11"
    settlement_price: float
    currency: str
    unit: str
    settled_on: date
    citation: Citation

    def __post_init__(self) -> None:
        for name in ("commodity", "exchange", "currency", "unit"):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(f"FuturesQuote.{name} is blank")
        if self.settlement_price <= 0:
            raise ValueError(
                f"{self.commodity} {self.contract_month}: settlement_price must be "
                "positive"
            )
        parts = self.contract_month.split("-")
        if len(parts) != 2 or len(parts[0]) != 4 or not parts[1].isdigit():
            raise ValueError(
                f"contract_month must be ISO year-month like '2026-11', got "
                f"{self.contract_month!r}"
            )
        if not 1 <= int(parts[1]) <= 12:
            raise ValueError(f"contract_month has an invalid month: {self.contract_month!r}")


# EMPTY. See the module docstring.
TRANSCRIBED: tuple[FuturesQuote, ...] = ()
