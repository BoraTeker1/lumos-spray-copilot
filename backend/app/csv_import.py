"""CSV pilot import: header mapping, per-row validation, duplicate detection, dry run.

Pure module (no FastAPI/SQLAlchemy) — routes/crud feed it CSV text plus the existing
records' duplicate keys and get back a `DryRunReport`; nothing here touches a database.

Design rules:
* NEVER silently guess a critical regulatory value. Missing PHI / REI / rate / harvest
  values stay missing and are reported as warnings ("unverified / check cannot run");
  they are never defaulted.
* Duplicates (inside the file, or against already-imported records) are flagged and
  excluded from the importable set — reported, never silently dropped.
* Mapping is header-alias based and correctable: the caller may override any detected
  column mapping (or "ignore" a column) before committing.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime

RECORD_TYPE_PLANNED = "planned_sprays"
RECORD_TYPE_SCOUTING = "scout_observations"

IGNORE = "ignore"


@dataclass(frozen=True)
class FieldSpec:
    name: str                 # canonical field name
    kind: str                 # str / date / float / int
    required: bool = False
    regulatory: bool = False  # missing => explicit "unverified" warning
    aliases: tuple[str, ...] = ()


PLANNED_SPRAY_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("external_record_id", "str",
              aliases=("record id", "id", "rec id", "external id", "record")),
    FieldSpec("field_block", "str",
              aliases=("field", "block", "field/block", "field block", "field id")),
    FieldSpec("crop", "str", aliases=("commodity",)),
    FieldSpec("treated_acres", "float",
              aliases=("acres", "treated acres", "area", "area (acres)")),
    FieldSpec("intended_date", "date", required=True,
              aliases=("intended date", "planned date", "application date", "date",
                       "app date", "intended application date")),
    FieldSpec("product_name", "str", required=True,
              aliases=("product", "product name", "trade name", "material")),
    FieldSpec("epa_reg_no", "str", regulatory=True,
              aliases=("epa", "epa reg no", "epa registration number", "epa reg",
                       "registration no", "epa reg. no.")),
    FieldSpec("active_ingredient", "str", regulatory=True,
              aliases=("ai", "active ingredient", "active")),
    FieldSpec("moa_group", "str",
              aliases=("moa", "moa group", "frac", "frac group", "irac", "irac group",
                       "hrac", "mode of action", "mode-of-action group")),
    FieldSpec("target_pest_or_disease", "str",
              aliases=("target", "pest", "disease", "target pest",
                       "target pest or disease", "pest/disease")),
    FieldSpec("rate_amount", "float", regulatory=True,
              aliases=("rate", "application rate", "rate amount")),
    FieldSpec("rate_unit", "str", regulatory=True,
              aliases=("rate unit", "unit", "units")),
    FieldSpec("estimated_cost", "float",
              aliases=("cost", "estimated cost", "est cost", "product cost",
                       "cost usd", "estimated product/application cost")),
    FieldSpec("pre_harvest_interval_days", "int", regulatory=True,
              aliases=("phi", "phi days", "phi (days)", "pre-harvest interval",
                       "pre harvest interval days")),
    FieldSpec("re_entry_interval_hours", "int", regulatory=True,
              aliases=("rei", "rei hours", "rei (hours)", "re-entry interval",
                       "re entry interval hours")),
    FieldSpec("expected_harvest_date", "date", regulatory=True,
              aliases=("harvest date", "expected harvest", "expected harvest date",
                       "harvest")),
    FieldSpec("recommendation_author", "str",
              aliases=("author", "recommended by", "recommendation author", "pca",
                       "pca name")),
    FieldSpec("notes", "str", aliases=("comments", "note")),
)

SCOUTING_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("external_record_id", "str",
              aliases=("record id", "id", "rec id", "external id", "record")),
    FieldSpec("field_block", "str",
              aliases=("field", "block", "field/block", "field block", "field id")),
    FieldSpec("observation_date", "date", required=True,
              aliases=("date", "observation date", "obs date", "scout date",
                       "scouting date")),
    FieldSpec("crop_stage", "str", aliases=("stage", "crop stage", "growth stage")),
    FieldSpec("visible_issue", "str", required=True,
              aliases=("pest", "disease", "issue", "pest or disease", "visible issue",
                       "target", "pest/disease")),
    FieldSpec("severity", "int",
              aliases=("severity", "severity 1-5", "severity (1-5)", "rating")),
    FieldSpec("severity_scale", "str", aliases=("severity scale", "scale")),
    FieldSpec("count_value", "float",
              aliases=("count", "count value", "count/threshold", "count or threshold")),
    FieldSpec("observer", "str", aliases=("scout", "scouted by")),
    FieldSpec("notes", "str", aliases=("comments", "note", "evidence notes")),
)

FIELDS_BY_TYPE = {
    RECORD_TYPE_PLANNED: PLANNED_SPRAY_FIELDS,
    RECORD_TYPE_SCOUTING: SCOUTING_FIELDS,
}

# Marker used in downloadable templates so example rows are unmistakably not data.
TEMPLATE_EXAMPLE_MARKER = "EXAMPLE-DELETE-THIS-ROW"

_TEMPLATE_EXAMPLES = {
    RECORD_TYPE_PLANNED: {
        "external_record_id": TEMPLATE_EXAMPLE_MARKER,
        "field_block": "Block 4",
        "crop": "strawberry",
        "treated_acres": "12",
        "intended_date": "2026-07-20",
        "product_name": "Switch 62.5 WG",
        "epa_reg_no": "100-953",
        "active_ingredient": "cyprodinil + fludioxonil",
        "moa_group": "FRAC 9 + 12",
        "target_pest_or_disease": "gray mold",
        "rate_amount": "14",
        "rate_unit": "oz/acre",
        "estimated_cost": "210",
        "pre_harvest_interval_days": "0",
        "re_entry_interval_hours": "12",
        "expected_harvest_date": "2026-07-24",
        "recommendation_author": "Jane PCA",
        "notes": "example row — delete before importing",
    },
    RECORD_TYPE_SCOUTING: {
        "external_record_id": TEMPLATE_EXAMPLE_MARKER,
        "field_block": "Block 4",
        "observation_date": "2026-07-18",
        "crop_stage": "fruiting",
        "visible_issue": "gray mold",
        "severity": "2",
        "severity_scale": "1-5",
        "count_value": "",
        "observer": "Sam Scout",
        "notes": "example row — delete before importing",
    },
}


def template_csv(record_type: str) -> str:
    """Downloadable example template: canonical headers + one clearly-marked example row."""
    specs = FIELDS_BY_TYPE[record_type]
    example = _TEMPLATE_EXAMPLES[record_type]
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([s.name for s in specs])
    writer.writerow([example.get(s.name, "") for s in specs])
    return buf.getvalue()


def _normalize_header(header: str) -> str:
    h = (header or "").strip().lower().replace("_", " ")
    return re.sub(r"\s+", " ", h)


def build_mapping(
    headers: list[str], specs: tuple[FieldSpec, ...], overrides: dict | None = None
) -> tuple[dict[str, str], list[str]]:
    """Map raw CSV headers to canonical field names.

    Returns (mapping: raw header -> canonical field or "ignore", unmapped headers).
    `overrides` wins over alias detection; an override to an unknown field is an error
    surfaced by the caller (we keep this function total and predictable).
    """
    overrides = overrides or {}
    known = {s.name: s for s in specs}
    alias_index: dict[str, str] = {}
    for s in specs:
        alias_index[_normalize_header(s.name)] = s.name
        for a in s.aliases:
            alias_index[_normalize_header(a)] = s.name

    mapping: dict[str, str] = {}
    unmapped: list[str] = []
    seen_fields: set[str] = set()
    for h in headers:
        override = overrides.get(h)
        if override is not None:
            target = override if (override == IGNORE or override in known) else IGNORE
        else:
            target = alias_index.get(_normalize_header(h), IGNORE)
        if target != IGNORE and target in seen_fields:
            # Two columns mapped to one field is ambiguous — keep the first, flag this one.
            unmapped.append(h)
            mapping[h] = IGNORE
            continue
        mapping[h] = target
        if target == IGNORE and override is None:
            unmapped.append(h)
        elif target != IGNORE:
            seen_fields.add(target)
    return mapping, unmapped


_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y")


def _parse_value(spec: FieldSpec, raw: str):
    """Parse one cell. Returns (value, error). Empty cells are (None, None)."""
    text = (raw or "").strip()
    if not text:
        return None, None
    if spec.kind == "str":
        return text, None
    if spec.kind == "date":
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(text, fmt).date(), None
            except ValueError:
                continue
        return None, f"{spec.name}: unrecognized date '{text}' (use YYYY-MM-DD)"
    cleaned = text.replace("$", "").replace(",", "")
    if spec.kind == "int":
        try:
            value = int(float(cleaned))
        except ValueError:
            return None, f"{spec.name}: '{text}' is not a whole number"
        if value < 0:
            return None, f"{spec.name}: must be >= 0 (got {value})"
        return value, None
    if spec.kind == "float":
        try:
            value = float(cleaned)
        except ValueError:
            return None, f"{spec.name}: '{text}' is not a number"
        if value < 0:
            return None, f"{spec.name}: must be >= 0 (got {value})"
        return value, None
    return text, None


@dataclass
class ParsedRow:
    row_number: int                      # 1-based data row (header excluded)
    values: dict = field(default_factory=dict)   # canonical field -> parsed value
    raw: dict = field(default_factory=dict)      # canonical field -> raw cell text
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    duplicate_of: str | None = None

    @property
    def importable(self) -> bool:
        return not self.errors and self.duplicate_of is None

    def as_payload(self) -> dict:
        return {
            "row_number": self.row_number,
            "values": {
                k: (v.isoformat() if isinstance(v, date) else v)
                for k, v in self.values.items()
            },
            "errors": self.errors,
            "warnings": self.warnings,
            "duplicate_of": self.duplicate_of,
            "importable": self.importable,
        }


@dataclass
class DryRunReport:
    record_type: str
    headers: list[str] = field(default_factory=list)
    mapping: dict = field(default_factory=dict)          # raw header -> field/ignore
    unmapped_headers: list[str] = field(default_factory=list)
    missing_required_columns: list[str] = field(default_factory=list)
    rows: list[ParsedRow] = field(default_factory=list)
    parse_error: str | None = None

    @property
    def importable_rows(self) -> list[ParsedRow]:
        return [r for r in self.rows if r.importable]

    def as_payload(self) -> dict:
        rows = [r.as_payload() for r in self.rows]
        return {
            "record_type": self.record_type,
            "headers": self.headers,
            "mapping": self.mapping,
            "unmapped_headers": self.unmapped_headers,
            "missing_required_columns": self.missing_required_columns,
            "parse_error": self.parse_error,
            "rows": rows,
            "total_rows": len(rows),
            "importable_count": sum(1 for r in rows if r["importable"]),
            "error_count": sum(1 for r in rows if r["errors"]),
            "duplicate_count": sum(1 for r in rows if r["duplicate_of"]),
            "warning_count": sum(1 for r in rows if r["warnings"]),
            "notes": [
                "Dry-run validation: nothing is imported until the import is committed.",
                "Missing regulatory values (PHI, REI, rate, harvest date, product "
                "identity) are never guessed — they stay missing and the decision "
                "check treats them as unverified.",
                "Duplicate rows are excluded from the importable set and listed above.",
            ],
        }


def duplicate_key_for_planned(
    external_record_id, product_name, intended_date, field_block=None
) -> tuple:
    """Duplicate identity for a planned spray (external id wins when present)."""
    ext = (str(external_record_id).strip().lower() if external_record_id else "")
    if ext:
        return ("ext", ext)
    return (
        "nat",
        (product_name or "").strip().lower(),
        intended_date.isoformat() if isinstance(intended_date, date) else str(intended_date),
        (field_block or "").strip().lower(),
    )


def duplicate_key_for_scouting(
    external_record_id, visible_issue, observation_date, field_block=None
) -> tuple:
    ext = (str(external_record_id).strip().lower() if external_record_id else "")
    if ext:
        return ("ext", ext)
    return (
        "nat",
        (visible_issue or "").strip().lower(),
        observation_date.isoformat()
        if isinstance(observation_date, date) else str(observation_date),
        (field_block or "").strip().lower(),
    )


def _row_duplicate_key(record_type: str, values: dict) -> tuple | None:
    if record_type == RECORD_TYPE_PLANNED:
        if values.get("product_name") and values.get("intended_date"):
            return duplicate_key_for_planned(
                values.get("external_record_id"), values["product_name"],
                values["intended_date"], values.get("field_block"),
            )
    else:
        if values.get("visible_issue") and values.get("observation_date"):
            return duplicate_key_for_scouting(
                values.get("external_record_id"), values["visible_issue"],
                values["observation_date"], values.get("field_block"),
            )
    return None


def _regulatory_warnings(record_type: str, values: dict) -> list[str]:
    """Explicit 'unverified / cannot run' notes for absent regulatory values."""
    if record_type != RECORD_TYPE_PLANNED:
        out = []
        if values.get("severity") is None:
            out.append("no severity recorded — threshold comparisons cannot run")
        return out
    out = []
    if values.get("pre_harvest_interval_days") is None:
        out.append("PHI missing — unverified; the pre-harvest interval check cannot run")
    if values.get("re_entry_interval_hours") is None:
        out.append("REI missing — unverified; the re-entry interval checks cannot run")
    if values.get("expected_harvest_date") is None:
        out.append(
            "expected harvest date missing — PHI/REI vs. harvest cannot be evaluated "
            "unless the farm record has one"
        )
    if not values.get("active_ingredient") and not values.get("epa_reg_no"):
        out.append(
            "no active ingredient or EPA reg. no. — product identity is ambiguous"
        )
    if (values.get("rate_amount") is None) != (not values.get("rate_unit")):
        out.append("incomplete application rate — amount and unit must both be present")
    return out


def parse_csv(
    record_type: str,
    csv_text: str,
    mapping_overrides: dict | None = None,
    existing_keys: dict | None = None,
) -> DryRunReport:
    """Parse + validate CSV text into a DryRunReport (never writes anything).

    `existing_keys` maps duplicate keys (see duplicate_key_for_*) of records already
    in the database to a human-readable label ("planned spray #12"), so re-imports are
    caught against prior imports, not just inside the file.
    """
    if record_type not in FIELDS_BY_TYPE:
        raise ValueError(f"Unknown record type '{record_type}'")
    specs = FIELDS_BY_TYPE[record_type]
    report = DryRunReport(record_type=record_type)
    existing_keys = existing_keys or {}

    text = (csv_text or "").strip("﻿").strip()
    if not text:
        report.parse_error = "The CSV is empty."
        return report

    # Delimiter: prefer the sniffer, fall back to tab-vs-comma on the header line.
    first_line = text.splitlines()[0]
    try:
        dialect = csv.Sniffer().sniff(first_line, delimiters=",;\t")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = "\t" if "\t" in first_line else ","

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        raw_headers = next(reader)
    except StopIteration:
        report.parse_error = "The CSV has no header row."
        return report

    headers = [h.strip() for h in raw_headers]
    report.headers = headers
    mapping, unmapped = build_mapping(headers, specs, mapping_overrides)
    report.mapping = mapping
    report.unmapped_headers = unmapped

    mapped_fields = {f for f in mapping.values() if f != IGNORE}
    report.missing_required_columns = [
        s.name for s in specs if s.required and s.name not in mapped_fields
    ]

    spec_by_name = {s.name: s for s in specs}
    seen_in_file: dict[tuple, int] = {}

    for i, cells in enumerate(reader, start=1):
        if not any((c or "").strip() for c in cells):
            continue  # blank line
        row = ParsedRow(row_number=i)
        for col_index, header in enumerate(headers):
            fname = mapping.get(header, IGNORE)
            if fname == IGNORE:
                continue
            raw_cell = cells[col_index] if col_index < len(cells) else ""
            row.raw[fname] = raw_cell
            value, error = _parse_value(spec_by_name[fname], raw_cell)
            if error:
                row.errors.append(error)
            elif value is not None:
                row.values[fname] = value

        # Template example rows must never be importable data.
        if TEMPLATE_EXAMPLE_MARKER in (row.raw.get("external_record_id") or ""):
            row.errors.append(
                "this is the template's example row — delete it before importing"
            )

        for s in specs:
            if s.required and row.values.get(s.name) is None:
                row.errors.append(f"{s.name} is required and missing")

        # Scouting severity honesty: an out-of-1-5 severity needs its scale stated.
        if record_type == RECORD_TYPE_SCOUTING:
            sev = row.values.get("severity")
            if sev is not None and not (1 <= sev <= 5) and not row.values.get(
                "severity_scale"
            ):
                row.errors.append(
                    f"severity {sev} is outside 1-5 and no severity_scale was given — "
                    f"state the scale rather than have it guessed"
                )

        row.warnings.extend(_regulatory_warnings(record_type, row.values))

        if not row.errors:
            key = _row_duplicate_key(record_type, row.values)
            if key is not None:
                if key in seen_in_file:
                    row.duplicate_of = f"row {seen_in_file[key]} in this file"
                elif key in existing_keys:
                    row.duplicate_of = f"already imported: {existing_keys[key]}"
                else:
                    seen_in_file[key] = i

        report.rows.append(row)

    return report
