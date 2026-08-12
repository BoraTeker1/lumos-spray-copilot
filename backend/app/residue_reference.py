"""Answer "what has actually been measured on this crop for this active ingredient?"
from the loaded USDA PDP reference, or refuse and say why.

This is the first EMPIRICAL layer in the codebase. Everything else either transcribes a
regulatory document (`label_table`) or computes from the farm's own records. PDP is a
third kind of input: a national measurement programme's published findings, which are
neither a rule the grower must obey nor an observation from their field.

That makes its authority genuinely awkward, and the awkwardness is handled explicitly
rather than smoothed over:

**It is context, never a verdict.** `ResidueProfile` has no band, score, verdict, or
recommended action, and there is nowhere to add one without editing this file — the
`disease_risk.RiskAssessment` technique (ENGINEERING_GUIDELINES.md §4). "Cyprodinil was detected on 52%
of domestic strawberry samples in 2016" is a fact about a past national sample. It is not
a statement about this grower's block, and it must never become "so do not spray it."

**It is not a label value and must never outrank one.** The EPA tolerance carried here
was transcribed by USDA into their own reference workbook. That is a secondary source
citing EPA. It travels with `AUTHORITY_REFERENCE_DATASET`, which is deliberately weaker
than `verified_label`, so a caller can never let it override a transcribed label or back
a definitive verdict.

**Staleness is a first-class field, not a footnote.** PDP rotates commodities: fresh
strawberries were sampled in 2014-2016 and not since. A profile therefore states its
`program_year` and `years_since_program`, and a caller that renders a detection rate
without the year is misrepresenting it. Staleness does not refuse — a 2016 measurement
is still a real measurement — but it cannot be invisible.

**A pair that was never analysed refuses.** It does not return zero. See
`pdp_dataset.aggregate` for why that inversion is the most dangerous number here.

Framework-free (stdlib only): plain rows in, dataclass or `Refusal` out.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from app import crop_aliases
from app.refusal import Refusal

# The authority tier this layer speaks with. Weaker than a verified label and weaker than
# a PCA-entered value, on purpose — see the module docstring.
AUTHORITY_REFERENCE_DATASET = "reference_dataset"

# ------------------------------------------------------------------ refusal codes
# Nothing has been loaded at all — an operator task (`python -m app.pdp_sync`), identical
# for every farm, and no grower activity fixes it.
NO_RESIDUE_REFERENCE_LOADED = "no_residue_reference_loaded"

# The crop does not correspond to any commodity in the loaded releases. PDP samples ~20
# commodities a year out of hundreds grown; most crops are simply not in the programme.
CROP_NOT_IN_PROGRAM = "crop_not_in_program"

# The crop name matched a commodity only by containment. Never resolved silently — the
# `crop_aliases` rule (ENGINEERING_GUIDELINES.md §6): exact, curated alias, or a human decides.
CROP_MATCH_AMBIGUOUS = "crop_match_ambiguous"

# The commodity is in the programme, and the compound is known from another loaded
# commodity, but it was not on THIS commodity's analytical panel. THIS IS NOT ZERO
# DETECTIONS. Real example in the 2016 release: emamectin benzoate was run on tomatoes
# and not on strawberries, so the strawberry answer is "not measured", not "not found".
PESTICIDE_NOT_ANALYSED = "pesticide_not_analysed"

# The active ingredient string did not resolve to exactly one PDP compound.
PESTICIDE_NOT_RESOLVED = "pesticide_not_resolved"

# Rows for this pair disagree on concentration unit, so no summary statistic is honest.
UNIT_CONFLICT = "unit_conflict"

# ------------------------------------------------------------ tolerance vocabulary
# EPA tolerance values as PDP publishes them. The non-numeric codes are meaningful and
# must never collapse to "no limit".
TOLERANCE_NONE_ESTABLISHED = "NT"  # No tolerance — a detection is itself a finding.
TOLERANCE_EXEMPT = "EX"  # Exempt from a tolerance requirement.
TOLERANCE_SURFACE_USE = "SU"  # Surface/post-harvest use.

_TOLERANCE_BASIS_TEXT = {
    TOLERANCE_NONE_ESTABLISHED: (
        "EPA has established NO tolerance for this pesticide/commodity pair. This does "
        "not mean there is no limit — it means any detectable residue is itself a "
        "regulatory finding. Confirm with the product label and your PCA."
    ),
    TOLERANCE_EXEMPT: (
        "This pair is exempt from a tolerance requirement. Confirm the exemption's scope "
        "with the product label and your PCA."
    ),
    TOLERANCE_SURFACE_USE: (
        "The published tolerance covers a surface or post-harvest use. It may not "
        "describe the field application being planned."
    ),
}


class ResidueRow(Protocol):
    """The shape this module reads. The ORM model satisfies it; so does a test stub.

    A Protocol rather than an import of `models.ResidueReferenceRecord` keeps this module
    free of SQLAlchemy, per the ENGINEERING_GUIDELINES.md §6 layering rule.
    """

    commodity_code: str
    commodity_name: str
    commodity_type: str
    pesticide_code: str
    pesticide_name: str
    program_year: int
    samples_tested: int
    samples_with_detection: int
    max_concentration: float | None
    median_detected_concentration: float | None
    concentration_unit: str | None
    unit_conflict: bool
    domestic_only: bool
    epa_tolerance_value: float | None
    epa_tolerance_basis: str | None
    tolerance_unit: str | None
    source_reference: str
    source_digest: str


@dataclass(frozen=True)
class ResidueProfile:
    """What PDP measured for one (crop, active ingredient) pair in one program year.

    NO verdict field, NO risk band, NO recommended action, and none may be added — this
    type existing without them is the guarantee, not a convention. See module docstring.
    """

    crop: str
    commodity_name: str
    commodity_type: str
    active_ingredient: str
    pesticide_code: str

    program_year: int
    years_since_program: int
    samples_tested: int
    samples_with_detection: int
    detection_rate: float

    max_concentration: float | None
    median_detected_concentration: float | None
    concentration_unit: str | None

    epa_tolerance_value: float | None
    epa_tolerance_basis: str | None
    tolerance_unit: str | None
    # Historical maximum as a share of the tolerance. None whenever either side is
    # missing or the units differ — never silently converted.
    max_as_share_of_tolerance: float | None

    domestic_only: bool
    source_reference: str
    source_digest: str
    authority: str = AUTHORITY_REFERENCE_DATASET

    @property
    def tolerance_note(self) -> str | None:
        """Plain-language meaning of a non-numeric tolerance code, or None."""
        if self.epa_tolerance_basis is None:
            return None
        return _TOLERANCE_BASIS_TEXT.get(self.epa_tolerance_basis)


def _normalize_compound(name: str | None) -> str:
    """Lowercase/trim only. No stemming and no token surgery, for the same reason
    `crop_aliases.normalize` does none: 'captan' and 'captafol' are different compounds
    and no amount of string overlap makes them the same."""
    return " ".join((name or "").strip().lower().split())


def resolve_commodity(crop: str | None, rows: Sequence[ResidueRow]) -> tuple[str | None, str]:
    """Map a farm's crop name onto a PDP commodity code, or say why not.

    Returns (commodity_code, verdict) where verdict is a `crop_aliases` verdict. Uses the
    curated alias table, so "Strawberries" (USDA's spelling) and "strawberry" (ours)
    resolve together while "strawberry tree" stays AMBIGUOUS and goes to a human.
    """
    if not crop:
        return None, crop_aliases.NO_MATCH

    ambiguous = False
    for row in rows:
        verdict = crop_aliases.match_crops(crop, row.commodity_name)
        if verdict == crop_aliases.MATCH:
            return row.commodity_code, crop_aliases.MATCH
        if verdict == crop_aliases.AMBIGUOUS:
            ambiguous = True
    return None, crop_aliases.AMBIGUOUS if ambiguous else crop_aliases.NO_MATCH


def lookup(
    *,
    crop: str | None,
    active_ingredient: str | None,
    rows: Sequence[ResidueRow],
    current_year: int,
) -> ResidueProfile | Refusal:
    """The one entry point. Returns the most recent matching profile, or a Refusal.

    "Most recent" is deliberate and is the only place a choice is made: when PDP sampled
    a commodity in several years, the latest release is the one reported, with its year
    attached. Averaging across years would blend different analytical panels and
    different tolerances into a number belonging to no release.
    """
    if not rows:
        return Refusal(
            code=NO_RESIDUE_REFERENCE_LOADED,
            detail=(
                "No USDA PDP release has been loaded, so no measured residue data is "
                "available. An operator loads one with `python -m app.pdp_sync <zip>`."
            ),
        )

    commodity_code, verdict = resolve_commodity(crop, rows)
    if verdict == crop_aliases.AMBIGUOUS:
        return Refusal(
            code=CROP_MATCH_AMBIGUOUS,
            detail=(
                f"Crop {crop!r} overlaps a PDP commodity name without matching it "
                "exactly. Resolving this by string overlap could attribute another "
                "crop's residue findings to this one, so it is left to a human."
            ),
            context={"crop": crop},
        )
    if commodity_code is None:
        return Refusal(
            code=CROP_NOT_IN_PROGRAM,
            detail=(
                f"USDA PDP has not sampled {crop!r} in any loaded release. PDP rotates "
                "roughly 20 commodities a year, so most crops are absent. This is not a "
                "finding of low residue — nothing was measured."
            ),
            context={"crop": crop},
        )

    wanted = _normalize_compound(active_ingredient)
    if not wanted:
        return Refusal(
            code=PESTICIDE_NOT_RESOLVED,
            detail="No active ingredient was supplied, so there is nothing to look up.",
        )

    for_commodity = [r for r in rows if r.commodity_code == commodity_code]
    matches = [r for r in for_commodity if _normalize_compound(r.pesticide_name) == wanted]

    if not matches:
        # Distinguish "we know this compound but not on this crop" from "we do not know
        # this compound at all" — different people fix those.
        known = any(_normalize_compound(r.pesticide_name) == wanted for r in rows)
        if known:
            years = sorted({r.program_year for r in for_commodity})
            return Refusal(
                code=PESTICIDE_NOT_ANALYSED,
                detail=(
                    f"{active_ingredient} was not on the analytical panel PDP ran for "
                    f"{crop} in the loaded release(s) {years}. No detections were "
                    "reported because the compound was not tested — this is NOT a zero "
                    "detection rate and must not be read as one."
                ),
                context={"crop": crop, "active_ingredient": active_ingredient,
                         "program_years": years},
            )
        return Refusal(
            code=PESTICIDE_NOT_RESOLVED,
            detail=(
                f"{active_ingredient!r} does not match any compound name in the loaded "
                "PDP releases. PDP names compounds in its own reference table; matching "
                "is exact by design, because a near-match could report a different "
                "compound's residues."
            ),
            context={"active_ingredient": active_ingredient},
        )

    row = max(matches, key=lambda r: r.program_year)

    if row.unit_conflict:
        return Refusal(
            code=UNIT_CONFLICT,
            detail=(
                "PDP rows for this pair report more than one concentration unit, so no "
                "maximum or median can be stated without an uncited conversion."
            ),
            context={"crop": crop, "active_ingredient": active_ingredient,
                     "program_year": row.program_year},
        )

    share: float | None = None
    if (
        row.epa_tolerance_value is not None
        and row.epa_tolerance_value > 0
        and row.max_concentration is not None
        and row.tolerance_unit is not None
        and row.concentration_unit is not None
        and row.tolerance_unit == row.concentration_unit
    ):
        share = row.max_concentration / row.epa_tolerance_value

    return ResidueProfile(
        crop=crop_aliases.canonical_crop(crop) or crop,
        commodity_name=row.commodity_name,
        commodity_type=row.commodity_type,
        active_ingredient=row.pesticide_name,
        pesticide_code=row.pesticide_code,
        program_year=row.program_year,
        years_since_program=max(0, current_year - row.program_year),
        samples_tested=row.samples_tested,
        samples_with_detection=row.samples_with_detection,
        detection_rate=row.samples_with_detection / row.samples_tested,
        max_concentration=row.max_concentration,
        median_detected_concentration=row.median_detected_concentration,
        concentration_unit=row.concentration_unit,
        epa_tolerance_value=row.epa_tolerance_value,
        epa_tolerance_basis=row.epa_tolerance_basis,
        tolerance_unit=row.tolerance_unit,
        max_as_share_of_tolerance=share,
        domestic_only=row.domestic_only,
        source_reference=row.source_reference,
        source_digest=row.source_digest,
    )


# The one piece of user-facing wording this layer owns, kept server-side so a card renders
# it verbatim and the tone has one home (ENGINEERING_GUIDELINES.md §10).
RESIDUE_REFERENCE_DISCLAIMER = (
    "Measured residue findings from the USDA Pesticide Data Program, a national sampling "
    "programme. These describe past samples of this commodity nationally — not this "
    "field, this season, or this application. They are context for a conversation with "
    "your PCA, not a prediction and not a clearance. Decision support only. Always "
    "confirm PHI, REI, rates, crop use, and restrictions with the product label and a "
    "licensed PCA / agronomist."
)


def basis_text(profile: ResidueProfile) -> str:
    """Server-owned sentence describing what a profile is, including its age.

    Built here rather than in the frontend so the staleness can never be dropped by a
    card that only wanted the percentage (ENGINEERING_GUIDELINES.md §7, the DataReadinessCard rule).
    """
    age = (
        "the most recent release covering this commodity"
        if profile.years_since_program == 0
        else f"{profile.years_since_program} year(s) old — PDP has not sampled this "
             f"commodity since"
    )
    scope = "domestic (US-grown) samples" if profile.domestic_only else "all samples"
    return (
        f"USDA PDP {profile.program_year}, {scope}: {profile.active_ingredient} was "
        f"detected in {profile.samples_with_detection} of {profile.samples_tested} "
        f"{profile.commodity_name} samples. This release is {age}."
    )
