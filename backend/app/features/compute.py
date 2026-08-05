"""Gather inputs, run features, store results. The only DB-touching module here.

Two responsibilities, and the second is the interesting one:

1. Load the inputs each feature needs and call it. Loading is per-entity and explicit —
   a feature never gets a session, so it cannot widen its own inputs without a visible
   change to this file.

2. Persist, with a leak check. Because `pit.admissible` excludes anything recorded after
   `as_of`, recomputing at a FIXED `as_of` must reproduce the identical `inputs_digest`
   forever. So a differing digest at an unchanged `as_of` is proof that something
   became visible which should not have been — and it is recorded as an issue rather
   than silently overwritten.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock, crud, models, pit
from app.features import base
from app.features.base import ENTITY_BLOCK, ENTITY_CROP_CYCLE, ENTITY_FIELD, FeatureResult
from app.features.pit_view import spray_views

# Namespace for the inputs digest. Bumping it deliberately invalidates every stored
# digest, which is correct only when the MEANING of a feature's inputs changes.
DIGEST_NAMESPACE = "feature-inputs-v1"

# Recorded when a fixed-`as_of` recompute disagrees with what is stored.
DIGEST_DRIFT_CODE = "feature_inputs_digest_drift"

# Square metres in a hectare. Definitional (SI), so it needs no external citation.
_M2_PER_HA = 10_000.0


def _digest_for(spec: base.FeatureSpec, entity_id: int, as_of: datetime, inputs) -> str:
    """Content digest of the ADMISSIBLE inputs, not of the raw query result.

    Digesting the admissible set is what makes the drift check meaningful: a row that
    arrives later but is correctly excluded must not change the digest, or the detector
    would fire on every ordinary late entry and be turned off within a week.
    """
    return pit.digest_of(
        {
            "feature": spec.key,
            "entity": [spec.entity_type, entity_id],
            "as_of": as_of.isoformat(),
            "inputs": inputs,
        },
        DIGEST_NAMESPACE,
    )


# --------------------------------------------------------------------------
# Input loading, one loader per entity type.
# --------------------------------------------------------------------------


def _field_inputs(db: Session, field: models.Field, as_of: datetime) -> dict:
    observations = list(
        db.scalars(
            select(models.WeatherObservation)
            .where(models.WeatherObservation.field_id == field.id)
            .order_by(models.WeatherObservation.observed_at)
        )
    )
    return {"observations": observations, "as_of": as_of}


def _crop_cycle_inputs(db: Session, cycle: models.CropCycle, as_of: datetime) -> dict:
    applications = list(
        db.scalars(
            select(models.SprayEvent)
            .where(models.SprayEvent.crop_cycle_id == cycle.id)
            .order_by(models.SprayEvent.application_date)
        )
    )
    planted_area_ha = (
        float(cycle.planted_area_m2) / _M2_PER_HA
        if cycle.planted_area_m2
        else None
    )
    return {
        "applications": applications,
        "planted_area_ha": planted_area_ha,
        # Concentrations come ONLY from labels a PCA verified for THIS farm. An
        # unverified transcription is on file, not in force, and a quantity computed
        # from one would be a number nobody attested to.
        "concentrations": crud.ai_concentrations_for_farm(db, cycle.farm_id),
        "as_of": as_of,
    }


def _block_inputs(db: Session, block: models.Block, as_of: datetime) -> dict:
    samples = list(
        db.scalars(
            select(models.ScoutingSample)
            .where(models.ScoutingSample.block_id == block.id)
            .order_by(models.ScoutingSample.observed_at)
        )
    )
    return {"samples": samples, "as_of": as_of}


_LOADERS = {
    ENTITY_FIELD: (models.Field, _field_inputs),
    ENTITY_CROP_CYCLE: (models.CropCycle, _crop_cycle_inputs),
    ENTITY_BLOCK: (models.Block, _block_inputs),
}


def _digest_inputs(spec: base.FeatureSpec, inputs: dict) -> dict:
    """A stable, small description of the ADMISSIBLE inputs.

    Digesting the admissible set rather than everything the query returned is what makes
    the drift check meaningful. A row that arrives later but is correctly excluded must
    NOT move the digest — otherwise the detector fires on every ordinary late entry, and
    an alarm that cries wolf is switched off within a week, taking the real signal with
    it.

    So this deliberately runs the same `pit` filter the features themselves run. The two
    could drift apart, which is why `test_recomputing_at_a_fixed_as_of_reproduces_the_
    digest_after_more_data_arrives` exercises both together.
    """
    as_of = inputs["as_of"]
    summary: dict = {}

    def rows_for(key, adapt=None):
        rows = inputs.get(key)
        if rows is None:
            return None
        candidates = adapt(rows) if adapt else rows
        admitted, _ = pit.partition(candidates, as_of, kind=key)
        return [
            [
                getattr(r, "id", None),
                str(getattr(r, "observed_at", None)),
                str(getattr(r, "recorded_at", None)),
            ]
            for r in admitted
        ]

    for key in ("observations", "samples"):
        admitted = rows_for(key)
        if admitted is not None:
            summary[key] = admitted

    applications = rows_for("applications", adapt=spray_views)
    if applications is not None:
        summary["applications"] = applications

    if "planted_area_ha" in inputs:
        summary["planted_area_ha"] = inputs["planted_area_ha"]
    if "concentrations" in inputs:
        summary["concentrations"] = sorted(inputs["concentrations"])
    return summary


# --------------------------------------------------------------------------
# Compute + persist.
# --------------------------------------------------------------------------


def compute_one(
    db: Session, spec: base.FeatureSpec, entity_id: int, as_of: datetime
) -> tuple[FeatureResult, str]:
    """Run one feature for one entity. Returns the result and its inputs digest."""
    model, loader = _LOADERS[spec.entity_type]
    entity = db.get(model, entity_id)
    if entity is None:
        raise base.FeatureError(
            f"{spec.entity_type} {entity_id} does not exist"
        )
    inputs = loader(db, entity, as_of)
    digest = _digest_for(spec, entity_id, as_of, _digest_inputs(spec, inputs))
    result = spec.compute(**inputs)
    return result, digest


def persist(
    db: Session,
    spec: base.FeatureSpec,
    entity_id: int,
    as_of: datetime,
    result: FeatureResult,
    digest: str,
    *,
    farm_id: int | None = None,
) -> models.FeatureValue:
    """Upsert a feature value, refusing to overwrite when the digest has drifted.

    A differing digest at an unchanged `as_of` is not a recompute, it is evidence of a
    point-in-time leak. Overwriting would destroy the only signal that it happened, so
    the stored row is left alone and the disagreement is recorded.
    """
    existing = db.scalar(
        select(models.FeatureValue).where(
            models.FeatureValue.entity_type == spec.entity_type,
            models.FeatureValue.entity_id == entity_id,
            models.FeatureValue.name == spec.name,
            models.FeatureValue.version == spec.version,
            models.FeatureValue.as_of == as_of,
        )
    )

    if existing is not None and existing.inputs_digest != digest:
        db.add(
            models.IngestionIssue(
                ingestion_run_id=_drift_run_id(db, spec, farm_id),
                stage="persist",
                severity="error",
                code=DIGEST_DRIFT_CODE,
                message=(
                    f"{spec.key} for {spec.entity_type} {entity_id} at {as_of.isoformat()} "
                    f"recomputed to a DIFFERENT inputs digest. At a fixed as_of this is "
                    f"impossible unless an input became visible that should not have "
                    f"been. The stored value was left unchanged."
                ),
                natural_key=f"{spec.key}:{spec.entity_type}:{entity_id}:{as_of.isoformat()}",
                detail={"stored": existing.inputs_digest, "recomputed": digest},
            )
        )
        db.commit()
        return existing

    row = existing or models.FeatureValue(
        name=spec.name, version=spec.version, entity_type=spec.entity_type,
        entity_id=entity_id, as_of=as_of, farm_id=farm_id,
    )
    row.value = result.value
    row.unit = result.unit or spec.unit
    row.evidence_grade = result.evidence_grade
    row.abstained = result.abstained
    row.reasons = list(result.reasons)
    row.excluded = list(result.excluded)
    row.inputs_digest = digest
    row.computed_at = clock.current_datetime()
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _drift_run_id(db: Session, spec, farm_id) -> int:
    """Digest drift is recorded against a synthetic run, so it lands where an operator
    already looks rather than in a log nobody tails."""
    run = models.IngestionRun(
        source_key="features.recompute", domain=spec.domain, farm_id=farm_id,
        status="failed", adapter_version=str(spec.version),
        error="inputs digest drift at a fixed as_of",
    )
    db.add(run)
    db.flush()
    return run.id


def recompute_for_entity(
    db: Session, entity_type: str, entity_id: int, as_of: datetime | None = None,
    farm_id: int | None = None,
) -> list[models.FeatureValue]:
    """Every registered feature for one entity, in dependency order."""
    as_of = as_of or clock.current_datetime()
    specs = [s for s in base.resolve_order() if s.entity_type == entity_type]
    out = []
    for spec in specs:
        result, digest = compute_one(db, spec, entity_id, as_of)
        out.append(persist(db, spec, entity_id, as_of, result, digest, farm_id=farm_id))
    return out
