"""Commodity price observations — EMPTY until a reported price series is transcribed.

`pricing.latest()` reads this table; while it is empty it returns a `Refusal` naming
`NO_PRICE_SERIES_SUPPLIED`.

The failure mode this module is shaped against is **staleness passed off as currency**.
A price is only meaningful attached to the moment it was observed, and the natural bug —
holding the last known price and serving it as "the price" — is invisible in the output:
the number looks exactly like a fresh one. Growers make sale-timing decisions on these
numbers, so a three-week-old strawberry price presented as today's is materially worse
than no price at all, which at least prompts them to go look.

So `PricePoint.observed_on` is required, and `pricing.py` refuses rather than serves any
point older than its freshness window. There is no "most recent available" fallback.

**What fills it:** a reported price series — USDA AMS terminal market reports, a
cooperative's settlement sheets, or an exchange's published spot data. A price a grower
mentioned on a call is a data point about that conversation, not a market price, and does
not belong here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.transcription import Citation

PRIMARY_SOURCE = (
    "A reported commodity price series — e.g. USDA AMS terminal market reports, a "
    "marketing cooperative's settlement sheets, or an exchange's published spot series. "
    "Each point carries the date it was observed and the market it was observed in."
)


@dataclass(frozen=True, kw_only=True)
class PricePoint:
    """One reported price, anchored to the day and market it was reported for."""

    commodity: str
    market: str
    price: float
    currency: str
    unit: str
    observed_on: date
    citation: Citation
    grade: str | None = None

    def __post_init__(self) -> None:
        for name in ("commodity", "market", "currency", "unit"):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(f"PricePoint.{name} is blank")
        if self.price <= 0:
            raise ValueError(
                f"{self.commodity}: price must be positive; got {self.price}. A zero "
                "price is a missing observation, and must be omitted rather than "
                "recorded as free."
            )
        if len(self.currency) != 3:
            raise ValueError(
                f"{self.commodity}: currency must be a 3-letter ISO code, "
                f"got {self.currency!r} — an ambiguous '$' has burned people before"
            )


# EMPTY. See the module docstring.
TRANSCRIBED: tuple[PricePoint, ...] = ()
