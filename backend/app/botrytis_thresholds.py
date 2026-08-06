"""Manually transcribed Botrytis infection thresholds. THE TABLE IS EMPTY.

Sibling of `app/label_table.py`, and empty for the same reason stated in
`BOTRYTIS_PILOT.md` §3: every test that can be written about a threshold rule checks the
arithmetic *against* the coefficients, never the coefficients themselves. A plausible
cut point recalled from memory or lifted from a search result would pass the entire
suite and then sit in a versioned, cited module that a licensed PCA is entitled to
trust. So the numbers are transcribed from the primary source — author, year,
publication, and the source's OWN stated crop, region and validation conditions,
verbatim — or `disease_risk.botrytis_wetness_v1` keeps abstaining with
`thresholds_not_supplied`.

Why a Python module rather than a data file or a seeded table:
  * A change arrives as a reviewed diff, not an UPDATE from whoever had DB access.
  * `BotrytisThresholdTable` is frozen and keyword-only with no defaults, so a table
    missing its citation raises at import. The check is construction, not validation.

## If the source's table is not shaped like `ThresholdRow`

**Change this dataclass to match the source. Do not reshape the source to match this
file.** The shape below (temperature band → leaf-wetness hours required to reach a
band) is the common form for wetness-duration infection models, but it is a guess about
a document nobody here has read. Reshaping a published table to fit a convenient struct
is a transcription error that no test can see. If the source keys on something else —
relative humidity, a spore-germination index, cumulative degree-wetness — encode that
instead and update `BotrytisWetnessV1.evaluate` to match.

## What stays true even after it is filled

`local_validation_status` still reports the rule is NOT validated for California Central
Coast strawberries (the known strawberry Botrytis advisory work is Florida-based), and
`calibration_status` stays `not_calibrated` until prospective outcomes exist. Supplying
coefficients raises the rule from "cannot speak" to "speaks, uncalibrated, out of its
validated region". It does not make it right.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class ThresholdRow:
    """One temperature band and the leaf-wetness duration it takes to reach a band.

    Half-open on the upper bound (`temperature_c_min <= t < temperature_c_max`) so
    adjacent rows transcribed from a table cannot silently overlap at their shared edge.
    """

    temperature_c_min: float
    temperature_c_max: float
    # Hours of leaf wetness at which this temperature band reaches each risk level.
    # `high` must be >= `moderate`; a source stating only one of them leaves the other
    # None, and `evaluate` then simply cannot reach that band.
    wetness_hours_moderate: float | None = None
    wetness_hours_high: float | None = None

    def __post_init__(self) -> None:
        if self.temperature_c_max <= self.temperature_c_min:
            raise ValueError(
                "ThresholdRow.temperature_c_max must exceed temperature_c_min"
            )
        if self.wetness_hours_moderate is None and self.wetness_hours_high is None:
            raise ValueError(
                "a ThresholdRow stating neither a moderate nor a high wetness "
                "threshold cannot move the band — omit the row instead"
            )
        both = (self.wetness_hours_moderate, self.wetness_hours_high)
        if all(v is not None for v in both) and self.wetness_hours_high < self.wetness_hours_moderate:
            raise ValueError(
                "wetness_hours_high must not be below wetness_hours_moderate — check "
                "the transcription against the source table"
            )

    def contains(self, temperature_c: float) -> bool:
        return self.temperature_c_min <= temperature_c < self.temperature_c_max


@dataclass(frozen=True, kw_only=True)
class BotrytisThresholdTable:
    """A transcribed threshold table plus everything needed to read it honestly.

    No field has a default. Omitting the citation or the source's own validation scope
    is a TypeError at import, not a None that flows into a PCA-facing assessment.
    """

    rows: tuple[ThresholdRow, ...]

    # ------------------------------------------------------------------ provenance
    citation: str
    source_crop: str
    source_region: str
    source_validation_conditions: str
    source_document_reference: str
    source_section_or_page: str
    source_snippet: str
    transcribed_by: str

    def __post_init__(self) -> None:
        if not self.rows:
            raise ValueError(
                "a BotrytisThresholdTable with no rows is an empty table wearing a "
                "citation — leave TRANSCRIBED_TABLE as None instead"
            )
        for name in (
            "citation", "source_crop", "source_region",
            "source_validation_conditions", "source_document_reference",
            "source_section_or_page", "source_snippet", "transcribed_by",
        ):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(f"BotrytisThresholdTable.{name} must not be blank")

        ordered = sorted(self.rows, key=lambda r: r.temperature_c_min)
        for earlier, later in zip(ordered, ordered[1:]):
            if later.temperature_c_min < earlier.temperature_c_max:
                raise ValueError(
                    "transcribed temperature bands overlap "
                    f"({earlier.temperature_c_min}-{earlier.temperature_c_max} and "
                    f"{later.temperature_c_min}-{later.temperature_c_max}) — a "
                    "temperature matching two rows makes the band order-dependent"
                )

    def row_for(self, temperature_c: float) -> ThresholdRow | None:
        """The band containing this temperature, or None when the table is silent.

        Silence is not "no risk". `evaluate` treats a missing row as an inability to
        assess, never as a low band.
        """
        for row in self.rows:
            if row.contains(temperature_c):
                return row
        return None


# ---------------------------------------------------------------------------------
# EMPTY BY DESIGN. Read the module docstring before changing this.
#
# The shape of a filled table, for whoever transcribes it:
#
#     TRANSCRIBED_TABLE = BotrytisThresholdTable(
#         rows=(
#             ThresholdRow(
#                 temperature_c_min=<from the source>,
#                 temperature_c_max=<from the source>,
#                 wetness_hours_moderate=<from the source>,
#                 wetness_hours_high=<from the source>,
#             ),
#             ...
#         ),
#         citation="<author, year, title, journal/publisher>",
#         source_crop="<the crop the SOURCE studied, not the crop we want>",
#         source_region="<the region the SOURCE studied, verbatim>",
#         source_validation_conditions=(
#             "<the source's own statement of what it validated: cultivars, seasons, "
#             "inoculum conditions, how the model was evaluated>"
#         ),
#         source_document_reference="<DOI or URL, precise enough to re-find>",
#         source_section_or_page="<table number and page>",
#         source_snippet="<verbatim caption/text of the table transcribed>",
#         transcribed_by="<who read the document>",
#     )
#
# Two conventions carried over from `label_table.py`:
#   * `source_snippet` is verbatim, whitespace-normalized. No word added, dropped or
#     reordered.
#   * A threshold the source does not state stays None. "The source is silent" and
#     "there is no threshold" are different facts, and only the first is ever true here.
# ---------------------------------------------------------------------------------
TRANSCRIBED_TABLE: BotrytisThresholdTable | None = None
