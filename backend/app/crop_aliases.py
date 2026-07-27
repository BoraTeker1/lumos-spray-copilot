"""Explicit crop name equivalence, for matching a decision's crop to a label's
registered crop.

Deliberately a sibling of `app/target_aliases.py` rather than a generalization of it:
crop names and pest names are different vocabularies with different failure modes, and
one dictionary serving both would invite an alias that is right for one and wrong for
the other.

The rule is the same and it is the important part: two crop names are the same crop ONLY
when they are exactly equal after normalization, or both map to the same canonical name
here. Containment is at best AMBIGUOUS, which escalates to a human — it is NEVER treated
as equivalence. A label registered for "strawberry" says nothing about "strawberry
tree", and no amount of string overlap makes it say something.

This is not crop expansion (ENGINEERING_GUIDELINES.md §4): it is aliases for the crops the wedge already
covers, so a label transcribed as "Strawberries" matches a farm recorded as "strawberry".

Framework-free; unit-testable alone.
"""
from __future__ import annotations

import re

# canonical name -> aliases (compared after normalization). Curated for the current
# wedge (CA strawberries + greenhouse tomato); extend deliberately, never generate
# programmatically.
CROP_ALIASES: dict[str, tuple[str, ...]] = {
    "strawberry": (
        "strawberries", "fragaria", "fragaria x ananassa", "fragaria ananassa",
        "day-neutral strawberry", "fresh market strawberry",
    ),
    "tomato": (
        "tomatoes", "solanum lycopersicum", "greenhouse tomato", "greenhouse tomatoes",
        "fresh market tomato", "field tomato",
    ),
}

# Match verdicts — same vocabulary as target_aliases, so callers handling one handle both.
MATCH = "match"
AMBIGUOUS = "ambiguous"
NO_MATCH = "none"

_ALIAS_TO_CANONICAL: dict[str, str] = {}
for _canonical, _aliases in CROP_ALIASES.items():
    _ALIAS_TO_CANONICAL[_canonical] = _canonical
    for _a in _aliases:
        _ALIAS_TO_CANONICAL[_a] = _canonical


def normalize(name: str | None) -> str:
    """Lowercase, trim, collapse whitespace. No stemming, no token surgery."""
    if not name:
        return ""
    return re.sub(r"\s+", " ", name.strip().lower())


def canonical_crop(name: str | None) -> str | None:
    """The canonical crop for an exact/alias match, else None. Never fuzzy."""
    return _ALIAS_TO_CANONICAL.get(normalize(name))


def match_crops(a: str | None, b: str | None) -> str:
    """Compare two crop names: "match" / "ambiguous" / "none".

    match     — normalized-equal, or both resolve to the same canonical entry.
    ambiguous — not a match, but one normalized name contains the other. A signal for
                PCA review, never equivalence: "strawberry" is inside "strawberry tree"
                and they are not the same plant.
    none      — no relationship this module is willing to assert.
    """
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return NO_MATCH
    if na == nb:
        return MATCH
    ca, cb = _ALIAS_TO_CANONICAL.get(na), _ALIAS_TO_CANONICAL.get(nb)
    if ca is not None and ca == cb:
        return MATCH
    if na in nb or nb in na:
        return AMBIGUOUS
    return NO_MATCH
