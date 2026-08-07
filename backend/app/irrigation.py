"""Crop water balance (pure, framework-free).

Computes crop evapotranspiration from measured reference ET and a transcribed crop
coefficient, and reports the balance against recorded rainfall and applied irrigation —
or refuses and says why.

    ETc = ETo × Kc(growth stage)
    deficit = ETc − effective rainfall − applied irrigation

**What this does not do: tell anyone how much to irrigate.** The deficit is a
description of what the crop used versus what it received. Turning that into an
irrigation instruction requires soil water-holding capacity, allowable depletion,
system efficiency and application uniformity — none of which this system has a cited
basis for, and the last two of which are properties of hardware §4 still excludes. So
`WaterBalance` has no `apply_mm` field, matching `fertilization.NutrientBudget`'s refusal
to convert removal into an application rate.

**Two abstentions worth keeping distinct**, because they send the reader to different
places: a missing Kc is an operator's transcription task, while missing ETo observations
are a data-feed gap the grower or the CIMIS credential fixes. `Refusal.code` carries the
difference; the prose explains it.

Effective rainfall, not total rainfall: runoff and deep percolation mean not all rain
reaches the root zone. There is no cited basis here for an effectiveness fraction, so
this module takes effective rainfall as an *input* the caller supplies, and refuses to
derive one from total rainfall. Defaulting that fraction to 1.0 would silently overstate
what the crop received and understate the deficit — an error in the direction that
under-irrigates.
"""
from __future__ import annotations

from dataclasses import dataclass

from app import irrigation_coefficients
from app.refusal import NO_DATA_FOR_FARM, NO_SOURCE_TRANSCRIBED, OUTSIDE_SOURCE_SCOPE, Refusal

MODEL_VERSION = "water_balance_v1"


@dataclass(frozen=True)
class WaterBalance:
    """Crop water use against what was received, over one window."""

    crop: str
    growth_stage: str
    days_after_planting: int
    eto_mm: float
    kc_used: float
    etc_mm: float
    effective_rainfall_mm: float
    applied_irrigation_mm: float
    model_version: str = MODEL_VERSION

    @property
    def deficit_mm(self) -> float:
        """Positive means the crop used more than it received over this window."""
        return self.etc_mm - self.effective_rainfall_mm - self.applied_irrigation_mm

    def as_payload(self) -> dict:
        return {
            "model_version": self.model_version,
            "crop": self.crop,
            "growth_stage": self.growth_stage,
            "days_after_planting": self.days_after_planting,
            "eto_mm": round(self.eto_mm, 2),
            "kc_used": self.kc_used,
            "etc_mm": round(self.etc_mm, 2),
            "effective_rainfall_mm": round(self.effective_rainfall_mm, 2),
            "applied_irrigation_mm": round(self.applied_irrigation_mm, 2),
            "deficit_mm": round(self.deficit_mm, 2),
            "not_calculated": {
                "irrigation_recommendation": (
                    "A deficit is not an instruction. Converting one into an irrigation "
                    "amount needs soil water-holding capacity, allowable depletion, and "
                    "system efficiency and uniformity — none of which this system has a "
                    "cited basis for."
                ),
            },
        }


def coefficient_for(*, crop: str, days_after_planting: int):
    """The Kc covering this day. Returns CropCoefficient | Refusal."""
    if not irrigation_coefficients.TRANSCRIBED:
        return Refusal(
            NO_SOURCE_TRANSCRIBED,
            "No crop coefficients have been transcribed, so measured ETo cannot be "
            "turned into crop water use. Transcribe a published Kc curve — see "
            "app/irrigation_coefficients.py.",
            {"model_version": MODEL_VERSION},
        )

    crop_key = crop.strip().lower()
    match = next(
        (
            c for c in irrigation_coefficients.TRANSCRIBED
            if c.crop.strip().lower() == crop_key and c.covers(days_after_planting)
        ),
        None,
    )
    if match is None:
        return Refusal(
            OUTSIDE_SOURCE_SCOPE,
            f"No transcribed crop coefficient covers day {days_after_planting} after "
            f"planting for {crop}. Kc varies through the season by a factor of two or "
            "more, so the nearest stage's value is not a safe substitute.",
            {"crop": crop, "days_after_planting": days_after_planting},
        )
    return match


def balance(*, crop: str, days_after_planting: int, eto_mm: float | None,
            effective_rainfall_mm: float | None, applied_irrigation_mm: float | None):
    """Water balance over one window. Returns WaterBalance | Refusal.

    Every input is required. None of them defaults to zero: a missing rainfall figure
    defaulted to zero overstates the deficit, and a missing irrigation figure does the
    same — both in the direction that would recommend more water than the crop needs.
    """
    coefficient = coefficient_for(crop=crop, days_after_planting=days_after_planting)
    if isinstance(coefficient, Refusal):
        return coefficient

    missing = [
        name for name, value in (
            ("eto_mm", eto_mm),
            ("effective_rainfall_mm", effective_rainfall_mm),
            ("applied_irrigation_mm", applied_irrigation_mm),
        )
        if value is None
    ]
    if missing:
        return Refusal(
            NO_DATA_FOR_FARM,
            f"Missing {', '.join(missing)} for this window. None of these defaults to "
            "zero: a missing rainfall or irrigation figure treated as zero overstates "
            "the deficit, which errs toward applying water the crop did not need.",
            {"crop": crop, "missing": missing},
        )
    if eto_mm < 0 or effective_rainfall_mm < 0 or applied_irrigation_mm < 0:
        return Refusal(
            NO_DATA_FOR_FARM,
            "Water balance inputs cannot be negative.",
            {"crop": crop},
        )

    return WaterBalance(
        crop=crop,
        growth_stage=coefficient.growth_stage,
        days_after_planting=days_after_planting,
        eto_mm=eto_mm,
        kc_used=coefficient.kc,
        etc_mm=eto_mm * coefficient.kc,
        effective_rainfall_mm=effective_rainfall_mm,
        applied_irrigation_mm=applied_irrigation_mm,
    )
