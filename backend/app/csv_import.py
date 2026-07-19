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
RECORD_TYPE_SPRAY_EVENTS = "spray_events"

IGNORE = "ignore"

# Date-format modes for imports. "auto" accepts ISO always and slash dates only when
# unambiguous; a date that reads validly as BOTH m/d and d/m is an error telling the
# operator to re-run with an explicit format — a compliance import must never guess
# which side of the slash is the day.
DATE_FORMAT_AUTO = "auto"
DATE_FORMAT_ISO = "iso"
DATE_FORMAT_MDY = "mdy"
DATE_FORMAT_DMY = "dmy"
DATE_FORMATS = (DATE_FORMAT_AUTO, DATE_FORMAT_ISO, DATE_FORMAT_MDY, DATE_FORMAT_DMY)


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

# Historical *actual* applications (the reduction baseline's denominator lives here:
# a prior_period baseline needs the farm's real pre-Lumos spray log on record).
SPRAY_EVENT_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("external_record_id", "str",
              aliases=("record id", "id", "rec id", "external id", "record")),
    FieldSpec("field_block", "str",
              aliases=("field", "block", "field/block", "field block", "field id")),
    FieldSpec("application_date", "date", required=True,
              aliases=("date", "application date", "app date", "date applied",
                       "sprayed on", "spray date", "date of application")),
    FieldSpec("product_name", "str", required=True,
              aliases=("product", "product name", "trade name", "material")),
    FieldSpec("active_ingredient", "str", regulatory=True,
              aliases=("ai", "active ingredient", "active")),
    FieldSpec("moa_group", "str",
              aliases=("moa", "moa group", "frac", "frac group", "irac", "irac group",
                       "hrac", "mode of action", "mode-of-action group")),
    FieldSpec("pesticide_class", "str",
              aliases=("class", "type", "pesticide class", "product type")),
    FieldSpec("target_pest_or_disease", "str",
              aliases=("target", "pest", "disease", "target pest",
                       "target pest or disease", "pest/disease")),
    FieldSpec("rate_amount", "float", regulatory=True,
              aliases=("rate", "application rate", "rate amount")),
    FieldSpec("rate_unit", "str", regulatory=True,
              aliases=("rate unit", "unit", "units")),
    FieldSpec("treated_acres", "float",
              aliases=("acres", "treated acres", "area", "area (acres)")),
    FieldSpec("cost", "float",
              aliases=("cost", "product cost", "total cost", "cost usd",
                       "application cost")),
    FieldSpec("pre_harvest_interval_days", "int", regulatory=True,
              aliases=("phi", "phi days", "phi (days)", "pre-harvest interval",
                       "pre harvest interval days")),
    FieldSpec("re_entry_interval_hours", "int", regulatory=True,
              aliases=("rei", "rei hours", "rei (hours)", "re-entry interval",
                       "re entry interval hours")),
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
    RECORD_TYPE_SPRAY_EVENTS: SPRAY_EVENT_FIELDS,
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
    RECORD_TYPE_SPRAY_EVENTS: {
        "external_record_id": TEMPLATE_EXAMPLE_MARKER,
        "field_block": "Block 4",
        "application_date": "2026-06-12",
        "product_name": "Captan 80 WDG",
        "active_ingredient": "captan",
        "moa_group": "FRAC M04",
        "pesticide_class": "fungicide",
        "target_pest_or_disease": "gray mold",
        "rate_amount": "3.75",
        "rate_unit": "lb/acre",
        "treated_acres": "12",
        "cost": "120",
        "pre_harvest_interval_days": "4",
        "re_entry_interval_hours": "24",
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


_ISO_FORMAT = "%Y-%m-%d"
_SLASH_FORMATS = {
    DATE_FORMAT_MDY: ("%m/%d/%Y", "%m/%d/%y"),
    DATE_FORMAT_DMY: ("%d/%m/%Y", "%d/%m/%y"),
}


def _try_formats(text: str, formats: tuple[str, ...]) -> date | None:
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_date(name: str, text: str, date_format: str):
    """Parse one date cell honoring the import's date_format. Returns (value, error).

    ISO (YYYY-MM-DD) always works. Slash dates follow the explicit format when one
    was chosen; under "auto" a slash date is accepted only when it is unambiguous
    (one side must be > 12) — a date valid as both m/d and d/m is an error, because
    guessing the day/month order would silently shift PHI/REI math by months.
    """
    iso = _try_formats(text, (_ISO_FORMAT,))
    if iso is not None:
        return iso, None
    if date_format in (DATE_FORMAT_MDY, DATE_FORMAT_DMY):
        value = _try_formats(text, _SLASH_FORMATS[date_format])
        if value is not None:
            return value, None
        return None, (
            f"{name}: unrecognized date '{text}' (use YYYY-MM-DD or "
            f"{'MM/DD/YYYY' if date_format == DATE_FORMAT_MDY else 'DD/MM/YYYY'})"
        )
    if date_format == DATE_FORMAT_ISO:
        return None, f"{name}: unrecognized date '{text}' (use YYYY-MM-DD)"
    # auto: only unambiguous slash dates pass.
    as_mdy = _try_formats(text, _SLASH_FORMATS[DATE_FORMAT_MDY])
    as_dmy = _try_formats(text, _SLASH_FORMATS[DATE_FORMAT_DMY])
    if as_mdy is not None and as_dmy is not None and as_mdy != as_dmy:
        return None, (
            f"{name}: ambiguous date '{text}' — could be "
            f"{as_mdy.isoformat()} (month/day) or {as_dmy.isoformat()} (day/month). "
            f"Re-run the import with date_format 'mdy' or 'dmy'."
        )
    value = as_mdy if as_mdy is not None else as_dmy
    if value is not None:
        return value, None
    return None, f"{name}: unrecognized date '{text}' (use YYYY-MM-DD)"


def _parse_value(spec: FieldSpec, raw: str, date_format: str = DATE_FORMAT_AUTO):
    """Parse one cell. Returns (value, error). Empty cells are (None, None)."""
    text = (raw or "").strip()
    if not text:
        return None, None
    if spec.kind == "str":
        return text, None
    if spec.kind == "date":
        return _parse_date(spec.name, text, date_format)
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


def duplicate_key_for_spray_event(
    external_record_id, product_name, application_date, field_block=None
) -> tuple:
    ext = (str(external_record_id).strip().lower() if external_record_id else "")
    if ext:
        return ("ext", ext)
    return (
        "nat",
        (product_name or "").strip().lower(),
        application_date.isoformat()
        if isinstance(application_date, date) else str(application_date),
        (field_block or "").strip().lower(),
    )


def _row_duplicate_key(record_type: str, values: dict) -> tuple | None:
    if record_type == RECORD_TYPE_PLANNED:
        if values.get("product_name") and values.get("intended_date"):
            return duplicate_key_for_planned(
                values.get("external_record_id"), values["product_name"],
                values["intended_date"], values.get("field_block"),
            )
    elif record_type == RECORD_TYPE_SPRAY_EVENTS:
        if values.get("product_name") and values.get("application_date"):
            return duplicate_key_for_spray_event(
                values.get("external_record_id"), values["product_name"],
                values["application_date"], values.get("field_block"),
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
    if record_type == RECORD_TYPE_SCOUTING:
        out = []
        if values.get("severity") is None:
            out.append("no severity recorded — threshold comparisons cannot run")
        return out
    if record_type == RECORD_TYPE_SPRAY_EVENTS:
        out = []
        if values.get("pre_harvest_interval_days") is None:
            out.append(
                "PHI missing — unverified; PHI-vs-harvest checks against this "
                "application cannot run"
            )
        if values.get("re_entry_interval_hours") is None:
            out.append(
                "REI missing — unverified; the re-entry overlap check cannot see "
                "this application"
            )
        if not values.get("active_ingredient"):
            out.append(
                "no active ingredient — this application cannot count toward "
                "rotation (resistance) checks"
            )
        if (values.get("rate_amount") is None) != (not values.get("rate_unit")):
            out.append(
                "incomplete application rate — amount and unit must both be present"
            )
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


def validate_rows(
    record_type: str,
    raw_rows: list[dict],
    existing_keys: dict | None = None,
    report: DryRunReport | None = None,
    date_format: str = DATE_FORMAT_AUTO,
) -> DryRunReport:
    """Validate pre-structured rows (canonical field -> raw value) into a DryRunReport.

    THE single validation path: the CSV importer feeds mapped rows through here, and
    the AI document extraction feeds its extracted rows through the exact same code —
    same type/required checks, same regulatory warnings, same duplicate detection.
    Never writes anything; values are never guessed.
    """
    if record_type not in FIELDS_BY_TYPE:
        raise ValueError(f"Unknown record type '{record_type}'")
    specs = FIELDS_BY_TYPE[record_type]
    spec_by_name = {s.name: s for s in specs}
    if report is None:
        report = DryRunReport(record_type=record_type)
    existing_keys = existing_keys or {}
    seen_in_file: dict[tuple, int] = {}

    for i, raw in enumerate(raw_rows, start=1):
        row = ParsedRow(row_number=i)
        for fname, raw_cell in (raw or {}).items():
            if fname not in spec_by_name:
                row.errors.append(f"unknown field '{fname}'")
                continue
            text = "" if raw_cell is None else str(raw_cell)
            row.raw[fname] = text
            value, error = _parse_value(spec_by_name[fname], text, date_format)
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


def parse_csv(
    record_type: str,
    csv_text: str,
    mapping_overrides: dict | None = None,
    existing_keys: dict | None = None,
    date_format: str = DATE_FORMAT_AUTO,
) -> DryRunReport:
    """Parse + validate CSV text into a DryRunReport (never writes anything).

    `existing_keys` maps duplicate keys (see duplicate_key_for_*) of records already
    in the database to a human-readable label ("planned spray #12"), so re-imports are
    caught against prior imports, not just inside the file. Validation itself is
    shared with the row-based path — see `validate_rows`.
    """
    if record_type not in FIELDS_BY_TYPE:
        raise ValueError(f"Unknown record type '{record_type}'")
    specs = FIELDS_BY_TYPE[record_type]
    report = DryRunReport(record_type=record_type)

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

    # Map each CSV line to a canonical-field raw dict, then share the validation path.
    raw_rows: list[dict] = []
    for cells in reader:
        if not any((c or "").strip() for c in cells):
            continue  # blank line
        raw: dict = {}
        for col_index, header in enumerate(headers):
            fname = mapping.get(header, IGNORE)
            if fname == IGNORE:
                continue
            raw[fname] = cells[col_index] if col_index < len(cells) else ""
        raw_rows.append(raw)

    return validate_rows(
        record_type, raw_rows, existing_keys, report=report, date_format=date_format
    )
