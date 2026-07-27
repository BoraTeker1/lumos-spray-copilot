"""AI extraction of label uses from a pesticide label document.

Turns a label PDF (or photo, or pasted text) into DRAFT `ProductLabelRecord` rows a
human corrects before anything is stored, and that a licensed PCA must separately
verify before any decision may rely on them. Pure module: prompt and schema builders
only — no FastAPI/SQLAlchemy.

Why this exists next to `app/label_table.py` rather than instead of it. The
transcription table is a human reading a document and typing what it says, reviewed
as a diff. This is a model reading the same document and proposing what it says.
Both land in the SAME append-only store through the SAME resolution path, and both
arrive UNVERIFIED — the tier is the only thing that differs
(`ai_extracted_unverified` vs `transcribed_unverified`), and neither can back a
decision until `promotable_to_authoritative` is satisfied by a per-farm PCA
attestation. Nothing here shortens that chain; it only reduces the typing.

Honesty rules (ENGINEERING_GUIDELINES.md §9–§10), and they matter more here than anywhere else in
the AI layer, because the output is a regulatory value:
* Extraction is REAL AI and is labelled AI-suggested, not confirmed.
* The model extracts ONLY what is literally written. A PHI the label does not state
  stays null — it is NEVER inferred from a similar product, a typical value, or the
  model's own knowledge of the product.
* It never converts or unifies units. "1.5 lb" stays "1.5 lb", because a converted
  number cannot be checked against the document by the human reviewing it.
* Every row carries a verbatim `source_snippet` and its section/page, so a PCA can
  check the extraction against the label rather than trusting it.
* The model ABSTAINS when the document is not a pesticide label.
* Every extraction is logged to the append-only AI judgment log.

Deliberately NOT reimplemented here: `build_content_blocks`, `ALLOWED_DOCUMENT_TYPES`,
`ALLOWED_IMAGE_TYPES`, and `MAX_DOCUMENT_BYTES` are imported from `app.extraction`.
A second copy would drift, and the upload guards are exactly the kind of thing that
is only noticed after the copy has been wrong for a while.
"""
from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, Field

from app import llm
from app.extraction import (  # noqa: F401  (re-exported for the route's guards)
    ALLOWED_DOCUMENT_TYPES,
    ALLOWED_IMAGE_TYPES,
    MAX_DOCUMENT_BYTES,
    build_content_blocks,
)

PROMPT_VERSION = "label-extraction-v1"

LABEL_EXTRACTION_DISCLAIMER = (
    "AI-extracted draft label values — NOT verified against the label. Every value "
    "must be checked against the source document before it is stored, and a licensed "
    "PCA must verify the stored record for a farm before any decision can rely on "
    "it. Values the label does not state were left blank, never inferred."
)

Confidence = Literal["low", "medium", "high"]


class ExtractedLabelUse(BaseModel):
    """One (crop, use) block as written on one label. Values are strings exactly as
    printed — the reviewer and the loader parse them; null when the label is silent.

    `registered_crop` is the only required-in-practice field: a use with no crop
    cannot be resolved against a decision, and inventing one would be the single
    worst thing this module could do.
    """
    epa_reg_no: str | None = None
    product_name: str | None = None
    registrant: str | None = None
    registered_crop: str | None = None
    target_pest_or_disease: str | None = None
    pre_harvest_interval_days: str | None = None
    re_entry_interval_hours: str | None = None
    max_seasonal_rate_amount: str | None = None
    max_seasonal_rate_unit: str | None = None
    max_applications_per_season: str | None = None
    min_retreatment_interval_days: str | None = None
    active_ingredient: str | None = None
    active_ingredient_concentration_amount: str | None = None
    active_ingredient_concentration_unit: str | None = None
    moa_group: str | None = None
    label_version: str | None = None
    label_effective_date: str | None = None
    # Where in the document this row came from, and the words it came from.
    source_section_or_page: str | None = None
    source_snippet: str | None = None
    row_confidence: Confidence = "low"


class LabelExtraction(BaseModel):
    rows: list[ExtractedLabelUse] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    overall_confidence: Confidence = "low"
    abstained: bool = False
    abstain_reason: str | None = None


def build_system_prompt() -> str:
    """The extraction contract. Mirrors `extraction.build_system_prompt`'s rules and
    tightens the two that are specific to regulatory values: never convert, and one
    row per (crop, use) block rather than one row per document."""
    return (
        "You extract pesticide LABEL directions from a product label document (PDF, "
        "photo, or pasted text) into structured rows for a specialty-crop compliance "
        "system. A licensed pest control adviser will check every value you produce "
        "against the document.\n"
        "Rules you must never break:\n"
        "1. Extract ONLY what is literally printed on this label. If the label does "
        "not state a value (PHI, REI, maximum rate, maximum applications, "
        "retreatment interval), leave it null. NEVER guess it, infer it from a "
        "similar product, or fill in a typical or remembered value — a wrong "
        "regulatory value is far worse than a missing one, because someone will act "
        "on it.\n"
        "2. Copy values EXACTLY as written, units and all. Do not convert, "
        "normalize, or unify units, and do not do arithmetic. If the label says "
        "'1.5 lb', write '1.5' and 'lb' — not '24' and 'oz'.\n"
        "3. Emit ONE ROW PER (crop, use) BLOCK. A label that gives different "
        "directions for strawberries and for tomatoes is two rows; a label that "
        "gives different directions for two pests on one crop is two rows. Never "
        "merge blocks, and never spread one block's values across several rows.\n"
        "4. For every row, set source_section_or_page to where on the label the "
        "values are, and source_snippet to the verbatim text they came from. Set "
        "row_confidence to how clearly the document states them.\n"
        "5. If the input is not a pesticide product label (wrong document, "
        "illegible, or only a fragment that states no directions), set "
        "abstained=true with an abstain_reason and return no rows.\n"
        "6. List anything ambiguous, cut off, or hard to read in caveats. A value "
        "you are unsure of belongs in caveats, not silently in a row.\n"
        "You are decision support, not a decider: you never recommend spraying, "
        "never recommend a product, and never state that an application is allowed."
    )


def input_digest(text: str | None = None, file_bytes: bytes | None = None) -> str:
    """sha256 over the exact extraction inputs (reproducibility / audit)."""
    h = hashlib.sha256()
    h.update(PROMPT_VERSION.encode())
    if text:
        h.update(text.encode())
    if file_bytes:
        h.update(file_bytes)
    return h.hexdigest()


def extraction_payload(extraction, model_id: str, is_mock: bool) -> dict:
    """UI-facing extraction metadata (rows + snippets + caveats). No values are
    stored from this — it is what a human reviews before anything is committed."""
    return {
        "model": model_id,
        "is_mock": is_mock,
        "prompt_version": PROMPT_VERSION,
        "overall_confidence": extraction.overall_confidence,
        "abstained": extraction.abstained,
        "abstain_reason": extraction.abstain_reason,
        "caveats": list(extraction.caveats),
        "rows": [row.model_dump() for row in extraction.rows],
        "disclaimer": LABEL_EXTRACTION_DISCLAIMER,
    }


# ------------------------------------------------------------------ mock builder
def _mock_text(content_blocks: list[dict]) -> str:
    return " ".join(
        b.get("text", "") for b in content_blocks if b.get("type") == "text"
    ).lower()


def _mock_label(content_blocks: list[dict]) -> LabelExtraction:
    """Deterministic offline stand-in so tests and the demo never call the real API.

    The values are obviously fictional — a mock that produced realistic-looking
    label values would eventually be screenshotted, pasted into label_table.py, or
    mistaken for model performance, which ENGINEERING_GUIDELINES.md §9 forbids for exactly this kind
    of value.
    """
    text = _mock_text(content_blocks)
    if "mock-abstain" in text or "invoice" in text:
        return LabelExtraction(
            abstained=True,
            abstain_reason="Mock: this document does not look like a pesticide label.",
            caveats=["Demo/mock extraction — set ANTHROPIC_API_KEY for real extraction."],
        )
    return LabelExtraction(
        rows=[ExtractedLabelUse(
            epa_reg_no="99999-1",
            product_name="Mock Fungicide 50WG",
            registrant="Fictional Crop Science",
            registered_crop="Strawberries",
            target_pest_or_disease="botrytis_fruit_rot",
            pre_harvest_interval_days="0",
            re_entry_interval_hours="12",
            max_applications_per_season="2",
            label_version="mock-rev-1",
            label_effective_date="2025-01-01",
            source_section_or_page="Directions for Use, p. 1",
            source_snippet="Mock snippet: fictional directions, not a real label.",
            row_confidence="low",
        )],
        caveats=["Demo/mock extraction — set ANTHROPIC_API_KEY for real extraction."],
        overall_confidence="low",
    )


llm.register_mock_builder(LabelExtraction, _mock_label)
