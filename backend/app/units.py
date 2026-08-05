"""Platform unit system: canonical units, definitional conversions, or a refusal.

Why this exists. Until now every measure in this system carried its unit as a habit —
`greenhouse_area` in "acres" or "m2" depending on the country, `treated_acres` that might
not be acres (hence `treated_area_unit`), rainfall in mm because the importer said so.
That is survivable for one crop and one workflow. It is not survivable for a platform
where a soil test, a weather feed, a fertiliser rate, a yield forecast, and a cost per
hectare all have to reach the same decision.

The discipline is copied deliberately from `app/label_data.py`, which is the module in
this codebase that got units right:

  * **A conversion is definitional and cited, or it is refused.** Every factor below is
    an exact definition (1 acre = 4840 square yards; 1 yard = 0.9144 m), not a
    measurement and not a convention. `convert` returns `Converted | Refusal`, never a
    best guess, because a silently wrong unit is worse than a missing number: it looks
    like an answer.
  * **Cross-dimension conversion is always refused.** Mass to volume needs a density,
    which is a property of a substance and not of the units. `label_data` refuses this
    for pesticide rates; so does this module, for the same reason.
  * **Currency is not a unit.** Money cannot be converted without a dated FX rate, which
    is data, not a definition. `convert_money` refuses unless the caller supplies one.

What this module deliberately does NOT do, and must not be used to do:

  * It does not license changing the existing refusals. `pilot_evidence._sum_treated_area`
    refuses to total a mixed-unit set, and `decision_engine` compares rates only through
    `label_data.convert_rate`. Those refusals are about what a NUMBER MEANS to a reader,
    not about whether arithmetic is possible. Having a converter available is not a
    reason to start totalling things the product previously declined to total.
  * It does not handle compound rate units (`lb/acre`, `l/ha`). Those are
    `label_data`'s vocabulary and stay there. `convert_ratio` composes a numerator and a
    denominator conversion for the platform's own ratio features (yield per area, cost
    per area), and carries both citations.

Framework-free (stdlib only): no FastAPI, no SQLAlchemy, no imports from `app` except
nothing at all. Callers pass plain numbers and strings.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# --------------------------------------------------------------------- dimensions
# The canonical unit for each dimension is what the database stores. Display units are
# a presentation concern resolved at the API edge from the farm's locale; nothing
# downstream of storage should ever have to ask what unit a column is in.
AREA = "area"
MASS = "mass"
VOLUME = "volume"
LENGTH = "length"
ENERGY = "energy"
DURATION = "duration"
TEMPERATURE = "temperature"

CANONICAL_UNIT = {
    AREA: "m2",
    MASS: "kg",
    VOLUME: "l",
    LENGTH: "m",
    ENERGY: "kwh",
    DURATION: "h",
    TEMPERATURE: "c",
}


@dataclass(frozen=True)
class UnitDef:
    """One unit: its dimension, its size in canonical units, and where that is defined.

    `factor` is how many canonical units one of this unit is. Temperature has no
    meaningful factor (it is affine, not proportional) and is handled separately.
    """
    canonical: str
    dimension: str
    factor: float
    citation: str
    aliases: tuple[str, ...] = ()


# Every factor here is EXACT by definition. Nothing in this table is a measurement, an
# average, or a rounded convention — that is the property that makes a conversion safe
# to perform without asking a human.
_UNITS: tuple[UnitDef, ...] = (
    # --- area
    UnitDef("m2", AREA, 1.0, "canonical unit", ("m^2", "sq m", "square metre", "square meter", "sqm")),
    UnitDef("ha", AREA, 10_000.0, "definition: 1 hectare = 10 000 square metres", ("hectare", "hectares")),
    UnitDef("km2", AREA, 1_000_000.0, "definition: 1 square kilometre = 1 000 000 square metres", ("km^2", "sq km")),
    UnitDef(
        "acre", AREA, 4046.8564224,
        "definition: 1 acre = 4840 square yards; 1 international yard = 0.9144 m exactly",
        ("acres", "ac"),
    ),
    UnitDef("ft2", AREA, 0.09290304, "definition: 1 international foot = 0.3048 m exactly", ("sq ft", "ft^2")),
    # --- mass
    UnitDef("kg", MASS, 1.0, "canonical unit", ("kilogram", "kilograms", "kilo", "kilos")),
    UnitDef("g", MASS, 0.001, "definition: 1 kilogram = 1000 grams", ("gram", "grams")),
    UnitDef("mg", MASS, 1e-6, "definition: 1 gram = 1000 milligrams", ("milligram", "milligrams")),
    UnitDef("t", MASS, 1000.0, "definition: 1 tonne = 1000 kilograms", ("tonne", "tonnes", "metric ton", "mt")),
    UnitDef(
        "lb", MASS, 0.45359237,
        "definition: 1 international avoirdupois pound = 0.45359237 kg exactly",
        ("lbs", "pound", "pounds"),
    ),
    UnitDef(
        "oz", MASS, 0.028349523125,
        "definition: 1 avoirdupois pound = 16 ounces; 1 pound = 0.45359237 kg exactly",
        ("ounce", "ounces"),
    ),
    UnitDef(
        "ton_us", MASS, 907.18474,
        "definition: 1 US short ton = 2000 avoirdupois pounds",
        ("short ton", "us ton"),
    ),
    # --- volume
    UnitDef("l", VOLUME, 1.0, "canonical unit", ("liter", "litre", "liters", "litres", "lt")),
    UnitDef("ml", VOLUME, 0.001, "definition: 1 litre = 1000 millilitres", ("milliliter", "millilitre")),
    UnitDef("m3", VOLUME, 1000.0, "definition: 1 cubic metre = 1000 litres", ("m^3", "cubic metre", "cubic meter")),
    UnitDef(
        "gal", VOLUME, 3.785411784,
        "definition: 1 US liquid gallon = 231 cubic inches; 1 inch = 0.0254 m exactly",
        ("gallon", "gallons", "us gal"),
    ),
    UnitDef(
        "fl oz", VOLUME, 0.0295735295625,
        "definition: 1 US liquid gallon = 128 US fluid ounces",
        ("floz", "fluid ounce", "fluid ounces"),
    ),
    UnitDef("qt", VOLUME, 0.946352946, "definition: 1 US liquid gallon = 4 US quarts", ("quart", "quarts")),
    UnitDef("pt", VOLUME, 0.473176473, "definition: 1 US liquid gallon = 8 US pints", ("pint", "pints")),
    UnitDef(
        "acre_in", VOLUME, 102790.15312896,
        "definition: 1 acre-inch = 1 acre x 1 inch; 1 acre = 4046.8564224 m2, 1 inch = 0.0254 m",
        ("acre-inch", "acre inch", "ac-in"),
    ),
    UnitDef(
        "af", VOLUME, 1233481.83754752,
        "definition: 1 acre-foot = 1 acre x 1 foot; 1 acre = 4046.8564224 m2, 1 foot = 0.3048 m",
        ("acre-foot", "acre foot", "acre-ft"),
    ),
    # --- length
    UnitDef("m", LENGTH, 1.0, "canonical unit", ("metre", "meter", "metres", "meters")),
    UnitDef("mm", LENGTH, 0.001, "definition: 1 metre = 1000 millimetres", ("millimetre", "millimeter")),
    UnitDef("cm", LENGTH, 0.01, "definition: 1 metre = 100 centimetres", ("centimetre", "centimeter")),
    UnitDef("km", LENGTH, 1000.0, "definition: 1 kilometre = 1000 metres", ("kilometre", "kilometer")),
    UnitDef("in", LENGTH, 0.0254, "definition: 1 international inch = 0.0254 m exactly", ("inch", "inches")),
    UnitDef("ft", LENGTH, 0.3048, "definition: 1 international foot = 0.3048 m exactly", ("foot", "feet")),
    UnitDef("mi", LENGTH, 1609.344, "definition: 1 international mile = 5280 feet", ("mile", "miles")),
    # --- energy
    UnitDef("kwh", ENERGY, 1.0, "canonical unit", ("kw h", "kw-h", "kilowatt hour", "kilowatt-hour")),
    UnitDef("wh", ENERGY, 0.001, "definition: 1 kilowatt-hour = 1000 watt-hours", ("watt hour", "watt-hour")),
    UnitDef("mwh", ENERGY, 1000.0, "definition: 1 megawatt-hour = 1000 kilowatt-hours", ("megawatt hour",)),
    UnitDef("mj", ENERGY, 1 / 3.6, "definition: 1 kilowatt-hour = 3.6 megajoules", ("megajoule", "megajoules")),
    UnitDef("kj", ENERGY, 1 / 3600.0, "definition: 1 kilowatt-hour = 3600 kilojoules", ("kilojoule", "kilojoules")),
    UnitDef(
        "therm", ENERGY, 29.3071,
        "definition: 1 US therm = 100 000 BTU(IT); 1 kWh = 3412.14 BTU(IT)",
        ("therms",),
    ),
    # --- duration
    UnitDef("h", DURATION, 1.0, "canonical unit", ("hour", "hours", "hr", "hrs")),
    UnitDef("min", DURATION, 1 / 60.0, "definition: 1 hour = 60 minutes", ("minute", "minutes")),
    UnitDef("s", DURATION, 1 / 3600.0, "definition: 1 hour = 3600 seconds", ("sec", "second", "seconds")),
    UnitDef("d", DURATION, 24.0, "definition: 1 day = 24 hours", ("day", "days")),
    # --- temperature (factor is unused; conversion is affine, see convert())
    UnitDef("c", TEMPERATURE, 1.0, "canonical unit", ("celsius", "centigrade", "degc", "deg c", "°c")),
    UnitDef("f", TEMPERATURE, 1.0, "definition: degF = degC x 9/5 + 32", ("fahrenheit", "degf", "deg f", "°f")),
    UnitDef("k", TEMPERATURE, 1.0, "definition: 0 K = -273.15 degC", ("kelvin",)),
)

_BY_ALIAS: dict[str, UnitDef] = {}
for _u in _UNITS:
    _BY_ALIAS[_u.canonical] = _u
    for _alias in _u.aliases:
        _BY_ALIAS[_alias] = _u


def normalize_unit(value: str | None) -> str:
    """Lowercase, trim, collapse internal whitespace. Never pattern-matched."""
    if not value:
        return ""
    return re.sub(r"\s+", " ", str(value).strip().lower())


def canonical_unit(value: str | None) -> str | None:
    """The canonical spelling for a known unit, else None.

    None means "this system has no definition for that unit" — it never falls back to
    guessing from a prefix or a substring, because `mt` (tonne) and `m` (metre) differ
    by a factor of a thousand and a dimension.
    """
    unit = _BY_ALIAS.get(normalize_unit(value))
    return unit.canonical if unit else None


def dimension_of(value: str | None) -> str | None:
    """Which dimension a unit measures, or None if the unit is unknown."""
    unit = _BY_ALIAS.get(normalize_unit(value))
    return unit.dimension if unit else None


@dataclass(frozen=True)
class Converted:
    """A converted quantity and every citation used to get there."""
    amount: float
    unit: str
    conversion_provenance: tuple[str, ...]


@dataclass(frozen=True)
class Refusal:
    """Why a conversion was not performed. Never carries a number."""
    reason: str


def _to_celsius(amount: float, unit: str) -> float:
    if unit == "c":
        return amount
    if unit == "f":
        return (amount - 32.0) * 5.0 / 9.0
    return amount - 273.15  # kelvin


def _from_celsius(amount: float, unit: str) -> float:
    if unit == "c":
        return amount
    if unit == "f":
        return amount * 9.0 / 5.0 + 32.0
    return amount + 273.15  # kelvin


def convert(amount: float | None, from_unit: str | None, to_unit: str | None):
    """Convert a scalar quantity, or refuse and say why. Returns Converted | Refusal.

    Refuses on: a missing amount, an unknown unit on either side, or a cross-dimension
    request. The last is the important one — converting kilograms to litres requires a
    density, which is a property of the substance and is not knowable from the units.
    """
    if amount is None:
        return Refusal("no amount to convert")
    source = _BY_ALIAS.get(normalize_unit(from_unit))
    target = _BY_ALIAS.get(normalize_unit(to_unit))
    if source is None:
        return Refusal(
            f"unit {from_unit!r} is not in the canonical unit vocabulary, so its "
            f"magnitude is unknown"
        )
    if target is None:
        return Refusal(
            f"unit {to_unit!r} is not in the canonical unit vocabulary, so nothing can "
            f"be converted to it"
        )
    if source.dimension != target.dimension:
        return Refusal(
            f"cannot convert {source.canonical!r} ({source.dimension}) to "
            f"{target.canonical!r} ({target.dimension}) — a cross-dimension conversion "
            f"needs a substance property this system does not have"
        )
    if source.canonical == target.canonical:
        return Converted(float(amount), target.canonical, ())
    if source.dimension == TEMPERATURE:
        celsius = _to_celsius(float(amount), source.canonical)
        return Converted(
            _from_celsius(celsius, target.canonical),
            target.canonical,
            (source.citation, target.citation),
        )
    converted = float(amount) * source.factor / target.factor
    return Converted(converted, target.canonical, (source.citation, target.citation))


def to_canonical(amount: float | None, unit: str | None):
    """Convert to the canonical unit for whatever dimension `unit` belongs to."""
    dimension = dimension_of(unit)
    if dimension is None:
        return Refusal(
            f"unit {unit!r} is not in the canonical unit vocabulary, so it has no "
            f"canonical form"
        )
    return convert(amount, unit, CANONICAL_UNIT[dimension])


def convert_ratio(
    amount: float | None,
    from_numerator: str | None,
    from_denominator: str | None,
    to_numerator: str | None,
    to_denominator: str | None,
):
    """Convert a ratio quantity (yield per area, cost per area, volume per area).

    Composes two scalar conversions and carries BOTH sets of citations. Refuses if
    either side refuses, and reports the numerator's reason first — a caller reading the
    refusal needs to know which half of the ratio it could not handle.

    Not a replacement for `label_data.convert_rate`. Pesticide rates keep their own
    vocabulary and their own deliberately narrower conversion table, because a rate
    compared against a label maximum has a regulatory consequence that a yield-per-
    hectare figure does not.
    """
    if amount is None:
        return Refusal("no amount to convert")
    numerator = convert(1.0, from_numerator, to_numerator)
    if isinstance(numerator, Refusal):
        return Refusal(f"ratio numerator: {numerator.reason}")
    denominator = convert(1.0, from_denominator, to_denominator)
    if isinstance(denominator, Refusal):
        return Refusal(f"ratio denominator: {denominator.reason}")
    factor = numerator.amount / denominator.amount
    unit = f"{numerator.unit}/{denominator.unit}"
    provenance = tuple(dict.fromkeys(numerator.conversion_provenance + denominator.conversion_provenance))
    return Converted(float(amount) * factor, unit, provenance)


# ------------------------------------------------------------------------- money
# Money is stored as an integer count of minor units plus an ISO-4217 code. Floats are
# not used for money anywhere in the platform: 0.1 + 0.2 is a rounding bug in a ledger
# and an argument with a lender. The exponent table is the only currency knowledge the
# core needs; anything beyond it (formatting, symbols) is a presentation concern.
CURRENCY_EXPONENT = {
    "USD": 2,
    "TRY": 2,
    "EUR": 2,
    "GBP": 2,
    "MXN": 2,
    "JPY": 0,
}

DEFAULT_CURRENCY = "USD"


def currency_exponent(currency: str | None) -> int | None:
    """Minor units per major unit, as a power of ten. None if the code is unknown."""
    if not currency:
        return None
    return CURRENCY_EXPONENT.get(str(currency).strip().upper())


def to_minor_units(amount: float | None, currency: str | None):
    """Major units (dollars) to integer minor units (cents). Returns int | Refusal.

    Rounds half away from zero at the currency's own precision. Anything finer than a
    cent was never money — it was the output of a rate calculation, and the rounding has
    to happen at exactly one place or two components of the same total will disagree.
    """
    exponent = currency_exponent(currency)
    if exponent is None:
        return Refusal(f"currency {currency!r} is not in the known-currency table")
    if amount is None:
        return Refusal("no amount to convert")
    scale = 10 ** exponent
    scaled = float(amount) * scale
    return int(scaled + (0.5 if scaled >= 0 else -0.5))


def from_minor_units(amount: int | None, currency: str | None):
    """Integer minor units back to major units, for display only."""
    exponent = currency_exponent(currency)
    if exponent is None:
        return Refusal(f"currency {currency!r} is not in the known-currency table")
    if amount is None:
        return Refusal("no amount to convert")
    return Converted(float(amount) / (10 ** exponent), str(currency).strip().upper(), ())


def convert_money(amount: int | None, from_currency: str | None, to_currency: str | None,
                  rate=None, rate_citation: str | None = None):
    """Convert money, which requires a dated FX rate the CALLER supplies.

    There is no FX table in this module and there will not be one. A rate is an
    observation with a date and a source, not a definition — the same reason
    `label_data` has no density table. Same-currency conversion is the identity and
    needs no rate.
    """
    source = (from_currency or "").strip().upper()
    target = (to_currency or "").strip().upper()
    if currency_exponent(source) is None:
        return Refusal(f"currency {from_currency!r} is not in the known-currency table")
    if currency_exponent(target) is None:
        return Refusal(f"currency {to_currency!r} is not in the known-currency table")
    if amount is None:
        return Refusal("no amount to convert")
    if source == target:
        return Converted(float(amount), target, ())
    if rate is None:
        return Refusal(
            f"converting {source} to {target} requires a dated FX rate, which is an "
            f"observation this module will not invent"
        )
    if not rate_citation:
        return Refusal(
            f"an FX rate was supplied for {source}->{target} without a source; an "
            f"uncited rate cannot be put in a ledger"
        )
    major = float(amount) / (10 ** currency_exponent(source))
    converted = to_minor_units(major * float(rate), target)
    if isinstance(converted, Refusal):
        return converted
    return Converted(float(converted), target, (rate_citation,))
