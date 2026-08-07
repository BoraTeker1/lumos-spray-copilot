"""Nutrient budgeting (pure, framework-free).

Computes crop nutrient removal for an expected yield against transcribed removal rates,
or refuses and says why.

**What this deliberately does not do: tell anyone how much fertilizer to apply.**
`NutrientBudget` reports *removal* — how much of a nutrient the crop is expected to take
off the field. Converting removal into an application rate requires soil supply, an
efficiency factor, irrigation water content, and split-timing decisions, each of which is
a judgment an agronomist makes and none of which this system has a cited basis for. So
the result has no `apply_kg` field and no product recommendation; that is inexpressible
here for the same reason `disease_risk.RiskAssessment` has no product field.

The distinction matters commercially as well as technically: removal is a fact about the
crop, and an application rate is advice about a regulated input. Lumos supplies the first
so a human can make the second.

**All-or-nothing, unlike `soil.interpret`.** A budget missing one nutrient's rate is not
a smaller budget, it is a *wrong* one — the reader sees a total and assumes it covers
what was asked. So a single missing rate refuses the whole budget, matching
`pest.active_ingredient_kg_per_ha` and `pilot_evidence._ai_quantity_avoided`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app import nutrient_tables
from app.refusal import NO_DATA_FOR_FARM, NO_SOURCE_TRANSCRIBED, OUTSIDE_SOURCE_SCOPE, Refusal

MODEL_VERSION = "nutrient_removal_v1"


@dataclass(frozen=True)
class NutrientRemoval:
    """One nutrient's expected removal, with the citation that backs the rate."""

    nutrient: str
    kg_removed: float
    rate_used_kg_per_tonne: float
    yield_basis: str
    source_document: str

    def as_payload(self) -> dict:
        return {
            "nutrient": self.nutrient,
            "kg_removed": round(self.kg_removed, 2),
            "rate_used_kg_per_tonne": self.rate_used_kg_per_tonne,
            "yield_basis": self.yield_basis,
            "source_document": self.source_document,
        }


@dataclass(frozen=True)
class NutrientBudget:
    """Expected removal for a crop cycle. Never an application recommendation."""

    crop: str
    expected_yield_tonnes: float
    model_version: str = MODEL_VERSION
    removals: tuple[NutrientRemoval, ...] = field(default_factory=tuple)

    def as_payload(self) -> dict:
        return {
            "model_version": self.model_version,
            "crop": self.crop,
            "expected_yield_tonnes": self.expected_yield_tonnes,
            "removals": [r.as_payload() for r in self.removals],
            # Named rather than merely absent: a reader who expects an application rate
            # should learn why there isn't one, not conclude the field was forgotten.
            "not_calculated": {
                "application_rate": (
                    "Removal is not an application rate. Converting one to the other "
                    "needs soil supply, use efficiency, irrigation water content and "
                    "split timing — agronomist judgments this system has no cited "
                    "basis for. Removal is reported so a human can make that call."
                ),
            },
        }


def _rate_for(nutrient: str, crop: str, variety: str | None):
    """The transcribed rate for this nutrient/crop, preferring an exact variety match.

    A variety-specific rate wins over the crop-general one; a rate for a *different*
    named variety is never used, because "close enough variety" is precisely the fuzzy
    agronomic matching `target_aliases` and `crop_aliases` exist to forbid.
    """
    crop_key = crop.strip().lower()
    candidates = [
        r for r in nutrient_tables.TRANSCRIBED
        if r.nutrient == nutrient and r.crop.strip().lower() == crop_key
    ]
    if variety:
        variety_key = variety.strip().lower()
        exact = [
            r for r in candidates
            if r.variety and r.variety.strip().lower() == variety_key
        ]
        if exact:
            return exact[0]
    general = [r for r in candidates if not r.variety]
    return general[0] if general else None


def budget(*, crop: str, expected_yield_tonnes: float | None, nutrients,
           variety: str | None = None):
    """Expected nutrient removal for a crop cycle. Returns NutrientBudget | Refusal."""
    if not nutrient_tables.TRANSCRIBED:
        return Refusal(
            NO_SOURCE_TRANSCRIBED,
            "No crop nutrient removal rates have been transcribed, so removal cannot be "
            "computed. Transcribe the guide the farm's agronomist uses — see "
            "app/nutrient_tables.py.",
            {"model_version": MODEL_VERSION},
        )
    if expected_yield_tonnes is None:
        return Refusal(
            NO_DATA_FOR_FARM,
            "No expected yield recorded for this crop cycle. Removal scales with yield, "
            "so without it there is no quantity to compute — and assuming a default "
            "yield would silently invent the answer.",
            {"crop": crop},
        )
    if expected_yield_tonnes <= 0:
        return Refusal(
            NO_DATA_FOR_FARM,
            "Expected yield must be positive to compute removal.",
            {"crop": crop, "expected_yield_tonnes": expected_yield_tonnes},
        )

    requested = tuple(nutrients or ())
    if not requested:
        return Refusal(
            NO_DATA_FOR_FARM,
            "No nutrients requested for the budget.",
            {"crop": crop},
        )

    removals = []
    missing = []
    for nutrient in requested:
        rate = _rate_for(nutrient, crop, variety)
        if rate is None:
            missing.append(nutrient)
            continue
        removals.append(NutrientRemoval(
            nutrient=nutrient,
            kg_removed=rate.kg_removed_per_tonne_yield * expected_yield_tonnes,
            rate_used_kg_per_tonne=rate.kg_removed_per_tonne_yield,
            yield_basis=rate.yield_basis,
            source_document=rate.citation.document,
        ))

    if missing:
        # All-or-nothing. See the module docstring: a partial budget reads as complete.
        return Refusal(
            OUTSIDE_SOURCE_SCOPE,
            "No transcribed removal rate covers "
            f"{', '.join(sorted(missing))} for {crop}"
            f"{f' ({variety})' if variety else ''}. The whole budget is withheld rather "
            "than reported partially: a budget missing a nutrient still reads as a "
            "complete answer to the question that was asked.",
            {"crop": crop, "missing_nutrients": sorted(missing)},
        )

    return NutrientBudget(
        crop=crop,
        expected_yield_tonnes=expected_yield_tonnes,
        removals=tuple(removals),
    )
