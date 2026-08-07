"""Insurance coverage products — EMPTY until an insurer's product terms are transcribed.

`insurance.assess_coverage()` reads this table; while it is empty it returns a `Refusal`
naming `NO_PRODUCTS_SUPPLIED`.

**Note what this module does not have: a premium rate.** That is deliberate and it is
structural, not an oversight to be filled in later. Pricing a policy from yield and
weather history is underwriting wearing a different word — it is the same act of
assessing a specific person's risk and attaching a number to it, and the same reasons
apply. `CoverageAssessment` therefore reports whether a farm's situation *matches a
product's stated coverage terms*, and says so; it never estimates what that coverage
would cost. A grower who wants a price gets one from the insurer.

The useful, honest thing this layer does: a farm has continuous operational records — a
spray history with dates, scouting samples, weather observations, harvest outcomes.
Whether those records satisfy a policy's evidence requirements is a real question with a
checkable answer, and it is a question growers currently answer by hand at claim time,
badly, under time pressure. That is the product here.

**What fills it:** the insurer's published product terms — perils covered, eligible
crops, the coverage basis, and the evidence a claim requires.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.transcription import Citation

PRIMARY_SOURCE = (
    "The insurer's published product terms or policy wording: perils covered, eligible "
    "crops and regions, coverage basis, exclusions, and the evidence a claim requires. "
    "Premium rates are deliberately NOT transcribed — this layer never prices a policy."
)


@dataclass(frozen=True, kw_only=True)
class CoverageProduct:
    """One insurance product's stated terms. No price, by design."""

    product_code: str
    insurer: str
    perils: tuple[str, ...]
    eligible_crops: tuple[str, ...]
    coverage_basis: str
    required_evidence: tuple[str, ...]
    citation: Citation
    exclusions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.product_code.strip():
            raise ValueError("CoverageProduct.product_code is blank")
        if not self.perils:
            raise ValueError(
                f"{self.product_code}: a product covering no named peril cannot be "
                "matched against a farm's situation"
            )
        if not self.eligible_crops:
            raise ValueError(
                f"{self.product_code}: eligible_crops is empty. An empty list reads as "
                "'all crops', which is the opposite of what silence means here."
            )
        if not self.coverage_basis.strip():
            raise ValueError(f"{self.product_code}: coverage_basis is blank")


# EMPTY. See the module docstring.
TRANSCRIBED: tuple[CoverageProduct, ...] = ()
