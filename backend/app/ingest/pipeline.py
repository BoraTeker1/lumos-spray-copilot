"""The eight stages, and the only module in `app/ingest/` that touches the database.

Every stage reuses something rather than reimplementing it, and the reuse is the point:

    fetch      storage.store_document(KIND_RAW_INGESTION)   + a Document row
    parse      the adapter
    validate   csv_import.validate_rows(RECORD_TYPE_WEATHER)
    normalize  units.convert / units.to_canonical
    align      geo.haversine_km against the field centroid
    resolve    the operator-stated IngestContext
    dedupe     csv_import.duplicate_key_for_weather + pit.digest_of
    persist    crud.create_weather_observations_bulk

`validate` is the one worth defending. Handing provider rows to the SAME validator the
concierge CSV import uses means an ingested reading is held to an identical contract —
same aliases, same required fields, same typed coercion, same per-row errors — so there
is no second, weaker path into the weather table. A provider integration that quietly
accepted rows the human path rejects would be indistinguishable from working.

Two rules the stages exist to enforce:

* **A refusal drops the row.** `units.Refusal` carries a reason and never a number, so
  there is no code path that keeps a half-converted reading. A temperature that silently
  stayed in Fahrenheit is worse than no temperature.
* **No centroid, no row.** `disease_risk` treats a NULL `station_distance_km` as
  in-range *and*, in `evidence_grade`, as close. That is tolerable for a human leaving a
  cell blank and dangerous for a machine writing 24 rows a day, so a row we cannot
  place is dropped with an issue rather than written with a null.
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from sqlalchemy.orm import Session

from app import clock, crud, csv_import, models, pit, storage, units
from app.ingest import base, geo
from app.ingest.base import (
    ISSUE_DUPLICATE_ROW,
    ISSUE_MISSING_OBSERVED_AT,
    ISSUE_NO_CREDENTIAL,
    ISSUE_NO_FIELD_GEOLOCATION,
    ISSUE_PARSE_FAILED,
    ISSUE_ROW_INVALID,
    ISSUE_UNIT_REFUSAL,
    ISSUE_UNREQUESTED_STATION,
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    IngestContext,
    Issue,
)

# Namespace for the value digest that decides duplicate-vs-correction. Bumping it
# deliberately invalidates the comparison, which is correct only when the meaning of a
# weather value changes.
VALUE_DIGEST_NAMESPACE = "weather-value-v1"

# The fields whose change makes an incoming reading a CORRECTION rather than a
# duplicate. Deliberately excludes `recorded_at`, `source_reference` and the run link:
# re-fetching the same hour tomorrow must not look like a correction just because the
# clock moved.
_VALUE_FIELDS = (
    "temperature_c",
    "relative_humidity_pct",
    "rainfall_mm",
    "leaf_wetness_minutes",
    "wetness_is_measured",
    "station_distance_km",
    "quality_flag",
)


def value_digest(values: dict) -> str:
    """Content digest of the parts of a reading that carry meaning."""
    return pit.digest_of({k: values.get(k) for k in _VALUE_FIELDS}, VALUE_DIGEST_NAMESPACE)


# Optional per-row unit declarations. An adapter that cannot emit canonical units says
# so with one of these instead of converting at the edge, which keeps every conversion
# inside `units` where it is cited and where a refusal is possible.
#
# They are stripped BEFORE validation, because `csv_import.validate_rows` rejects any
# column it does not declare — correctly, since an unknown column in a human's CSV is a
# mis-mapped header.
UNIT_HINTS: dict[str, tuple[str, str]] = {
    "temperature_unit": ("temperature_c", "c"),
    "rainfall_unit": ("rainfall_mm", "mm"),
    "leaf_wetness_unit": ("leaf_wetness_minutes", "min"),
}


def _extract_unit_hints(rows: list[dict]) -> tuple[list[dict], dict[int, dict]]:
    """Split unit declarations off the rows, keyed by 1-based row number.

    1-based because that is what `ParsedRow.row_number` uses, and the two have to line
    up for the normalize stage to find the hint belonging to a validated row.
    """
    cleaned: list[dict] = []
    hints: dict[int, dict] = {}
    for index, row in enumerate(rows, start=1):
        row = dict(row)
        row_hints = {
            column: (row.pop(key), target)
            for key, (column, target) in UNIT_HINTS.items()
            if key in row
        }
        if row_hints:
            hints[index] = row_hints
        cleaned.append(row)
    return cleaned, hints


def _record_issues(db: Session, run: models.IngestionRun, issues: list[Issue]) -> None:
    for issue in issues:
        db.add(
            models.IngestionIssue(
                ingestion_run_id=run.id,
                stage=issue.stage,
                severity=issue.severity,
                code=issue.code,
                message=issue.message[:4000],
                row_index=issue.row_index,
                natural_key=issue.natural_key,
                detail=issue.detail,
            )
        )
    run.issue_count = (run.issue_count or 0) + len(issues)


def _finish(
    db: Session,
    run: models.IngestionRun,
    status: str,
    issues: list[Issue],
    now: datetime,
    error: str | None = None,
) -> models.IngestionRun:
    run.status = status
    run.error = error[:4000] if error else None
    run.finished_at = now
    started = run.started_at or now
    run.duration_ms = max(0, int((now - started).total_seconds() * 1000))
    _record_issues(db, run, issues)
    db.commit()
    db.refresh(run)
    return run


def run_source(
    db: Session,
    adapter,
    ctx: IngestContext,
    *,
    store=None,
    now: datetime | None = None,
    job_id: int | None = None,
) -> models.IngestionRun:
    """Run one source over one window. Always returns a run; never raises for data.

    The `describe()` gate is checked BEFORE anything else and returns without calling
    `fetch`. That ordering is the guarantee that a deployment with no credential makes
    no network call — it is enforced by this function rather than by each adapter
    remembering to check, because "every adapter remembers" is not a guarantee.
    """
    now = now or clock.current_datetime()
    descriptor = adapter.describe()

    run = models.IngestionRun(
        source_key=descriptor.source_key,
        domain=descriptor.domain,
        farm_id=ctx.farm_id,
        field_id=ctx.field_id,
        window_start=ctx.window_start,
        window_end=ctx.window_end,
        status=base.RUN_RUNNING,
        adapter_version=descriptor.adapter_version,
        request_digest=pit.digest_of(ctx.as_request_payload(), "ingest-request-v1"),
        started_at=now,
        job_id=job_id,
        # An ingestion run onto a demo farm is itself demo scaffolding. Tagging it here
        # keeps `has_non_demo_data` honest about what a demo deployment contains.
        data_source="demo" if ctx.is_demo else "provider_api",
        data_confidence="simulated" if ctx.is_demo else "provider_reported",
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    if not descriptor.can_fetch:
        return _finish(
            db, run, base.RUN_SKIPPED_NO_CREDENTIAL,
            [
                Issue(
                    stage=base.STAGE_FETCH,
                    severity=SEVERITY_WARNING,
                    code=ISSUE_NO_CREDENTIAL,
                    message=descriptor.blocker or "adapter cannot run",
                )
            ],
            now,
        )

    issues: list[Issue] = []
    try:
        # ---- 1. fetch -----------------------------------------------------
        fetched = adapter.fetch(ctx)
        stored = storage.store_document(
            storage.KIND_RAW_INGESTION,
            fetched.raw,
            filename=fetched.filename,
            content_type=fetched.content_type,
            store=store,
        )
        document = models.Document(
            storage_key=stored.key,
            sha256=stored.sha256,
            kind=stored.kind,
            filename=fetched.filename,
            content_type=stored.content_type,
            size_bytes=stored.size_bytes,
            # Soft polymorphic reference — the Document docstring already names an
            # ingestion run as an intended subject.
            subject_type="ingestion_run",
            subject_id=run.id,
            farm_id=ctx.farm_id,
            notes="raw provider response",
            data_source=run.data_source,
            data_confidence=run.data_confidence,
        )
        db.add(document)
        db.flush()
        run.document_id = document.id

        # ---- 2. parse -----------------------------------------------------
        rows, parse_issues = adapter.parse(fetched.raw, ctx)
        issues.extend(parse_issues)
        run.fetched_count = len(rows) + sum(
            1 for i in parse_issues if i.code == ISSUE_PARSE_FAILED
        )

        # ---- 3. validate --------------------------------------------------
        # NO `existing_keys` here on purpose. That parameter makes `validate_rows` mark
        # any row matching a stored natural key as a duplicate, which is right for a
        # human re-uploading a spreadsheet and wrong here: it cannot tell a repeat from
        # a CORRECTION, so a station revising an hour would be silently discarded.
        # Against-DB deduplication is stage 7's job, where the value digest can tell
        # those two apart.
        rows, unit_hints = _extract_unit_hints(rows)
        report = csv_import.validate_rows(
            csv_import.RECORD_TYPE_WEATHER,
            rows,
            date_format=csv_import.DATE_FORMAT_ISO,
        )
        run.parsed_count = len(report.rows)

        candidates: list[dict] = []
        for parsed in report.rows:
            if parsed.errors:
                issues.append(
                    Issue(
                        stage=base.STAGE_VALIDATE,
                        severity=SEVERITY_ERROR,
                        code=ISSUE_ROW_INVALID,
                        message="; ".join(parsed.errors),
                        row_index=parsed.row_number,
                    )
                )
                continue
            candidates.append({**parsed.values, "_row_index": parsed.row_number})

        # ---- 4. normalize -------------------------------------------------
        # The adapter is expected to have emitted canonical units already; this stage
        # exists so that any adapter which cannot must route through `units` and let a
        # Refusal drop the row, rather than inventing a conversion at the edge.
        normalized: list[dict] = []
        for values in candidates:
            refusal = _normalize_row(values, unit_hints.get(values["_row_index"], {}))
            if refusal is not None:
                issues.append(
                    Issue(
                        stage=base.STAGE_NORMALIZE,
                        severity=SEVERITY_ERROR,
                        code=ISSUE_UNIT_REFUSAL,
                        message=refusal,
                        row_index=values.get("_row_index"),
                        # Note: no numeric value in the detail. A refusal never
                        # carries a number, and neither does the record of it.
                        detail={"refusal": refusal},
                    )
                )
                continue
            normalized.append(values)

        # ---- 5. align + 6. resolve ---------------------------------------
        distance = geo.haversine_km(
            ctx.station_lat, ctx.station_lon, ctx.field_lat, ctx.field_lon
        )
        placed: list[dict] = []
        for values in normalized:
            station_id = (values.get("station_id") or "").strip()
            if station_id.lower() != ctx.station_id.strip().lower():
                issues.append(
                    Issue(
                        stage=base.STAGE_RESOLVE,
                        severity=SEVERITY_ERROR,
                        code=ISSUE_UNREQUESTED_STATION,
                        message=(
                            f"row reports station {station_id!r} but this run asked for "
                            f"{ctx.station_id!r}; refusing to join it to the field"
                        ),
                        row_index=values.get("_row_index"),
                    )
                )
                continue
            if values.get("observed_at") is None:
                issues.append(
                    Issue(
                        stage=base.STAGE_ALIGN,
                        severity=SEVERITY_ERROR,
                        code=ISSUE_MISSING_OBSERVED_AT,
                        message="no observation timestamp; the row cannot be placed in time",
                        row_index=values.get("_row_index"),
                    )
                )
                continue
            if values.get("station_distance_km") is None:
                if distance is None:
                    issues.append(
                        Issue(
                            stage=base.STAGE_ALIGN,
                            severity=SEVERITY_ERROR,
                            code=ISSUE_NO_FIELD_GEOLOCATION,
                            message=(
                                "no station-to-field distance: the field has no centroid "
                                "or the station has no coordinates. Writing a NULL "
                                "distance would be read downstream as 'in range and "
                                "close', so the row is dropped instead."
                            ),
                            row_index=values.get("_row_index"),
                            detail={"field_id": ctx.field_id, "station_id": ctx.station_id},
                        )
                    )
                    continue
                values["station_distance_km"] = round(distance, 2)
            placed.append(values)

        # ---- 7. dedupe (in-batch + value-digest against live rows) --------
        admitted, superseded_pairs = _dedupe(db, ctx, placed, issues, run)

        # ---- 8. persist ---------------------------------------------------
        if admitted or superseded_pairs:
            crud.create_weather_observations_bulk(
                db,
                ctx.farm_id,
                admitted,
                field_id=ctx.field_id,
                ingestion_run_id=run.id,
                is_demo=ctx.is_demo,
                superseded_pairs=superseded_pairs,
            )
        run.admitted_count = len(admitted) + len(superseded_pairs)
        run.superseded_count = len(superseded_pairs)

        return _finish(db, run, base.RUN_SUCCEEDED, issues, clock.current_datetime())

    except Exception as exc:  # noqa: BLE001 - the run must record its own failure
        db.rollback()
        run = db.get(models.IngestionRun, run.id)
        return _finish(
            db, run, base.RUN_FAILED, issues, clock.current_datetime(),
            error=f"{type(exc).__name__}: {exc}",
        )


def _normalize_row(values: dict, hints: dict) -> str | None:
    """Force declared values into the unit each column name states. Returns a refusal.

    The column names carry their units (`temperature_c`, `rainfall_mm`,
    `leaf_wetness_minutes`), so "normalized" has an unambiguous target. Only a column
    with an explicit hint is converted — a value with no hint is taken at its column's
    word, which is the same contract the CSV import has always had.

    Returning the reason rather than a converted-or-original value is deliberate: there
    is no path here that yields a partially converted row.
    """
    for column, (source_unit, target) in hints.items():
        amount = values.get(column)
        if amount is None or source_unit is None:
            continue
        result = units.convert(amount, source_unit, target)
        if isinstance(result, units.Refusal):
            return f"{column}: {result.reason}"
        values[column] = result.amount
    return None


def _dedupe(db: Session, ctx: IngestContext, rows: list[dict], issues, run):
    """Split rows into new-admissions and corrections; drop exact repeats.

    Three outcomes per row, and the middle one is what makes re-running a window free:
      * no live row for this (farm, station, hour) -> admit
      * a live row with the SAME value digest      -> duplicate, skip
      * a live row with a DIFFERENT value digest   -> a correction; append with
        `supersedes_id` rather than editing, because the old reading was a real thing
        that a stored snapshot may already have used.
    """
    existing_rows = crud.live_weather_by_station_hour(db, ctx.farm_id)

    admitted: list[dict] = []
    superseded_pairs: list[tuple[dict, int]] = []
    seen_in_batch: set[tuple] = set()

    for values in rows:
        key = csv_import.duplicate_key_for_weather(
            values.get("station_id"), values.get("observed_at")
        )
        if key in seen_in_batch:
            run.duplicate_count += 1
            issues.append(
                Issue(
                    stage=base.STAGE_DEDUPE,
                    severity=SEVERITY_WARNING,
                    code=ISSUE_DUPLICATE_ROW,
                    message="repeated station+timestamp within this batch",
                    row_index=values.get("_row_index"),
                    natural_key=str(key),
                )
            )
            continue
        seen_in_batch.add(key)

        existing = existing_rows.get(
            ((values.get("station_id") or "").strip().lower(), values.get("observed_at"))
        )
        if existing is None:
            admitted.append(values)
            continue

        incoming_digest = value_digest(values)
        current_digest = value_digest(
            {f: getattr(existing, f, None) for f in _VALUE_FIELDS}
        )
        if incoming_digest == current_digest:
            run.duplicate_count += 1
            continue
        superseded_pairs.append((values, existing.id))

    return admitted, superseded_pairs
