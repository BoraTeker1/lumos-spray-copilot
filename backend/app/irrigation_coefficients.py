"""Crop coefficients (Kc) — EMPTY until a published Kc curve is transcribed.

This is the one admitted domain with a live upstream data path already built. CIMIS
publishes reference evapotranspiration (ETo) hourly and the adapter in
`app/ingest/cimis.py` can already fetch it. What turns ETo into crop water use is the
crop coefficient:

    ETc = ETo × Kc(growth stage)

ETo is measured and arrives over a wire. **Kc is published, stage-dependent, and must be
transcribed.** The distinction matters because it would be very easy to ship a single
default Kc and produce a plausible water balance for every farm on day one — the numbers
would look right, the units would be right, and the answer would be wrong by whatever the
real curve says at that growth stage.

Kc varies through the season by a factor of two or more between establishment and peak
canopy, so a mid-season value applied at establishment overstates water use substantially.
`irrigation.balance()` therefore requires a coefficient whose stage range covers the date
being asked about, and refuses otherwise rather than reaching for the nearest one.

**What fills it:** FAO-56, a UC ANR crop coefficient publication, or the regional guide
the farm's irrigation advisor already uses.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.transcription import Citation

PRIMARY_SOURCE = (
    "A published crop coefficient curve for the crop and region — FAO Irrigation and "
    "Drainage Paper 56, a UC ANR crop coefficient publication, or the regional guide "
    "the farm's irrigation advisor uses: growth stage, days after planting range, and "
    "the Kc value for that stage."
)


@dataclass(frozen=True, kw_only=True)
class CropCoefficient:
    """Kc for one crop at one growth stage, bounded by days after planting.

    Bounds are inclusive-exclusive on days after planting so consecutive stages cannot
    both claim a boundary day.
    """

    crop: str
    growth_stage: str
    days_after_planting_from: int
    days_after_planting_to: int
    kc: float
    citation: Citation

    def __post_init__(self) -> None:
        if not self.crop.strip():
            raise ValueError("CropCoefficient.crop is blank")
        if not self.growth_stage.strip():
            raise ValueError(f"{self.crop}: growth_stage is blank")
        if self.days_after_planting_from < 0:
            raise ValueError(f"{self.crop}/{self.growth_stage}: stage start is negative")
        if self.days_after_planting_to <= self.days_after_planting_from:
            raise ValueError(
                f"{self.crop}/{self.growth_stage}: stage range "
                f"[{self.days_after_planting_from}, {self.days_after_planting_to}) is "
                "empty or inverted"
            )
        if not 0 < self.kc <= 2.0:
            raise ValueError(
                f"{self.crop}/{self.growth_stage}: Kc of {self.kc} is outside the "
                "physically plausible range (0, 2.0]. Published Kc values sit roughly "
                "between 0.15 and 1.25; a value outside this is a transcription slip."
            )

    def covers(self, days_after_planting: int) -> bool:
        return (
            self.days_after_planting_from
            <= days_after_planting
            < self.days_after_planting_to
        )


# EMPTY. See the module docstring.
TRANSCRIBED: tuple[CropCoefficient, ...] = ()
