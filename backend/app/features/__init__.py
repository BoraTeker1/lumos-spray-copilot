"""Derived values over held data, each of which abstains rather than guessing.

    base.py      PURE  FeatureSpec, FeatureResult, register(), REGISTRY, resolve_order()
    pit_view.py  PURE  gives non-observation rows a point-in-time shape
    weather.py   PURE  climate features
    pest.py      PURE  crop_protection features
    agronomy.py  PURE  soil / fertilization / water / energy features (2026-08-07)
    compute.py         the ONLY DB-touching module
    tasks.py           the recompute job

The one invariant everything else rests on lives in `FeatureResult.__post_init__`: a
result is abstained if and only if it has no value. There is no "abstained but here is a
number anyway" state, so no card can ever render an abstention as `0` — which is the
specific way a data-quality gap turns into a false claim about a farm.
"""
from app.features import base, pit_view, weather, pest, agronomy  # noqa: F401
from app.features import compute, tasks  # noqa: F401,E402
