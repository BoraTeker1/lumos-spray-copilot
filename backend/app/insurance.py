"""Insurance coverage matching (pure, framework-free).

Reports whether a farm's situation and records match a transcribed product's stated
terms, or refuses. **It never prices a policy.**

The genuinely useful thing here — and the reason this is worth building on this
substrate rather than being a form — is the evidence check. A crop insurance claim
requires records: application dates, scouting observations, weather at the loss event,
harvest outcomes. Growers assemble those by hand at claim time, under time pressure,
months after the fact, and discover then that something was never recorded. This system
already holds append-only, dated, point-in-time-correct versions of exactly those
records. Telling a grower *today* which required evidence they are missing is worth
more than any premium estimate would be.

**Why there is no premium.** Pricing a policy from a farm's yield and weather history is
underwriting wearing a different word — the same act of assessing one person's risk and
attaching a number to it, with the same consequences for getting it wrong from invented
inputs. `insurance_products.CoverageProduct` therefore carries no rate, and
`CoverageAssessment` has no premium field to put one in.

**A missing evidence record is reported, never assumed present.** The asymmetry: telling
someone they are covered when their evidence is incomplete is the failure that surfaces
at claim time, when it is far too late to fix.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app import insurance_products
from app.refusal import NO_SOURCE_TRANSCRIBED, OUTSIDE_SOURCE_SCOPE, Refusal

MODEL_VERSION = "coverage_match_v1"

NO_PRODUCTS_SUPPLIED = NO_SOURCE_TRANSCRIBED


@dataclass(frozen=True)
class ProductMatch:
    """One product's fit against a farm's crop, peril and records."""

    product_code: str
    insurer: str
    crop_eligible: bool
    peril_covered: bool
    coverage_basis: str
    present_evidence: tuple[str, ...] = field(default_factory=tuple)
    missing_evidence: tuple[str, ...] = field(default_factory=tuple)
    exclusions: tuple[str, ...] = field(default_factory=tuple)

    @property
    def evidence_complete(self) -> bool:
        return not self.missing_evidence

    @property
    def terms_match(self) -> bool:
        """Crop and peril fit. Deliberately separate from evidence completeness."""
        return self.crop_eligible and self.peril_covered

    def as_payload(self) -> dict:
        return {
            "product_code": self.product_code,
            "insurer": self.insurer,
            "crop_eligible": self.crop_eligible,
            "peril_covered": self.peril_covered,
            "terms_match": self.terms_match,
            "coverage_basis": self.coverage_basis,
            "evidence_complete": self.evidence_complete,
            "present_evidence": list(self.present_evidence),
            "missing_evidence": list(self.missing_evidence),
            "exclusions_to_review": list(self.exclusions),
        }


@dataclass(frozen=True)
class CoverageAssessment:
    """Which transcribed products match, and what evidence is missing. Never a price."""

    crop: str
    peril: str
    model_version: str = MODEL_VERSION
    matches: tuple[ProductMatch, ...] = field(default_factory=tuple)

    def as_payload(self) -> dict:
        return {
            "model_version": self.model_version,
            "crop": self.crop,
            "peril": self.peril,
            "products": [m.as_payload() for m in self.matches],
            "not_calculated": {
                "premium": (
                    "No premium is estimated. Pricing a policy from yield and weather "
                    "history is underwriting wearing a different word; coverage terms "
                    "are matched here, never priced. The insurer quotes."
                ),
                "coverage_decision": (
                    "Matching a product's stated terms is not a binding of cover and "
                    "not a claim determination. Only the insurer decides either."
                ),
            },
        }


def assess_coverage(*, crop: str, peril: str, available_evidence=()):
    """Match transcribed products against a farm. Returns CoverageAssessment | Refusal."""
    if not insurance_products.TRANSCRIBED:
        return Refusal(
            NO_PRODUCTS_SUPPLIED,
            "No insurance product terms have been transcribed, so coverage cannot be "
            "matched. Transcribe the insurer's published product terms — see "
            "app/insurance_products.py.",
            {"model_version": MODEL_VERSION},
        )

    crop_key = crop.strip().lower()
    peril_key = peril.strip().lower()
    available = {str(e).strip().lower() for e in (available_evidence or ())}

    matches = []
    for product in insurance_products.TRANSCRIBED:
        crop_eligible = crop_key in {c.strip().lower() for c in product.eligible_crops}
        peril_covered = peril_key in {p.strip().lower() for p in product.perils}
        if not (crop_eligible or peril_covered):
            continue  # wholly unrelated product; not worth reporting

        required = [str(e) for e in product.required_evidence]
        present = tuple(e for e in required if e.strip().lower() in available)
        missing = tuple(e for e in required if e.strip().lower() not in available)

        matches.append(ProductMatch(
            product_code=product.product_code, insurer=product.insurer,
            crop_eligible=crop_eligible, peril_covered=peril_covered,
            coverage_basis=product.coverage_basis,
            present_evidence=present, missing_evidence=missing,
            exclusions=tuple(product.exclusions),
        ))

    if not matches:
        return Refusal(
            OUTSIDE_SOURCE_SCOPE,
            f"No transcribed product relates to {peril} on {crop}.",
            {"crop": crop, "peril": peril},
        )

    return CoverageAssessment(crop=crop, peril=peril, matches=tuple(matches))
