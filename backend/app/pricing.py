"""Commodity price lookup (pure, framework-free).

Serves the most recent reported price for a commodity and market, **or refuses because
it is too old**. There is no "most recent available" fallback, and that absence is the
entire design of this module.

The failure it prevents: a grower opens the app to decide whether to sell this week and
sees a price. If that price is three weeks stale, nothing in the number says so — a
stale price and a fresh one are both just a number with a currency symbol. They make a
real commercial decision on it and are wrong for a reason the screen never showed. A
refusal is strictly better, because it sends them to look up the current price, which is
what they would have done had the app said nothing at all.

So `latest()` takes an explicit freshness window and refuses outside it. The window is a
parameter rather than a constant because it is genuinely commodity-dependent — daily
terminal-market reporting for strawberries and a weekly settlement series are different
staleness regimes — and hard-coding one would apply the wrong tolerance to the other.

Mirrors `disease_risk`'s treatment of `MAX_SCOUTING_AGE_DAYS`: an input past its window
is an abstention, not a value with a caveat attached.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app import price_series
from app.refusal import INPUTS_TOO_STALE, NO_SOURCE_TRANSCRIBED, OUTSIDE_SOURCE_SCOPE, Refusal

MODEL_VERSION = "price_view_v1"


@dataclass(frozen=True)
class PriceView:
    """One reported price, with the age the reader needs to judge it."""

    commodity: str
    market: str
    price: float
    currency: str
    unit: str
    observed_on: date
    age_days: int
    source_document: str
    grade: str | None = None
    model_version: str = MODEL_VERSION

    def as_payload(self) -> dict:
        return {
            "model_version": self.model_version,
            "commodity": self.commodity,
            "market": self.market,
            "grade": self.grade,
            "price": self.price,
            "currency": self.currency,
            "unit": self.unit,
            "observed_on": self.observed_on.isoformat(),
            # Always rendered beside the price. A price without its age is the failure
            # this module exists to prevent.
            "age_days": self.age_days,
            "source_document": self.source_document,
            "not_calculated": {
                "forecast": (
                    "No price forecast. This is a reported observation, not a "
                    "prediction, and nothing here models where the price goes next."
                ),
                "sell_recommendation": (
                    "No sell/hold advice. When to sell is a commercial decision that "
                    "depends on the grower's contracts, cash needs and risk appetite."
                ),
            },
        }


def latest(*, commodity: str, market: str, as_of: date, max_age_days: int,
           grade: str | None = None):
    """The most recent price within the freshness window. Returns PriceView | Refusal."""
    if not price_series.TRANSCRIBED:
        return Refusal(
            NO_SOURCE_TRANSCRIBED,
            "No commodity price series has been transcribed. Transcribe a reported "
            "series — see app/price_series.py.",
            {"model_version": MODEL_VERSION},
        )
    if max_age_days <= 0:
        raise ValueError("max_age_days must be positive")

    commodity_key = commodity.strip().lower()
    market_key = market.strip().lower()
    grade_key = grade.strip().lower() if grade else None

    candidates = [
        p for p in price_series.TRANSCRIBED
        if p.commodity.strip().lower() == commodity_key
        and p.market.strip().lower() == market_key
        and p.observed_on <= as_of
        and (
            grade_key is None
            or (p.grade is not None and p.grade.strip().lower() == grade_key)
        )
    ]
    if not candidates:
        return Refusal(
            OUTSIDE_SOURCE_SCOPE,
            f"No transcribed price for {commodity} at {market}"
            f"{f' ({grade})' if grade else ''} on or before {as_of.isoformat()}.",
            {"commodity": commodity, "market": market, "grade": grade},
        )

    newest = max(candidates, key=lambda p: p.observed_on)
    age_days = (as_of - newest.observed_on).days
    if age_days > max_age_days:
        return Refusal(
            INPUTS_TOO_STALE,
            f"The most recent transcribed price for {commodity} at {market} is "
            f"{age_days} days old, past the {max_age_days}-day window. Serving it would "
            "present a stale price as a current one, and nothing about the number would "
            "show the difference.",
            {
                "commodity": commodity, "market": market,
                "age_days": age_days, "max_age_days": max_age_days,
                "observed_on": newest.observed_on.isoformat(),
            },
        )

    return PriceView(
        commodity=newest.commodity, market=newest.market, grade=newest.grade,
        price=newest.price, currency=newest.currency, unit=newest.unit,
        observed_on=newest.observed_on, age_days=age_days,
        source_document=newest.citation.document,
    )
