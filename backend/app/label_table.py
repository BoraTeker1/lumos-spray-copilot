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
# ---------------------------------------------------------------------------------
TRANSCRIBED_LABEL_USES: tuple[TranscribedLabelUse, ...] = ()
