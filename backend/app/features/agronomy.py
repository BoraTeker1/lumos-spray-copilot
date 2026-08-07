"""Agronomic features for the domains admitted on 2026-08-07.

Framework-free (stdlib + `app.pit`, `app.features.base`).

These are the derived values the finance layer will read: `credit_scoring` consumes
`FeatureResult`s rather than raw rows precisely so that a missing input abstains the
score instead of scoring as zero. That contract is only worth anything if the features
themselves abstain honestly, which is what this module is careful about.

The recurring judgment call here is **which gaps are abstentions and which are true
zeros**, and it is decided per feature rather than by a blanket rule:

* `soil_test_recency_days` — no soil test is an abstention. A farm that has never
  tested is not a farm with a zero-day-old test, and it is not a farm with an
  infinitely old one either; it is a farm nobody can answer the question for.
* `applied_irrigation_mm` — no irrigation *events* on a farm that records irrigation
  is a genuine zero (they irrigated nothing this window). No irrigation *recording at
  all* is an abstention. The difference is whether the farm keeps this record type,
  which is why the caller passes `records_irrigation` explicitly rather than letting
  an empty list decide.

That second distinction is the same one `weather.weather_observation_coverage_pct`
makes — it is the one place in that module where `0.0` is allowed to mean zero, because
a configured station reporting nothing is a real measurement of nothing.
"""
from __future__ import annotations

from app import pit
from app.features.base import ENTITY_CROP_CYCLE, ENTITY_FARM, FeatureResult, feature

# --- soil -------------------------------------------------------------------
DOMAIN_SOIL = "soil"
NO_SOIL_TEST = "no_soil_test_recorded"

# --- fertilization ----------------------------------------------------------
DOMAIN_FERTILIZATION = "fertilization"
NO_FERTILIZER_APPLICATIONS = "no_fertilizer_applications_recorded"
NO_PLANTED_AREA = "no_planted_area_recorded"
SOME_APPLICATIONS_HAVE_NO_NUTRIENT_MASS = "some_applications_have_no_nutrient_mass"

# --- water / energy ---------------------------------------------------------
# There is no `irrigation` domain among the seventeen. Water features register under
# `land_selection`, which is the domain that actually declares them; inventing an
# eighteenth domain here to make an import read better would put the feature registry
# and the domain registry out of step. `app/irrigation.py` is the model regardless.
DOMAIN_WATER = "land_selection"
DOMAIN_ENERGY = "energy"
FARM_DOES_NOT_RECORD_IRRIGATION = "farm_does_not_record_irrigation"
NO_ENERGY_RECORDS = "no_energy_use_recorded"


@feature(
    "soil_test_recency_days", version=1, entity_type=ENTITY_FARM,
    domain=DOMAIN_SOIL, unit="d",
)
def soil_test_recency_days(*, soil_tests, as_of, **_):
    """Days since the most recent admissible soil test.

    Reports the number only — no fresh/stale verdict. What counts as a stale soil test
    depends on the analyte and the crop, and putting a threshold here would be a second
    copy of a judgment that belongs in `soil_thresholds`, drifting from it on first edit.
    Same reasoning as `pest.scouting_recency_days`.
    """
    admitted, excluded = pit.partition(soil_tests or [], as_of, kind="soil_test")
    dates = [t.observed_at for t in admitted if getattr(t, "observed_at", None) is not None]
    if not dates:
        return FeatureResult.abstain(NO_SOIL_TEST, as_of=as_of, excluded=excluded)
    days = (as_of - max(dates)).total_seconds() / 86400.0
    return FeatureResult.computed(round(max(days, 0.0), 2), "d", as_of=as_of,
                                  excluded=excluded)


@feature(
    "nutrient_applied_kg_per_ha", version=1, entity_type=ENTITY_CROP_CYCLE,
    domain=DOMAIN_FERTILIZATION, unit="kg/ha",
)
def nutrient_applied_kg_per_ha(*, applications, planted_area_ha, as_of, **_):
    """Nutrient mass applied per hectare over a crop cycle.

    All-or-nothing, for the identical reason as `pest.active_ingredient_kg_per_ha`: a
    partial total is a *smaller* number, not an approximate one, and the applications
    missing a nutrient mass are disproportionately the ones entered in a hurry — which
    biases the total downward exactly where a reader would read it as "we applied less".
    """
    admitted, excluded = pit.partition(applications or [], as_of, kind="fertilizer_application")
    if not admitted:
        return FeatureResult.abstain(NO_FERTILIZER_APPLICATIONS, as_of=as_of,
                                     excluded=excluded)
    if not planted_area_ha:
        return FeatureResult.abstain(NO_PLANTED_AREA, as_of=as_of, excluded=excluded)

    masses = [getattr(a, "nutrient_kg", None) for a in admitted]
    missing = sum(1 for m in masses if m is None)
    if missing:
        return FeatureResult.abstain(
            f"{SOME_APPLICATIONS_HAVE_NO_NUTRIENT_MASS} ({missing} of {len(masses)})",
            as_of=as_of, excluded=excluded,
        )
    return FeatureResult.computed(
        round(sum(masses) / planted_area_ha, 4), "kg/ha", as_of=as_of, excluded=excluded,
    )


@feature(
    "applied_irrigation_mm", version=1, entity_type=ENTITY_CROP_CYCLE,
    domain=DOMAIN_WATER, unit="mm",
)
def applied_irrigation_mm(*, irrigation_events, records_irrigation, as_of, **_):
    """Irrigation depth applied over a crop cycle.

    `records_irrigation` is passed explicitly rather than inferred from an empty list,
    and that is the whole point of this feature's signature. "This farm applied no
    irrigation this window" and "this farm does not log irrigation" are different facts
    that produce the same empty list, and only one of them is a zero. Inferring would
    report every farm without an irrigation log as a farm running entirely on rainfall.
    """
    if not records_irrigation:
        return FeatureResult.abstain(FARM_DOES_NOT_RECORD_IRRIGATION, as_of=as_of)

    admitted, excluded = pit.partition(irrigation_events or [], as_of,
                                       kind="irrigation_event")
    depths = [getattr(e, "depth_mm", None) for e in admitted]
    if any(d is None for d in depths):
        missing = sum(1 for d in depths if d is None)
        return FeatureResult.abstain(
            f"some_irrigation_events_have_no_depth ({missing} of {len(depths)})",
            as_of=as_of, excluded=excluded,
        )
    # A true zero: the farm keeps this record type and recorded no water this window.
    return FeatureResult.computed(round(sum(depths), 2), "mm", as_of=as_of,
                                  excluded=excluded)


@feature(
    "energy_use_kwh_per_ha", version=1, entity_type=ENTITY_CROP_CYCLE,
    domain=DOMAIN_ENERGY, unit="kWh/ha",
)
def energy_use_kwh_per_ha(*, energy_records, planted_area_ha, as_of, **_):
    """Energy use per hectare over a crop cycle.

    The `energy` domain's rationale in the registry said "nothing computes it". This is
    the first thing that does. Conversions come from `app/units.py`, which already
    carries kWh/Wh/MWh/MJ/kJ/therm — the caller is expected to have normalised to kWh
    via `units`, and a record in another unit abstains rather than being coerced here.
    """
    admitted, excluded = pit.partition(energy_records or [], as_of, kind="energy_record")
    if not admitted:
        return FeatureResult.abstain(NO_ENERGY_RECORDS, as_of=as_of, excluded=excluded)
    if not planted_area_ha:
        return FeatureResult.abstain(NO_PLANTED_AREA, as_of=as_of, excluded=excluded)

    values = [getattr(r, "kwh", None) for r in admitted]
    missing = sum(1 for v in values if v is None)
    if missing:
        return FeatureResult.abstain(
            f"some_energy_records_have_no_kwh ({missing} of {len(values)})",
            as_of=as_of, excluded=excluded,
        )
    return FeatureResult.computed(
        round(sum(values) / planted_area_ha, 2), "kWh/ha", as_of=as_of, excluded=excluded,
    )
