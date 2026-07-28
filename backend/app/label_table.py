"""Manually transcribed pesticide-label uses. THE TABLE IS EMPTY.

This file is the source of record for label values a human read off a primary document
and typed in. It ships with `TRANSCRIBED_LABEL_USES = ()` on purpose, exactly as
`disease_risk.BotrytisWetnessV1.thresholds` ships as None, and for exactly the same
reason: a plausible-looking PHI is indistinguishable from a correct one to every test
that can be written about it, and this value ends up in a record a licensed PCA is
entitled to trust and an auditor may read.

So the numbers are not recalled, not inferred from a similar product, and not lifted from
a search result. They are transcribed from the label document, with the document
reference, the revision, its effective date, the section, and a verbatim snippet — or the
row is not added and the corresponding check keeps reporting that it did not run.

Why this is a Python module and not a data file or a seeded table:
  * A change arrives as a reviewed diff, not as an UPDATE from whoever had DB access.
  * `TranscribedLabelUse` is frozen and keyword-only with no defaults on the provenance
    fields, so a row missing its citation raises a TypeError at import. The check is not
    a validation step someone can skip; it is construction.
  * The runtime store is still the database (`ProductLabelRecord`), loaded by
    `crud.sync_transcribed_labels`. One store, one resolution path, whichever ingestion
    route a record arrived by.

To add a use, append a TranscribedLabelUse below. `python -m app.label_sync` loads it.
Leave a value None when the label does not state it — None means "the label is silent",
which correctly leaves that check unevaluated. It must never mean "no limit".

This file is NEVER loaded by `seed.run()` or `init_db()`: label-grounded demo decisions
would be a fabricated regulatory claim, which is ENGINEERING_GUIDELINES.md §9 applied to the one kind of
value where it matters most.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import date


@dataclass(frozen=True, kw_only=True)
class TranscribedLabelUse:
    """One (product, registered crop) use as written on one revision of one label.

    Keyword-only so a 15-field transcription cannot be silently misaligned, and frozen so
    a loaded row cannot be edited in place. No provenance field has a default: omitting
    one is a TypeError, not a None that flows into the database.
    """

    # ------------------------------------------------------------- product identity
    epa_reg_no: str
    product_name: str
    registrant: str
    registered_crop: str

    # ---------------------------------------------- what the label states (or None)
    # None means the label is silent on this value. It never means "unlimited".
    target_pest_or_disease: str | None = None
    pre_harvest_interval_days: int | None = None
    re_entry_interval_hours: int | None = None
    max_seasonal_rate_amount: float | None = None
    max_seasonal_rate_unit: str | None = None
    max_applications_per_season: int | None = None
    min_retreatment_interval_days: int | None = None
    active_ingredient: str | None = None
    active_ingredient_concentration_amount: float | None = None
    active_ingredient_concentration_unit: str | None = None
    moa_group: str | None = None

    # ------------------------------------------------------------------ provenance
    # Required. Every one of these is what lets a PCA check the transcription against the
    # document, and what lets a reader tell whether this describes the label in the
    # applicator's hand today.
    label_version: str
    label_effective_date: date
    source_document_reference: str
    source_section_or_page: str
    source_snippet: str
    transcribed_by: str

    def __post_init__(self) -> None:
        for name in (
            "epa_reg_no", "product_name", "registrant", "registered_crop",
            "label_version", "source_document_reference", "source_section_or_page",
            "source_snippet", "transcribed_by",
        ):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(f"TranscribedLabelUse.{name} must not be blank")
        if not any(
            getattr(self, name) is not None
            for name in (
                "pre_harvest_interval_days", "re_entry_interval_hours",
                "max_seasonal_rate_amount", "max_applications_per_season",
                "min_retreatment_interval_days",
            )
        ):
            raise ValueError(
                "a TranscribedLabelUse that states no regulatory value has nothing to "
                "contribute to a decision — omit the row instead"
            )
        if (self.max_seasonal_rate_amount is None) != (self.max_seasonal_rate_unit is None):
            raise ValueError(
                "max_seasonal_rate_amount and max_seasonal_rate_unit must be given "
                "together — a rate without its unit cannot be compared to anything"
            )

    def as_values(self) -> dict:
        """Flat dict of every transcribed field (used for content-addressing)."""
        return {f.name: getattr(self, f.name) for f in fields(self)}


# ---------------------------------------------------------------------------------
# EMPTY BY DESIGN. See the module docstring before adding anything here.
#
# The shape of an entry, for whoever transcribes the first one:
#
#     TranscribedLabelUse(
#         epa_reg_no="<from the label>",
#         product_name="<from the label>",
#         registrant="<from the label>",
#         registered_crop="strawberry",
#         pre_harvest_interval_days=<int the label states>,
#         re_entry_interval_hours=<int the label states>,
#         max_applications_per_season=<int the label states>,
#         min_retreatment_interval_days=<int the label states>,
#         max_seasonal_rate_amount=<float>, max_seasonal_rate_unit="<e.g. oz/acre>",
#         label_version="<revision id or date printed on the label>",
#         label_effective_date=date(YYYY, M, D),
#         source_document_reference="<what document, precisely enough to re-find it>",
#         source_section_or_page="<section heading or page number>",
#         source_snippet="<verbatim text of the directions being transcribed>",
#         transcribed_by="<who read the label>",
#     )
#
# Two conventions the first transcriptions established, for whoever adds the third:
#
#   * `source_snippet` is verbatim wording with whitespace normalized — PDF text
#     extraction turns a table cell into ragged line breaks, and re-flowing those is
#     not editing. No word is added, dropped, or reordered.
#   * A value the label does not state stays None, and the reason is recorded in a
#     comment beside it. "The label is silent" and "the label permits any amount" are
#     different facts, and only the first one is ever true here.
# ---------------------------------------------------------------------------------
TRANSCRIBED_LABEL_USES: tuple[TranscribedLabelUse, ...] = (
    # -----------------------------------------------------------------------------
    # Captan 80 WDG — the multi-site protectant fungicide in the strawberry program.
    #
    # Note for anyone comparing this against the demo story: the label states a
    # ZERO-day pre-harvest interval for strawberries ("May be applied up to day of
    # harvest"). The seeded demo blocks a captan application on an ENTERED PHI of 4
    # days. The entered value was wrong, and this row is what lets the engine say so.
    # That is the label layer working, not a transcription error.
    # -----------------------------------------------------------------------------
    TranscribedLabelUse(
        epa_reg_no="34704-1075",
        product_name="Captan 80 WDG",
        registrant="Loveland Products Inc.",
        registered_crop="strawberry",
        target_pest_or_disease="Botrytis (Gray mold), Leaf spot",
        pre_harvest_interval_days=0,
        re_entry_interval_hours=24,
        max_seasonal_rate_amount=30.0,
        max_seasonal_rate_unit="lb/acre",
        # The strawberry RESTRICTIONS block states a per-year rate cap and nothing
        # about an application count, so this stays None.
        max_applications_per_season=None,
        # DIRECTIONS say "Repeat at 7- to 14-day intervals" but also "continue
        # applications through harvest period treating immediately after each
        # picking" — the two cannot both be a minimum interval, and neither sits in
        # RESTRICTIONS. The label does not state an unambiguous retreatment minimum,
        # so the retreatment check correctly keeps reporting that it did not run.
        min_retreatment_interval_days=None,
        active_ingredient="captan",
        active_ingredient_concentration_amount=80.0,
        active_ingredient_concentration_unit="%",
        moa_group="M4",
        label_version="EPA-accepted 2019-06-21 (Decision Number 529290)",
        label_effective_date=date(2019, 6, 21),
        source_document_reference=(
            "US EPA Pesticide Product Label System, CAPTAN 80 WDG, EPA Reg. No. "
            "34704-1075, label amendment accepted 2019-06-21 — "
            "https://www3.epa.gov/pesticides/chem_search/ppls/"
            "034704-01075-20190621.pdf"
        ),
        source_section_or_page=(
            "DIRECTIONS FOR USE — STRAWBERRIES (printed label page 11; PDF page 13). "
            "Active ingredient statement, printed label page 1; REI also stated under "
            "AGRICULTURAL USE REQUIREMENTS, printed label page 3."
        ),
        source_snippet=(
            "STRAWBERRIES. DISEASE: Botrytis (Gray mold), Leaf spot. APPLICATION "
            "RATE (Lb Product/Acre): 1.87 to 3.75. RESTRICTIONS: Do not apply more "
            "than 30.0 lbs. per acre per year. May be applied up to day of harvest. "
            "The REI is 24 hours."
        ),
        transcribed_by=(
            "Claude Code, transcribed from the EPA PPLS PDF — UNVERIFIED, pending "
            "PCA review against the primary document"
        ),
    ),
    # -----------------------------------------------------------------------------
    # Switch 62.5WG — the rotation partner. This is the row that makes three of the
    # four label-dependent checks executable: the label states a season application
    # cap, a minimum interval, AND a season rate cap in one restrictions block.
    # -----------------------------------------------------------------------------
    TranscribedLabelUse(
        epa_reg_no="100-953",
        product_name="Switch 62.5WG",
        registrant="Syngenta Crop Protection, LLC",
        registered_crop="strawberry",
        target_pest_or_disease=(
            "Gray Mold (Botrytis cinerea), Powdery mildew (Sphaerotheca macularis), "
            "Anthracnose (Colletotrichum spp.)"
        ),
        pre_harvest_interval_days=0,
        re_entry_interval_hours=12,
        max_seasonal_rate_amount=56.0,
        max_seasonal_rate_unit="oz/acre",
        max_applications_per_season=4,
        min_retreatment_interval_days=7,
        # Switch is a TWO active-ingredient product (37.5% cyprodinil + 25.0%
        # fludioxonil). `active_ingredient` is a single field, so the honest entry is
        # both names — not one of them, which would understate what went on the field.
        active_ingredient="cyprodinil + fludioxonil",
        # Deliberately None. There is no single active-ingredient concentration for a
        # two-active product, and inventing a combined 62.5% would make the
        # active-ingredient quantity metric produce a number for a conversion nobody
        # can cite. Absent here means the metric REFUSES for Switch, which is correct.
        active_ingredient_concentration_amount=None,
        active_ingredient_concentration_unit=None,
        moa_group="9 + 12",
        label_version="EPA-accepted 2025-04-21 (Case Number 476706)",
        label_effective_date=date(2025, 4, 21),
        source_document_reference=(
            "US EPA Pesticide Product Label System, SWITCH 62.5WG, EPA Reg. No. "
            "100-953, PRIA label amendment accepted 2025-04-21 — "
            "https://www3.epa.gov/pesticides/chem_search/ppls/"
            "000100-00953-20250421.pdf"
        ),
        source_section_or_page=(
            "Strawberry and Berry, Low Growing Subgroup 13-07G (except Cranberry) "
            "use table and its Specific Use Restrictions (printed label page 35; PDF "
            "page 39). REI stated under AGRICULTURAL USE REQUIREMENTS, printed label "
            "page 6. Active ingredient statement, printed label page 1."
        ),
        source_snippet=(
            "Strawberry and Berry, Low Growing Subgroup 13-07G (except Cranberry). "
            "Gray Mold (Botrytis cinerea), Powdery mildew (Sphaerotheca macularis), "
            "Anthracnose (Colletotrichum spp.). Product Rate oz/Acre: 11-14. "
            "Specific Use Restrictions: 1) Maximum Single Application Rate: DO NOT "
            "exceed the maximum rate listed in the table above. 2) DO NOT apply more "
            "than 4 applications per year at the highest rate mentioned in the table "
            "above. 3) Minimum Application Interval: 7 days. 4) DO NOT make more than "
            "two applications by air. 5) Make only one pre-plant dip application per "
            "crop. 6) DO NOT apply more than 56 oz/A of Switch 62.5WG per year (1.3 "
            "lb cyprodinil and 0.9 lb fludioxonil). 7) DO NOT apply more than 1.3 lb "
            "ai/A of cyprodinil-containing products and 0.9 lb ai/A of "
            "fludioxonil-containing products per year. 8) May be applied on the day "
            "of harvest (0-day PHI)."
        ),
        transcribed_by=(
            "Claude Code, transcribed from the EPA PPLS PDF — UNVERIFIED, pending "
            "PCA review against the primary document"
        ),
    ),
)
