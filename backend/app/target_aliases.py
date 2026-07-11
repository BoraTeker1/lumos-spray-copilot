"""Explicit pest/disease name equivalence for the specialty-crop wedge.

The decision engine may treat two target names as the same pest/disease ONLY when
they are exactly equal after normalization or both map to the same canonical name in
this curated dictionary. Anything less is at best AMBIGUOUS — the engine escalates
ambiguity to PCA review and records it; it NEVER silently infers that two names are
equivalent (no fuzzy matching, no scoring).

Framework-free; unit-testable alone.
"""
from __future__ import annotations

import re

# canonical name -> aliases (all compared after normalization). Curated for the
# current wedge (CA strawberries + greenhouse tomato); extend deliberately, never
# generate programmatically.
TARGET_ALIASES: dict[str, tuple[str, ...]] = {
    "gray mold": (
        "grey mold", "botrytis", "botrytis cinerea", "botrytis fruit rot",
        "gray mold (botrytis)", "botrytis gray mold",
    ),
    "twospotted spider mite": (
        "two-spotted spider mite", "two spotted spider mite", "tetranychus urticae",
        "spider mite", "spider mites",
    ),
    "lygus bug": (
        "lygus", "lygus hesperus", "tarnished plant bug", "western tarnished plant bug",
    ),
    "powdery mildew": ("podosphaera aphanis", "oidium"),
    "whitefly": ("whiteflies", "greenhouse whitefly", "bemisia", "bemisia tabaci"),
    "early blight": ("alternaria", "alternaria solani"),
    "late blight": ("phytophthora infestans",),
    "aphids": ("aphid", "green peach aphid", "melon aphid"),
    "thrips": ("western flower thrips", "frankliniella occidentalis"),
    "anthracnose": ("colletotrichum", "colletotrichum acutatum", "anthracnose fruit rot"),
}

# Match verdicts.
MATCH = "match"
AMBIGUOUS = "ambiguous"
NO_MATCH = "none"

_ALIAS_TO_CANONICAL: dict[str, str] = {}
for _canonical, _aliases in TARGET_ALIASES.items():
    _ALIAS_TO_CANONICAL[_canonical] = _canonical
    for _a in _aliases:
        _ALIAS_TO_CANONICAL[_a] = _canonical


def normalize(name: str | None) -> str:
    """Lowercase, trim, collapse whitespace. No stemming, no token surgery."""
    if not name:
        return ""
    return re.sub(r"\s+", " ", name.strip().lower())


def canonical_target(name: str | None) -> str | None:
    """The canonical name for an exact/alias match, else None. Never fuzzy."""
    return _ALIAS_TO_CANONICAL.get(normalize(name))


def match_targets(a: str | None, b: str | None) -> str:
    """Compare two target names: "match" / "ambiguous" / "none".

    match     — normalized-equal, or both resolve to the same canonical alias entry.
    ambiguous — not a match, but one normalized name contains the other, or one
                contains a known alias of the other's canonical entry. This is a
                signal for PCA review, never treated as equivalence.
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
    # Containment either way is a hint worth a human look — nothing more.
    if na in nb or nb in na:
        return AMBIGUOUS
    # One side is a known target; does any of its aliases appear inside the other's
    # free text (e.g. target "gray mold" vs. note "botrytis on ripening fruit")?
    for canonical, side_norm, other in ((ca, na, nb), (cb, nb, na)):
        if canonical is None:
            continue
        for alias in (canonical, *TARGET_ALIASES[canonical]):
            if normalize(alias) in other:
                return AMBIGUOUS
    return NO_MATCH
