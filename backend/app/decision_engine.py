"""Pre-spray decision engine (the core Lumos workflow).

A grower/PCA enters a *planned* spray; this module checks it against harvest timing,
PHI/REI, recent applications, repeated active ingredients, scouting evidence, and
missing data, and returns ONE clear outcome:

    approve / block / delay / inspect_first / pca_review_required

Design rules (same spirit as `recommendation_engine.py`):
* No FastAPI / SQLAlchemy imports — plain objects via duck typing, unit-testable alone.
* Every verdict is explainable: exact triggered rules, the inputs used, the arithmetic,
  what information is missing, and an honest confidence derived from input completeness.
* Honest by design: a compliance check that could not run (missing PHI, REI, harvest
  date, or active ingredient) can NEVER produce "approve" — it escalates to PCA review.
* "block" only ever means "this application conflicts with the entered timing values" —
  it blocks a spray, it never prescribes one. Nothing here says "must spray".
* PHI/REI values are user-entered, not label-verified; the disclaimer travels with
  every decision verbatim.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta

from app import crop_aliases, label_data, target_aliases
from app.recommendation_engine import (
    RECENT_WINDOW_DAYS,
    SAME_INGREDIENT_MAX,
)

# Outcome vocabulary (single source of truth; schemas mirror this).
OUTCOME_APPROVE = "approve"
OUTCOME_BLOCK = "block"
OUTCOME_DELAY = "delay"
OUTCOME_INSPECT_FIRST = "inspect_first"
OUTCOME_PCA_REVIEW = "pca_review_required"

SEVERITY_NONE = "none"
SEVERITY_CAUTION = "caution"
SEVERITY_CRITICAL = "critical"

CONFIDENCE_LOW = "low"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_HIGH = "high"

# --- Rule-source authority -----------------------------------------------------------
# Every rule states where its inputs came from and how trustworthy that source is.
# Only verified-label or PCA-entered sources may back a DEFINITIVE approve/block;
# grower-entered values and heuristics always yield a PROVISIONAL result that a PCA
# must confirm. There is deliberately no label database yet, so nothing currently
# produces "verified_label" — the vocabulary exists so the gating is already correct
# the day label data arrives.
AUTHORITY_VERIFIED_LABEL = "verified_label"
AUTHORITY_PCA = "pca_entered"
AUTHORITY_GROWER = "grower_entered"
AUTHORITY_IMPORTED = "imported_unverified"
AUTHORITY_HEURISTIC = "heuristic"

DEFINITIVE_AUTHORITIES = (AUTHORITY_VERIFIED_LABEL, AUTHORITY_PCA)

AUTHORITY_LABELS = {
    AUTHORITY_VERIFIED_LABEL: "verified label",
    AUTHORITY_PCA: "PCA-entered value",
    AUTHORITY_GROWER: "grower-entered value",
    AUTHORITY_IMPORTED: "imported, unverified value",
    AUTHORITY_HEURISTIC: "heuristic (rule-of-thumb threshold)",
}

# Weakest-first ranking: a rule (and a decision) is only as strong as its weakest input.
_AUTHORITY_RANK = {
    AUTHORITY_HEURISTIC: 0,
    AUTHORITY_IMPORTED: 1,
    AUTHORITY_GROWER: 2,
    AUTHORITY_PCA: 3,
    AUTHORITY_VERIFIED_LABEL: 4,
}

# Field-level provenance source types (DecisionInputValue vocabulary) -> rule authority.
INPUT_SOURCE_TO_AUTHORITY = {
    "authoritative_provider": AUTHORITY_VERIFIED_LABEL,
    "pca_verified": AUTHORITY_PCA,
    "user_entered": AUTHORITY_GROWER,
    # Demo values behave like user-entered inside the engine; demo separation happens
    # at the record level (data_source/data_confidence), never here.
    "demo": AUTHORITY_GROWER,
    "imported_unverified": AUTHORITY_IMPORTED,
}

# Checks this engine deliberately does NOT run, and says so, because they require
# authoritative pesticide-label data that does not exist in the system. They are
# reported per decision under `not_evaluated` — never simulated with guesses.
#
# Each carries a stable id as well as the human name a PCA reads: a rule that genuinely
# starts running has to be able to remove itself from the disclosure, and it identifies
# itself by id, not by matching prose.
CHECK_MAX_SEASONAL_RATE = "max_seasonal_rate"
CHECK_MAX_APPLICATIONS = "max_applications_per_season"
CHECK_RETREATMENT_INTERVAL = "min_retreatment_interval"
CHECK_CROP_REGISTRATION = "crop_use_registration"

LABEL_DEPENDENT_CHECK_NAMES = {
    CHECK_MAX_SEASONAL_RATE: "maximum seasonal rate",
    CHECK_MAX_APPLICATIONS: "maximum number of applications per season",
    CHECK_RETREATMENT_INTERVAL: "minimum retreatment interval",
    CHECK_CROP_REGISTRATION: "crop/use registration match",
}

# Why none of them can run. There is one reason today because exactly one thing is
# missing, but the reason travels per check so a specific one ("this product has no
# registration number", "no label record on file for this crop") can replace it for a
# single check later without touching any caller.
REASON_NO_LABEL_DATA = "requires authoritative label data — no label database exists"

NOT_EVALUATED_CHECKS = tuple(
    {"check_id": check_id, "check": name, "reason": REASON_NO_LABEL_DATA}
    for check_id, name in LABEL_DEPENDENT_CHECK_NAMES.items()
)


def label_checks_not_evaluated(evaluated_check_ids=None, reasons=None) -> list[dict]:
    """The label-dependent checks that did NOT run for one decision, each with its reason.

    Derived per decision rather than declared once, because a fixed list cannot express
    the thing that matters: the moment a check can genuinely run it must disappear from
    this disclosure, and until then it must say why it did not.

    Every check not named in `evaluated_check_ids` is disclosed. That direction is
    deliberate — a check missing from both the rules and this list would be silently
    unaccounted for, which reads as "fine" rather than "never looked at".

    `reasons` supplies the specific sentence for a check ("this product has no
    registration number", "the label states no retreatment interval"). Anything without
    one falls back to the generic reason, so a new abstention path can never produce a
    check that is silently absent from both the rules and the disclosure.
    """
    evaluated = set(evaluated_check_ids or ())
    reasons = dict(reasons or {})
    return [
        {**entry, "reason": reasons.get(entry["check_id"], entry["reason"])}
        for entry in NOT_EVALUATED_CHECKS
        if entry["check_id"] not in evaluated
    ]


@dataclass(frozen=True)
class LabelContext:
    """Pre-resolved label data for ONE decision. Built by crud, consumed here.

    The engine stays framework-free, so everything requiring a database — which product
    a registration number identifies, which label record is live, and whether a licensed
    PCA has verified it for this farm — is resolved by the caller and handed over as
    plain values. What the engine does with them (the arithmetic, the reasons, the
    verdict) stays here and unit-tests alone.

    The default instance is the state the system has been in until now: nothing
    resolved, every label-dependent check disclosed as not run. That is why every field
    has a default — an evaluation that is not given label data behaves exactly as before.

    `record` is the live label record for this crop. It is used ONLY when
    `promotion_blocked_reason` is None: a transcription nobody has verified is on file,
    not in force, and treating it as authoritative is the failure mode this whole layer
    exists to prevent.
    """
    record: object | None = None
    # Why no record resolved (no registration number, base-only match, wrong crop...).
    unresolved_reason: str | None = None
    # Why a resolved record may not back a check (unverified, missing provenance...).
    promotion_blocked_reason: str | None = None
    # Stable citation for the record, e.g. "label:100-1234:strawberry:rev. 2025-03".
    reference: str | None = None
    # Every crop registered on this product's PROMOTABLE live records, and why that
    # list may not be compared against. A partial transcription's silence about a crop
    # is NOT evidence the crop is unregistered, so `crop_registration_reason` is None
    # only when a human has confirmed the list is complete — the check that most needs
    # this guard is also the one that would otherwise emit a false BLOCK.
    registered_crops: tuple = ()
    crop_registration_reason: str | None = None
    # What a human had entered for the fields the label now backs, so a disagreement is
    # reported rather than silently resolved by whoever wrote last.
    entered_values: dict = field(default_factory=dict)
    # The season the per-season limits are counted over, or why it is unknown.
    season_start: date | None = None
    season_reason: str | None = None

    @property
    def usable_record(self):
        """The record, but only when it may actually back a regulatory check."""
        if self.record is None or self.promotion_blocked_reason is not None:
            return None
        return self.record

    @property
    def blocking_reason(self) -> str | None:
        """Why no label check can run at all, or None when one can."""
        if self.record is None:
            return self.unresolved_reason or REASON_NO_LABEL_DATA
        return self.promotion_blocked_reason

# Decision authority levels — how strongly the determining inputs back the verdict.
# Three honest levels replace the old binary "definitive"/"provisional":
#   verified_label_grounded — every determining check backed by verified label data.
#     Deliberately unreachable today (no label database exists); the level exists so
#     the gate is already correct the day label data arrives.
#   pca_authorized — every determining check backed by PCA-entered (or verified)
#     values. A licensed PCA supplied the inputs; still not label-verified.
#   provisional — anything else; a PCA must confirm before it is relied on.
LEVEL_VERIFIED_LABEL = "verified_label_grounded"
LEVEL_PCA_AUTHORIZED = "pca_authorized"
LEVEL_PROVISIONAL = "provisional"

DECISION_AUTHORITY_LABELS = {
    LEVEL_VERIFIED_LABEL: "Verified-label grounded",
    LEVEL_PCA_AUTHORIZED: "PCA-authorized",
    LEVEL_PROVISIONAL: "Provisional",
}

# Appended verbatim to every decision so nobody mistakes user-entered PHI/REI values
# for label-verified ones.
PLANNED_SPRAY_DISCLAIMER = (
    "PHI and REI checks use values entered by the user and are not independently verified "
    "against the current pesticide label."
)

# The same sentence for a decision whose values DID come from a verified label. It
# still says what was not checked, because a verified PHI does not make the rotation
# and scouting heuristics label-grounded, and it still names the label so a reader
# can go and look. Nothing is deleted here — the honest default above stays the
# default, and this replaces it only for decisions that genuinely earned it.
LABEL_GROUNDED_DISCLAIMER = (
    "PHI and REI values come from {reference}, verified against the label document by "
    "a licensed PCA for this farm. Other checks (resistance rotation, scouting "
    "evidence) remain heuristics, not label requirements."
)


def planned_spray_disclaimer(label_reference: str | None = None) -> str:
    """The disclaimer for one decision — conditional on what actually backed it.

    Kept as a function beside the constant rather than replacing it: every caller
    without label coverage gets the byte-identical original sentence, so no existing
    surface changes wording until a real verified label is behind the numbers.
    """
    if not label_reference:
        return PLANNED_SPRAY_DISCLAIMER
    return LABEL_GROUNDED_DISCLAIMER.format(reference=label_reference)

# Farmer/PCA-facing next actions, one per outcome.
NEXT_ACTIONS = {
    OUTCOME_BLOCK: (
        "Conflict with entered harvest/re-entry timing — resolve the conflict with your "
        "PCA before this application."
    ),
    OUTCOME_DELAY: "Wait until the active re-entry interval clears, then re-check.",
    OUTCOME_PCA_REVIEW: "PCA / agronomist review required before this application.",
    OUTCOME_INSPECT_FIRST: "Inspect and log scouting evidence for the target first.",
    OUTCOME_APPROVE: (
        "No conflicts found from entered records — final decision stays with you and "
        "your PCA."
    ),
}


@dataclass
class DecisionRule:
    """One evaluated rule, whether it triggered or not (the full audit trail)."""
    rule_id: str
    name: str
    triggered: bool
    severity: str          # none / caution / critical (severity if triggered)
    detail: str            # human sentence: what was found (or confirmed OK)
    calculation: str | None = None  # the exact arithmetic, when there is any
    inputs: dict = field(default_factory=dict)  # the values this rule read
    # Where this rule's inputs came from and how trustworthy that source is.
    source_authority: str = AUTHORITY_HEURISTIC
    verification_status: str = "unverified"  # "verified" only for verified_label
    entered_by: str | None = None            # who supplied the values, when known


@dataclass
class PlannedSprayDecision:
    """The single explainable result of a pre-spray check."""
    outcome: str = OUTCOME_PCA_REVIEW
    severity: str = SEVERITY_NONE
    confidence: str = CONFIDENCE_LOW
    rules: list[DecisionRule] = field(default_factory=list)
    inputs_used: dict = field(default_factory=dict)
    missing_information: list[str] = field(default_factory=list)
    required_next_action: str = ""
    review_required: bool = True
    narrative: str = ""            # cautious plain-text summary (stored as check_text)
    disclaimer: str = PLANNED_SPRAY_DISCLAIMER
    # Authority gating: verified_label_grounded / pca_authorized only when the
    # determining rules are backed by those sources; otherwise provisional (a PCA
    # must confirm before the result is relied on).
    authority_level: str = LEVEL_PROVISIONAL
    authority_basis: str = ""
    # Label-dependent checks that were NOT run (with reasons) — honest, never guessed.
    # Defaults to disclosing all four; a label rule that runs narrows this by id.
    not_evaluated: list = field(default_factory=label_checks_not_evaluated)

    @property
    def triggered_rules(self) -> list[DecisionRule]:
        return [r for r in self.rules if r.triggered]

    def as_payload(self) -> dict:
        """JSON-serializable snapshot persisted with the planned spray."""
        return {
            "outcome": self.outcome,
            "severity": self.severity,
            "confidence": self.confidence,
            "authority_level": self.authority_level,
            "authority_basis": self.authority_basis,
            "rules": [
                {
                    "rule_id": r.rule_id,
                    "name": r.name,
                    "triggered": r.triggered,
                    "severity": r.severity,
                    "detail": r.detail,
                    "calculation": r.calculation,
                    "inputs": r.inputs,
                    "source_authority": r.source_authority,
                    "verification_status": r.verification_status,
                    "entered_by": r.entered_by,
                }
                for r in self.rules
            ],
            "inputs_used": self.inputs_used,
            "missing_information": self.missing_information,
            "not_evaluated": self.not_evaluated,
            "required_next_action": self.required_next_action,
            "review_required": self.review_required,
            "disclaimer": self.disclaimer,
        }


# The severity scale `PcaPolicy.min_severity_to_treat` is expressed on. An observation
# recorded on any OTHER scale is not comparable to that threshold and is never
# converted: a 3 on a 1-10 scale is not a 3 on a 1-5 scale, and silently comparing them
# reads as "threshold met" when it is not. Unstated means the default scale.
DEFAULT_SEVERITY_SCALE = "1-5"
_COMPARABLE_SEVERITY_SCALES = ("", "1-5", "1to5", "1_5", "0-5", "0to5")


def severity_is_comparable_to_threshold(observation) -> bool:
    """Is this observation's severity on the same scale as a PCA threshold?"""
    scale = (getattr(observation, "severity_scale", None) or "").strip().lower()
    return scale.replace(" ", "") in _COMPARABLE_SEVERITY_SCALES


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def _recent(items, date_attr: str, today: date):
    cutoff = today - timedelta(days=RECENT_WINDOW_DAYS)
    return [
        it for it in items
        if getattr(it, date_attr, None) is not None
        and cutoff <= getattr(it, date_attr) <= today
    ]


def evaluate_planned_spray(
    farm,
    planned,
    spray_events,
    scout_observations,
    pca_policies=None,
    today: date | None = None,
    input_sources: dict | None = None,
    label_context: "LabelContext | None" = None,
) -> PlannedSprayDecision:
    """Check an intended spray before it happens and return one explainable outcome.

    Parameters
    ----------
    farm: object with `expected_harvest_date` (date or None).
    planned: object with `intended_date`, `product_name`, `active_ingredient`,
        `target_pest_or_disease`, `pre_harvest_interval_days`, `re_entry_interval_hours`
        (optionally `epa_reg_no`, `moa_group`, `rate_amount`, `rate_unit`, ...).
    spray_events / scout_observations: the farm's current records (duck-typed).
    pca_policies: PCA-entered action thresholds (objects with `target_pest_or_disease`,
        `min_severity_to_treat`, `entered_by`). Optional — without a matching policy
        the scouting rule stays a plain heuristic; a threshold is NEVER invented.
    today: injectable "current date" for deterministic testing.
    input_sources: optional field-level provenance —
        {field_name: {"source_type": InputSourceType, "entered_by": str|None}}.
        When present it drives each rule's source authority (a rule is only as strong
        as its weakest input); when absent the legacy record-level `values_source`
        applies. Imported values can never back a definitive result.
    label_context: pre-resolved, PCA-verified label data for this product and crop
        (see `LabelContext`). Absent — the normal case — every label-dependent check
        reports that it did not run and no verdict changes.
    """
    if today is None:
        today = date.today()

    spray_events = list(spray_events or [])
    scout_observations = list(scout_observations or [])
    pca_policies = list(pca_policies or [])
    input_sources = dict(input_sources or {})
    label = label_context or LabelContext()

    decision = PlannedSprayDecision()

    product = getattr(planned, "product_name", None) or "the planned product"
    intended = getattr(planned, "intended_date", None) or today
    planned_ai = (getattr(planned, "active_ingredient", None) or "").strip().lower()
    target = (getattr(planned, "target_pest_or_disease", None) or "").strip().lower()
    phi = getattr(planned, "pre_harvest_interval_days", None)
    rei_hours = getattr(planned, "re_entry_interval_hours", None)
    harvest = getattr(farm, "expected_harvest_date", None)
    epa_reg_no = (getattr(planned, "epa_reg_no", None) or "").strip()
    moa_group = (getattr(planned, "moa_group", None) or "").strip().lower()
    rate_amount = getattr(planned, "rate_amount", None)
    rate_unit = (getattr(planned, "rate_unit", None) or "").strip()

    # Who supplied the PHI/REI values for THIS check (never a verified label today).
    values_source = getattr(planned, "values_source", None) or AUTHORITY_GROWER
    if values_source not in (AUTHORITY_GROWER, AUTHORITY_PCA, AUTHORITY_IMPORTED):
        values_source = AUTHORITY_GROWER
    values_entered_by = getattr(planned, "values_entered_by", None) or {
        AUTHORITY_PCA: "PCA",
        AUTHORITY_IMPORTED: "imported record",
    }.get(values_source, "grower")

    def field_authority(*field_names: str) -> tuple[str, str | None]:
        """(weakest source authority, its attribution) across the named fields.

        Field-level provenance wins when available; otherwise the legacy record-level
        values_source stands in for every field.
        """
        weakest = None
        weakest_by = None
        for name in field_names:
            info = input_sources.get(name)
            if info:
                authority = INPUT_SOURCE_TO_AUTHORITY.get(
                    info.get("source_type"), AUTHORITY_IMPORTED
                )
                by = info.get("entered_by")
            else:
                authority, by = values_source, values_entered_by
            if weakest is None or _AUTHORITY_RANK[authority] < _AUTHORITY_RANK[weakest]:
                weakest, weakest_by = authority, by
        return weakest or values_source, weakest_by or values_entered_by

    decision.inputs_used = {
        "product_name": product,
        "epa_reg_no": epa_reg_no or None,
        "active_ingredient": planned_ai or None,
        "moa_group": moa_group or None,
        "target_pest_or_disease": target or None,
        "intended_date": _iso(intended),
        "rate_amount": rate_amount,
        "rate_unit": rate_unit or None,
        "pre_harvest_interval_days": phi,
        "re_entry_interval_hours": rei_hours,
        "expected_harvest_date": _iso(harvest),
        "phi_rei_values_source": values_source,
        "phi_rei_values_entered_by": values_entered_by,
        "spray_events_on_record": len(spray_events),
        "scouting_observations_on_record": len(scout_observations),
        "recent_window_days": RECENT_WINDOW_DAYS,
        # Which label record backed this decision, so a later revision can be detected
        # rather than silently changing what a stored, signed decision means.
        "label_reference": label.reference,
        "label_record_id": getattr(label.record, "id", None),
    }
    if input_sources:
        decision.inputs_used["field_sources"] = {
            name: info.get("source_type") for name, info in input_sources.items()
        }

    # ---------------------------------------------------------------- missing data
    # Any compliance check that cannot run means the result can never be "approve".
    missing: list[str] = []
    if harvest is None:
        missing.append(
            "Expected harvest date is not set on the farm — the PHI and harvest re-entry "
            "checks could not run."
        )
    # `is None` deliberately: PHI 0 days / REI 0 hours are real label values (the check
    # runs and passes), not missing data.
    if phi is None:
        missing.append(
            "No PHI (days) entered for this product — the pre-harvest interval check "
            "could not run."
        )
    if rei_hours is None:
        missing.append(
            "No REI (hours) entered for this product — the re-entry interval checks "
            "could not run."
        )
    if not planned_ai:
        missing.append(
            "No active ingredient entered — the repeated-ingredient (resistance) check "
            "could not run."
        )
    if not target:
        missing.append(
            "No target pest/disease entered — scouting evidence could not be linked."
        )
    decision.missing_information = missing

    # ------------------------------------------- Rule 1: PHI vs. expected harvest
    phi_authority, phi_entered_by = field_authority(
        "pre_harvest_interval_days", "expected_harvest_date", "intended_date"
    )
    rei_authority, rei_entered_by = field_authority(
        "re_entry_interval_hours", "expected_harvest_date", "intended_date"
    )
    phi_conflict = False
    if harvest is not None and phi is not None:
        phi_clears_on = intended + timedelta(days=phi)
        phi_conflict = harvest < phi_clears_on
        decision.rules.append(DecisionRule(
            rule_id="phi_harvest_conflict",
            name="Pre-harvest interval vs. expected harvest",
            triggered=phi_conflict,
            severity=SEVERITY_CRITICAL if phi_conflict else SEVERITY_NONE,
            detail=(
                f"Applying '{product}' on {intended.isoformat()} with the entered PHI of "
                f"{phi} days would clear on {phi_clears_on.isoformat()}, "
                + (
                    f"AFTER the expected harvest on {harvest.isoformat()} — residue risk."
                    if phi_conflict
                    else f"before the expected harvest on {harvest.isoformat()}."
                )
            ),
            calculation=(
                f"{intended.isoformat()} + {phi} days (entered PHI) = "
                f"{phi_clears_on.isoformat()} vs. harvest {harvest.isoformat()}"
            ),
            inputs={
                "intended_date": _iso(intended),
                "pre_harvest_interval_days": phi,
                "expected_harvest_date": _iso(harvest),
            },
            source_authority=phi_authority,
            entered_by=phi_entered_by,
        ))

    # -------------------------------------- Rule 2: planned REI vs. expected harvest
    # Hand-harvest crews cannot enter while the REI is active. Rounded up to whole
    # days (cautious) because records have date granularity.
    rei_harvest_conflict = False
    if harvest is not None and rei_hours is not None:
        rei_days = math.ceil(rei_hours / 24)
        rei_clears_on = intended + timedelta(days=rei_days)
        rei_harvest_conflict = harvest < rei_clears_on
        decision.rules.append(DecisionRule(
            rule_id="rei_active_at_harvest",
            name="Planned re-entry interval vs. expected harvest",
            triggered=rei_harvest_conflict,
            severity=SEVERITY_CRITICAL if rei_harvest_conflict else SEVERITY_NONE,
            detail=(
                f"The entered REI of {rei_hours}h (rounded up to {rei_days} day(s)) would "
                + (
                    f"still be active on the expected harvest date "
                    f"{harvest.isoformat()} — workers could not enter to pick."
                    if rei_harvest_conflict
                    else f"clear on {rei_clears_on.isoformat()}, before harvest."
                )
            ),
            calculation=(
                f"{intended.isoformat()} + ceil({rei_hours}h / 24) = "
                f"{rei_clears_on.isoformat()} vs. harvest {harvest.isoformat()}"
            ),
            inputs={
                "intended_date": _iso(intended),
                "re_entry_interval_hours": rei_hours,
                "expected_harvest_date": _iso(harvest),
            },
            source_authority=rei_authority,
            entered_by=rei_entered_by,
        ))

    # ------------------------------- Rule 3: a prior spray's REI active on intended date
    prior_rei_active = False
    prior_rei_clears: date | None = None
    for s in spray_events:
        s_rei = getattr(s, "re_entry_interval_hours", None)
        applied = getattr(s, "application_date", None)
        if s_rei and applied:
            clears_on = applied + timedelta(days=math.ceil(s_rei / 24))
            if clears_on > intended:
                prior_rei_active = True
                if prior_rei_clears is None or clears_on > prior_rei_clears:
                    prior_rei_clears = clears_on
    decision.rules.append(DecisionRule(
        rule_id="prior_rei_overlap",
        name="Prior application's re-entry interval on the intended date",
        triggered=prior_rei_active,
        severity=SEVERITY_CAUTION if prior_rei_active else SEVERITY_NONE,
        detail=(
            f"A previous application's re-entry interval may still be active on "
            f"{intended.isoformat()}; it clears about {prior_rei_clears.isoformat()}."
            if prior_rei_active
            else "No prior application's re-entry interval overlaps the intended date."
        ),
        calculation=(
            f"latest prior REI clears {prior_rei_clears.isoformat()} > intended "
            f"{intended.isoformat()}"
            if prior_rei_active
            else None
        ),
        inputs={"intended_date": _iso(intended)},
        source_authority=AUTHORITY_GROWER,
        entered_by="farm spray records",
    ))

    # ---------------------------------------- Rule 4: repeated active ingredient
    overuse = False
    if planned_ai:
        recent_sprays = _recent(spray_events, "application_date", today)
        prior_uses = sum(
            1 for s in recent_sprays
            if (getattr(s, "active_ingredient", None) or "").strip().lower() == planned_ai
        )
        overuse = prior_uses + 1 > SAME_INGREDIENT_MAX
        decision.rules.append(DecisionRule(
            rule_id="repeated_active_ingredient",
            name="Repeated active ingredient (resistance)",
            triggered=overuse,
            severity=SEVERITY_CAUTION if overuse else SEVERITY_NONE,
            detail=(
                f"This would be use number {prior_uses + 1} of '{planned_ai}' in the last "
                f"{RECENT_WINDOW_DAYS} days (limit {SAME_INGREDIENT_MAX}). Frequent repeat "
                f"use raises resistance and residue concerns — rotation should be reviewed."
                if overuse
                else f"'{planned_ai}' used {prior_uses} time(s) in the last "
                f"{RECENT_WINDOW_DAYS} days — within the rotation limit."
            ),
            calculation=(
                f"{prior_uses} recent use(s) + 1 planned = {prior_uses + 1} vs. limit "
                f"{SAME_INGREDIENT_MAX} in {RECENT_WINDOW_DAYS} days"
            ),
            inputs={
                "active_ingredient": planned_ai,
                "prior_uses_in_window": prior_uses,
                "limit": SAME_INGREDIENT_MAX,
            },
        ))

    # --------------------------- Rule 4b: repeated mode-of-action group (resistance)
    # Only runs when structured MoA data exists on the planned spray — the engine
    # never infers a FRAC/IRAC group from a product or ingredient name.
    moa_repeat = False
    if moa_group:
        recent_sprays = _recent(spray_events, "application_date", today)
        moa_prior = sum(
            1 for s in recent_sprays
            if (getattr(s, "moa_group", None) or "").strip().lower() == moa_group
        )
        moa_repeat = moa_prior + 1 > SAME_INGREDIENT_MAX
        moa_authority, moa_entered_by = field_authority("moa_group")
        decision.rules.append(DecisionRule(
            rule_id="repeated_moa_group",
            name="Repeated mode-of-action group (resistance)",
            triggered=moa_repeat,
            severity=SEVERITY_CAUTION if moa_repeat else SEVERITY_NONE,
            detail=(
                f"This would be use number {moa_prior + 1} of MoA group '{moa_group}' in "
                f"the last {RECENT_WINDOW_DAYS} days (limit {SAME_INGREDIENT_MAX}) — "
                f"repeating one mode of action drives resistance; rotation should be "
                f"reviewed."
                if moa_repeat
                else f"MoA group '{moa_group}' used {moa_prior} time(s) in the last "
                f"{RECENT_WINDOW_DAYS} days — within the rotation limit "
                f"(only applications with recorded MoA data are counted)."
            ),
            calculation=(
                f"{moa_prior} recent use(s) + 1 planned = {moa_prior + 1} vs. limit "
                f"{SAME_INGREDIENT_MAX} in {RECENT_WINDOW_DAYS} days"
            ),
            inputs={
                "moa_group": moa_group,
                "prior_uses_in_window": moa_prior,
                "limit": SAME_INGREDIENT_MAX,
            },
            source_authority=moa_authority,
            entered_by=moa_entered_by,
        ))

    # ------------------------------------ Rule 4c: product identity completeness
    identity_ambiguous = not planned_ai and not epa_reg_no
    identity_authority, identity_entered_by = field_authority(
        "product_name", "active_ingredient", "epa_reg_no"
    )
    decision.rules.append(DecisionRule(
        rule_id="product_identity",
        name="Product identity (name + active ingredient / EPA reg. no.)",
        triggered=identity_ambiguous,
        severity=SEVERITY_CAUTION if identity_ambiguous else SEVERITY_NONE,
        detail=(
            f"'{product}' has no active ingredient and no EPA registration number on "
            f"record — the product identity is ambiguous, so resistance and label "
            f"checks cannot be tied to a specific chemistry."
            if identity_ambiguous
            else f"Product identity for '{product}' includes "
            + (f"EPA reg. no. {epa_reg_no}" if epa_reg_no else f"active ingredient '{planned_ai}'")
            + "."
        ),
        calculation=None,
        inputs={
            "product_name": product,
            "active_ingredient": planned_ai or None,
            "epa_reg_no": epa_reg_no or None,
        },
        source_authority=identity_authority,
        entered_by=identity_entered_by,
    ))

    # ---------------------------------------- Rule 4d: application-rate completeness
    rate_incomplete = False
    if rate_amount is not None or rate_unit:
        rate_incomplete = (rate_amount is None) != (not rate_unit)
        rate_authority, rate_entered_by = field_authority("rate_amount", "rate_unit")
        decision.rules.append(DecisionRule(
            rule_id="rate_completeness",
            name="Application rate completeness (amount + unit)",
            triggered=rate_incomplete,
            severity=SEVERITY_CAUTION if rate_incomplete else SEVERITY_NONE,
            detail=(
                "The application rate is incomplete — "
                + (
                    f"an amount ({rate_amount}) was recorded without a unit."
                    if rate_amount is not None
                    else f"a unit ('{rate_unit}') was recorded without an amount."
                )
                + " A rate that cannot be read unambiguously cannot be reviewed."
                if rate_incomplete
                else f"Application rate recorded as {rate_amount} {rate_unit}."
            ),
            calculation=None,
            inputs={"rate_amount": rate_amount, "rate_unit": rate_unit or None},
            source_authority=rate_authority,
            entered_by=rate_entered_by,
        ))

    # ------------------------------- Rule 4e: unverified imported compliance values
    # Imported values are explicitly unverified until a PCA (or, one day, an
    # authoritative label provider) confirms them — they can never back an approve.
    imported_fields = sorted(
        name for name, info in input_sources.items()
        if info.get("source_type") == "imported_unverified"
    )
    imported_unverified = bool(imported_fields)
    if imported_unverified:
        decision.rules.append(DecisionRule(
            rule_id="unverified_imported_values",
            name="Imported values not yet verified",
            triggered=True,
            severity=SEVERITY_CAUTION,
            detail=(
                f"{len(imported_fields)} input value(s) came from an import and have "
                f"not been verified by a PCA: {', '.join(imported_fields)}. Unverified "
                f"regulatory data can never produce an automatic approve — a PCA must "
                f"review this decision."
            ),
            calculation=None,
            inputs={"imported_unverified_fields": imported_fields},
            source_authority=AUTHORITY_IMPORTED,
            entered_by=values_entered_by,
        ))

    # ---------------------------- Rules L1-L5: label-grounded checks
    # The four checks that have always reported "not evaluated", plus one that can only
    # exist once label data does. Each either appends a DecisionRule or records the
    # SPECIFIC reason it could not run. Nothing here is ever simulated: an absent label
    # value leaves its check unevaluated rather than assuming "no limit".
    #
    # These are the only rules that may carry AUTHORITY_VERIFIED_LABEL, because they are
    # the only ones reading a value a licensed PCA checked against the primary document.
    #
    # Cross-decision counting reads SprayEvent ONLY, never PlannedSpray: an applied
    # outcome already materializes a linked SprayEvent, so counting both would report
    # one application twice — as an over-count, i.e. a false BLOCK.
    label_checks_run: set[str] = set()
    label_reasons: dict[str, str] = {}
    label_record = label.usable_record
    label_block = False
    label_delay = False
    label_disagreement = False
    crop = (getattr(planned, "crop", None) or "").strip()

    def _label_rule(check_id: str | None, **kwargs) -> None:
        if check_id is not None:
            label_checks_run.add(check_id)
        decision.rules.append(DecisionRule(
            source_authority=AUTHORITY_VERIFIED_LABEL,
            verification_status="verified",
            entered_by=label.reference,
            **kwargs,
        ))

    # Prior applications of THIS product, identified by an EXACT registration-number
    # match. A base-registration match is a different label and is never counted.
    prior_same_product = [
        s for s in spray_events
        if getattr(s, "application_date", None) is not None
        and label_data.match_product_identity(
            epa_reg_no, getattr(s, "epa_reg_no", None)
        ) == label_data.MATCH
    ]

    # --- L1: crop / use registration ------------------------------------------------
    # The only label check that does not need a record for THIS crop — its whole point
    # is what happens when there is none.
    if label.crop_registration_reason is not None:
        label_reasons[CHECK_CROP_REGISTRATION] = label.crop_registration_reason
    elif not label.registered_crops:
        # No verified registered-crop list at all — the generic reason, not a complaint
        # about the decision's own data.
        label_reasons[CHECK_CROP_REGISTRATION] = label.blocking_reason
    elif not crop:
        label_reasons[CHECK_CROP_REGISTRATION] = (
            "no crop is recorded on this decision, so it cannot be compared to the "
            "crops this product is registered for"
        )
    else:
        registered = list(label.registered_crops)
        verdicts = {c: crop_aliases.match_crops(crop, c) for c in registered}
        matched = [c for c, v in verdicts.items() if v == crop_aliases.MATCH]
        ambiguous = [c for c, v in verdicts.items() if v == crop_aliases.AMBIGUOUS]
        if not matched and ambiguous:
            # "strawberry" inside "strawberry tree" is not a registration. Refusing to
            # decide is right in both directions: neither a clearance nor a block.
            label_reasons[CHECK_CROP_REGISTRATION] = (
                f"crop {crop!r} only partially matches the registered crop(s) "
                f"{', '.join(repr(c) for c in ambiguous)} — a related crop is not the "
                f"same registration, so a human must decide"
            )
        else:
            _label_rule(
                CHECK_CROP_REGISTRATION,
                rule_id="label_crop_registration",
                name="Crop / use registered on the label",
                triggered=not matched,
                severity=SEVERITY_CRITICAL if not matched else SEVERITY_NONE,
                detail=(
                    f"The verified label for {product} does not list {crop!r} among its "
                    f"registered crops ({', '.join(sorted(registered))}). Applying a "
                    f"product to a crop it is not registered for is an off-label use."
                    if not matched
                    else f"{crop!r} is a registered crop on the verified label."
                ),
                calculation=(
                    f"decision crop {crop!r} vs registered crops "
                    f"{sorted(registered)} (exact or explicit alias only)"
                ),
                inputs={"crop": crop, "registered_crops": sorted(registered)},
            )
            label_block = label_block or not matched

    # --- L2: maximum applications per season ----------------------------------------
    max_applications = getattr(label_record, "max_applications_per_season", None)
    if label_record is None:
        label_reasons[CHECK_MAX_APPLICATIONS] = label.blocking_reason
    elif max_applications is None:
        label_reasons[CHECK_MAX_APPLICATIONS] = (
            "this label states no maximum number of applications per season — a silent "
            "label is not a limit of 'unlimited', so nothing is compared"
        )
    elif label.season_start is None:
        label_reasons[CHECK_MAX_APPLICATIONS] = (
            label.season_reason
            or "no season window is on record for this farm, so applications cannot be "
               "counted over a season"
        )
    else:
        in_season = [
            s for s in prior_same_product
            if label.season_start <= getattr(s, "application_date") <= intended
        ]
        # +1 for the application being checked: the question is whether making THIS
        # application would exceed the label, not whether past ones already did.
        would_be = len(in_season) + 1
        exceeded = would_be > max_applications
        _label_rule(
            CHECK_MAX_APPLICATIONS,
            rule_id="label_max_applications",
            name="Maximum applications per season (label)",
            triggered=exceeded,
            severity=SEVERITY_CRITICAL if exceeded else SEVERITY_NONE,
            detail=(
                f"This would be application {would_be} of {product} this season; the "
                f"verified label allows {max_applications}."
                if exceeded
                else f"Application {would_be} of a label maximum of {max_applications} "
                     f"this season."
            ),
            calculation=(
                f"{len(in_season)} recorded application(s) since "
                f"{label.season_start.isoformat()} + this one = {would_be} vs label "
                f"maximum {max_applications}"
            ),
            inputs={
                "applications_this_season": len(in_season),
                "including_this_one": would_be,
                "label_maximum": max_applications,
                "season_start": _iso(label.season_start),
            },
        )
        label_block = label_block or exceeded

    # --- L3: minimum retreatment interval -------------------------------------------
    min_retreatment = getattr(label_record, "min_retreatment_interval_days", None)
    if label_record is None:
        label_reasons[CHECK_RETREATMENT_INTERVAL] = label.blocking_reason
    elif min_retreatment is None:
        label_reasons[CHECK_RETREATMENT_INTERVAL] = (
            "this label states no minimum retreatment interval, so there is nothing to "
            "compare the interval since the last application against"
        )
    else:
        previous = [
            getattr(s, "application_date") for s in prior_same_product
            if getattr(s, "application_date") <= intended
        ]
        last_applied = max(previous) if previous else None
        if last_applied is None:
            _label_rule(
                CHECK_RETREATMENT_INTERVAL,
                rule_id="label_retreatment_interval",
                name="Minimum retreatment interval (label)",
                triggered=False,
                severity=SEVERITY_NONE,
                detail=(
                    f"No previous application of {product} is on record, so the label's "
                    f"{min_retreatment}-day retreatment interval does not apply."
                ),
                calculation=None,
                inputs={"label_minimum_days": min_retreatment},
            )
        else:
            gap = (intended - last_applied).days
            too_soon = gap < min_retreatment
            _label_rule(
                CHECK_RETREATMENT_INTERVAL,
                rule_id="label_retreatment_interval",
                name="Minimum retreatment interval (label)",
                triggered=too_soon,
                severity=SEVERITY_CAUTION if too_soon else SEVERITY_NONE,
                detail=(
                    f"{gap} day(s) since the last application of {product} on "
                    f"{last_applied.isoformat()}; the verified label requires at least "
                    f"{min_retreatment}. The interval clears on "
                    f"{(last_applied + timedelta(days=min_retreatment)).isoformat()}."
                    if too_soon
                    else f"{gap} day(s) since the last application of {product} — the "
                         f"label's {min_retreatment}-day minimum is met."
                ),
                calculation=(
                    f"{intended.isoformat()} - {last_applied.isoformat()} = {gap} days "
                    f"vs label minimum {min_retreatment} days"
                ),
                inputs={
                    "days_since_last_application": gap,
                    "label_minimum_days": min_retreatment,
                    "last_application_date": _iso(last_applied),
                },
            )
            label_delay = label_delay or too_soon

    # --- L4: maximum seasonal rate --------------------------------------------------
    # The only check that needs arithmetic across records in different units. Every
    # conversion is definitional and cited, or it is refused by name (label_data) — an
    # invented density would produce a rate comparison that LOOKS like a finding.
    max_rate = getattr(label_record, "max_seasonal_rate_amount", None)
    max_rate_unit = getattr(label_record, "max_seasonal_rate_unit", None)
    if label_record is None:
        label_reasons[CHECK_MAX_SEASONAL_RATE] = label.blocking_reason
    elif max_rate is None:
        label_reasons[CHECK_MAX_SEASONAL_RATE] = (
            "this label states no maximum seasonal rate, so there is no total to "
            "compare a season's applications against"
        )
    elif label.season_start is None:
        label_reasons[CHECK_MAX_SEASONAL_RATE] = (
            label.season_reason
            or "no season window is on record for this farm, so a seasonal total "
               "cannot be added up"
        )
    elif rate_amount is None:
        label_reasons[CHECK_MAX_SEASONAL_RATE] = (
            "no application rate was entered for this planned spray, so it cannot be "
            "added to the season's total"
        )
    else:
        contributions = [(rate_amount, rate_unit, "this planned application")] + [
            (
                getattr(s, "rate_amount", None),
                getattr(s, "rate_unit", None),
                f"application on {getattr(s, 'application_date').isoformat()}",
            )
            for s in prior_same_product
            if label.season_start <= getattr(s, "application_date") <= intended
        ]
        total = 0.0
        provenance: list[str] = []
        refusal = None
        for amount, unit, what in contributions:
            if amount is None:
                refusal = (
                    f"the {what} has no recorded rate, so the season's total cannot be "
                    f"added up without silently treating it as zero"
                )
                break
            converted = label_data.convert_rate(amount, unit, max_rate_unit)
            if isinstance(converted, label_data.Refusal):
                refusal = f"{converted.reason} ({what})"
                break
            total += converted.amount
            provenance.extend(converted.conversion_provenance)
        if refusal is not None:
            label_reasons[CHECK_MAX_SEASONAL_RATE] = refusal
        else:
            exceeded = total > max_rate
            _label_rule(
                CHECK_MAX_SEASONAL_RATE,
                rule_id="label_max_seasonal_rate",
                name="Maximum seasonal rate (label)",
                triggered=exceeded,
                severity=SEVERITY_CRITICAL if exceeded else SEVERITY_NONE,
                detail=(
                    f"Including this application, {product} would total "
                    f"{round(total, 4)} {max_rate_unit} this season; the verified label "
                    f"allows {max_rate} {max_rate_unit}."
                    if exceeded
                    else f"Season total including this application: {round(total, 4)} "
                         f"{max_rate_unit} of a label maximum of {max_rate} "
                         f"{max_rate_unit}."
                ),
                calculation=(
                    f"sum of {len(contributions)} application rate(s) since "
                    f"{label.season_start.isoformat()} = {round(total, 4)} "
                    f"{max_rate_unit} vs label maximum {max_rate} {max_rate_unit}"
                    + (f"; conversions: {'; '.join(sorted(set(provenance)))}"
                       if provenance else "")
                ),
                inputs={
                    "season_total": round(total, 4),
                    "unit": max_rate_unit,
                    "label_maximum": max_rate,
                    "applications_counted": len(contributions),
                    "conversion_provenance": sorted(set(provenance)),
                },
            )
            label_block = label_block or exceeded

    # --- L5: label vs entered value disagreement ------------------------------------
    # Not one of the four disclosed checks — it can only exist once label data does.
    # The label value drives the arithmetic above; the disagreement is REPORTED, never
    # swallowed, because "your label says 21 days and this decision was entered as 3"
    # is the most useful thing this layer produces.
    if label_record is not None:
        disagreements = []
        for field_name, label_value in (
            ("pre_harvest_interval_days", getattr(label_record, "pre_harvest_interval_days", None)),
            ("re_entry_interval_hours", getattr(label_record, "re_entry_interval_hours", None)),
        ):
            entered = label.entered_values.get(field_name)
            if label_value is None or entered is None:
                continue
            if entered != label_value:
                disagreements.append({
                    "field": field_name,
                    "entered_value": entered,
                    "label_value": label_value,
                })
        label_disagreement = bool(disagreements)
        if label_disagreement:
            _label_rule(
                None,
                rule_id="label_value_disagreement",
                name="Entered value disagrees with the verified label",
                triggered=True,
                severity=SEVERITY_CAUTION,
                detail=(
                    "The verified label states "
                    + "; ".join(
                        f"{d['field'].replace('_', ' ')} = {d['label_value']} "
                        f"(entered here as {d['entered_value']})"
                        for d in disagreements
                    )
                    + f". The label value is what this decision was checked against. "
                      f"Source: {label.reference}."
                ),
                calculation=None,
                inputs={"disagreements": disagreements, "label_reference": label.reference},
            )

    # --------------------------------------- Rule 5: linked scouting evidence
    # Exact normalized names or the explicit alias dictionary (app/target_aliases.py)
    # only — the engine NEVER fuzzily infers that two pest/disease names are the same.
    # A partial overlap (one name contained in the other, or a known alias appearing
    # inside free text) is AMBIGUOUS: it is escalated to PCA review and recorded, not
    # treated as evidence. When the farm has a PCA-entered action threshold for this
    # target, the rule additionally requires the linked scouting pressure to reach
    # that threshold, and the rule's authority becomes pca_entered (attributed).
    # Without a policy the behavior is the plain heuristic — a threshold is NEVER
    # invented by Lumos.
    scouting_linked = False
    target_match_ambiguous = False
    if target:
        recent_obs = _recent(scout_observations, "observation_date", today)
        linked, ambiguous_obs = [], []
        for o in recent_obs:
            verdict = target_aliases.match_targets(
                target, getattr(o, "visible_issue", None)
            )
            if verdict == target_aliases.MATCH:
                linked.append(o)
            elif verdict == target_aliases.AMBIGUOUS:
                ambiguous_obs.append(o)
        # Matching observations that exist but fell out of the recent window: report
        # them as STALE evidence explicitly instead of silently ignoring them.
        stale_dates = [
            getattr(o, "observation_date", None)
            for o in scout_observations
            if o not in recent_obs
            and getattr(o, "observation_date", None) is not None
            and getattr(o, "observation_date") <= today
            and target_aliases.match_targets(
                target, getattr(o, "visible_issue", None)
            ) == target_aliases.MATCH
        ]
        latest_stale = max(stale_dates) if stale_dates else None
        stale_note = (
            f" The most recent matching observation is from "
            f"{latest_stale.isoformat()} ({(today - latest_stale).days} days ago) — "
            f"older than the {RECENT_WINDOW_DAYS}-day window, so it is stale evidence."
            if latest_stale is not None
            else ""
        )
        policy = next(
            (
                p for p in pca_policies
                if target_aliases.match_targets(
                    getattr(p, "target_pest_or_disease", None), target
                ) == target_aliases.MATCH
            ),
            None,
        )
        if policy is not None:
            threshold = policy.min_severity_to_treat
            # Only severities recorded on the threshold's own scale may be compared.
            # An observation on another scale is reported, never converted, and never
            # counted as evidence — converting it would invent a reading.
            comparable = [o for o in linked if severity_is_comparable_to_threshold(o)]
            off_scale = [
                (getattr(o, "severity_1_to_5", None), getattr(o, "severity_scale", None))
                for o in linked
                if not severity_is_comparable_to_threshold(o)
                and getattr(o, "severity_1_to_5", None) is not None
            ]
            severities = [
                s for s in (getattr(o, "severity_1_to_5", None) for o in comparable)
                if s is not None
            ]
            max_linked_severity = max(severities) if severities else None
            evidence_sufficient = (
                max_linked_severity is not None and max_linked_severity >= threshold
            )
            off_scale_note = (
                ""
                if not off_scale
                else (
                    " " + "; ".join(
                        f"an observation recorded as severity {value} on the "
                        f"'{scale}' scale is NOT comparable to a "
                        f"{DEFAULT_SEVERITY_SCALE} threshold and was not counted"
                        for value, scale in off_scale
                    ) + "."
                )
            )
            if evidence_sufficient:
                detail = (
                    f"Recent scouting for '{target}' shows severity "
                    f"{max_linked_severity}, at or above the PCA-entered action "
                    f"threshold of {threshold} (logged "
                    f"{linked[0].observation_date.isoformat()})."
                )
            elif linked:
                detail = (
                    f"PCA-entered action threshold for '{target}': treat only if "
                    f"scouting severity >= {threshold}; the latest linked scouting "
                    f"severity is {max_linked_severity if max_linked_severity is not None else 'not recorded'}"
                    f" — below the entered threshold." + off_scale_note
                )
            else:
                detail = (
                    f"PCA-entered action threshold for '{target}': treat only if "
                    f"scouting severity >= {threshold}; no scouting observation "
                    f"referencing '{target}' in the last {RECENT_WINDOW_DAYS} days."
                    + stale_note
                )
            decision.rules.append(DecisionRule(
                rule_id="scouting_evidence",
                name="Scouting evidence vs. PCA-entered action threshold",
                triggered=not evidence_sufficient,
                severity=SEVERITY_NONE if evidence_sufficient else SEVERITY_CAUTION,
                detail=detail,
                calculation=(
                    f"max linked severity "
                    f"{max_linked_severity if max_linked_severity is not None else '—'} "
                    f"vs. PCA-entered threshold {threshold}"
                ),
                inputs={
                    "target_pest_or_disease": target,
                    "recent_observations_checked": len(recent_obs),
                    "max_linked_severity": max_linked_severity,
                    "pca_entered_threshold": threshold,
                    "threshold_severity_scale": DEFAULT_SEVERITY_SCALE,
                    "policy_entered_by": getattr(policy, "entered_by", None),
                    # Observations excluded because their scale differs from the
                    # threshold's — recorded so the exclusion is auditable.
                    "excluded_off_scale_severities": [
                        {"severity": value, "severity_scale": scale}
                        for value, scale in off_scale
                    ],
                },
                source_authority=AUTHORITY_PCA,
                entered_by=getattr(policy, "entered_by", None),
            ))
            scouting_linked = evidence_sufficient
        else:
            scouting_linked = bool(linked)
            decision.rules.append(DecisionRule(
                rule_id="scouting_evidence",
                name="Scouting evidence for the stated target",
                triggered=not scouting_linked,
                severity=SEVERITY_NONE if scouting_linked else SEVERITY_CAUTION,
                detail=(
                    f"A recent scouting observation explicitly referencing '{target}' was "
                    f"found (logged {linked[0].observation_date.isoformat()})."
                    if scouting_linked
                    else f"No scouting observation explicitly referencing '{target}' in the "
                    f"last {RECENT_WINDOW_DAYS} days — no logged evidence of pressure."
                    + stale_note
                ),
                calculation=None,
                inputs={
                    "target_pest_or_disease": target,
                    "recent_observations_checked": len(recent_obs),
                },
            ))

        # ------------------- Rule 5b: ambiguous target-name overlap (never inferred)
        # Only relevant when no proper (exact/alias) match exists: a partial name
        # overlap is escalated to PCA review with both names recorded — the engine
        # never silently decides two pest/disease names mean the same thing.
        if ambiguous_obs and not scouting_linked:
            target_match_ambiguous = True
            pairs = [
                f"'{(getattr(o, 'visible_issue', None) or '').strip()}' "
                f"(logged {getattr(o, 'observation_date').isoformat()})"
                for o in ambiguous_obs[:3]
                if getattr(o, "observation_date", None) is not None
            ]
            decision.rules.append(DecisionRule(
                rule_id="scouting_target_ambiguity",
                name="Ambiguous pest/disease name overlap",
                triggered=True,
                severity=SEVERITY_CAUTION,
                detail=(
                    f"The stated target '{target}' partially overlaps "
                    f"{len(ambiguous_obs)} scouting observation(s) — {'; '.join(pairs)} — "
                    f"but is not an exact or known-alias match. Lumos does not infer "
                    f"that the names are equivalent; a PCA must decide whether these "
                    f"observations are evidence for this application."
                ),
                calculation=(
                    "match method: exact normalized name or explicit alias dictionary "
                    "only — partial overlap escalates, never matches"
                ),
                inputs={
                    "target_pest_or_disease": target,
                    "ambiguous_observations": len(ambiguous_obs),
                },
            ))

    # --------------------------------------- Rule 6: missing-data escalation
    decision.rules.append(DecisionRule(
        rule_id="missing_data",
        name="Data completeness",
        triggered=bool(missing),
        severity=SEVERITY_CAUTION if missing else SEVERITY_NONE,
        detail=(
            f"{len(missing)} check input(s) missing — a check that could not run can "
            f"never produce an approve outcome."
            if missing
            else "All check inputs were provided; every rule ran."
        ),
        calculation=None,
        inputs={"missing_count": len(missing)},
    ))

    # ------------------------------------------------------------ verdict mapping
    # Precedence: block > delay > pca_review_required > inspect_first > approve.
    review_triggers = (
        overuse or moa_repeat or bool(missing) or identity_ambiguous
        or rate_incomplete or imported_unverified or target_match_ambiguous
        # A label that disagrees with what was entered is a question for a human, not
        # something to resolve by picking a number.
        or label_disagreement
    )
    if phi_conflict or rei_harvest_conflict or label_block:
        decision.outcome = OUTCOME_BLOCK
        decision.severity = SEVERITY_CRITICAL
    elif prior_rei_active or label_delay:
        decision.outcome = OUTCOME_DELAY
        decision.severity = SEVERITY_CAUTION
    elif review_triggers:
        decision.outcome = OUTCOME_PCA_REVIEW
        decision.severity = SEVERITY_CAUTION
    elif not scouting_linked:
        decision.outcome = OUTCOME_INSPECT_FIRST
        decision.severity = SEVERITY_CAUTION
    else:
        decision.outcome = OUTCOME_APPROVE
        decision.severity = SEVERITY_NONE

    # --------------------------------------------------- authority gating
    # A verdict is only as authoritative as the weakest source that determined it.
    # block: determined by the triggered critical rules. approve: determined by EVERY
    # rule that ran (the "all clear" claim rests on all of them). Since the rotation
    # and scouting checks are heuristics, a label-grounded or PCA-authorized approve
    # is impossible until verified label data exists — by design.
    if decision.outcome == OUTCOME_BLOCK:
        determining = [
            r for r in decision.triggered_rules if r.severity == SEVERITY_CRITICAL
        ]
    elif decision.outcome == OUTCOME_APPROVE:
        determining = list(decision.rules)
    else:
        determining = []  # delay / inspect_first / pca_review are inherently provisional

    if determining and all(
        r.source_authority == AUTHORITY_VERIFIED_LABEL for r in determining
    ):
        # Unreachable today (no label database) — kept so the gate is already correct
        # the day verified label data exists.
        decision.authority_level = LEVEL_VERIFIED_LABEL
        decision.authority_basis = (
            "Verified-label grounded: every determining check is backed by verified "
            "label data."
        )
    elif determining and all(
        r.source_authority in DEFINITIVE_AUTHORITIES for r in determining
    ):
        decision.authority_level = LEVEL_PCA_AUTHORIZED
        sources = sorted({AUTHORITY_LABELS[r.source_authority] for r in determining})
        decision.authority_basis = (
            f"PCA-authorized: every determining check is backed by {' and '.join(sources)} "
            f"— a licensed PCA supplied the inputs; not independently label-verified."
        )
    else:
        decision.authority_level = LEVEL_PROVISIONAL
        if decision.outcome in (OUTCOME_APPROVE, OUTCOME_BLOCK):
            weak = sorted({
                AUTHORITY_LABELS[r.source_authority]
                for r in determining
                if r.source_authority not in DEFINITIVE_AUTHORITIES
            })
            decision.authority_basis = (
                f"Provisional: this result rests on {' and '.join(weak) or 'unverified sources'} "
                f"— a PCA / agronomist must confirm it before it is relied on."
            )
        else:
            decision.authority_basis = (
                "Provisional: this outcome requires a human decision by design."
            )

    decision.required_next_action = NEXT_ACTIONS[decision.outcome]
    # A provisional approve is NOT a green light — it needs PCA confirmation too.
    decision.review_required = decision.outcome in (
        OUTCOME_BLOCK, OUTCOME_DELAY, OUTCOME_PCA_REVIEW
    ) or (
        decision.outcome == OUTCOME_APPROVE
        and decision.authority_level == LEVEL_PROVISIONAL
    )
    if decision.outcome == OUTCOME_APPROVE and decision.authority_level == LEVEL_PROVISIONAL:
        decision.required_next_action = (
            "No conflicts found from entered records — provisional result; have your PCA "
            "confirm the entered values before relying on it."
        )

    # The disclaimer follows what actually backed this decision: the label reference
    # when PHI/REI came from a verified label, the honest default otherwise.
    decision.disclaimer = planned_spray_disclaimer(
        label.reference if label_record is not None else None
    )

    # Every label-dependent check that did not run, each with the reason it did not.
    # Set from what actually happened above, so a check that starts running disappears
    # from the disclosure by construction rather than by anyone remembering to.
    decision.not_evaluated = label_checks_not_evaluated(label_checks_run, label_reasons)

    # Confidence reflects input completeness only — never model certainty.
    if not missing:
        decision.confidence = CONFIDENCE_HIGH
    elif len(missing) == 1:
        decision.confidence = CONFIDENCE_MEDIUM
    else:
        decision.confidence = CONFIDENCE_LOW

    decision.narrative = _build_narrative(decision, product)
    return decision


_OUTCOME_HEADERS = {
    OUTCOME_BLOCK: (
        "Outcome: BLOCK — as entered, this application conflicts with harvest or "
        "re-entry timing."
    ),
    OUTCOME_DELAY: (
        "Outcome: DELAY — a previous application's re-entry interval may still be active."
    ),
    OUTCOME_PCA_REVIEW: (
        "Outcome: PCA REVIEW REQUIRED — review this application with your PCA / "
        "agronomist before proceeding."
    ),
    OUTCOME_INSPECT_FIRST: (
        "Outcome: INSPECT FIRST — no logged scouting evidence supports this application yet."
    ),
    OUTCOME_APPROVE: (
        "Outcome: APPROVE — no conflicts or evidence gaps found from entered records."
    ),
}


def _build_narrative(decision: PlannedSprayDecision, product: str) -> str:
    """Cautious plain-text summary of the decision (stored as the check snapshot)."""
    header = _OUTCOME_HEADERS[decision.outcome]
    if decision.authority_level == LEVEL_PROVISIONAL and decision.outcome in (
        OUTCOME_APPROVE, OUTCOME_BLOCK
    ):
        header = header.replace("Outcome: ", "Outcome: PROVISIONAL ", 1)
    lines = [
        header,
        f"Authority: {DECISION_AUTHORITY_LABELS[decision.authority_level]} — "
        f"{decision.authority_basis}",
        f"Required next action: {decision.required_next_action}",
        f"Confidence: {decision.confidence} (based on how complete the entered data is).",
        "",
    ]
    triggered = decision.triggered_rules
    if triggered:
        lines.append("Findings:")
        for i, r in enumerate(triggered, start=1):
            lines.append(f"{i}. {r.detail}")
            if r.calculation:
                lines.append(f"   Calculation: {r.calculation}")
            lines.append(
                f"   Source: {AUTHORITY_LABELS[r.source_authority]}"
                f" · {r.verification_status}"
                + (f" · entered by {r.entered_by}" if r.entered_by else "")
            )
    else:
        lines.append(
            f"No elevated risk found for '{product}' from current records. "
            "The decision remains with you and your PCA / agronomist."
        )
    if decision.missing_information:
        lines.append("")
        lines.append("Missing information:")
        for m in decision.missing_information:
            lines.append(f"- {m}")
    if decision.not_evaluated:
        lines.append("")
        lines.append("Not evaluated (never guessed — each check states why):")
        for c in decision.not_evaluated:
            lines.append(f"- {c['check']} — {c['reason']}")
    lines += [
        "",
        "Note: This is cautious decision support, not a prescription or a diagnosis. "
        "It never instructs anyone to spray. Final decisions rest with the grower and a "
        "licensed PCA / agronomist.",
        PLANNED_SPRAY_DISCLAIMER,
    ]
    return "\n".join(lines)
