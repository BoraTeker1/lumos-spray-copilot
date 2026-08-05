"""Crop-protection features: the two that bear directly on pesticide reduction.

Framework-free (stdlib + `app.pit`, `app.label_data`, `app.features.pit_view`).

Both features here are all-or-nothing, for the same reason and in the same direction:
a partial total reads as a smaller number rather than as an incomplete one, and both of
these numbers are ones a grower or investor would read as "we used less" / "we rotated
well". Getting that wrong is not a rounding error, it is a claim.
"""
from __future__ import annotations

from app import label_data, pit, units
from app.features.base import ENTITY_BLOCK, ENTITY_CROP_CYCLE, FeatureResult, feature
from app.features.pit_view import spray_views

DOMAIN = "crop_protection"

NO_APPLICATIONS = "no_applications_recorded"
NO_PLANTED_AREA = "no_planted_area_recorded"
NO_MOA_ON_EVERY_APPLICATION = "some_applications_have_no_moa_group"
TOO_FEW_APPLICATIONS_TO_ROTATE = "fewer_than_two_applications"
NO_SCOUTING_SAMPLE = "no_scouting_sample_for_this_block"


@feature(
    "active_ingredient_kg_per_ha", version=1, entity_type=ENTITY_CROP_CYCLE,
    domain=DOMAIN, unit="kg/ha",
)
def active_ingredient_kg_per_ha(*, applications, planted_area_ha, concentrations, as_of,
                                **_):
    """Active-ingredient mass applied per hectare over a crop cycle.

    ALL-OR-NOTHING. If ANY application cannot be converted, the whole feature abstains
    and carries every refusal reason verbatim, naming the application that blocked it.

    This mirrors `label_data.ai_quantity`'s own rule, and the reasoning is worth
    repeating: a total that silently omits three of eleven applications is not an
    approximate total, it is a smaller one. Someone reading "1.2 kg/ha" has no way to
    know it should have been 3.4, and the error runs in the flattering direction —
    which is exactly the direction a pesticide-reduction claim must never drift.

    On today's data this abstains for nearly every farm, because only two products have
    a transcribed label concentration on file. Naming WHICH applications blocked it
    turns that into a work item (transcribe those labels) rather than a dead end.
    """
    if not applications:
        return FeatureResult.abstain(NO_APPLICATIONS, as_of=as_of)
    if not planted_area_ha or planted_area_ha <= 0:
        return FeatureResult.abstain(NO_PLANTED_AREA, as_of=as_of)

    admitted, excluded = pit.partition(spray_views(applications), as_of, kind="spray")
    if not admitted:
        return FeatureResult.abstain(NO_APPLICATIONS, as_of=as_of, excluded=excluded)

    total_kg = 0.0
    refusals: list[str] = []
    provenance: set[str] = set()

    for view in admitted:
        row = view.source
        reg_no = label_data.normalize_epa_reg_no(getattr(row, "epa_reg_no", None))
        concentration = concentrations.get(reg_no) if reg_no else None
        amount, unit = concentration if concentration else (None, None)

        quantity = label_data.ai_quantity(
            getattr(row, "rate_amount", None),
            getattr(row, "rate_unit", None),
            getattr(row, "treated_acres", None),
            getattr(row, "treated_area_unit", None),
            amount,
            unit,
        )
        label = getattr(row, "product_name", None) or f"application #{view.id}"
        if isinstance(quantity, label_data.Refusal):
            refusals.append(f"{label} ({view.observed_at:%Y-%m-%d}): {quantity.reason}")
            continue

        # `ai_quantity` returns the mass in whatever unit the RATE was expressed in —
        # oz for oz/acre, lb for lb/acre, kg for kg/ha. Normalising goes through
        # `units`, which refuses rather than guessing, so an unconvertible unit becomes
        # one more named reason instead of an exception that loses the whole run.
        as_kg = units.convert(quantity.amount, quantity.unit, "kg")
        if isinstance(as_kg, units.Refusal):
            refusals.append(f"{label} ({view.observed_at:%Y-%m-%d}): {as_kg.reason}")
            continue
        total_kg += as_kg.amount
        provenance.update(quantity.conversion_provenance)
        provenance.update(as_kg.conversion_provenance)

    if refusals:
        return FeatureResult.abstain(*refusals, as_of=as_of, excluded=excluded)

    return FeatureResult.computed(
        round(total_kg / planted_area_ha, 4), "kg/ha", as_of=as_of, excluded=excluded,
    )


@feature(
    "moa_rotation_diversity", version=1, entity_type=ENTITY_CROP_CYCLE,
    domain=DOMAIN, unit="ratio",
)
def moa_rotation_diversity(*, applications, as_of, **_):
    """Distinct mode-of-action groups over total applications, in [0, 1].

    ABSTAINS IF ANY APPLICATION LACKS AN MoA GROUP, and this is the load-bearing
    decision. Scoring only the subset that happens to have MoA recorded reports BETTER
    rotation than reality: the applications most likely to be missing a MoA group are
    the ones logged carelessly, which are disproportionately the repeat sprays of a
    familiar product — precisely the ones that drag diversity down.

    So a partial answer here is not merely incomplete, it is biased toward the
    flattering direction, on a resistance-management number. Refusing is the only
    honest option.
    """
    if not applications:
        return FeatureResult.abstain(NO_APPLICATIONS, as_of=as_of)

    admitted, excluded = pit.partition(spray_views(applications), as_of, kind="spray")
    if len(admitted) < 2:
        return FeatureResult.abstain(
            TOO_FEW_APPLICATIONS_TO_ROTATE, as_of=as_of, excluded=excluded
        )

    groups = [
        (getattr(view.source, "moa_group", None) or "").strip() for view in admitted
    ]
    if not all(groups):
        missing = sum(1 for g in groups if not g)
        return FeatureResult.abstain(
            f"{NO_MOA_ON_EVERY_APPLICATION} ({missing} of {len(groups)})",
            as_of=as_of, excluded=excluded,
        )

    return FeatureResult.computed(
        round(len(set(groups)) / len(groups), 4), "ratio", as_of=as_of, excluded=excluded,
    )


@feature(
    "scouting_recency_days", version=1, entity_type=ENTITY_BLOCK,
    domain=DOMAIN, unit="d",
)
def scouting_recency_days(*, samples, as_of, **_):
    """Days since the most recent admissible scouting sample for a block.

    Reports the NUMBER ONLY. It deliberately does not compare against
    `disease_risk.MAX_SCOUTING_AGE_DAYS` or emit a stale/fresh verdict: that threshold
    belongs to the pilot's assessment contract, and a second copy of it here would
    drift from the original the first time either changed.
    """
    admitted, excluded = pit.partition(samples or [], as_of, kind="scouting_sample")
    timestamps = [s.observed_at for s in admitted if s.observed_at is not None]
    if not timestamps:
        return FeatureResult.abstain(NO_SCOUTING_SAMPLE, as_of=as_of, excluded=excluded)
    days = (as_of - max(timestamps)).total_seconds() / 86400.0
    return FeatureResult.computed(round(max(days, 0.0), 2), "d", as_of=as_of,
                                  excluded=excluded)
