"""Soil test interpretation (pure, framework-free).

Turns a lab result into a class — "adequate", "low" — against thresholds transcribed
from a regional extension guide, or refuses and says why. Never invents a threshold, and
never averages across analytes into a single "soil score".

The one behaviour worth stating up front, because it is the opposite of what a
convenience-minded reader would add: **an analyte with no transcribed threshold is
reported as un-interpreted, and it does not stop the other analytes from being
interpreted.** This is a deliberate departure from the all-or-nothing rule used in
`pest.active_ingredient_kg_per_ha` and `credit_scoring.score`, and the difference is the
direction of the error:

* A partial *credit score* is a smaller number that reads as a worse borrower. Bias.
* A partial *soil panel* is fewer answered questions, each still correct on its own.
  Nothing is understated, because nothing is summed.

So this module returns per-analyte results with the un-interpreted ones named. The place
that must stay all-or-nothing is any figure that aggregates them — which is why there is
no such figure here.

Mirrors `disease_risk.assess`: the result carries no action field, so "apply lime" or
"add nitrogen" is inexpressible rather than merely discouraged. Soil interpretation
informs a human's fertilization decision; it does not make one.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app import soil_thresholds
from app.refusal import NO_DATA_FOR_FARM, NO_SOURCE_TRANSCRIBED, OUTSIDE_SOURCE_SCOPE, Refusal

MODEL_VERSION = "soil_interpretation_v1"


@dataclass(frozen=True)
class AnalyteReading:
    """One measured value from a lab report."""

    analyte: str
    value: float
    method: str


@dataclass(frozen=True)
class AnalyteInterpretation:
    """One analyte's class, or the reason it has none."""

    analyte: str
    value: float
    method: str
    soil_class: str | None = None
    refusal: Refusal | None = None

    @property
    def interpreted(self) -> bool:
        return self.soil_class is not None

    def as_payload(self) -> dict:
        payload = {
            "analyte": self.analyte,
            "value": self.value,
            "method": self.method,
            "interpreted": self.interpreted,
        }
        if self.soil_class is not None:
            payload["soil_class"] = self.soil_class
        if self.refusal is not None:
            payload["refusal"] = self.refusal.as_payload()
        return payload


@dataclass(frozen=True)
class SoilAssessment:
    """Per-analyte interpretations for one soil test. Deliberately not a score."""

    crop: str
    model_version: str = MODEL_VERSION
    analytes: tuple[AnalyteInterpretation, ...] = field(default_factory=tuple)

    @property
    def interpreted_count(self) -> int:
        return sum(1 for a in self.analytes if a.interpreted)

    def as_payload(self) -> dict:
        return {
            "model_version": self.model_version,
            "crop": self.crop,
            "analytes": [a.as_payload() for a in self.analytes],
            "interpreted_count": self.interpreted_count,
            "total_count": len(self.analytes),
            # No aggregate class, no score, no index. See the module docstring: any
            # figure that sums across analytes would have to be all-or-nothing, and
            # there is no agronomically meaningful one to compute.
        }


def _matching(analyte: str, method: str, crop: str) -> list:
    """Thresholds for exactly this analyte + method + crop. Never a near-match.

    Matching is exact on all three by design, following `target_aliases` and
    `crop_aliases`: a partial match here would apply one crop's thresholds to another,
    which is precisely the error this module exists to prevent.
    """
    return [
        t for t in soil_thresholds.TRANSCRIBED
        if t.analyte == analyte
        and t.method.strip().lower() == method.strip().lower()
        and t.crop.strip().lower() == crop.strip().lower()
    ]


def interpret(readings, *, crop: str):
    """Interpret a soil test. Returns SoilAssessment | Refusal.

    Refuses outright only when there is nothing to work with at all — no thresholds
    anywhere, or no readings. A per-analyte gap is reported per analyte, not escalated.
    """
    if not soil_thresholds.TRANSCRIBED:
        return Refusal(
            NO_SOURCE_TRANSCRIBED,
            "No soil interpretation thresholds have been transcribed, so a lab result "
            "cannot be classified. Transcribe the extension guide the farm's own lab or "
            "advisor uses — see app/soil_thresholds.py.",
            {"model_version": MODEL_VERSION},
        )
    readings = list(readings or [])
    if not readings:
        return Refusal(
            NO_DATA_FOR_FARM,
            "No soil test readings recorded for this field. A soil test is a document "
            "the grower uploads or an operator transcribes; nothing computes it.",
            {"crop": crop},
        )

    interpretations = []
    for reading in readings:
        candidates = _matching(reading.analyte, reading.method, crop)
        if not candidates:
            interpretations.append(AnalyteInterpretation(
                analyte=reading.analyte, value=reading.value, method=reading.method,
                refusal=Refusal(
                    OUTSIDE_SOURCE_SCOPE,
                    f"No transcribed threshold covers {reading.analyte} by "
                    f"{reading.method} for {crop}. Thresholds are specific to the "
                    "extraction method and the crop; applying another one's would be "
                    "wrong in a direction the output would not show.",
                    {"analyte": reading.analyte, "method": reading.method, "crop": crop},
                ),
            ))
            continue

        band = next((t for t in candidates if t.contains(reading.value)), None)
        if band is None:
            # The transcribed table has bands for this analyte but none containing this
            # value — a gap in the guide, or a reading outside its published range.
            # Extrapolating past the end of a table is exactly what
            # `disease_risk.ABSTAIN_TEMPERATURE_OUTSIDE_TABLE` refuses to do.
            interpretations.append(AnalyteInterpretation(
                analyte=reading.analyte, value=reading.value, method=reading.method,
                refusal=Refusal(
                    OUTSIDE_SOURCE_SCOPE,
                    f"{reading.value} is outside every transcribed band for "
                    f"{reading.analyte} ({reading.method}, {crop}). Reading past the "
                    "end of a table is extrapolation, not lookup.",
                    {"analyte": reading.analyte, "value": reading.value},
                ),
            ))
            continue

        interpretations.append(AnalyteInterpretation(
            analyte=reading.analyte, value=reading.value, method=reading.method,
            soil_class=band.soil_class,
        ))

    return SoilAssessment(crop=crop, analytes=tuple(interpretations))
