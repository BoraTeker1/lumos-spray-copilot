"""Price dispersion across supplier quotes (pure, framework-free).

The vision's phrase is "better buying power". This module is what that means concretely
and honestly: **how much the same product varies in price between the suppliers who
actually quoted it.** Not a recommendation, not a ranking, not a negotiated rate.

**Why this needs the product catalogue, and why that is the whole point of wiring up
`InputProduct`.** Quote lines carry free-text `product_name`. "Switch 62.5WG",
"Switch 62.5 WG" and "SWITCH 62.5wg" are three strings and one product, and a dispersion
computed over strings silently reports three separate products with no spread each —
which reads as "prices are consistent" when the truth is "we failed to group them". So
dispersion is computed over the CATALOGUE id, and a line with no catalogue link is
excluded and counted, never bucketed by name.

**Matching is exact or it is nothing.** `catalog_key` uses the same rule as
`target_aliases` and `crop_aliases`: normalise, then match exactly, or hand it to a human.
Fuzzy matching a fungicide to a slightly different trade name is how a grower ends up
comparing the price of two different chemistries.

**Three refusals, each guarding a different way a spread can lie:**

* **Fewer than two quotes** — a "spread" over one quote is zero, and zero spread reads as
  a competitive market rather than as an empty comparison.
* **Mixed units** — $12/L and $12/kg are not comparable without a per-product density,
  which `label_data.convert_rate` already refuses to invent. Same refusal here.
* **Mixed currency** — needs an FX rate this system does not hold and would not know the
  date of.

**No ranking, ever.** `procurement_status` and the quote table already carry an explicit
no-ranking policy — Lumos takes no commission and returns quotes in entry order. A
"cheapest supplier" field here would reintroduce exactly that conflict through the back
door, so the result carries min and max **with their supplier names attached to the
observation, not to a verdict**, and no ordering key.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.refusal import CONVERSION_NOT_CITED, NO_DATA_FOR_FARM, Refusal

MODEL_VERSION = "price_dispersion_v1"

# Below this, a spread is not evidence of anything. Two is the real minimum: it is the
# smallest number for which "these suppliers disagree" is a meaningful sentence.
MIN_QUOTES_FOR_DISPERSION = 2

# Refusal codes specific to this module.
TOO_FEW_QUOTES = "too_few_quotes_for_dispersion"
NO_CATALOG_LINK = "no_catalog_linked_quote_lines"


def catalog_key(name: str | None) -> str | None:
    """Normalise a product name for catalogue lookup. Exact-or-nothing, never fuzzy.

    Lowercase, collapse internal whitespace, strip. That is deliberately the whole
    transformation: it absorbs the casing and spacing differences that are certainly the
    same product, and nothing else. Stemming, edit distance or token overlap would start
    matching different chemistries, which is the error this codebase refuses to make
    anywhere else in agronomy.
    """
    if not name:
        return None
    collapsed = " ".join(str(name).split()).strip().lower()
    return collapsed or None


@dataclass(frozen=True)
class PriceObservation:
    """One supplier's unit price for one catalogued product."""

    supplier_name: str
    unit_price: float
    unit: str
    currency: str
    quote_id: int | None = None

    def as_payload(self) -> dict:
        return {
            "supplier_name": self.supplier_name,
            "unit_price": self.unit_price,
            "unit": self.unit,
            "currency": self.currency,
            "quote_id": self.quote_id,
        }


@dataclass(frozen=True)
class PriceDispersion:
    """How much one product's unit price varied across the suppliers who quoted it."""

    input_product_id: int
    product_name: str
    unit: str
    currency: str
    model_version: str = MODEL_VERSION
    observations: tuple[PriceObservation, ...] = field(default_factory=tuple)

    @property
    def lowest(self) -> float:
        return min(o.unit_price for o in self.observations)

    @property
    def highest(self) -> float:
        return max(o.unit_price for o in self.observations)

    @property
    def spread(self) -> float:
        return self.highest - self.lowest

    @property
    def spread_pct(self) -> float:
        """Spread as a share of the lowest price. Zero-safe by construction: unit prices
        are validated positive upstream, so the denominator cannot be zero here."""
        return (self.spread / self.lowest) * 100.0 if self.lowest else 0.0

    def as_payload(self) -> dict:
        return {
            "model_version": self.model_version,
            "input_product_id": self.input_product_id,
            "product_name": self.product_name,
            "unit": self.unit,
            "currency": self.currency,
            "quote_count": len(self.observations),
            "lowest_unit_price": round(self.lowest, 4),
            "highest_unit_price": round(self.highest, 4),
            "spread": round(self.spread, 4),
            "spread_pct": round(self.spread_pct, 2),
            # Entry order, deliberately. Sorting by price here would make this a ranking
            # in everything but name, and the no-ranking policy is a commitment about
            # Lumos's incentives, not a UI preference.
            "observations": [o.as_payload() for o in self.observations],
            "not_calculated": {
                "recommended_supplier": (
                    "No supplier is recommended or ranked. Lumos takes no commission "
                    "and does not rank suppliers; this reports what they quoted."
                ),
                "savings": (
                    "No savings figure. The spread is what suppliers quoted, not money "
                    "saved — a grower may have good reasons to buy above the lowest "
                    "quote, and calling the difference a saving assumes they did not."
                ),
            },
        }


def dispersion_for_product(observations, *, input_product_id: int, product_name: str):
    """Dispersion across one product's observations. Returns PriceDispersion | Refusal."""
    rows = list(observations or ())
    if len(rows) < MIN_QUOTES_FOR_DISPERSION:
        return Refusal(
            TOO_FEW_QUOTES,
            f"Only {len(rows)} supplier quoted {product_name}. A spread computed over "
            "fewer than two quotes is zero, which reads as a competitive market rather "
            "than as an empty comparison.",
            {"product_name": product_name, "quote_count": len(rows)},
        )

    units = {o.unit.strip().lower() for o in rows}
    if len(units) > 1:
        return Refusal(
            CONVERSION_NOT_CITED,
            f"{product_name} was quoted in different units ({', '.join(sorted(units))}). "
            "Comparing them needs a per-product conversion this system does not hold — "
            "the same refusal label_data.convert_rate makes for mass-to-volume.",
            {"product_name": product_name, "units": sorted(units)},
        )

    currencies = {o.currency.strip().upper() for o in rows}
    if len(currencies) > 1:
        return Refusal(
            CONVERSION_NOT_CITED,
            f"{product_name} was quoted in different currencies "
            f"({', '.join(sorted(currencies))}), and converting needs an FX rate this "
            "system does not hold and would not know the date of.",
            {"product_name": product_name, "currencies": sorted(currencies)},
        )

    return PriceDispersion(
        input_product_id=input_product_id,
        product_name=product_name,
        unit=rows[0].unit,
        currency=rows[0].currency,
        observations=tuple(rows),
    )


@dataclass(frozen=True)
class DispersionReport:
    """Dispersion across every catalogued product in a set of quotes."""

    model_version: str = MODEL_VERSION
    products: tuple[PriceDispersion, ...] = field(default_factory=tuple)
    refusals: tuple[Refusal, ...] = field(default_factory=tuple)
    unlinked_line_count: int = 0

    def as_payload(self) -> dict:
        return {
            "model_version": self.model_version,
            "products": [p.as_payload() for p in self.products],
            "not_compared": [r.as_payload() for r in self.refusals],
            # Surfaced rather than swallowed: an unlinked line is a product nobody can
            # compare, and a report that hid them would understate its own blind spot.
            "unlinked_line_count": self.unlinked_line_count,
            "unlinked_note": (
                "Quote lines with no catalogue link are excluded from every comparison. "
                "Product names are free text, and grouping them by name would report "
                "spellings of one product as separate products with no spread each."
            ),
        }


def build_report(lines):
    """Group quote lines by catalogued product and compute each dispersion.

    `lines` is an iterable of objects exposing `input_product_id`, `product_name`,
    `supplier_name`, `unit_price`, `unit`, `currency` and optionally `quote_id`.
    Lines with no `input_product_id` are counted and excluded — never bucketed by name.
    """
    buckets: dict[int, list] = {}
    names: dict[int, str] = {}
    unlinked = 0

    for line in lines or ():
        product_id = getattr(line, "input_product_id", None)
        if product_id is None:
            unlinked += 1
            continue
        buckets.setdefault(product_id, []).append(PriceObservation(
            supplier_name=line.supplier_name,
            unit_price=line.unit_price,
            unit=line.unit,
            currency=getattr(line, "currency", "USD"),
            quote_id=getattr(line, "quote_id", None),
        ))
        names.setdefault(product_id, line.product_name)

    computed, refused = [], []
    for product_id in sorted(buckets):
        result = dispersion_for_product(
            buckets[product_id],
            input_product_id=product_id,
            product_name=names[product_id],
        )
        (refused if isinstance(result, Refusal) else computed).append(result)

    return DispersionReport(
        products=tuple(computed),
        refusals=tuple(refused),
        unlinked_line_count=unlinked,
    )
