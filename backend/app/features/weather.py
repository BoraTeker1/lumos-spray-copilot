"""Climate features. Framework-free (stdlib + `app.pit`).

Three features, and the third one is the honest centrepiece: `leaf_wetness_hours`
abstains permanently on CIMIS-only data, because CIMIS publishes no wetness item. That
is not a gap to be worked around — it is the measured, farm-specific statement of what
an on-site sensor would buy. Reporting it as a number derived from humidity would turn
a procurement question into a fabricated input.
"""
from __future__ import annotations

from datetime import timedelta

from app import pit
from app.features.base import ENTITY_FIELD, FeatureResult, feature

DOMAIN = "climate"

# Abstention reasons. Named constants so a surface can branch on them and a test can
# assert on them without matching prose.
NO_STATION_CONFIGURED = "no_station_configured_for_this_field"
NO_ADMISSIBLE_WEATHER = "no_admissible_weather_at_this_as_of"
NO_MEASURED_LEAF_WETNESS = "no_measured_leaf_wetness"
DERIVED_WETNESS_PRESENT = "derived_wetness_present_but_no_cited_method"


def _admissible(observations, as_of):
    return pit.partition(observations or [], as_of, kind="weather")


@feature(
    "weather_observation_coverage_pct", version=1, entity_type=ENTITY_FIELD,
    domain=DOMAIN, unit="pct",
)
def weather_observation_coverage_pct(*, observations, as_of, window_hours=168, **_):
    """Share of the trailing window that has an admissible hourly reading.

    THE ONE PLACE A ZERO IS NOT A LIE. If a station is configured and returned nothing,
    `0.0` is the true and useful answer: coverage really is zero, and the operator needs
    to see it as a number that can be compared against last week's. Contrast every other
    feature here, where a zero would mean "no data" and would read as "no risk".

    The distinction is carried by the abstention above it: no station configured at all
    means we cannot speak to coverage, and that abstains.
    """
    if not observations:
        return FeatureResult.abstain(NO_STATION_CONFIGURED, as_of=as_of)

    admitted, excluded = _admissible(observations, as_of)
    window_start = as_of - timedelta(hours=window_hours)
    in_window = {
        row.observed_at.replace(minute=0, second=0, microsecond=0)
        for row in admitted
        if row.observed_at is not None and window_start <= row.observed_at <= as_of
    }
    coverage = 100.0 * len(in_window) / max(1, window_hours)
    return FeatureResult.computed(
        round(min(coverage, 100.0), 2), "pct", as_of=as_of, excluded=excluded
    )


@feature(
    "weather_data_staleness_hours", version=1, entity_type=ENTITY_FIELD,
    domain=DOMAIN, unit="h",
)
def weather_data_staleness_hours(*, observations, as_of, **_):
    """Hours since the most recent admissible reading.

    Abstains when there is none, rather than returning a very large number. "9999 hours
    stale" and "no data at all" are different facts, and a threshold alert built on the
    first would fire identically for both while meaning something else.
    """
    admitted, excluded = _admissible(observations or [], as_of)
    timestamps = [r.observed_at for r in admitted if r.observed_at is not None]
    if not timestamps:
        return FeatureResult.abstain(NO_ADMISSIBLE_WEATHER, as_of=as_of, excluded=excluded)
    hours = (as_of - max(timestamps)).total_seconds() / 3600.0
    return FeatureResult.computed(round(max(hours, 0.0), 2), "h", as_of=as_of,
                                  excluded=excluded)


@feature(
    "leaf_wetness_hours", version=1, entity_type=ENTITY_FIELD,
    domain=DOMAIN, unit="h",
)
def leaf_wetness_hours(*, observations, as_of, window_hours=168, **_):
    """Measured leaf-wetness hours in the trailing window. Abstains on anything else.

    THIS FEATURE ABSTAINS PERMANENTLY ON CIMIS-ONLY DATA, AND THAT IS THE POINT. CIMIS
    publishes no leaf-wetness item, so a farm served only by a CIMIS station has no
    wetness datum, and the feature says so by name instead of returning 0.0.

    Two distinct abstentions, and the second one matters more than it looks:

      * `no_measured_leaf_wetness` — nothing carries a wetness value at all.
      * `derived_wetness_present_but_no_cited_method` — some rows DO carry wetness, but
        with `wetness_is_measured=False`. The tempting move is to drop those rows and
        total the rest. That would report a real number computed over an arbitrary
        subset, which reads as a complete measurement. So the whole feature abstains.

    It never derives wetness from relative humidity. `disease_risk` accepts no proxy
    because the derivation would itself need a cited source, and inventing one here
    would launder a guess into a measurement.
    """
    admitted, excluded = _admissible(observations or [], as_of)
    window_start = as_of - timedelta(hours=window_hours)
    in_window = [
        r for r in admitted
        if r.observed_at is not None and window_start <= r.observed_at <= as_of
    ]

    with_wetness = [
        r for r in in_window if getattr(r, "leaf_wetness_minutes", None) is not None
    ]
    if not with_wetness:
        return FeatureResult.abstain(
            NO_MEASURED_LEAF_WETNESS, as_of=as_of, excluded=excluded
        )
    if any(not getattr(r, "wetness_is_measured", False) for r in with_wetness):
        return FeatureResult.abstain(
            DERIVED_WETNESS_PRESENT, as_of=as_of, excluded=excluded
        )

    minutes = sum(float(r.leaf_wetness_minutes) for r in with_wetness)
    return FeatureResult.computed(
        round(minutes / 60.0, 2), "h", as_of=as_of, excluded=excluded,
    )
