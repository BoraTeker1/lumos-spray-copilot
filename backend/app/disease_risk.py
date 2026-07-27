"""Versioned disease-risk rules: the thing that proposes, and mostly abstains.

This module reads a `risk_snapshot` payload and returns a risk band, or declines to.
It sits between the leakage boundary and the licensed PCA, and its whole job is to be
the least trusted component in the chain:

* **It is arithmetic. No LLM is involved anywhere in this path.** A language model
  cannot be asked what the Botrytis risk is, because there is no call site for one.
* **It cannot recommend a pesticide.** `RiskAssessment` has no product, rate, tank-mix,
  or action field, so a recommendation is not something this code is forbidden from
  emitting — it is something it has no way to express. Same discipline as
  `ai_brief.EvidenceActionType`.
* **It abstains by default and says why.** Every abstention condition is checked
  *before* the rule runs and ALL of them are reported, not just the first. An assessment
  that ran on thin evidence is worse than no assessment, because someone will believe it.
* **It never declares a deferral safe.** The vocabulary is low/moderate/high/abstain.
  `low` means "this rule's inputs put it in the low band"; it does not mean safe, and
  the licensed PCA remains the only party that decides anything.

## On the missing numbers

`botrytis_wetness_v1` is registered, versioned, tested, and returns ABSTAIN
(`thresholds_not_supplied`). Its coefficients are absent deliberately. Every test that
can be written about a threshold rule checks the arithmetic *against* the constants, not
the constants themselves — so a plausible-looking cut point recalled from memory or
lifted from a search result would pass the entire suite and then sit in a cited,
versioned module that a PCA is entitled to trust. The table gets transcribed from the
primary source, with its crop, region and validation conditions recorded verbatim, or
the rule keeps abstaining. Supplying it later is a one-function change; the plumbing and
the tests are already here.

Even once supplied, `local_validation_status` stays explicit: the published strawberry
Botrytis advisory work is Florida-based and is not validated for California's Central
Coast. `calibration_status` stays `not_calibrated` until prospective outcomes exist.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

ASSESSMENT_VERSION = "disease-risk-v1"

# ---------------------------------------------------------------- risk vocabulary
BAND_LOW = "low"
BAND_MODERATE = "moderate"
BAND_HIGH = "high"
BAND_ABSTAIN = "abstain"
RISK_BANDS = (BAND_LOW, BAND_MODERATE, BAND_HIGH, BAND_ABSTAIN)

# Evidence grade describes the INPUTS, never the confidence of the answer. A grade-A
# input set feeding an uncalibrated rule is still an uncalibrated rule.
GRADE_A = "A"  # measured leaf wetness, close station, continuous record, fresh scouting
GRADE_B = "B"  # derived wetness or a more distant station — usable, weaker
GRADE_C = "C"  # sparse or stale; reportable but never headline evidence
EVIDENCE_GRADES = (GRADE_A, GRADE_B, GRADE_C)

CALIBRATION_NOT_CALIBRATED = "not_calibrated"

LOCAL_VALIDATION_UNVALIDATED = (
    "published rule; NOT validated for California Central Coast strawberries — no "
    "local outcome data exists yet"
)

# ------------------------------------------------------------ abstention reasons
ABSTAIN_THRESHOLDS_NOT_SUPPLIED = "thresholds_not_supplied"
ABSTAIN_NO_SNAPSHOT = "no_snapshot_payload"
ABSTAIN_UNKNOWN_MODEL = "unknown_model_version"
ABSTAIN_NO_NEARBY_STATION = "no_station_within_range"
ABSTAIN_NO_WEATHER = "no_weather_in_window"
ABSTAIN_WEATHER_GAP = "weather_gap_exceeds_limit"
ABSTAIN_NO_LEAF_WETNESS = "no_leaf_wetness_or_accepted_proxy"
ABSTAIN_SCOUTING_STALE = "scouting_older_than_limit"
ABSTAIN_NO_SCOUTING = "no_scouting_sample_for_target"
ABSTAIN_CONFLICTING_READINGS = "conflicting_readings_same_hour"
ABSTAIN_OUT_OF_SCOPE = "crop_or_target_outside_pilot_scope"
ABSTAIN_DEMO_INPUT = "demo_or_simulated_input_present"
ABSTAIN_HINDSIGHT_LEAK = "input_observed_after_as_of"

# --------------------------------------------------------------- data-quality gates
# PROVISIONAL. These bound what counts as usable evidence; they do not change any risk
# number, only whether one is produced at all. They must be set from the pilot farm's
# actual station configuration and scouting cadence before the first real decision —
# see BOTRYTIS_PILOT.md open question B2. Chosen conservatively in the meantime.
MAX_STATION_KM = 15.0
MAX_GAP_HOURS = 3
MAX_SCOUTING_AGE_DAYS = 14
# Two stations reporting the same hour this far apart are not measuring the same
# weather; using either would be arbitrary.
CONFLICT_TEMP_C = 5.0
CONFLICT_WETNESS_MINUTES = 120

# The pilot's declared scope. Anything else abstains rather than extrapolating.
PILOT_CROPS = ("strawberry",)
PILOT_TARGETS = ("botrytis_fruit_rot",)


@dataclass(frozen=True)
class RiskAssessment:
    """The full result. Note what is absent: no product, no rate, no action.

    A pesticide recommendation is structurally inexpressible here, which is a stronger
    guarantee than a rule saying it must not be emitted. `test_disease_risk` asserts
    this field list stays free of them.
    """
    model_family: str
    model_version: str
    input_digest: str
    horizon_hours: int
    risk_band: str
    abstained: bool
    abstain_reason: str | None = None
    probability_or_index: float | None = None
    evidence_grade: str | None = None
    missing_or_unreliable_inputs: tuple = ()
    calibration_status: str = CALIBRATION_NOT_CALIBRATED
    local_validation_status: str = LOCAL_VALIDATION_UNVALIDATED
    citation: str | None = None
    # The shown arithmetic. Empty while abstaining — there is nothing to show.
    calculation: dict = field(default_factory=dict)

    def as_payload(self) -> dict:
        return {
            "assessment_version": ASSESSMENT_VERSION,
            "model_family": self.model_family,
            "model_version": self.model_version,
            "input_digest": self.input_digest,
            "horizon_hours": self.horizon_hours,
            "risk_band": self.risk_band,
            "abstained": self.abstained,
            "abstain_reason": self.abstain_reason,
            "probability_or_index": self.probability_or_index,
            "evidence_grade": self.evidence_grade,
            "missing_or_unreliable_inputs": list(self.missing_or_unreliable_inputs),
            "calibration_status": self.calibration_status,
            "local_validation_status": self.local_validation_status,
            "citation": self.citation,
            "calculation": dict(self.calculation),
        }


# ------------------------------------------------------------------ input checks
def _parse(ts) -> datetime | None:
    if isinstance(ts, datetime):
        return ts
    try:
        return datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return None


def _scope_problems(payload: dict) -> list[str]:
    crop = (payload.get("block") or {}).get("crop")
    target = payload.get("target")
    problems = []
    if target not in PILOT_TARGETS:
        problems.append(ABSTAIN_OUT_OF_SCOPE)
    elif crop is None or str(crop).strip().lower() not in PILOT_CROPS:
        # Crop is checked only once the target is in scope, so the reason is specific.
        problems.append(ABSTAIN_OUT_OF_SCOPE)
    return problems


def _weather_problems(payload: dict) -> list[str]:
    rows = payload.get("weather") or []
    if not rows:
        return [ABSTAIN_NO_WEATHER]

    problems = []
    as_of = _parse(payload.get("as_of"))

    # A demo row must never reach an assessment. risk_snapshot already excludes them;
    # this is belt-and-braces, because one fabricated input poisons calibration.
    if any(r.get("source_type") == "demo" for r in rows):
        problems.append(ABSTAIN_DEMO_INPUT)

    # A future observation in the payload means the snapshot layer is broken. Abstain
    # and flag loudly rather than degrading quietly.
    #
    # NOTE the limit of what is checkable here: `recorded_at` is deliberately NOT
    # serialized into the snapshot payload, so the "entered on Friday about Tuesday"
    # guard cannot be re-verified downstream. It is enforced once, in
    # risk_snapshot.admissible, and pinned by tests/test_leakage.py.
    if as_of is not None:
        for r in rows:
            observed = _parse(r.get("observed_at"))
            if observed is not None and observed > as_of:
                problems.append(ABSTAIN_HINDSIGHT_LEAK)
                break

    in_range = [
        r for r in rows
        if r.get("station_distance_km") is None
        or r["station_distance_km"] <= MAX_STATION_KM
    ]
    if not in_range:
        problems.append(ABSTAIN_NO_NEARBY_STATION)
        return problems

    # Leaf wetness, measured or via an accepted proxy. No proxy is accepted yet — the
    # derivation would itself need a cited source — so absence abstains.
    if not any(r.get("leaf_wetness_minutes") is not None for r in in_range):
        problems.append(ABSTAIN_NO_LEAF_WETNESS)

    times = sorted(t for t in (_parse(r.get("observed_at")) for r in in_range) if t)
    for earlier, later in zip(times, times[1:]):
        if later - earlier > timedelta(hours=MAX_GAP_HOURS):
            problems.append(ABSTAIN_WEATHER_GAP)
            break

    if _has_conflicting_readings(in_range):
        problems.append(ABSTAIN_CONFLICTING_READINGS)
    return problems


def _has_conflicting_readings(rows) -> bool:
    """Two stations describing the same hour irreconcilably differently."""
    by_hour: dict = {}
    for r in rows:
        observed = _parse(r.get("observed_at"))
        if observed is None:
            continue
        by_hour.setdefault(observed.replace(minute=0, second=0, microsecond=0), []).append(r)

    for group in by_hour.values():
        if len(group) < 2:
            continue
        for key, limit in (
            ("temperature_c", CONFLICT_TEMP_C),
            ("leaf_wetness_minutes", CONFLICT_WETNESS_MINUTES),
        ):
            values = [r[key] for r in group if r.get(key) is not None]
            if len(values) >= 2 and (max(values) - min(values)) > limit:
                return True
    return False


def _scouting_problems(payload: dict) -> list[str]:
    samples = payload.get("scouting_samples") or []
    target = payload.get("target")
    relevant = [s for s in samples if s.get("target") == target] or samples
    if not relevant:
        return [ABSTAIN_NO_SCOUTING]

    problems = []
    if any(s.get("source_type") == "demo" for s in relevant):
        problems.append(ABSTAIN_DEMO_INPUT)

    as_of = _parse(payload.get("as_of"))
    if as_of is not None:
        observed = [t for t in (_parse(s.get("observed_at")) for s in relevant) if t]
        if observed and (as_of - max(observed)) > timedelta(days=MAX_SCOUTING_AGE_DAYS):
            problems.append(ABSTAIN_SCOUTING_STALE)
    return problems


def evidence_grade(payload: dict) -> str:
    """Grade the inputs. Only ever consulted when nothing abstained."""
    rows = payload.get("weather") or []
    measured = any(r.get("wetness_is_measured") for r in rows)
    distances = [
        r["station_distance_km"] for r in rows
        if r.get("station_distance_km") is not None
    ]
    close = not distances or max(distances) <= (MAX_STATION_KM / 3.0)
    if measured and close:
        return GRADE_A
    if measured or close:
        return GRADE_B
    return GRADE_C


def abstention_reasons(payload: dict) -> list[str]:
    """Every reason this payload cannot support an assessment, in check order.

    ALL conditions are evaluated rather than short-circuiting on the first, so the
    stored assessment records the full evidence gap — "we could not answer, and here
    is everything that was wrong" is the useful artifact for a pilot.
    """
    if not payload:
        return [ABSTAIN_NO_SNAPSHOT]
    reasons = (
        _scope_problems(payload)
        + _weather_problems(payload)
        + _scouting_problems(payload)
    )
    # Stable order, no duplicates (demo input can be flagged by two checks).
    seen: dict = {}
    for r in reasons:
        seen.setdefault(r, None)
    return list(seen)


# ------------------------------------------------------------------ model registry
class RiskModel:
    """A named, versioned rule. Subclasses supply thresholds and arithmetic."""

    family: str = ""
    version: str = ""
    citation: str | None = None
    # What the cited source actually validated, recorded verbatim from that source.
    # A threshold table is not interpretable without them: the same coefficients
    # validated on Florida plasticulture strawberries are not a Central Coast rule,
    # and `local_validation_status` cannot be stated honestly if the source's own
    # scope was never written down. Required by is_ready() for that reason.
    source_crop: str | None = None
    source_region: str | None = None
    source_validation_conditions: str | None = None

    def is_ready(self) -> bool:
        """False until the published thresholds have been transcribed."""
        raise NotImplementedError

    def evaluate(self, payload: dict) -> tuple[float, str, dict]:
        """(index, band, shown_calculation). Only called when is_ready() and no abstention."""
        raise NotImplementedError


class BotrytisWetnessV1(RiskModel):
    """Botrytis cinerea infection risk from temperature during leaf-wetness duration.

    The published rule keys infection risk on how long the crop stays wet and at what
    temperature. THE COEFFICIENTS ARE NOT PRESENT. See this module's docstring for why
    they are not being recalled or approximated: `thresholds` stays None, `is_ready()`
    stays False, and every assessment abstains with `thresholds_not_supplied`.

    To supply them: set `thresholds` to the transcribed table, `citation` to the primary
    source (author, year, publication), and `source_crop` / `source_region` /
    `source_validation_conditions` to that source's own stated scope verbatim; then
    implement `evaluate`. is_ready() requires ALL of them. Nothing else in the pipeline
    changes.
    """

    family = "botrytis_wetness"
    version = "botrytis_wetness_v1"
    citation = None
    thresholds = None
    source_crop = None
    source_region = None
    source_validation_conditions = None

    def is_ready(self) -> bool:
        # The coefficients alone are NOT enough. A transcriber who supplies the table
        # and forgets the citation would ship an uncited rule inside a versioned module
        # a PCA is entitled to trust — the exact failure this module's docstring exists
        # to prevent, and one no test of the arithmetic can catch. Every provenance
        # field is load-bearing for reading the output, so every one is required.
        return all(
            (
                self.thresholds is not None,
                (self.citation or "").strip(),
                (self.source_crop or "").strip(),
                (self.source_region or "").strip(),
                (self.source_validation_conditions or "").strip(),
            )
        )

    def evaluate(self, payload: dict) -> tuple[float, str, dict]:
        raise NotImplementedError(
            "botrytis_wetness_v1 has no thresholds; assess() must abstain before here"
        )


RISK_MODELS: dict = {BotrytisWetnessV1.version: BotrytisWetnessV1()}
DEFAULT_MODEL_VERSION = BotrytisWetnessV1.version


def _abstain(model, payload, horizon, reasons) -> RiskAssessment:
    return RiskAssessment(
        model_family=getattr(model, "family", "unknown"),
        model_version=getattr(model, "version", "unknown"),
        input_digest=(payload or {}).get("input_digest") or "",
        horizon_hours=horizon,
        risk_band=BAND_ABSTAIN,
        abstained=True,
        abstain_reason=reasons[0],
        missing_or_unreliable_inputs=tuple(reasons),
        citation=getattr(model, "citation", None),
    )


def assess(
    snapshot_payload: dict,
    model_version: str = DEFAULT_MODEL_VERSION,
    input_digest: str | None = None,
) -> RiskAssessment:
    """Assess deferral risk from a snapshot payload, or abstain and say why.

    Abstention is checked before the rule runs, so a rule can never execute on inputs
    it should not have seen — not even once, not even in a branch nobody reads.
    """
    payload = dict(snapshot_payload or {})
    if input_digest:
        payload["input_digest"] = input_digest
    horizon = int(payload.get("horizon_hours") or 0)

    model = RISK_MODELS.get(model_version)
    if model is None:
        return _abstain(
            type("UnknownModel", (), {"family": "unknown", "version": model_version,
                                      "citation": None})(),
            payload, horizon, [ABSTAIN_UNKNOWN_MODEL],
        )

    reasons = abstention_reasons(payload)
    # The model's own readiness is the last reason appended, so a genuinely thin
    # payload reports its data gaps too instead of hiding behind the missing table.
    if not model.is_ready():
        reasons = reasons + [ABSTAIN_THRESHOLDS_NOT_SUPPLIED]
    if reasons:
        return _abstain(model, payload, horizon, reasons)

    index, band, calculation = model.evaluate(payload)
    return RiskAssessment(
        model_family=model.family,
        model_version=model.version,
        input_digest=payload.get("input_digest") or "",
        horizon_hours=horizon,
        risk_band=band,
        abstained=False,
        probability_or_index=index,
        evidence_grade=evidence_grade(payload),
        citation=model.citation,
        calculation=calculation,
    )
