"""Pesticide-label data: product identity, label-record resolution, and rate units.

What this module is for. Four checks in `app/decision_engine.py` (maximum seasonal rate,
maximum applications per season, minimum retreatment interval, crop/use registration)
cannot run because nothing in this system knows what a *product* is — product identity is
free text on five different models. This module is the vocabulary and the arithmetic those
checks need. It does not contain any label data; see `app/label_table.py`.

Three rules govern everything here, and they are the reason the module exists at all
rather than being inlined into crud:

  * **A label value is only usable when it is attributable.** `promotable_to_authoritative`
    returns the REASON a record cannot back a decision, and there are many such reasons.
    Silence means promotable; anything else is a sentence a PCA can act on.
  * **Product identity is exact or it is ambiguous.** A registration number's base segments
    identify a registrant's product family, not a label. `100-1234` and `100-1234-5905`
    are DIFFERENT labels with different use directions, so a base-only match is AMBIGUOUS
    and goes to a human. Applying the wrong label's PHI is the single worst thing this
    feature could do.
  * **A conversion is cited or it is refused.** Every entry in RATE_CONVERSIONS is
    definitional (16 oz to a pound) and carries its citation. Mass-to-volume is absent
    because it needs a per-product density, which is not definitional and is not on the
    label in a form we transcribe. `convert_rate` returns a Refusal naming the unit rather
    than inventing a factor — the same discipline as `pilot_evidence._sum_treated_area`,
    which refuses to add acres to square metres.

Framework-free (stdlib only): no FastAPI, no SQLAlchemy. Callers pass plain objects.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from app import crop_aliases

# --------------------------------------------------------------- provenance tiers
# How a stored label record came to exist. Deliberately a SEPARATE vocabulary from
# schemas.InputSourceType: one describes how a label record was obtained, the other how a
# decision's input value was sourced. Collapsing them would let "someone typed this from a
# PDF" and "an authoritative provider asserted this" share a name.
TIER_TRANSCRIBED = "transcribed_unverified"
TIER_AI_EXTRACTED = "ai_extracted_unverified"
TIER_PCA_VERIFIED = "pca_verified_transcription"
TIER_PROVIDER_FEED = "registrant_provider_feed"

LABEL_SOURCE_TIERS = (
    TIER_TRANSCRIBED, TIER_AI_EXTRACTED, TIER_PCA_VERIFIED, TIER_PROVIDER_FEED,
)

# The provenance a decision input value gets when a label record backs it. Only an
# attributed PCA act (or a real provider feed, which does not exist) reaches
# "authoritative_provider" — a human typing from a PDF does not, however carefully.
SOURCE_AUTHORITATIVE = "authoritative_provider"
SOURCE_IMPORTED_UNVERIFIED = "imported_unverified"

LABEL_TIER_TO_INPUT_SOURCE = {
    TIER_TRANSCRIBED: SOURCE_IMPORTED_UNVERIFIED,
    TIER_AI_EXTRACTED: SOURCE_IMPORTED_UNVERIFIED,
    TIER_PCA_VERIFIED: SOURCE_AUTHORITATIVE,
    TIER_PROVIDER_FEED: SOURCE_AUTHORITATIVE,
}

# The regulatory values a label record can carry. Every one is optional: a real label
# states some and not others, and a label that does not state a retreatment interval must
# leave that check not-evaluated rather than imply "no limit".
REGULATORY_FIELDS = (
    "pre_harvest_interval_days",
    "re_entry_interval_hours",
    "max_seasonal_rate_amount",
    "max_applications_per_season",
    "min_retreatment_interval_days",
)

# Provenance every record must carry before it may back a decision. Each is load-bearing:
# without the version and effective date you cannot tell whether the record describes the
# label in the applicator's hand, and without the document reference and snippet a PCA
# cannot check the transcription against the source.
REQUIRED_PROVENANCE_FIELDS = (
    "label_version",
    "label_effective_date",
    "source_document_reference",
    "source_snippet",
)

MATCH = crop_aliases.MATCH
AMBIGUOUS = crop_aliases.AMBIGUOUS
NO_MATCH = crop_aliases.NO_MATCH


# ----------------------------------------------------------------- product identity
def normalize_epa_reg_no(value: str | None) -> str:
    """Canonical form of a registration number: digits and hyphens, nothing else.

    Case, spaces, and a trailing period are formatting. The hyphen structure is NOT —
    it is what distinguishes a label from a supplemental registration of the same
    product, so it is preserved exactly.
    """
    if not value:
        return ""
    cleaned = re.sub(r"[\s.]+", "", str(value).strip().lower())
    return cleaned


def epa_reg_base(value: str | None) -> str:
    """The first two hyphen segments — the registrant's product, not a specific label.

    Useful only for spotting that two numbers are RELATED. Never for concluding they are
    the same label; see `match_product_identity`.
    """
    normalized = normalize_epa_reg_no(value)
    if not normalized:
        return ""
    return "-".join(normalized.split("-")[:2])


def match_product_identity(a: str | None, b: str | None) -> str:
    """Compare two registration numbers: "match" / "ambiguous" / "none".

    match     — identical after normalization. The only case that identifies one label.
    ambiguous — same base registration, different full number. These are related products
                whose labels may differ in crops, rates and intervals, so this goes to a
                human and is never treated as equivalence.
    none      — unrelated, or either side missing.
    """
    na, nb = normalize_epa_reg_no(a), normalize_epa_reg_no(b)
    if not na or not nb:
        return NO_MATCH
    if na == nb:
        return MATCH
    base_a, base_b = epa_reg_base(na), epa_reg_base(nb)
    if base_a and base_a == base_b:
        return AMBIGUOUS
    return NO_MATCH


# ------------------------------------------------------------------- rate units
# Curated canonical rate units and their accepted spellings. Explicit, like the target and
# crop dictionaries: "oz/A" maps to "oz/acre" because it is written here, never because a
# pattern matched. An unknown unit is refused, not guessed.
RATE_UNIT_ALIASES: dict[str, tuple[str, ...]] = {
    "oz/acre": ("oz/a", "oz per acre", "ounces/acre", "ounce/acre", "oz/ac"),
    "lb/acre": ("lb/a", "lbs/acre", "lbs/a", "pound/acre", "pounds/acre", "lb/ac"),
    "fl oz/acre": (
        "fl oz/a", "floz/acre", "fluid oz/acre", "fluid ounce/acre",
        "fluid ounces/acre", "fl.oz/acre", "fl oz/ac",
    ),
    "pt/acre": ("pt/a", "pint/acre", "pints/acre", "pt/ac"),
    "qt/acre": ("qt/a", "quart/acre", "quarts/acre", "qt/ac"),
    "gal/acre": ("gal/a", "gallon/acre", "gallons/acre", "gal/ac"),
    "g/ha": ("gram/hectare", "grams/hectare", "g/hectare"),
    "kg/ha": ("kilogram/hectare", "kilograms/hectare", "kg/hectare"),
    "l/ha": ("liter/hectare", "liters/hectare", "litre/hectare", "litres/hectare"),
    "ml/ha": ("milliliter/hectare", "millilitre/hectare", "ml/hectare"),
}

_RATE_ALIAS_TO_CANONICAL: dict[str, str] = {}
for _canonical, _aliases in RATE_UNIT_ALIASES.items():
    _RATE_ALIAS_TO_CANONICAL[_canonical] = _canonical
    for _a in _aliases:
        _RATE_ALIAS_TO_CANONICAL[_a] = _canonical


def normalize_rate_unit(value: str | None) -> str:
    """Lowercase, trim, collapse whitespace and spaces around the slash."""
    if not value:
        return ""
    text = re.sub(r"\s+", " ", str(value).strip().lower())
    return re.sub(r"\s*/\s*", "/", text)


def canonical_rate_unit(value: str | None) -> str | None:
    """The canonical unit for a known spelling, else None. Never pattern-matched."""
    return _RATE_ALIAS_TO_CANONICAL.get(normalize_rate_unit(value))


@dataclass(frozen=True)
class Conversion:
    """A definitional unit conversion and where the definition comes from."""
    factor: float
    citation: str


# ONLY definitional conversions, each cited. Note what is deliberately absent: there is no
# mass<->volume entry (oz/acre to fl oz/acre), because that requires a per-product density
# which is not definitional and is not something we transcribe from a label. A caller
# needing it gets a Refusal, which is the correct answer.
RATE_CONVERSIONS: dict[tuple[str, str], Conversion] = {
    ("lb/acre", "oz/acre"): Conversion(16.0, "definition: 1 avoirdupois pound = 16 ounces"),
    ("oz/acre", "lb/acre"): Conversion(1 / 16.0, "definition: 1 avoirdupois pound = 16 ounces"),
    ("gal/acre", "fl oz/acre"): Conversion(128.0, "definition: 1 US gallon = 128 US fluid ounces"),
    ("fl oz/acre", "gal/acre"): Conversion(1 / 128.0, "definition: 1 US gallon = 128 US fluid ounces"),
    ("gal/acre", "pt/acre"): Conversion(8.0, "definition: 1 US gallon = 8 US pints"),
    ("pt/acre", "gal/acre"): Conversion(1 / 8.0, "definition: 1 US gallon = 8 US pints"),
    ("gal/acre", "qt/acre"): Conversion(4.0, "definition: 1 US gallon = 4 US quarts"),
    ("qt/acre", "gal/acre"): Conversion(1 / 4.0, "definition: 1 US gallon = 4 US quarts"),
    ("pt/acre", "fl oz/acre"): Conversion(16.0, "definition: 1 US pint = 16 US fluid ounces"),
    ("fl oz/acre", "pt/acre"): Conversion(1 / 16.0, "definition: 1 US pint = 16 US fluid ounces"),
    ("qt/acre", "fl oz/acre"): Conversion(32.0, "definition: 1 US quart = 32 US fluid ounces"),
    ("fl oz/acre", "qt/acre"): Conversion(1 / 32.0, "definition: 1 US quart = 32 US fluid ounces"),
    ("kg/ha", "g/ha"): Conversion(1000.0, "definition: 1 kilogram = 1000 grams"),
    ("g/ha", "kg/ha"): Conversion(1 / 1000.0, "definition: 1 kilogram = 1000 grams"),
    ("l/ha", "ml/ha"): Conversion(1000.0, "definition: 1 litre = 1000 millilitres"),
    ("ml/ha", "l/ha"): Conversion(1 / 1000.0, "definition: 1 litre = 1000 millilitres"),
}


@dataclass(frozen=True)
class Converted:
    """A converted rate and every citation used to get there."""
    amount: float
    unit: str
    conversion_provenance: tuple[str, ...]


@dataclass(frozen=True)
class Refusal:
    """Why a conversion was not performed. Never a number."""
    reason: str


def convert_rate(amount: float | None, from_unit: str | None, to_unit: str | None):
    """Convert a rate, or refuse and say why. Returns Converted | Refusal.

    Refuses rather than approximates. A wrong rate comparison against a label maximum is
    worse than no comparison, because it looks like a finding.
    """
    if amount is None:
        return Refusal("no rate amount to convert")
    source = canonical_rate_unit(from_unit)
    target = canonical_rate_unit(to_unit)
    if source is None:
        return Refusal(
            f"rate unit {from_unit!r} is not in the canonical unit vocabulary, so it "
            f"cannot be compared to a label rate"
        )
    if target is None:
        return Refusal(
            f"label rate unit {to_unit!r} is not in the canonical unit vocabulary, so "
            f"nothing can be converted to it"
        )
    if source == target:
        return Converted(float(amount), target, ())
    conversion = RATE_CONVERSIONS.get((source, target))
    if conversion is None:
        return Refusal(
            f"no cited conversion exists from {source!r} to {target!r} — converting "
            f"would require a factor this system does not have a source for"
        )
    return Converted(float(amount) * conversion.factor, target, (conversion.citation,))


# --------------------------------------------------- active-ingredient quantity
# What a rate is a rate OF. Multiplying a product amount by a concentration is only
# definitional when the two share a basis: a percentage is percent BY WEIGHT, so it
# pairs with a mass rate and nothing else; "lb/gal" pairs with a volume rate. Pairing
# across bases needs a per-product density, which is exactly the factor this module
# refuses to invent (see RATE_CONVERSIONS).
RATE_UNIT_BASIS = {
    "oz/acre": "mass", "lb/acre": "mass",
    "fl oz/acre": "volume", "pt/acre": "volume", "qt/acre": "volume",
    "gal/acre": "volume",
    "g/ha": "mass", "kg/ha": "mass",
    "l/ha": "volume", "ml/ha": "volume",
}

# The area unit each rate is expressed per. A rate per acre needs an area in acres:
# converting the farm's recorded area would be the same silent error
# `pilot_evidence._sum_treated_area` refuses to make, so this refuses too.
RATE_UNIT_AREA = {
    unit: ("acres" if unit.endswith("/acre") else "ha") for unit in RATE_UNIT_BASIS
}

CONCENTRATION_UNIT_ALIASES: dict[str, tuple[str, ...]] = {
    "%": ("percent", "pct", "% w/w", "w/w %", "%w/w"),
    "lb/gal": ("lbs/gal", "pound/gallon", "pounds/gallon", "lb/gallon"),
    "g/l": ("grams/liter", "g/liter", "gram/litre", "grams/litre", "g/litre"),
}

_CONCENTRATION_ALIAS_TO_CANONICAL: dict[str, str] = {}
for _canonical, _aliases in CONCENTRATION_UNIT_ALIASES.items():
    _CONCENTRATION_ALIAS_TO_CANONICAL[_canonical] = _canonical
    for _a in _aliases:
        _CONCENTRATION_ALIAS_TO_CANONICAL[_a] = _canonical

# (concentration unit) -> (required rate basis, the rate unit the product amount must
# be converted to, the resulting active-ingredient unit, citation for the pairing).
_CONCENTRATION_RULES = {
    "%": ("mass", None, None, "definition: % w/w is mass of active per mass of product"),
    "lb/gal": (
        "volume", "gal/acre", "lb",
        "definition: lb/gal is mass of active per US gallon of product",
    ),
    "g/l": (
        "volume", "l/ha", "g",
        "definition: g/L is mass of active per litre of product",
    ),
}


def canonical_concentration_unit(value: str | None) -> str | None:
    """The canonical concentration unit for a known spelling, else None."""
    if not value:
        return None
    text = re.sub(r"\s+", "", str(value).strip().lower())
    return _CONCENTRATION_ALIAS_TO_CANONICAL.get(text)


@dataclass(frozen=True)
class Quantity:
    """An active-ingredient mass and every citation used to arrive at it."""
    amount: float
    unit: str
    conversion_provenance: tuple[str, ...]


def ai_quantity(
    rate_amount: float | None,
    rate_unit: str | None,
    treated_area: float | None,
    area_unit: str | None,
    concentration_amount: float | None,
    concentration_unit: str | None,
):
    """Active-ingredient mass for ONE application, or a Refusal saying why not.

    Returns Quantity | Refusal. Every input is required, and every step is either a
    definitional conversion carrying its citation or a refusal — there is no path
    that produces a number from an assumption.

    This is the metric `pilot_evidence.NOT_CALCULATED` has always disclosed as
    impossible. It becomes possible only for a product whose label concentration is
    on file, and only when the rate, area and concentration bases line up. When they
    do not, the caller must keep disclosing it as not calculated rather than
    reporting a partial total — a "quantity avoided" missing some applications reads
    as a smaller number, not as an incomplete one.
    """
    if rate_amount is None or float(rate_amount) <= 0:
        return Refusal("no application rate recorded")
    if treated_area is None or float(treated_area) <= 0:
        return Refusal("no treated area recorded")
    if concentration_amount is None or float(concentration_amount) <= 0:
        return Refusal("no active-ingredient concentration on file for this product")

    source_rate_unit = canonical_rate_unit(rate_unit)
    if source_rate_unit is None:
        return Refusal(
            f"rate unit {rate_unit!r} is not in the canonical unit vocabulary"
        )
    concentration = canonical_concentration_unit(concentration_unit)
    if concentration is None:
        return Refusal(
            f"concentration unit {concentration_unit!r} is not one of "
            f"{', '.join(sorted(CONCENTRATION_UNIT_ALIASES))}"
        )

    required_basis, target_rate_unit, ai_unit, citation = _CONCENTRATION_RULES[
        concentration
    ]
    if RATE_UNIT_BASIS[source_rate_unit] != required_basis:
        return Refusal(
            f"a {concentration!r} concentration is per {required_basis} of product, "
            f"but the rate is in {source_rate_unit!r} — pairing them would need a "
            f"per-product density this system has no source for"
        )

    expected_area_unit = RATE_UNIT_AREA[source_rate_unit]
    if (area_unit or "").strip().lower() != expected_area_unit:
        return Refusal(
            f"the rate is per {expected_area_unit} but the treated area is recorded "
            f"in {area_unit or 'an unspecified unit'} — areas are never converted"
        )

    provenance: list[str] = []
    amount = float(rate_amount)
    unit = source_rate_unit
    if target_rate_unit is not None and source_rate_unit != target_rate_unit:
        converted = convert_rate(amount, source_rate_unit, target_rate_unit)
        if isinstance(converted, Refusal):
            return converted
        amount, unit = converted.amount, converted.unit
        provenance.extend(converted.conversion_provenance)

    product_amount = amount * float(treated_area)
    if concentration == "%":
        # Percent by weight: the active's unit is the product's own mass unit.
        active = product_amount * float(concentration_amount) / 100.0
        result_unit = unit.split("/")[0]
    else:
        active = product_amount * float(concentration_amount)
        result_unit = ai_unit
    provenance.append(citation)

    return Quantity(round(active, 4), result_unit, tuple(dict.fromkeys(provenance)))


# ------------------------------------------------------- transcription addressing
def transcription_digest(values: dict) -> str:
    """Content address of one transcribed label use.

    Lets the loader be idempotent without an UPDATE: an unchanged digest is a no-op, a
    changed digest appends a superseding row. Canonical JSON (sorted keys, no whitespace)
    so dict ordering cannot change the address.
    """
    canonical = json.dumps(values, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# --------------------------------------------------------------- record resolution
def _is_superseded(record, all_records) -> bool:
    return any(
        getattr(other, "supersedes_label_record_id", None) == getattr(record, "id", None)
        for other in all_records
        if getattr(record, "id", None) is not None
    )


def active_label_records(records) -> list:
    """Non-superseded records, newest effective date first.

    A revision supersedes its predecessor; a withdrawal supersedes it with every
    regulatory value blank. Both are just rows, so resolution is one rule.
    """
    rows = list(records or [])
    live = [r for r in rows if not _is_superseded(r, rows)]
    return sorted(
        live,
        key=lambda r: (getattr(r, "label_effective_date", None) or "", getattr(r, "id", 0)),
        reverse=True,
    )


def resolve_label_record(records, crop: str | None):
    """The live label record for a crop, or (None, reason).

    Returns (record, None) on success and (None, reason) otherwise, so every caller has a
    sentence to report instead of an unexplained absence. An AMBIGUOUS crop match is a
    refusal, not a match: a label registered for a related crop is a different label.
    """
    live = active_label_records(records)
    if not live:
        return None, "no label record on file for this product"

    ambiguous = []
    for record in live:
        verdict = crop_aliases.match_crops(crop, getattr(record, "registered_crop", None))
        if verdict == MATCH:
            if not any(getattr(record, f, None) is not None for f in REGULATORY_FIELDS):
                return None, (
                    "the label record on file for this crop states no regulatory values "
                    "(it records a withdrawal or an incomplete transcription)"
                )
            return record, None
        if verdict == AMBIGUOUS:
            ambiguous.append(getattr(record, "registered_crop", None))
    if ambiguous:
        return None, (
            f"crop {crop!r} only partially matches the registered crop(s) "
            f"{', '.join(repr(c) for c in ambiguous)} on this label — a related crop is "
            f"not the same registration, so a human must decide"
        )
    return None, f"no label record on file for crop {crop!r}"


def promotable_to_authoritative(record, verifications=None) -> str | None:
    """None if this record may back a decision as label-verified, else the reason it cannot.

    Returning the reason rather than a boolean is the point: every one of these becomes
    the `not_evaluated` text a PCA reads, and "not promotable" on its own is useless to
    someone trying to fix it.
    """
    if record is None:
        return "no label record to promote"

    tier = getattr(record, "source_tier", None)
    if tier not in LABEL_SOURCE_TIERS:
        return f"label record has an unrecognized source tier {tier!r}"

    for field_name in REQUIRED_PROVENANCE_FIELDS:
        value = getattr(record, field_name, None)
        if value is None or (isinstance(value, str) and not value.strip()):
            return (
                f"label record is missing {field_name.replace('_', ' ')} — a value "
                f"nobody can trace back to a specific label revision cannot back a "
                f"regulatory check"
            )

    if LABEL_TIER_TO_INPUT_SOURCE[tier] != SOURCE_AUTHORITATIVE:
        live = [
            v for v in (verifications or [])
            if getattr(v, "revoked_at", None) is None
        ]
        if not live:
            return (
                "no licensed PCA has verified this label record against the primary "
                "document for this farm — a transcription is unverified until one does"
            )
        if any(
            (getattr(v, "data_confidence", None) == "simulated"
             or getattr(v, "data_source", None) == "demo")
            for v in live
        ):
            return (
                "the only verification on this label record is a simulated demo record "
                "— demo data can never make a value label-verified"
            )
        if any(getattr(v, "verified_by_credential_id", None) is None for v in live):
            return "a label verification exists but is not attributed to a PCA credential"

    return None
