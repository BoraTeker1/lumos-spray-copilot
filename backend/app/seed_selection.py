"""Variety trait lookup (pure, framework-free).

Reports what transcribed trials say about a variety's traits, or refuses and says why.

**It does not rank varieties and does not recommend one.** Two reasons, and the second is
the load-bearing one:

1. Ratings from different trials are on different scales under different conditions.
   Ranking them requires normalising incommensurable measurements — the same class of
   error as `label_data.convert_rate` refusing mass↔volume without a density.
2. Variety choice is a commercial decision entangled with contracts, plant availability,
   market preference and price. A system that ranked varieties would be steering a
   purchasing decision on agronomic grounds alone, and the moment that ranking could be
   influenced by who supplies the plants it becomes the commission-shaped conflict the
   procurement module was explicitly built to avoid.

So `compare()` returns each variety's ratings **side by side, attributed to its trial**,
and explicitly reports when two ratings are not comparable. The grower and their PCA do
the comparing. This mirrors `QuoteComparisonTable` showing quotes in entry order with a
delta rather than a ranking.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app import variety_table
from app.refusal import NO_SOURCE_TRANSCRIBED, OUTSIDE_SOURCE_SCOPE, Refusal

MODEL_VERSION = "variety_traits_v1"


@dataclass(frozen=True)
class VarietyTrait:
    """One rating, carrying enough context to know what it can be compared with."""

    variety: str
    trait: str
    rating: str
    rating_scale: str
    trial_conditions: str
    source_document: str

    def as_payload(self) -> dict:
        return {
            "variety": self.variety,
            "trait": self.trait,
            "rating": self.rating,
            "rating_scale": self.rating_scale,
            "trial_conditions": self.trial_conditions,
            "source_document": self.source_document,
        }


@dataclass(frozen=True)
class TraitComparison:
    """Several varieties' ratings for one trait, side by side. Never ranked."""

    crop: str
    trait: str
    model_version: str = MODEL_VERSION
    traits: tuple[VarietyTrait, ...] = field(default_factory=tuple)
    comparable: bool = False
    incomparable_reason: str | None = None

    def as_payload(self) -> dict:
        payload = {
            "model_version": self.model_version,
            "crop": self.crop,
            "trait": self.trait,
            "varieties": [t.as_payload() for t in self.traits],
            "comparable": self.comparable,
            # No "best", no "recommended", no ordering key. See the module docstring.
            "not_calculated": {
                "ranking": (
                    "Varieties are not ranked. Ratings from different trials are on "
                    "different scales under different conditions, and variety choice is "
                    "a commercial decision this system does not make."
                ),
            },
        }
        if self.incomparable_reason:
            payload["incomparable_reason"] = self.incomparable_reason
        return payload


def traits_for(*, variety: str, crop: str):
    """Every transcribed trait rating for one variety. Returns tuple | Refusal."""
    if not variety_table.TRANSCRIBED:
        return Refusal(
            NO_SOURCE_TRANSCRIBED,
            "No variety trait ratings have been transcribed. Transcribe the breeder's "
            "variety description or a regional trial report — see app/variety_table.py.",
            {"model_version": MODEL_VERSION},
        )

    variety_key = variety.strip().lower()
    crop_key = crop.strip().lower()
    rows = [
        r for r in variety_table.TRANSCRIBED
        if r.variety.strip().lower() == variety_key and r.crop.strip().lower() == crop_key
    ]
    if not rows:
        return Refusal(
            OUTSIDE_SOURCE_SCOPE,
            f"No transcribed trial covers {variety} for {crop}.",
            {"variety": variety, "crop": crop},
        )

    return tuple(
        VarietyTrait(
            variety=r.variety, trait=r.trait, rating=r.rating,
            rating_scale=r.rating_scale, trial_conditions=r.trial_conditions,
            source_document=r.citation.document,
        )
        for r in rows
    )


def compare(*, varieties, crop: str, trait: str):
    """Side-by-side ratings for one trait. Returns TraitComparison | Refusal.

    `comparable` is True only when every rating came from the same scale AND the same
    trial conditions. Anything else is presented as not comparable, with the reason,
    rather than quietly ordered.
    """
    if not variety_table.TRANSCRIBED:
        return Refusal(
            NO_SOURCE_TRANSCRIBED,
            "No variety trait ratings have been transcribed — see app/variety_table.py.",
            {"model_version": MODEL_VERSION},
        )

    crop_key = crop.strip().lower()
    trait_key = trait.strip().lower()
    wanted = {v.strip().lower() for v in varieties or ()}
    rows = [
        r for r in variety_table.TRANSCRIBED
        if r.crop.strip().lower() == crop_key
        and r.trait.strip().lower() == trait_key
        and r.variety.strip().lower() in wanted
    ]
    if not rows:
        return Refusal(
            OUTSIDE_SOURCE_SCOPE,
            f"No transcribed trial covers {trait} for the requested {crop} varieties.",
            {"crop": crop, "trait": trait, "varieties": sorted(wanted)},
        )

    scales = {r.rating_scale.strip().lower() for r in rows}
    conditions = {r.trial_conditions.strip().lower() for r in rows}
    comparable = len(scales) == 1 and len(conditions) == 1
    reason = None
    if not comparable:
        if len(scales) > 1:
            reason = (
                "These ratings use different scales, so they cannot be placed on one "
                f"axis ({', '.join(sorted(scales))}). Read each against its own trial."
            )
        else:
            reason = (
                "These ratings come from trials under different conditions, so a "
                "difference between them may be the trial rather than the variety."
            )

    return TraitComparison(
        crop=crop, trait=trait, comparable=comparable, incomparable_reason=reason,
        traits=tuple(
            VarietyTrait(
                variety=r.variety, trait=r.trait, rating=r.rating,
                rating_scale=r.rating_scale, trial_conditions=r.trial_conditions,
                source_document=r.citation.document,
            )
            for r in rows
        ),
    )
