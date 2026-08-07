"""Soil interpretation thresholds — EMPTY until a regional guide is transcribed.

A soil test returns numbers: pH 6.2, organic matter 2.1%, Bray-P 18 ppm. Turning those
into "low / adequate / high" requires an interpretation table, and **interpretation tables
are regional and crop-specific in a way that is easy to miss**. 18 ppm phosphorus is
adequate for one crop on one soil series under one extraction method and deficient for
another; the number alone does not carry that context, and neither does a plausible
threshold someone half-remembers.

Worse, the extraction method is part of the answer. Bray-P and Olsen-P are different
assays producing different numbers for the same soil, and a threshold transcribed from a
Bray guide applied to an Olsen result is wrong in a direction nobody can see from the
output. `SoilThreshold.method` exists so that mistake cannot be made silently.

`soil.interpret()` reads this table; while it is empty it returns
`Refusal(NO_SOURCE_TRANSCRIBED)` and no soil interpretation exists anywhere in the system.

**What fills it:** the extension guide the grower's own lab or advisor already uses —
e.g. a UC ANR publication for California, a state extension bulletin elsewhere. The
grower's agronomist almost certainly names one; transcribe that one rather than picking.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.transcription import Citation

PRIMARY_SOURCE = (
    "The regional extension interpretation guide the grower's lab or advisor already "
    "uses (e.g. a UC ANR publication for California specialty crops): analyte, "
    "extraction method, crop, and the class boundaries it publishes. Transcribe the "
    "guide the farm already works to — not a different region's, and not an average."
)

# Analytes this system can describe. Each still needs its own transcribed thresholds
# before it can be interpreted for any crop.
ANALYTES = (
    "ph",
    "organic_matter_pct",
    "phosphorus_ppm",
    "potassium_ppm",
    "nitrate_n_ppm",
    "electrical_conductivity_ds_m",
    "cation_exchange_capacity_meq_100g",
)

# Interpretation classes, low to high. Deliberately not a 1-5 score: a score invites
# averaging across analytes, and "average soil fertility 3.2" is a number with no
# agronomic meaning that would nonetheless get put on a dashboard.
CLASSES = ("very_low", "low", "adequate", "high", "excessive")


@dataclass(frozen=True, kw_only=True)
class SoilThreshold:
    """One class boundary, for one analyte, one extraction method, one crop.

    Bounds are half-open [lower, upper) for the same reason as the scorecard bands: an
    overlap is a silent disagreement about a boundary value, not a visible error.
    """

    analyte: str
    method: str
    crop: str
    soil_class: str
    lower_inclusive: float | None
    upper_exclusive: float | None
    citation: Citation

    def __post_init__(self) -> None:
        if self.analyte not in ANALYTES:
            raise ValueError(
                f"unknown analyte {self.analyte!r}; declared analytes are {ANALYTES}"
            )
        if self.soil_class not in CLASSES:
            raise ValueError(
                f"{self.analyte}: unknown class {self.soil_class!r}; expected {CLASSES}"
            )
        if not self.method.strip():
            raise ValueError(
                f"{self.analyte}: extraction method is blank. Bray-P and Olsen-P are "
                "different assays with different thresholds; a threshold without its "
                "method cannot be safely applied to a lab result."
            )
        if not self.crop.strip():
            raise ValueError(
                f"{self.analyte}: crop is blank. Interpretation classes are crop-"
                "specific, and an unlabelled threshold will be applied to all of them."
            )
        if (
            self.lower_inclusive is not None
            and self.upper_exclusive is not None
            and self.lower_inclusive >= self.upper_exclusive
        ):
            raise ValueError(
                f"{self.analyte} {self.soil_class}: band "
                f"[{self.lower_inclusive}, {self.upper_exclusive}) is empty or inverted"
            )

    def contains(self, value: float) -> bool:
        if self.lower_inclusive is not None and value < self.lower_inclusive:
            return False
        if self.upper_exclusive is not None and value >= self.upper_exclusive:
            return False
        return True


# EMPTY. See the module docstring.
TRANSCRIBED: tuple[SoilThreshold, ...] = ()
