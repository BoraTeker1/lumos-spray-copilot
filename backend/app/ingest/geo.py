"""Great-circle distance. Framework-free (stdlib only).

Exists as its own module because `station_distance_km` is load-bearing in a way that is
easy to miss: `disease_risk` treats a NULL distance as in-range, so a pipeline that
cannot compute a distance must drop the row rather than write a null. That makes this
twelve-line function a correctness dependency of the pilot, not a utility.
"""
from __future__ import annotations

import math

# Mean Earth radius (IUGG). Distances here are between a field centroid and a weather
# station tens of kilometres away at most, where the spherical approximation is well
# under the precision anyone acts on.
EARTH_RADIUS_KM = 6371.0088


def haversine_km(
    lat1: float | None, lon1: float | None, lat2: float | None, lon2: float | None
) -> float | None:
    """Distance in km, or None when any coordinate is missing.

    None means "cannot be computed" and callers must treat it as a reason to drop a
    row. It must never be coerced to 0.0, which would assert the station sits on top of
    the field.
    """
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return None
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))
