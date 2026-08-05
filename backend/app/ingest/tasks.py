"""Background tasks that drive ingestion.

Two tasks and a deliberate split: a fan-out that decides WHAT should be fetched, and a
worker that fetches ONE thing. The fan-out is scheduled; the worker is idempotent per
(source, farm, window bucket) so the same hour can be enqueued twice and fetched once.

Subscriptions — which farm watches which station — live in the task payload and in the
`LUMOS_CIMIS_SUBSCRIPTIONS` environment variable rather than in a table. A
`WeatherStationSubscription` model is the eventual right answer and is a table-per-noun
with one row today. Saying so here is better than building it and pretending the
decision was made on evidence.

Format: `LUMOS_CIMIS_SUBSCRIPTIONS="farm_id:field_id:station_id,farm_id::station_id"`
(field_id may be empty, though a run with no field centroid will drop every row — see
`pipeline`'s align stage).
"""
from __future__ import annotations

import logging
import os
from datetime import timedelta

from app import clock, models
from app.ingest import base, pipeline, registry
from app.jobs import queue
from app.jobs.registry import task

logger = logging.getLogger(__name__)

SUBSCRIPTIONS_ENV = "LUMOS_CIMIS_SUBSCRIPTIONS"

# How far back a scheduled fetch reaches. Wider than the hourly cadence on purpose:
# stations publish late, and re-fetching an already-stored hour is free because the
# value digest recognises it as a duplicate.
DEFAULT_LOOKBACK_HOURS = 6


def parse_subscriptions(raw: str | None) -> list[dict]:
    """`farm:field:station` triples. A malformed entry is skipped, never guessed at."""
    out: list[dict] = []
    for chunk in (raw or "").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = chunk.split(":")
        if len(parts) != 3:
            logger.warning("ignoring malformed subscription %r", chunk)
            continue
        farm_raw, field_raw, station = (p.strip() for p in parts)
        if not farm_raw.isdigit() or not station:
            logger.warning("ignoring malformed subscription %r", chunk)
            continue
        out.append(
            {
                "farm_id": int(farm_raw),
                "field_id": int(field_raw) if field_raw.isdigit() else None,
                "station_id": station,
            }
        )
    return out


def window_bucket(now, every_seconds: int = 3600) -> int:
    return int(now.timestamp()) // max(1, every_seconds)


@task(
    "ingest.enqueue_due_weather",
    queue="ingest",
    max_attempts=1,
    priority=50,
    description="Fan out one ingest.run_source job per configured weather subscription.",
)
def enqueue_due_weather(db, payload: dict) -> dict:
    """One job per subscription per hourly bucket.

    max_attempts=1 because a fan-out that fails is re-run by the next schedule tick
    anyway; retrying it would only duplicate the enqueue attempt, which the idempotency
    key would then swallow.
    """
    now = clock.current_datetime()
    subscriptions = payload.get("subscriptions") or parse_subscriptions(
        os.getenv(SUBSCRIPTIONS_ENV)
    )
    source_key = payload.get("source_key", "cimis_hourly")
    bucket = window_bucket(now)

    enqueued = []
    for sub in subscriptions:
        key = f"ingest:{source_key}:{sub['farm_id']}:{sub['station_id']}:{bucket}"
        job = queue.enqueue(
            db,
            "ingest.run_source",
            {
                "source_key": source_key,
                "farm_id": sub["farm_id"],
                "field_id": sub.get("field_id"),
                "station_id": sub["station_id"],
                "lookback_hours": payload.get("lookback_hours", DEFAULT_LOOKBACK_HOURS),
            },
            idempotency_key=key,
            source_key=source_key,
        )
        enqueued.append(job.id)
    return {"enqueued": enqueued, "subscriptions": len(subscriptions)}


@task(
    "ingest.run_source",
    queue="ingest",
    max_attempts=5,
    description="Fetch, validate and persist one source over one window.",
)
def run_source_task(db, payload: dict) -> dict:
    """Run one window for one subscription.

    Returns the run's counts rather than raising on data problems: a run that dropped
    every row is a recorded fact an operator can act on, not an exception. Only a
    genuine programming error escapes, and the queue's retry/dead-letter path handles it.
    """
    source_key = payload["source_key"]
    farm_id = int(payload["farm_id"])
    station_id = payload["station_id"]
    field_id = payload.get("field_id")
    lookback = int(payload.get("lookback_hours", DEFAULT_LOOKBACK_HOURS))

    now = clock.current_datetime()
    farm = db.get(models.Farm, farm_id)
    field = db.get(models.Field, field_id) if field_id else None

    ctx = base.IngestContext(
        farm_id=farm_id,
        field_id=field_id,
        station_id=station_id,
        window_start=now - timedelta(hours=lookback),
        window_end=now,
        field_lat=getattr(field, "centroid_lat", None),
        field_lon=getattr(field, "centroid_lon", None),
        # A demo farm's ingested rows must be demo rows, or `ensure_demo_real_separation`
        # rejects the batch and — worse — a simulated reading could reach a real metric.
        is_demo=bool(farm is not None and farm.data_source == "demo"),
    )

    adapter = registry.build_adapter(source_key)
    run = pipeline.run_source(db, adapter, ctx, job_id=payload.get("_job_id"))
    return {
        "ingestion_run_id": run.id,
        "status": run.status,
        "fetched": run.fetched_count,
        "admitted": run.admitted_count,
        "duplicate": run.duplicate_count,
        "issues": run.issue_count,
    }
