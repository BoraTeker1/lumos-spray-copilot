"""Point-in-time shapes for rows that were never designed to have one.

Framework-free (stdlib only).

`pit.admissible` needs `observed_at` and `recorded_at`. `WeatherObservation` and
`ScoutingSample` were built with both. `SprayEvent` has neither — it has
`application_date` (a date, when the spray happened) and `created_at` (when the row was
written). Those ARE the two timestamps; they are simply spelled differently, because
`SprayEvent` predates the hindsight rule by about a year.

The fix is an adapter, not a migration. Adding columns would mean backfilling values
nobody recorded, and a backfilled `recorded_at` is a fabricated claim about when
something was known — the precise thing the rule exists to prevent.

The consequence is worth stating plainly, because it is the first time the hindsight
rule reaches spray records: **a spray keyed in on Friday about Tuesday is excluded from
a Wednesday `as_of`.** That is correct and will occasionally surprise someone. A
pesticide-use figure that includes applications entered after the fact is not a figure
anyone could have acted on.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time


@dataclass(frozen=True)
class SprayPitView:
    """A `SprayEvent` wearing the two timestamps `pit.admissible` reads.

    `observed_at` is midnight of the application date. A date has no time, and
    midnight is the only choice that cannot claim a spray happened later in the day
    than it did — erring toward "knowable earlier" would leak.
    """

    id: int
    observed_at: datetime | None
    recorded_at: datetime | None
    supersedes_id: None = None
    quality_flag: None = None
    data_source: str | None = None
    data_confidence: str | None = None
    source: object = None  # the original row, for the feature to read fields from


def spray_view(row) -> SprayPitView:
    application_date = getattr(row, "application_date", None)
    observed_at = None
    if isinstance(application_date, datetime):
        observed_at = application_date
    elif isinstance(application_date, date):
        observed_at = datetime.combine(application_date, time.min)
    return SprayPitView(
        id=getattr(row, "id", None),
        observed_at=observed_at,
        recorded_at=getattr(row, "created_at", None),
        data_source=getattr(row, "data_source", None),
        data_confidence=getattr(row, "data_confidence", None),
        source=row,
    )


def spray_views(rows) -> list[SprayPitView]:
    return [spray_view(row) for row in (rows or [])]
