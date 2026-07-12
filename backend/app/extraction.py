"""AI extraction of spray recommendations / scouting records from messy documents.

Turns a PDF, image, or pasted text (email / WhatsApp / spreadsheet export) into
DRAFT structured rows that flow into the exact same dry-run validation, duplicate
detection, and human-corrected preview as the CSV import. Pure module: prompt and
schema builders only — no FastAPI/SQLAlchemy.

Honesty rules (ENGINEERING_GUIDELINES.md §9–§10)
--------------------------------
* Extraction is REAL AI and is labelled AI-suggested, not confirmed. A human reviews
  and corrects every row in the dry-run preview before anything is committed.
* The model extracts ONLY what is literally written. Missing PHI/REI/rate/dates stay
  null — regulatory values are NEVER guessed (same rule as the CSV importer).
* Every value carries a verbatim `source_snippet` so a human can check it against the
  document. Committed rows land as `ai_extracted` + field-level imported_unverified —
  the decision engine escalates them and they can never auto-approve.
* The model must ABSTAIN when the input is not a spray recommendation / scouting
  record. Every extraction is logged to the append-only AI judgment log.
"""
from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, Field

from app import llm
from app.csv_import import RECORD_TYPE_PLANNED, RECORD_TYPE_SCOUTING

PROMPT_VERSION = "extraction-v1"

# Upload guards.
ALLOWED_DOCUMENT_TYPES = ("application/pdf",)
ALLOWED_IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp", "image/gif")
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024  # 10 MB

EXTRACTION_DISCLAIMER = (
    "AI-extracted draft rows — not confirmed. Every value must be reviewed against "
    "the source document before import; missing regulatory values were left blank, "
    "never guessed. Imported values remain unverified until a PCA verifies them."
)

Confidence = Literal["low", "medium", "high"]


class ExtractedPlannedSpray(BaseModel):
    """One draft planned-spray row. All values are strings exactly as written in the
    document (the importer's validator parses/normalizes them); null when absent."""
    external_record_id: str | None = None
    field_block: str | None = None
    crop: str | None = None
    treated_acres: str | None = None
    intended_date: str | None = None
    product_name: str | None = None
    epa_reg_no: str | None = None
    active_ingredient: str | None = None
    moa_group: str | None = None
    target_pest_or_disease: str | None = None
    rate_amount: str | None = None
    rate_unit: str | None = None
    estimated_cost: str | None = None
    pre_harvest_interval_days: str | None = None
    re_entry_interval_hours: str | None = None
    expected_harvest_date: str | None = None
    recommendation_author: str | None = None
    notes: str | None = None
    # Verbatim text the values came from, so a human can check the extraction.
    source_snippet: str | None = None
    row_confidence: Confidence = "low"


class ExtractedScoutingRow(BaseModel):
    """One draft scouting-observation row (strings as written; null when absent)."""
    external_record_id: str | None = None
    field_block: str | None = None
    observation_date: str | None = None
    crop_stage: str | None = None
    visible_issue: str | None = None
    severity: str | None = None
    severity_scale: str | None = None
    count_value: str | None = None
    observer: str | None = None
    notes: str | None = None
    source_snippet: str | None = None
    row_confidence: Confidence = "low"


class PlannedSprayExtraction(BaseModel):
    rows: list[ExtractedPlannedSpray] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    overall_confidence: Confidence = "low"
    abstained: bool = False
    abstain_reason: str | None = None


class ScoutingExtraction(BaseModel):
    rows: list[ExtractedScoutingRow] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    overall_confidence: Confidence = "low"
    abstained: bool = False
    abstain_reason: str | None = None


OUTPUT_MODELS = {
    RECORD_TYPE_PLANNED: PlannedSprayExtraction,
    RECORD_TYPE_SCOUTING: ScoutingExtraction,
}

# Fields the validator will re-parse; excluded metadata stays on the extraction side.
_ROW_METADATA_FIELDS = ("source_snippet", "row_confidence")


def build_system_prompt(record_type: str) -> str:
    what = (
        "planned pesticide spray recommendations"
        if record_type == RECORD_TYPE_PLANNED
        else "pest/disease scouting observations"
    )
    return (
        f"You extract {what} from a document (PDF, photo, email, or chat text) into "
        f"structured rows for a specialty-crop compliance system.\n"
        f"Rules you must never break:\n"
        f"1. Extract ONLY what is literally written. If a value (PHI, REI, rate, "
        f"date, EPA number, cost) is not stated, leave it null. NEVER guess, infer, "
        f"or fill in typical/label values — a wrong regulatory value is worse than a "
        f"missing one.\n"
        f"2. Copy values exactly as written (units and all); do not convert or "
        f"normalize.\n"
        f"3. For every row, set source_snippet to the verbatim text the values came "
        f"from, and row_confidence to how clearly the document states them.\n"
        f"4. If the input is not actually {what} (wrong document, illegible, or "
        f"ambiguous), set abstained=true with an abstain_reason and return no rows.\n"
        f"5. List anything uncertain or ambiguous in caveats.\n"
        f"You are decision support, not a decider: you never recommend spraying or "
        f"any product."
    )


def build_content_blocks(
    text: str | None = None,
    file_bytes: bytes | None = None,
    media_type: str | None = None,
) -> list[dict]:
    """User-content blocks: document/image first (when present), instructions last."""
    import base64

    blocks: list[dict] = []
    if file_bytes is not None and media_type in ALLOWED_DOCUMENT_TYPES:
        blocks.append({
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64.b64encode(file_bytes).decode("ascii"),
            },
        })
    elif file_bytes is not None and media_type in ALLOWED_IMAGE_TYPES:
        blocks.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64.b64encode(file_bytes).decode("ascii"),
            },
        })
    instruction = "Extract the rows from this input as instructed."
    if text:
        instruction = f"Input text:\n---\n{text}\n---\n{instruction}"
    blocks.append({"type": "text", "text": instruction})
    return blocks


def input_digest(
    record_type: str,
    text: str | None = None,
    file_bytes: bytes | None = None,
) -> str:
    """sha256 over the exact extraction inputs (reproducibility / audit)."""
    h = hashlib.sha256()
    h.update(PROMPT_VERSION.encode())
    h.update(record_type.encode())
    if text:
        h.update(text.encode())
    if file_bytes:
        h.update(file_bytes)
    return h.hexdigest()


def rows_to_raw(extraction) -> list[dict]:
    """Extracted rows -> raw dicts for csv_import.validate_rows (metadata stripped).

    Only non-null values are passed on, so the validator's missing-value warnings
    ("PHI missing — unverified") fire exactly as they do for a sparse CSV.
    """
    out: list[dict] = []
    for row in extraction.rows:
        data = row.model_dump()
        out.append({
            k: v for k, v in data.items()
            if k not in _ROW_METADATA_FIELDS and v is not None and str(v).strip() != ""
        })
    return out


def extraction_payload(extraction, model_id: str, is_mock: bool) -> dict:
    """UI-facing extraction metadata (snippets/confidence per row + caveats)."""
    return {
        "model": model_id,
        "is_mock": is_mock,
        "prompt_version": PROMPT_VERSION,
        "overall_confidence": extraction.overall_confidence,
        "abstained": extraction.abstained,
        "abstain_reason": extraction.abstain_reason,
        "caveats": list(extraction.caveats),
        "rows": [row.model_dump() for row in extraction.rows],
        "disclaimer": EXTRACTION_DISCLAIMER,
    }


# ------------------------------------------------------------------ mock builders
def _mock_text(content_blocks: list[dict]) -> str:
    return " ".join(
        b.get("text", "") for b in content_blocks if b.get("type") == "text"
    ).lower()


def _mock_planned(content_blocks: list[dict]) -> PlannedSprayExtraction:
    text = _mock_text(content_blocks)
    if "mock-abstain" in text or "invoice" in text:
        return PlannedSprayExtraction(
            abstained=True,
            abstain_reason="Mock: input does not look like a spray recommendation.",
            caveats=["Demo/mock extraction — set ANTHROPIC_API_KEY for real extraction."],
        )
    return PlannedSprayExtraction(
        rows=[ExtractedPlannedSpray(
            intended_date="2026-07-20",
            product_name="Switch 62.5 WG",
            active_ingredient="cyprodinil + fludioxonil",
            target_pest_or_disease="gray mold",
            rate_amount="14",
            rate_unit="oz/acre",
            pre_harvest_interval_days="0",
            re_entry_interval_hours="12",
            estimated_cost="210",
            source_snippet="Mock snippet: 'Apply Switch 62.5 WG at 14 oz/A for botrytis…'",
            row_confidence="medium",
        )],
        caveats=["Demo/mock extraction — set ANTHROPIC_API_KEY for real extraction."],
        overall_confidence="medium",
    )


def _mock_scouting(content_blocks: list[dict]) -> ScoutingExtraction:
    text = _mock_text(content_blocks)
    if "mock-abstain" in text or "invoice" in text:
        return ScoutingExtraction(
            abstained=True,
            abstain_reason="Mock: input does not look like a scouting record.",
            caveats=["Demo/mock extraction — set ANTHROPIC_API_KEY for real extraction."],
        )
    return ScoutingExtraction(
        rows=[ExtractedScoutingRow(
            observation_date="2026-07-18",
            visible_issue="gray mold",
            severity="2",
            severity_scale="1-5",
            source_snippet="Mock snippet: 'light botrytis on low rows, ~2/5'",
            row_confidence="medium",
        )],
        caveats=["Demo/mock extraction — set ANTHROPIC_API_KEY for real extraction."],
        overall_confidence="medium",
    )


llm.register_mock_builder(PlannedSprayExtraction, _mock_planned)
llm.register_mock_builder(ScoutingExtraction, _mock_scouting)
