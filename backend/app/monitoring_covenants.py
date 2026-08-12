"""Portfolio covenants — EMPTY until a lender's covenant schedule is transcribed.

Ongoing monitoring is the part of the finance thesis that this codebase is genuinely,
unusually well-suited to: it already holds append-only, point-in-time-correct operational
records with a leakage boundary (`app/pit.py`) that can reconstruct what was knowable on
a given date without hindsight. A covenant check answered against that substrate is
verifiable in a way that a covenant check answered against a spreadsheet is not.

What it is not suited to is *deciding what the covenants are*. A threshold like "scouting
recency must stay under 14 days" looks agronomic and is actually a credit term — it
determines when a borrower is in breach, and breach has consequences. That number belongs
to the lender.

`monitoring.evaluate()` reads this schedule; while it is empty it returns a `Refusal`
naming `NO_COVENANTS_SUPPLIED`, and no farm is ever reported as in breach or in good
standing. Note that "no covenants" must not render as compliant — an empty schedule means
nothing was checked, and `monitoring.py` treats the two as distinct outcomes for the same
reason `features/base.py` refuses to let an abstention render as `0`.

**What fills it:** the covenant schedule from the executed facility agreement.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.transcription import Citation

PRIMARY_SOURCE = (
    "The covenant schedule from the executed facility agreement: each covenant, the "
    "measure it tests, its threshold and direction, the reporting frequency, and the "
    "consequence of breach. Never inferred from what the platform happens to measure."
)

# Direction of the test. Spelled out rather than using operator strings so a schedule
# cannot be transcribed with the comparison inverted and still parse.
Comparator = Literal["at_most", "at_least", "equals"]

# How serious a breach is, per the agreement — not per Lumos's judgment.
BreachSeverity = Literal["reportable", "remediable", "event_of_default"]


@dataclass(frozen=True, kw_only=True)
class Covenant:
    """One covenant, tied to a feature this system can actually compute."""

    covenant_id: str
    description: str
    feature_name: str
    comparator: Comparator
    threshold: float
    breach_severity: BreachSeverity
    citation: Citation
    reporting_frequency_days: int | None = None

    def __post_init__(self) -> None:
        if not self.covenant_id.strip():
            raise ValueError("Covenant.covenant_id is blank")
        if not self.feature_name.strip():
            raise ValueError(
                f"{self.covenant_id}: feature_name is blank. A covenant must name the "
                "measure it tests, or it cannot be evaluated against anything."
            )
        if not self.description.strip():
            raise ValueError(
                f"{self.covenant_id}: description is blank. A breach reported without "
                "the covenant's own wording is not actionable by the borrower."
            )
        if (
            self.reporting_frequency_days is not None
            and self.reporting_frequency_days <= 0
        ):
            raise ValueError(f"{self.covenant_id}: reporting_frequency_days must be positive")


@dataclass(frozen=True, kw_only=True)
class CovenantSchedule:
    """A facility's whole covenant schedule, transcribed as one artifact."""

    lender: str
    facility_reference: str
    version: str
    covenants: tuple[Covenant, ...]
    citation: Citation

    def __post_init__(self) -> None:
        if not self.covenants:
            raise ValueError("a CovenantSchedule with no covenants tests nothing")
        ids = [c.covenant_id for c in self.covenants]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate covenant_id in schedule")


# EMPTY. See the module docstring.
TRANSCRIBED: CovenantSchedule | None = None
