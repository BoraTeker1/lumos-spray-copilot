"""Variety resistance traits — EMPTY until breeder or trial data is transcribed.

Variety choice is one of the few genuine levers on season-long spray count: a strawberry
variety with real Botrytis field resistance changes the disease-pressure calculus before
a single application is planned. That makes this table valuable and makes inventing it
tempting.

The specific trap here is different from the other empty sources, and worth naming: a
variety's resistance rating is **relative to the trial's conditions**, not absolute.
"Resistant" in a Watsonville trial under overhead irrigation means something different
from "resistant" in a Florida trial under plasticulture. So `TraitRating` carries the
trial context, and `seed_selection` refuses to compare ratings that came from different
sources rather than ranking them against each other — ranking across incommensurable
scales is how a variety gets recommended on the strength of a more generous rater.

`seed_selection.traits_for()` reads this table; while it is empty it returns
`Refusal(NO_SOURCE_TRANSCRIBED)`.

**What fills it:** the breeder's published variety description, or a university variety
trial report for the growing region. A seed catalogue's marketing copy is not a trial.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.transcription import Citation

PRIMARY_SOURCE = (
    "The breeder's published variety description or a university variety trial report "
    "for the growing region: variety, trait, rating, the rating scale used, and the "
    "trial conditions the rating was observed under. Marketing copy is not a trial."
)

# Ratings, worst to best. A named scale rather than a number, because the underlying
# trial scales differ (1-5, 1-9, percentage infection) and normalising them into one
# number would erase exactly the incommensurability this module refuses to paper over.
RATINGS = ("susceptible", "moderately_susceptible", "intermediate",
           "moderately_resistant", "resistant")


@dataclass(frozen=True, kw_only=True)
class TraitRating:
    """One variety's rating for one trait, with the trial it came from."""

    variety: str
    crop: str
    trait: str
    rating: str
    rating_scale: str
    trial_conditions: str
    citation: Citation

    def __post_init__(self) -> None:
        if self.rating not in RATINGS:
            raise ValueError(
                f"{self.variety}/{self.trait}: unknown rating {self.rating!r}; "
                f"expected one of {RATINGS}"
            )
        for name in ("variety", "crop", "trait", "rating_scale", "trial_conditions"):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(
                    f"TraitRating.{name} is blank"
                    + (
                        ". A rating without its trial conditions cannot be compared "
                        "with another trial's rating, which is the main thing anyone "
                        "wants to do with it."
                        if name == "trial_conditions" else ""
                    )
                )


# EMPTY. See the module docstring.
TRANSCRIBED: tuple[TraitRating, ...] = ()
