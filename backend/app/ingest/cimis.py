"""CIMIS hourly station data — the first and only outbound network call in this codebase.

CIMIS is the California Irrigation Management Information System, run by the Department
of Water Resources. It is the right first adapter for a Central Coast strawberry pilot:
public, free, dense in the wedge geography, and already named as the realistic weather
source in `DESIGN_PARTNER_SPRINT.md`.

THE HEADLINE, AND IT IS NOT THE GOOD ONE
----------------------------------------
**CIMIS does not report leaf wetness.** Verified 2026-08-05 against the published hourly
item catalog, which is: hly-air-tmp, hly-soil-tmp, hly-rel-hum, hly-eto, hly-asce-eto,
hly-asce-etr, hly-sol-rad, hly-net-rad, hly-wind-spd, hly-wind-dir, hly-res-wind,
hly-precip, hly-dew-pnt, hly-vap-pres. There is no wetness item.

So this adapter does NOT unblock the Botrytis assessment. It moves the binding blocker:

    BEFORE:  abstain — no_weather_in_window, thresholds_not_supplied
    AFTER:   abstain — no_leaf_wetness_or_accepted_proxy, thresholds_not_supplied

That is still worth building. `no_weather_in_window` was a software gap and is now
closed; `no_leaf_wetness_or_accepted_proxy` is a procurement decision (buy an on-site
sensor) and `thresholds_not_supplied` is a transcription task. Two vague blockers become
two named, farm-specific facts.

**This adapter must never derive `leaf_wetness_minutes` from relative humidity.**
`disease_risk` is explicit that no proxy is accepted, because the derivation would
itself need a cited source. Inventing one here would be the same failure as guessing the
Botrytis coefficients, one layer down — and it would be worse, because the fabricated
number would arrive wearing `wetness_is_measured` and look like evidence. The adapter
writes `leaf_wetness_minutes=None` and `wetness_is_measured=None`, and
`test_the_recorded_payload_carries_no_leaf_wetness_and_the_adapter_invents_none` exists
to keep it that way.

CREDENTIAL AND NETWORK CONFINEMENT
----------------------------------
Gating mirrors `vision._build_default_service`: without `LUMOS_CIMIS_APP_KEY`,
`describe()` returns `requires_credential` and the pipeline never calls `fetch`. Inert
by construction, not by discipline.

Every outbound request goes through the single `_http_get` below. `transport` exists so
tests can inject `httpx.MockTransport`; it is never set from application code.
`_redact` strips `appKey` before a request description can reach the object store, an
issue row, or a log — a credential that reaches durable storage is a leaked credential.
"""
from __future__ import annotations

import json
import os
from datetime import datetime

from app.ingest import registry
from app.ingest.base import (
    ISSUE_PARSE_FAILED,
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    SOURCE_IMPLEMENTED,
    SOURCE_REQUIRES_CREDENTIAL,
    STAGE_PARSE,
    FetchResult,
    IngestContext,
    Issue,
    SourceDescriptor,
)

SOURCE_KEY = "cimis_hourly"
ADAPTER_VERSION = "1"
API_KEY_ENV = "LUMOS_CIMIS_APP_KEY"
BASE_URL_ENV = "LUMOS_CIMIS_BASE_URL"
DEFAULT_BASE_URL = "https://et.water.ca.gov"
DEFAULT_TIMEOUT_SECONDS = 30.0

CREDENTIAL_BLOCKER = (
    f"Set {API_KEY_ENV} to a CIMIS AppKey (free, from et.water.ca.gov) to enable this "
    f"source. Without it no request is made and every run is recorded as "
    f"skipped_no_credential."
)

# The hourly items we ask for. Every one maps onto a column that already exists on
# `WeatherObservation`; we deliberately do not request items we have nowhere to put,
# because an unused column is a future temptation to invent a meaning for it.
HOURLY_ITEMS = ("hly-air-tmp", "hly-rel-hum", "hly-precip")

# CIMIS QC flags. An empty flag (or a space) means the value passed QC. Anything else is
# carried onto `quality_flag`, and `pit.admissible` then excludes the row entirely
# rather than averaging over a reading the station itself doubts.
_GOOD_QC_FLAGS = {"", " ", "*"}


def _redact(params: dict) -> dict:
    """Everything about a request except the thing that must never be stored."""
    return {k: v for k, v in params.items() if k.lower() != "appkey"}


def _http_get(
    path: str,
    params: dict,
    *,
    base_url: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    transport=None,
) -> bytes:
    """The only outbound HTTP call in this codebase.

    `httpx` is imported lazily so the module — and therefore the source registry, and
    therefore `/internal/ingestion/sources` — keeps working in an environment where the
    dependency is absent.
    """
    import httpx

    base = base_url or os.getenv(BASE_URL_ENV) or DEFAULT_BASE_URL
    client_kwargs = {"timeout": timeout, "base_url": base}
    if transport is not None:
        client_kwargs["transport"] = transport
    with httpx.Client(**client_kwargs) as client:
        response = client.get(path, params=params)
        response.raise_for_status()
        return response.content


def _parse_number(raw) -> float | None:
    """CIMIS reports a value as {"Value": "15.2", "Qc": " "}. Absent stays absent."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _quality_flag(*records) -> str | None:
    """The first QC flag that is not a pass, or None.

    Any flag at all excludes the row downstream. That is deliberately blunt: a station
    that flags its own reading has told us not to trust it, and averaging over it is how
    a bad sensor quietly moves a risk number.
    """
    for record in records:
        if not isinstance(record, dict):
            continue
        flag = (record.get("Qc") or "").strip()
        if flag and flag not in _GOOD_QC_FLAGS:
            return flag[:60]
    return None


class CimisAdapter:
    """Hourly readings for one station over one window."""

    def __init__(self, api_key: str | None = None, *, transport=None, base_url=None):
        self._api_key = api_key if api_key is not None else os.getenv(API_KEY_ENV)
        # Test seam only. Application code never passes this.
        self._transport = transport
        self._base_url = base_url

    # -- description -------------------------------------------------------

    def describe(self) -> SourceDescriptor:
        has_key = bool(self._api_key)
        return SourceDescriptor(
            source_key=SOURCE_KEY,
            domain="climate",
            title="CIMIS hourly station data",
            provider="California Department of Water Resources",
            status=SOURCE_IMPLEMENTED if has_key else SOURCE_REQUIRES_CREDENTIAL,
            adapter_version=ADAPTER_VERSION,
            blocker=None if has_key else CREDENTIAL_BLOCKER,
            notes=(
                "Hourly air temperature, relative humidity and precipitation. CIMIS "
                "publishes NO leaf-wetness item (verified 2026-08-05), so the Botrytis "
                "assessment still abstains with no_leaf_wetness_or_accepted_proxy. "
                "This adapter never derives wetness from humidity."
            ),
        )

    # -- fetch -------------------------------------------------------------

    def fetch(self, ctx: IngestContext) -> FetchResult:
        params = {
            "appKey": self._api_key,
            "targets": ctx.station_id,
            "startDate": ctx.window_start.date().isoformat(),
            "endDate": ctx.window_end.date().isoformat(),
            "dataItems": ",".join(HOURLY_ITEMS),
            # Metric, so the values arrive in the units the columns are named for. A
            # payload that declares English units anyway is routed through `units` by
            # the pipeline's normalize stage rather than trusted.
            "unitOfMeasure": "M",
        }
        raw = _http_get(
            "/api/data", params,
            base_url=self._base_url, transport=self._transport,
        )
        return FetchResult(
            raw=raw,
            content_type="application/json",
            filename=f"cimis-{ctx.station_id}-{ctx.window_start.date()}.json",
            request_description=_redact(params),
        )

    # -- parse -------------------------------------------------------------

    def parse(self, raw: bytes, ctx: IngestContext) -> tuple[list[dict], list[Issue]]:
        """CIMIS JSON -> canonical rows, plus issues for anything unreadable.

        Returns rows keyed by the SAME canonical names
        `csv_import.WEATHER_OBSERVATION_FIELDS` declares, because the next stage hands
        them to the identical validator the concierge CSV import uses.
        """
        issues: list[Issue] = []
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return [], [
                Issue(
                    stage=STAGE_PARSE, severity=SEVERITY_ERROR, code=ISSUE_PARSE_FAILED,
                    message=f"response was not readable JSON: {exc}",
                )
            ]

        records = (
            payload.get("Data", {}).get("Providers", [{}])[0].get("Records", [])
            if isinstance(payload.get("Data"), dict)
            else []
        )
        if not records:
            issues.append(
                Issue(
                    stage=STAGE_PARSE, severity=SEVERITY_WARNING, code=ISSUE_PARSE_FAILED,
                    message="response contained no records for the requested window",
                )
            )

        rows: list[dict] = []
        for index, record in enumerate(records):
            observed_at = _observed_at(record)
            if observed_at is None:
                issues.append(
                    Issue(
                        stage=STAGE_PARSE, severity=SEVERITY_ERROR,
                        code=ISSUE_PARSE_FAILED,
                        message="record has no readable Date/Hour",
                        row_index=index + 1,
                    )
                )
                continue

            air = record.get("HlyAirTmp") or {}
            humidity = record.get("HlyRelHum") or {}
            precip = record.get("HlyPrecip") or {}

            row = {
                "station_id": str(record.get("Station") or ctx.station_id),
                "observed_at": observed_at.isoformat(),
                "temperature_c": _as_text(_parse_number(air.get("Value"))),
                "relative_humidity_pct": _as_text(_parse_number(humidity.get("Value"))),
                "rainfall_mm": _as_text(_parse_number(precip.get("Value"))),
                "quality_flag": _quality_flag(air, humidity, precip),
                "source_reference": f"CIMIS /api/data station {ctx.station_id}",
                # leaf_wetness_minutes and wetness_is_measured are ABSENT, not empty
                # strings and not False. CIMIS has no wetness datum, and `None` is the
                # only honest representation of "no such measurement exists".
            }

            unit = (record.get("Scope") or payload.get("UnitOfMeasure") or "").strip()
            if unit.lower() in ("e", "english"):
                # Declare the units and let the pipeline's normalize stage convert
                # through `units`, where the conversion is cited and a refusal drops
                # the row. Never convert at the edge.
                row["temperature_unit"] = "F"
                row["rainfall_unit"] = "in"

            rows.append({k: v for k, v in row.items() if v is not None})
        return rows, issues


def _as_text(value: float | None) -> str | None:
    return None if value is None else str(value)


def _observed_at(record: dict) -> datetime | None:
    """CIMIS gives Date as YYYY-MM-DD and Hour as "HHMM" (with "2400" for midnight)."""
    date_text = (record.get("Date") or "").strip()
    hour_text = (record.get("Hour") or "").strip()
    if not date_text:
        return None
    try:
        day = datetime.strptime(date_text, "%Y-%m-%d")
    except ValueError:
        return None
    if not hour_text:
        return day
    try:
        hour = int(hour_text) // 100
        minute = int(hour_text) % 100
    except ValueError:
        return None
    # CIMIS writes the last hour of a day as 2400, meaning midnight ending that day.
    if hour == 24:
        return day.replace(hour=23, minute=59)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return day.replace(hour=hour, minute=minute)


def build_adapter() -> CimisAdapter:
    """Factory. Reads the credential FRESH on every call, so an operator who exports the
    key and restarts the worker does not have to reason about import order."""
    return CimisAdapter()


registry.register(SOURCE_KEY, build_adapter)
