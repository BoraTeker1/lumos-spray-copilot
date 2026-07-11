"""The single "what time is it" source for the whole app (stdlib only).

Every runtime "today"/"now" must come from here so the live API and the seeded demo
story agree. Set LUMOS_DEMO_TODAY=YYYY-MM-DD to pin the clock to a fixed anchor —
seeding AND live checks/reviews/outcomes then all compute against the same date, so
the seeded story can be reproduced deterministically (screenshots, invariant tests).

Caution: with the env var set on a *live* server, every new row is timestamped at the
anchor. That is intended for demos and tests only — never run a real pilot with it set.

Pure modules (decision_engine, recommendation_engine, analytics, reduction,
pilot_evidence, vision) keep their injectable `today` parameter and never import this
module; callers (crud/main/seed) pass `clock.current_date()` in.
"""
from __future__ import annotations

import os
from datetime import date, datetime, time


def current_date() -> date:
    """Today's date, honoring the LUMOS_DEMO_TODAY pin."""
    pinned = os.environ.get("LUMOS_DEMO_TODAY")
    return date.fromisoformat(pinned) if pinned else date.today()


def current_datetime() -> datetime:
    """Now, honoring the LUMOS_DEMO_TODAY pin.

    When pinned, returns midnight of the anchor date — matching how the seed anchors
    its timestamps, so seeded and live records sort/compare consistently.

    Deliberately LOCAL time (naive), matching `current_date()`: every domain date in
    the app (application, harvest, outcome dates) is a civil/local date, and mixing
    UTC timestamps with local dates made chronology checks fail near midnight.
    """
    pinned = os.environ.get("LUMOS_DEMO_TODAY")
    if pinned:
        return datetime.combine(date.fromisoformat(pinned), time.min)
    return datetime.now()
