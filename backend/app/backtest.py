"""Historical opportunity scan — pilot ladder Stage 2. Pure, framework-free.

Replays a past season's scheduled spray dates, freezes a snapshot at each one, and runs
the versioned rule over it. The output is a histogram: how often the rule read each
band, and — while the thresholds are still absent — how often it could not read anything
and exactly why.

## What this can and cannot say

It can size an opportunity: "on N of M scheduled Botrytis sprays last season, this rule
read low pressure." That is `DESIGN_PARTNER_SPRINT.md` §5 Stage 2's ceiling, and it is
useful for one thing — making a design-partner conversation concrete instead of
hypothetical.

It CANNOT say any of those sprays were safely avoidable, and the code refuses to help
anyone imply it:

* **Every historical outcome followed the actual spray.** There is no untreated
  counterfactual anywhere in the record set. The block that stayed clean stayed clean
  *having been sprayed*; whether it would have stayed clean otherwise is unobserved and
  unobservable from this data.
* **`low` is a band, not a safety statement** (BOTRYTIS_PILOT.md §2). It means this
  rule's inputs fell in its low range. It does not mean deferral was safe, and the rule
  is uncalibrated and outside its validated region besides.
* **The snapshots are retrospective**, not point-in-time (see `risk_snapshot`). The
  record set was assembled with hindsight about which observations were worth keeping,
  so this is not "what the rule would have said at the time" either.

`ScanResult` therefore has no avoided count, no reduction figure, and no
recommendation — the same structural discipline as `RiskAssessment` having no product
field. `test_backtest.py` asserts no such key ever appears in a payload.

## Why the reason histogram is the real product right now

With the threshold table empty, every date abstains and the scan looks useless. It is
not: the reason counts turn "we cannot assess your farm" into a specific, ordered work
list — *this* many dates lacked leaf wetness, *this* many had a station too far away,
*this* many had stale scouting. That is the artifact a first partner conversation
actually needs, and it is available before a single coefficient is transcribed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app import disease_risk, risk_snapshot

SCAN_VERSION = "opportunity-scan-v1"

# The claim ceiling, carried verbatim on every payload. Shaped like
# `pilot_evidence.NOT_CALCULATED`: a dict of metric -> why it is absent, so a reader
# sees the refusal in the same place they would have seen the number.
SCAN_CANNOT_CONCLUDE = {
    "sprays_safely_avoidable": (
        "not calculated — every historical outcome followed the actual spray, so there "
        "is no untreated counterfactual and the outcome is confounded by the treatment. "
        "A low band on a past date is not evidence that date's spray could have been "
        "skipped"
    ),
    "pesticide_use_reduction": (
        "not calculated — this is a retrospective scan of what conditions occurred, not "
        "a comparison of two arms. Sizing an opportunity is not measuring a reduction"
    ),
    "what_the_rule_would_have_said": (
        "not calculated — these snapshots are retrospective reconstructions, admitted on "
        "observed_at alone. Backfilled records carry an ingest-time recorded_at, so a "
        "true point-in-time replay of a past season admits nothing at all"
    ),
}

# Substrings that must never appear as a key in a scan payload. A future edit that adds
# an "avoided_applications" count would be adding the one number this whole module
# exists to withhold, and it should fail a test rather than ship.
FORBIDDEN_KEY_SUBSTRINGS = ("avoid", "reduc", "saved", "prevent", "recommend")


@dataclass(frozen=True)
class ScanItem:
    """One replayed decision date."""

    as_of: datetime
    risk_band: str
    abstained: bool
    reasons: tuple = ()
    evidence_grade: str | None = None
    probability_or_index: float | None = None
    input_digest: str = ""
    excluded_count: int = 0

    def as_payload(self) -> dict:
        return {
            "as_of": self.as_of.isoformat(),
            "risk_band": self.risk_band,
            "abstained": self.abstained,
            "reasons": list(self.reasons),
            "evidence_grade": self.evidence_grade,
            "probability_or_index": self.probability_or_index,
            "input_digest": self.input_digest,
            "excluded_count": self.excluded_count,
        }


@dataclass(frozen=True)
class ScanResult:
    """The histogram plus its own claim ceiling."""

    model_version: str
    target: str
    basis: str
    items: tuple = ()
    band_counts: dict = field(default_factory=dict)
    reason_counts: dict = field(default_factory=dict)
    grade_counts: dict = field(default_factory=dict)

    @property
    def dates_scanned(self) -> int:
        return len(self.items)

    @property
    def assessed_count(self) -> int:
        """Dates that produced a band. Zero while the thresholds are absent."""
        return sum(1 for i in self.items if not i.abstained)

    def as_payload(self) -> dict:
        return {
            "scan_version": SCAN_VERSION,
            "model_version": self.model_version,
            "target": self.target,
            # Stated in the payload, not just the column, so a result read back later
            # carries the weaker basis it was computed under.
            "basis": self.basis,
            "dates_scanned": self.dates_scanned,
            "assessed_count": self.assessed_count,
            "band_counts": dict(self.band_counts),
            "reason_counts": dict(self.reason_counts),
            "grade_counts": dict(self.grade_counts),
            "items": [i.as_payload() for i in self.items],
            "cannot_conclude": dict(SCAN_CANNOT_CONCLUDE),
        }


def run_scan(
    *,
    decision_dates,
    block,
    weather_observations,
    scouting_samples,
    target: str,
    horizon_hours: int = 72,
    lookback_hours: int = 168,
    model_version: str = disease_risk.DEFAULT_MODEL_VERSION,
) -> ScanResult:
    """Replay each date and tally the outcomes.

    Framework-free by the same rule as `risk_snapshot` and `disease_risk`: plain objects
    in, plain result out, no session. It cannot reach an outcome, a disposition or a
    harvest result, because it has no way to query for one.

    Reuses `risk_snapshot.build_snapshot` and `disease_risk.assess` rather than
    reimplementing either. A scan that scored dates with its own copy of the rule would
    be measuring something other than the product.
    """
    items: list[ScanItem] = []
    band_counts: dict = {}
    reason_counts: dict = {}
    grade_counts: dict = {}

    for as_of in sorted(decision_dates or []):
        draft = risk_snapshot.build_snapshot(
            as_of=as_of,
            horizon_hours=horizon_hours,
            target=target,
            block=block,
            weather_observations=weather_observations,
            scouting_samples=scouting_samples,
            lookback_hours=lookback_hours,
            # The whole point of this module. Passed explicitly at the one call site
            # that is allowed to weaken the basis.
            basis=risk_snapshot.BASIS_RETROSPECTIVE,
        )
        assessment = disease_risk.assess(
            draft.as_payload(),
            model_version=model_version,
            input_digest=draft.input_digest,
        )

        items.append(
            ScanItem(
                as_of=as_of,
                risk_band=assessment.risk_band,
                abstained=assessment.abstained,
                reasons=tuple(assessment.missing_or_unreliable_inputs),
                evidence_grade=assessment.evidence_grade,
                probability_or_index=assessment.probability_or_index,
                input_digest=assessment.input_digest,
                excluded_count=len(draft.excluded),
            )
        )

        band_counts[assessment.risk_band] = band_counts.get(assessment.risk_band, 0) + 1
        # ALL reasons are counted, not just the first. A date blocked by three separate
        # gaps is three work items, and reporting only the first would make the second
        # one appear only after the first was fixed — the slowest possible way to learn
        # what a farm is missing.
        for reason in assessment.missing_or_unreliable_inputs:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
        if assessment.evidence_grade:
            grade_counts[assessment.evidence_grade] = (
                grade_counts.get(assessment.evidence_grade, 0) + 1
            )

    return ScanResult(
        model_version=model_version,
        target=target,
        basis=risk_snapshot.BASIS_RETROSPECTIVE,
        items=tuple(items),
        band_counts=band_counts,
        reason_counts=reason_counts,
        grade_counts=grade_counts,
    )
