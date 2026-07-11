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
AUTHORITY_HEURISTIC = "heuristic"

DEFINITIVE_AUTHORITIES = (AUTHORITY_VERIFIED_LABEL, AUTHORITY_PCA)

AUTHORITY_LABELS = {
    AUTHORITY_VERIFIED_LABEL: "verified label",
    AUTHORITY_PCA: "PCA-entered value",
    AUTHORITY_GROWER: "grower-entered value",
    AUTHORITY_HEURISTIC: "heuristic (rule-of-thumb threshold)",
}

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
            "required_next_action": self.required_next_action,
            "review_required": self.review_required,
            "disclaimer": self.disclaimer,
        }


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
) -> PlannedSprayDecision:
    """Check an intended spray before it happens and return one explainable outcome.

    Parameters
    ----------
    farm: object with `expected_harvest_date` (date or None).
    planned: object with `intended_date`, `product_name`, `active_ingredient`,
        `target_pest_or_disease`, `pre_harvest_interval_days`, `re_entry_interval_hours`.
    spray_events / scout_observations: the farm's current records (duck-typed).
    pca_policies: PCA-entered action thresholds (objects with `target_pest_or_disease`,
        `min_severity_to_treat`, `entered_by`). Optional — without a matching policy
        the scouting rule stays a plain heuristic; a threshold is NEVER invented.
    today: injectable "current date" for deterministic testing.
    """
    if today is None:
        today = date.today()

    spray_events = list(spray_events or [])
    scout_observations = list(scout_observations or [])
    pca_policies = list(pca_policies or [])

    decision = PlannedSprayDecision()

    product = getattr(planned, "product_name", None) or "the planned product"
    intended = getattr(planned, "intended_date", None) or today
    planned_ai = (getattr(planned, "active_ingredient", None) or "").strip().lower()
    target = (getattr(planned, "target_pest_or_disease", None) or "").strip().lower()
    phi = getattr(planned, "pre_harvest_interval_days", None)
    rei_hours = getattr(planned, "re_entry_interval_hours", None)
    harvest = getattr(farm, "expected_harvest_date", None)

    # Who supplied the PHI/REI values for THIS check (never a verified label today).
    values_source = getattr(planned, "values_source", None) or AUTHORITY_GROWER
    if values_source not in (AUTHORITY_GROWER, AUTHORITY_PCA):
        values_source = AUTHORITY_GROWER
    values_entered_by = getattr(planned, "values_entered_by", None) or (
        "PCA" if values_source == AUTHORITY_PCA else "grower"
    )

    decision.inputs_used = {
        "product_name": product,
        "active_ingredient": planned_ai or None,
        "target_pest_or_disease": target or None,
        "intended_date": _iso(intended),
        "pre_harvest_interval_days": phi,
        "re_entry_interval_hours": rei_hours,
        "expected_harvest_date": _iso(harvest),
        "phi_rei_values_source": values_source,
        "phi_rei_values_entered_by": values_entered_by,
        "spray_events_on_record": len(spray_events),
        "scouting_observations_on_record": len(scout_observations),
        "recent_window_days": RECENT_WINDOW_DAYS,
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
            source_authority=values_source,
            entered_by=values_entered_by,
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
            source_authority=values_source,
            entered_by=values_entered_by,
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

    # --------------------------------------- Rule 5: linked scouting evidence
    # Exact normalized match only — anything less counts as "not explicitly linked",
    # which is all this rule claims. When the farm has a PCA-entered action threshold
    # for this target, the rule additionally requires the linked scouting pressure to
    # reach that threshold, and the rule's authority becomes pca_entered (attributed).
    # Without a policy the behavior is the plain heuristic — a threshold is NEVER
    # invented by Lumos.
    scouting_linked = False
    if target:
        recent_obs = _recent(scout_observations, "observation_date", today)
        linked = [
            o for o in recent_obs
            if (getattr(o, "visible_issue", None) or "").strip().lower() == target
        ]
        policy = next(
            (
                p for p in pca_policies
                if (getattr(p, "target_pest_or_disease", None) or "").strip().lower()
                == target
            ),
            None,
        )
        if policy is not None:
            threshold = policy.min_severity_to_treat
            severities = [
                s for s in (getattr(o, "severity_1_to_5", None) for o in linked)
                if s is not None
            ]
            max_linked_severity = max(severities) if severities else None
            evidence_sufficient = (
                max_linked_severity is not None and max_linked_severity >= threshold
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
                    f" — below the entered threshold."
                )
            else:
                detail = (
                    f"PCA-entered action threshold for '{target}': treat only if "
                    f"scouting severity >= {threshold}; no scouting observation "
                    f"referencing '{target}' in the last {RECENT_WINDOW_DAYS} days."
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
                    "policy_entered_by": getattr(policy, "entered_by", None),
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
                ),
                calculation=None,
                inputs={
                    "target_pest_or_disease": target,
                    "recent_observations_checked": len(recent_obs),
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
    if phi_conflict or rei_harvest_conflict:
        decision.outcome = OUTCOME_BLOCK
        decision.severity = SEVERITY_CRITICAL
    elif prior_rei_active:
        decision.outcome = OUTCOME_DELAY
        decision.severity = SEVERITY_CAUTION
    elif overuse or missing:
        decision.outcome = OUTCOME_PCA_REVIEW
        decision.severity = SEVERITY_CAUTION if (overuse or missing) else SEVERITY_NONE
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
    lines += [
        "",
        "Note: This is cautious decision support, not a prescription or a diagnosis. "
        "It never instructs anyone to spray. Final decisions rest with the grower and a "
        "licensed PCA / agronomist.",
        PLANNED_SPRAY_DISCLAIMER,
    ]
    return "\n".join(lines)
