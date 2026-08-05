"""Background recomputation of features.

Same fan-out/worker split as ingestion: one scheduled task decides what needs
recomputing, another recomputes one entity. The idempotency key buckets by `as_of`, so
a schedule that fires twice inside a bucket recomputes once.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from app import clock, models
from app.features import base, compute
from app.jobs import queue
from app.jobs.registry import task

# How `as_of` is snapped for the idempotency key. Hourly: finer would recompute
# constantly for no new information, coarser would leave a stale card up for too long.
AS_OF_BUCKET_SECONDS = 3600


def as_of_bucket(now) -> int:
    return int(now.timestamp()) // AS_OF_BUCKET_SECONDS


@task(
    "features.recompute",
    queue="features",
    max_attempts=3,
    description="Recompute every registered feature for one entity at one as_of.",
)
def recompute(db, payload: dict) -> dict:
    entity_type = payload["entity_type"]
    entity_id = int(payload["entity_id"])
    as_of = (
        datetime.fromisoformat(payload["as_of"])
        if payload.get("as_of")
        else clock.current_datetime()
    )
    rows = compute.recompute_for_entity(
        db, entity_type, entity_id, as_of, farm_id=payload.get("farm_id")
    )
    return {
        "computed": len(rows),
        "abstained": sum(1 for r in rows if r.abstained),
    }


@task(
    "features.recompute_due",
    queue="features",
    max_attempts=1,
    priority=60,
    description="Fan out one features.recompute job per entity that has features.",
)
def recompute_due(db, payload: dict) -> dict:
    """One job per entity per as_of bucket.

    Entity discovery is a plain query per entity type in the registry: features are
    declared against `field`, `crop_cycle` and `block`, so those are what get enqueued.
    A farm with none of them enqueues nothing.
    """
    now = clock.current_datetime()
    bucket = as_of_bucket(now)
    entity_types = {spec.entity_type for spec in base.REGISTRY.values()}

    models_by_type = {
        base.ENTITY_FIELD: models.Field,
        base.ENTITY_CROP_CYCLE: models.CropCycle,
        base.ENTITY_BLOCK: models.Block,
    }

    enqueued = []
    for entity_type in sorted(entity_types):
        model = models_by_type.get(entity_type)
        if model is None:
            continue
        for entity in db.scalars(select(model)):
            key = f"feature:{entity_type}:{entity.id}:{bucket}"
            job = queue.enqueue(
                db,
                "features.recompute",
                {
                    "entity_type": entity_type,
                    "entity_id": entity.id,
                    "farm_id": getattr(entity, "farm_id", None),
                    "as_of": now.isoformat(),
                },
                idempotency_key=key,
                source_key="features",
            )
            enqueued.append(job.id)
    return {"enqueued": len(enqueued)}
