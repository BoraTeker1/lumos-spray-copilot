"""Covenant monitoring (pure, framework-free).

Evaluates a transcribed covenant schedule against a farm's computed features, or refuses.
This is the part of the finance thesis the existing substrate genuinely earns: covenant
checks answered against append-only, point-in-time-correct records are verifiable in a
way that the same checks answered against a spreadsheet are not.

**The invariant that matters most: "nothing checked" is not "compliant".**

An empty covenant schedule, or a covenant whose feature abstains, must never render as
a farm in good standing. The temptation is structural — a status field with values
`compliant | breached` has nowhere to put "we could not look", so the unchecked case
falls into whichever value is the default, and the default that reads well is
`compliant`. `CovenantStatus` therefore has three values, and
`MonitoringSnapshot.standing` is `unknown` whenever anything went unevaluated.

This is the same construction as `features/base.py` refusing to let an abstention render
as `0`, and `underwriting.assess` refusing to fold an unevaluated rule into a pass count.
In all three the shape of the type does the work, because prose in a docstring does not
survive a later refactor.

**Breach severity comes from the agreement, never from Lumos.** How serious a breach is
determines what happens to the borrower, and that is a term of the facility, not a
judgment this system gets to form.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app import monitoring_covenants
from app.refusal import NO_SOURCE_TRANSCRIBED, Refusal

MODEL_VERSION = "covenant_monitoring_v1"

NO_COVENANTS_SUPPLIED = NO_SOURCE_TRANSCRIBED

# Per-covenant status. Three values, not two — see the module docstring.
WITHIN = "within"
BREACHED = "breached"
NOT_EVALUATED = "not_evaluated"

# Overall standing. `unknown` is reachable and is the honest answer far more often than
# either of the others on today's data.
STANDING_GOOD = "in_good_standing"
STANDING_BREACH = "in_breach"
STANDING_UNKNOWN = "unknown"


@dataclass(frozen=True)
class CovenantStatus:
    """One covenant's status at a point in time."""

    covenant_id: str
    description: str
    status: str
    breach_severity: str | None = None
    observed_value: float | None = None
    threshold: float | None = None
    comparator: str | None = None
    not_evaluated_reason: str | None = None

    def as_payload(self) -> dict:
        payload = {
            "covenant_id": self.covenant_id,
            "description": self.description,
            "status": self.status,
        }
        for name in ("breach_severity", "observed_value", "threshold", "comparator",
                     "not_evaluated_reason"):
            value = getattr(self, name)
            if value is not None:
                payload[name] = value
        return payload


@dataclass(frozen=True)
class MonitoringSnapshot:
    """Covenant standing at one moment, over one facility."""

    lender: str
    facility_reference: str
    as_of: datetime
    model_version: str = MODEL_VERSION
    covenants: tuple[CovenantStatus, ...] = field(default_factory=tuple)

    @property
    def breached(self) -> tuple[CovenantStatus, ...]:
        return tuple(c for c in self.covenants if c.status == BREACHED)

    @property
    def unevaluated(self) -> tuple[CovenantStatus, ...]:
        return tuple(c for c in self.covenants if c.status == NOT_EVALUATED)

    @property
    def standing(self) -> str:
        """A breach outranks an unknown; an unknown outranks good standing.

        Ordering matters: a farm with one confirmed breach and one uncheckable covenant
        is in breach, not merely unknown. But a farm with no breaches and one
        uncheckable covenant is NOT in good standing — nobody looked at all of it.
        """
        if self.breached:
            return STANDING_BREACH
        if self.unevaluated or not self.covenants:
            return STANDING_UNKNOWN
        return STANDING_GOOD

    def as_payload(self) -> dict:
        return {
            "model_version": self.model_version,
            "lender": self.lender,
            "facility_reference": self.facility_reference,
            "as_of": self.as_of.isoformat(),
            "standing": self.standing,
            "covenants": [c.as_payload() for c in self.covenants],
            "breached_covenant_ids": [c.covenant_id for c in self.breached],
            "unevaluated_covenant_ids": [c.covenant_id for c in self.unevaluated],
        }


def _compare(value: float, comparator: str, threshold: float) -> bool:
    if comparator == "at_most":
        return value <= threshold
    if comparator == "at_least":
        return value >= threshold
    if comparator == "equals":
        return value == threshold
    raise ValueError(f"unknown comparator {comparator!r}")


def evaluate(*, features, as_of: datetime):
    """Evaluate the transcribed covenant schedule. MonitoringSnapshot | Refusal."""
    schedule = monitoring_covenants.TRANSCRIBED
    if schedule is None:
        return Refusal(
            NO_COVENANTS_SUPPLIED,
            "No covenant schedule has been transcribed, so nothing about this farm's "
            "standing can be reported. An empty schedule is not compliance — it means "
            "nothing was checked. See app/monitoring_covenants.py.",
            {"model_version": MODEL_VERSION},
        )

    features = dict(features or {})
    statuses = []
    for covenant in schedule.covenants:
        result = features.get(covenant.feature_name)
        if result is None or getattr(result, "abstained", False) or getattr(
            result, "value", None
        ) is None:
            reasons = list(getattr(result, "reasons", ()) or ()) if result else []
            statuses.append(CovenantStatus(
                covenant_id=covenant.covenant_id, description=covenant.description,
                status=NOT_EVALUATED, comparator=covenant.comparator,
                threshold=covenant.threshold,
                not_evaluated_reason=(
                    f"{covenant.feature_name} could not be computed"
                    + (f" ({'; '.join(reasons)})" if reasons else "")
                ),
            ))
            continue

        value = float(result.value)
        within = _compare(value, covenant.comparator, covenant.threshold)
        statuses.append(CovenantStatus(
            covenant_id=covenant.covenant_id, description=covenant.description,
            status=WITHIN if within else BREACHED,
            breach_severity=None if within else covenant.breach_severity,
            observed_value=value, threshold=covenant.threshold,
            comparator=covenant.comparator,
        ))

    return MonitoringSnapshot(
        lender=schedule.lender, facility_reference=schedule.facility_reference,
        as_of=as_of, covenants=tuple(statuses),
    )
