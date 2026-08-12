"""Crop nutrient removal rates — EMPTY until a published guide is transcribed.

A nutrient budget is arithmetic: what the crop removes, minus what the soil supplies,
is roughly what must be applied. The arithmetic is easy. The **removal rate** — kg of
nitrogen removed per tonne of fruit harvested — is the part that must come from a
published trial, and it is exactly the number a hurried developer would fill in from
memory because it "sounds about right".

Three reasons a remembered rate is worse here than it looks:

* Rates vary by crop *and* variety *and* yield level, and the variation is large enough
  to change a recommendation, not just refine it.
* Over-application is an environmental and regulatory event in California, not merely a
  wasted input — nitrate loading is regulated, and a farm acting on a fabricated rate
  would be generating real compliance exposure from a made-up number.
* Nothing downstream can detect the error. A wrong rate produces a plausible budget, and
  the feedback loop (a soil test months later) is far too slow and too noisy to attribute.

`fertilization.budget()` reads this table; while it is empty it returns
`Refusal(NO_SOURCE_TRANSCRIBED)`.

**What fills it:** the published removal figures the farm's own agronomist works to —
a UC ANR or equivalent extension publication, or the crop nutrition guide their lab
issues with soil reports.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.transcription import Citation

PRIMARY_SOURCE = (
    "A published crop nutrient removal guide for the crop and region (e.g. a UC ANR "
    "publication for California strawberries): nutrient, crop, and removal per unit of "
    "harvested yield, with the yield basis the figure assumes. Transcribe the guide the "
    "farm's agronomist already uses."
)

# Nutrients this system can budget. Each needs its own transcribed rate per crop.
NUTRIENTS = ("nitrogen", "phosphorus", "potassium", "calcium", "magnesium", "sulfur")


@dataclass(frozen=True, kw_only=True)
class RemovalRate:
    """How much of one nutrient a crop removes per unit of harvested yield."""

    nutrient: str
    crop: str
    kg_removed_per_tonne_yield: float
    yield_basis: str
    citation: Citation
    variety: str | None = None

    def __post_init__(self) -> None:
        if self.nutrient not in NUTRIENTS:
            raise ValueError(
                f"unknown nutrient {self.nutrient!r}; declared nutrients are {NUTRIENTS}"
            )
        if not self.crop.strip():
            raise ValueError(f"{self.nutrient}: crop is blank")
        if self.kg_removed_per_tonne_yield <= 0:
            raise ValueError(
                f"{self.nutrient}/{self.crop}: removal must be positive; a zero rate "
                "would silently budget nothing for this nutrient, which reads as "
                "'none needed' rather than 'not known'."
            )
        if not self.yield_basis.strip():
            raise ValueError(
                f"{self.nutrient}/{self.crop}: yield_basis is blank. Removal per tonne "
                "of FRESH fruit and per tonne of DRY matter differ by roughly an order "
                "of magnitude; the basis is part of the number."
            )


# EMPTY. See the module docstring.
TRANSCRIBED: tuple[RemovalRate, ...] = ()
