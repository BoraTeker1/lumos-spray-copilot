"""The Lumos Value Ledger: recommendation → action → outcome → attributable value.

Pure and framework-free (no FastAPI / SQLAlchemy imports), reading plain objects by
duck typing — the same contract as `analytics.py`, `reduction.py` and
`pilot_evidence.py`, whose `derive_follow_up_summary` this module reuses rather than
re-deriving. The caller owns the DB access and the crop-cycle scoping.

What this module answers, per decision, in one row:

    what did Lumos recommend → what did the grower/PCA do → what happened afterwards
    → how much of that is money, and what evidence backs the figure

Three rules decide whether a number appears at all
--------------------------------------------------
1. **A value needs a documented baseline.** The only per-decision figure claimed here
   is an application that was planned, costed, and then not made. The cost comes from
   the `estimated_cost` a human entered on that plan — not a farm average, not a
   market rate. No baseline, no number.

2. **A deferral is recorded and is not valued.** `delayed` and `inspected_first` are
   real outcomes and appear in the ledger, but "no rescue application happened" is not
   a saving: nothing states what a later application would have cost, and treating the
   absence of a second spray as money would credit Lumos for the weather. They carry
   `not_calculated` with that reason.

3. **A procurement saving is measured against the intended price**, `InputPlanItem.
   estimated_cost` — what the farm expected to pay before quotes arrived. Never
   "highest quote minus selected quote": the highest quote is a number a supplier made
   up, and nobody was ever going to pay it, so the difference is not a saving.

Verified vs estimated
---------------------
Kept apart in every total and never summed together, because they are different
claims. `verified` means the recorded outcome is backed by the append-only follow-up
timeline (the same test `decision_status.evidence_state` applies) or, for procurement,
that an order was actually placed. `estimated` means a human recorded the outcome and
nothing has corroborated it yet. `not_calculated` always carries its reason and never
renders as a zero.

Nothing here is a claim about causation. Lumos documented a decision; the grower and
their PCA made it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app import decision_status
from app.pilot_evidence import derive_follow_up_summary

MODEL_VERSION = "value_ledger_v1"

# Evidence tiers. Never summed across — see the module docstring.
TIER_VERIFIED = "verified"
TIER_ESTIMATED = "estimated"
TIER_NOT_CALCULATED = "not_calculated"

# Where an amount came from.
SOURCE_AVOIDED_APPLICATION = "avoided_application"
SOURCE_PROCUREMENT_SAVING = "procurement_saving"

KIND_DECISION = "decision"
KIND_PROCUREMENT = "procurement"

LEDGER_DISCLAIMER = (
    "Value attributed to a decision Lumos documented — not a claim that Lumos caused "
    "the outcome. Verified figures are backed by recorded follow-up evidence; "
    "estimated figures are not corroborated yet. Decision support only."
)


@dataclass(frozen=True)
class ValueItem:
    """One row of the loop. Carries its own arithmetic and its own evidence.

    The invariant: an amount exists if and only if the tier is not
    `not_calculated`, and a `not_calculated` row must say why. This is
    `features/base.py`'s abstention rule applied to money — a missing figure that
    renders as `0` reads as "this decision was worth nothing", which is the opposite
    of "we cannot attribute a figure to it".
    """

    kind: str
    reference_id: int
    label: str
    occurred_on: date | None = None
    # Machine keys only. The user-facing vocabulary lives in `frontend/lib/labels.js`
    # and `app/decision_status.py`; duplicating prose here would let two surfaces
    # disagree about what "inspected_first" is called.
    verdict: str | None = None
    review_state: str | None = None
    action: str | None = None
    action_reason: str | None = None
    evidence_state: str | None = None
    tier: str = TIER_NOT_CALCULATED
    source: str | None = None
    amount: float | None = None
    currency: str | None = None
    # Server-owned sentence explaining how the figure was reached, rendered verbatim
    # (the `DataReadinessCard` rule). Every dollar on screen can be read back.
    basis: str = ""
    evidence: tuple[str, ...] = ()
    not_calculated_reason: str | None = None
    # Shown, never counted: a figure that is real but not attributable to Lumos.
    informational: dict | None = None

    def __post_init__(self) -> None:
        if (self.amount is None) != (self.tier == TIER_NOT_CALCULATED):
            raise ValueError(
                f"{self.kind}#{self.reference_id}: an amount and a calculated tier "
                "must appear together. A tiered row with no amount renders as 0; an "
                "amount with no tier hides whether it is verified or merely entered."
            )
        if self.tier == TIER_NOT_CALCULATED and not self.not_calculated_reason:
            raise ValueError(
                f"{self.kind}#{self.reference_id}: a not_calculated row must carry a "
                "reason — a blank one reads as an empty card, not as a gap."
            )

    def as_payload(self) -> dict:
        payload = {
            "kind": self.kind,
            "reference_id": self.reference_id,
            "label": self.label,
            "occurred_on": self.occurred_on.isoformat() if self.occurred_on else None,
            "verdict": self.verdict,
            "review_state": self.review_state,
            "action": self.action,
            "action_reason": self.action_reason,
            "evidence_state": self.evidence_state,
            "tier": self.tier,
            "source": self.source,
            "basis": self.basis,
            "evidence": list(self.evidence),
        }
        # The value key is OMITTED rather than nulled when nothing was calculated —
        # a null in a numeric slot is what a template turns into 0 or "--".
        if self.amount is not None:
            payload["amount"] = round(self.amount, 2)
            payload["currency"] = self.currency
        else:
            payload["not_calculated_reason"] = self.not_calculated_reason
        if self.informational:
            payload["informational"] = self.informational
        return payload


# --------------------------------------------------------------- decision items
def _cost_of(planned) -> float | None:
    cost = getattr(planned, "estimated_cost", None)
    return float(cost) if cost is not None else None


def _decision_item(planned, events, currency: str | None) -> ValueItem:
    """One decision's row: what was recommended, done, observed, and what it was worth."""
    outcome = getattr(planned, "outcome", decision_status.OUTCOME_PLANNED)
    summary = derive_follow_up_summary(planned, events)
    base = {
        "kind": KIND_DECISION,
        "reference_id": getattr(planned, "id", 0),
        "label": getattr(planned, "product_name", None) or "Planned application",
        "occurred_on": getattr(planned, "outcome_date", None)
        or getattr(planned, "intended_date", None),
        "verdict": getattr(planned, "decision_outcome", None),
        "review_state": decision_status.review_state(planned),
        "action": outcome,
        "action_reason": getattr(planned, "outcome_reason", None),
        "evidence_state": decision_status.evidence_state(planned, events),
        "currency": currency,
    }

    def not_calculated(reason: str, informational: dict | None = None) -> ValueItem:
        return ValueItem(
            **base, tier=TIER_NOT_CALCULATED, not_calculated_reason=reason,
            basis="", informational=informational,
        )

    if outcome == decision_status.OUTCOME_PLANNED:
        return not_calculated(
            "No real-world outcome has been recorded for this decision yet."
        )

    # A deferral is documented, never valued (rule 2 in the module docstring).
    if outcome in ("delayed", "inspected_first"):
        return not_calculated(
            "A deferral is recorded, not valued. Nothing on file states what a later "
            "application would have cost, so the absence of one is not a measurable "
            "saving."
        )

    if outcome == "sprayed_as_planned":
        return not_calculated(
            "The application went ahead as planned, so no planned cost was avoided."
        )

    if outcome == "changed_product":
        # Displayed, never counted: a cheaper replacement is a real cost difference,
        # but the two products do different jobs and the delta is not a saving.
        planned_cost = _cost_of(planned)
        actual_cost = summary["application_cost"] or None
        informational = None
        if planned_cost is not None and actual_cost:
            informational = {
                "kind": "cost_delta",
                "planned_cost": round(planned_cost, 2),
                "actual_cost": round(actual_cost, 2),
                "delta": round(planned_cost - actual_cost, 2),
                "currency": currency,
                "note": (
                    "Cost difference between the planned product and what was applied "
                    "instead. Shown for the record, not counted as value: a "
                    "replacement product is a different treatment, not the same "
                    "treatment bought cheaper."
                ),
            }
        return not_calculated(
            "A replacement product was applied, so the planned application was not "
            "avoided.",
            informational,
        )

    # outcome == "avoided" — the one case with a defensible baseline.
    if summary["spray_ultimately_applied"]:
        return not_calculated(
            "An application was recorded against this decision after the avoidance, "
            "so the planned application was not in fact avoided."
        )

    planned_cost = _cost_of(planned)
    if planned_cost is None:
        return not_calculated(
            "No estimated cost was entered on this planned application, so there is "
            "no documented baseline to value the avoidance against."
        )

    # Costs incurred *because* the application was held are netted off — an avoidance
    # that required three extra scouting passes did not save the whole sticker price.
    scouting_cost = float(summary["additional_scouting_cost"] or 0.0)
    amount = planned_cost - scouting_cost
    confirmed = bool(summary["confirmed_avoided"])

    evidence = [f"planned_spray:{getattr(planned, 'id', 0)}:estimated_cost"]
    evidence += [
        f"follow_up_event:{getattr(e, 'id', 0)}:{getattr(e, 'event_type', '')}"
        for e in (events or [])
    ]

    basis = (
        f"{planned_cost:,.2f} planned application cost entered on the decision"
        + (f", less {scouting_cost:,.2f} of follow-up scouting recorded against it"
           if scouting_cost else "")
        + "."
    )
    if confirmed:
        basis += (
            f" Verified: {summary['event_count']} follow-up event(s) recorded and no "
            "application was made."
        )
    else:
        basis += (
            " Estimated: the avoidance is the grower/PCA's recorded outcome and no "
            "follow-up evidence corroborates it yet."
        )

    return ValueItem(
        **base,
        tier=TIER_VERIFIED if confirmed else TIER_ESTIMATED,
        source=SOURCE_AVOIDED_APPLICATION,
        amount=amount,
        basis=basis,
        evidence=tuple(evidence),
    )


# ------------------------------------------------------------ procurement items
def _selected_quote(plan):
    selected_id = getattr(plan, "selected_quote_id", None)
    if selected_id is None:
        return None
    for quote in getattr(plan, "quotes", None) or []:
        if getattr(quote, "id", None) == selected_id:
            return quote
    return None


def _procurement_items(plan, currency: str | None) -> list[ValueItem]:
    """One row per plan item, comparing the intended price to what was quoted.

    The baseline is `InputPlanItem.estimated_cost` — the price the farm expected to
    pay, recorded before any supplier answered. That is the only number in the
    procurement chain that represents a real alternative.
    """
    quote = _selected_quote(plan)
    ordered = getattr(plan, "order", None) is not None
    items: list[ValueItem] = []

    for plan_item in getattr(plan, "items", None) or []:
        base = {
            "kind": KIND_PROCUREMENT,
            "reference_id": getattr(plan_item, "id", 0),
            "label": getattr(plan_item, "product_name", None) or "Input",
            "occurred_on": getattr(plan_item, "needed_by_date", None),
            "currency": currency,
        }

        def not_calculated(reason: str, informational: dict | None = None) -> ValueItem:
            return ValueItem(
                **base, tier=TIER_NOT_CALCULATED, not_calculated_reason=reason,
                basis="", informational=informational,
            )

        if quote is None:
            items.append(not_calculated(
                "No quote has been selected on this plan, so there is nothing to "
                "compare the intended price against."
            ))
            continue

        baseline = getattr(plan_item, "estimated_cost", None)
        lines = [
            line for line in (getattr(quote, "items", None) or [])
            if getattr(line, "input_plan_item_id", None) == getattr(plan_item, "id", None)
        ]

        if baseline is None:
            informational = None
            if len(lines) == 1:
                informational = {
                    "kind": "quoted_price",
                    "quoted_total": round(lines[0].line_total, 2),
                    "supplier": getattr(quote, "supplier_name", None),
                    "currency": currency,
                    "note": (
                        "What was quoted and selected. No saving is claimed: the plan "
                        "recorded no intended price, so there is no baseline."
                    ),
                }
            items.append(not_calculated(
                "No intended price was recorded on this plan item, so there is no "
                "documented baseline for a saving.",
                informational,
            ))
            continue

        if not lines:
            items.append(not_calculated(
                "The selected quote has no line answering this plan item."
            ))
            continue
        if len(lines) > 1:
            items.append(not_calculated(
                "More than one quoted line answers this plan item, so the comparison "
                "is not like-for-like."
            ))
            continue

        line = lines[0]
        planned_unit = (getattr(plan_item, "unit", None) or "").strip().lower()
        quoted_unit = (getattr(line, "unit", None) or "").strip().lower()
        if planned_unit != quoted_unit:
            items.append(not_calculated(
                f"The quote is priced in {quoted_unit or 'an unstated unit'} and the "
                f"plan in {planned_unit or 'an unstated unit'}; nothing here converts "
                "between them."
            ))
            continue

        planned_qty = float(getattr(plan_item, "quantity", 0) or 0)
        quoted_qty = float(getattr(line, "quantity", 0) or 0)
        if abs(planned_qty - quoted_qty) > 1e-9:
            items.append(not_calculated(
                f"The quote is for {quoted_qty:g} {quoted_unit} and the plan asked "
                f"for {planned_qty:g} {planned_unit} — not a like-for-like comparison."
            ))
            continue

        quoted_total = float(line.line_total)
        amount = float(baseline) - quoted_total
        basis = (
            f"{float(baseline):,.2f} intended price recorded on the plan, less "
            f"{quoted_total:,.2f} on the selected quote from "
            f"{getattr(quote, 'supplier_name', None) or 'the chosen supplier'}, for "
            f"the same {planned_qty:g} {planned_unit}. Product lines only — delivery "
            f"and fees are quote-level and are not in the intended price."
        )
        basis += (
            " Verified: an order was placed against this quote."
            if ordered else
            " Estimated: the quote is selected but no order has been placed yet."
        )
        items.append(ValueItem(
            **base,
            tier=TIER_VERIFIED if ordered else TIER_ESTIMATED,
            source=SOURCE_PROCUREMENT_SAVING,
            amount=amount,
            basis=basis,
            evidence=(
                f"input_plan_item:{getattr(plan_item, 'id', 0)}:estimated_cost",
                f"supplier_quote_item:{getattr(line, 'id', 0)}:unit_price",
            ) + ((f"purchase_order:{getattr(plan.order, 'id', 0)}",) if ordered else ()),
        ))
    return items


# ------------------------------------------------------------------ season roll-up
def _season_costs(spray_events, operations, currency: str | None) -> dict:
    """What the season actually cost, from records that carry a cost.

    Records without a cost are counted and reported rather than treated as zero —
    a spray with no cost entered is an unknown, and folding it in as 0 would make
    the season look cheaper the less diligently it was logged.
    """
    spray_costs = [
        float(getattr(s, "cost", None)) for s in (spray_events or [])
        if getattr(s, "cost", None) is not None
    ]
    sprays_without = sum(
        1 for s in (spray_events or []) if getattr(s, "cost", None) is None
    )

    op_costs: list[float] = []
    ops_without = 0
    ops_other_currency = 0
    by_type: dict[str, float] = {}
    for op in operations or []:
        amount = getattr(op, "cost_amount", None)
        if amount is None:
            ops_without += 1
            continue
        op_currency = getattr(op, "currency_code", None)
        if op_currency and currency and op_currency != currency:
            ops_other_currency += 1
            continue
        op_costs.append(float(amount))
        op_type = getattr(op, "operation_type", None) or "other"
        by_type[op_type] = round(by_type.get(op_type, 0.0) + float(amount), 2)

    total = sum(spray_costs) + sum(op_costs)
    return {
        "currency": currency,
        "total": round(total, 2),
        "applications": round(sum(spray_costs), 2),
        "applications_counted": len(spray_costs),
        "applications_without_cost": sprays_without,
        "operations": round(sum(op_costs), 2),
        "operations_counted": len(op_costs),
        "operations_without_cost": ops_without,
        "operations_in_other_currency": ops_other_currency,
        "operations_by_type": by_type,
        "note": (
            "Recorded costs only. "
            f"{sprays_without} application(s) and {ops_without} operation(s) carry no "
            "cost and are excluded rather than counted as zero."
        ),
    }


def _season_outcomes(block_outcomes) -> list[dict]:
    """Measured outcomes grouped by type and unit. Nothing is converted."""
    grouped: dict[tuple[str, str | None], dict] = {}
    for row in block_outcomes or []:
        if getattr(row, "supersedes_id", None) is not None:
            continue  # a correction supersedes; the superseded row is not re-counted
        value = getattr(row, "value", None)
        key = (getattr(row, "outcome_type", "") or "other", getattr(row, "unit", None))
        bucket = grouped.setdefault(key, {
            "outcome_type": key[0], "unit": key[1], "total": 0.0,
            "observations": 0, "without_value": 0,
        })
        bucket["observations"] += 1
        if value is None:
            bucket["without_value"] += 1
        else:
            bucket["total"] = round(bucket["total"] + float(value), 2)
    return [grouped[k] for k in sorted(grouped, key=lambda k: (k[0], k[1] or ""))]


# ------------------------------------------------------------------ the ledger
def currency_for(farm) -> str | None:
    """The farm's currency, or None. Never a default — an unlabelled amount is not money."""
    code = getattr(farm, "currency_code", None)
    if code:
        return code
    # `Farm.currency_code` is nullable and was backfilled from country; a farm that
    # predates it still resolves by the same rule `main._currency_symbol` uses.
    country = (getattr(farm, "country", None) or "").upper()
    return {"US": "USD", "USA": "USD", "TR": "TRY"}.get(country)


def build_ledger(
    *,
    farm,
    decisions,
    follow_ups_by_decision: dict,
    input_plans,
    spray_events,
    operations,
    block_outcomes,
    scope: dict | None = None,
) -> dict:
    """Assemble the whole loop for one farm, optionally scoped to one crop cycle.

    Scope is all-or-nothing, exactly as `pilot_evidence.summarize_decisions_for_report`
    does it, and for the same reason: `crud.ensure_demo_real_separation` guarantees a
    farm's records are all demo or all real. A farm with real decisions reports on
    those and never on seeded ones; a demo farm reports `is_simulated`, so the loop is
    visible on the demo without a single figure ever being mistaken for value someone
    created (ENGINEERING_GUIDELINES.md §9).
    """
    currency = currency_for(farm)
    all_decisions = list(decisions or [])
    real_decisions = [d for d in all_decisions if not decision_status.is_demo_record(d)]
    simulated_decisions = [d for d in all_decisions if decision_status.is_demo_record(d)]
    # Prefer real, so a real decision can never be hidden behind a simulated label.
    scoped_decisions, record_scope = (
        (real_decisions, "real") if real_decisions else (simulated_decisions, "simulated")
    )
    is_simulated = record_scope == "simulated" and bool(scoped_decisions)

    items = [
        _decision_item(d, follow_ups_by_decision.get(getattr(d, "id", None)) or [], currency)
        for d in scoped_decisions
    ]
    for plan in input_plans or []:
        if decision_status.is_demo_record(plan) != (record_scope == "simulated"):
            continue
        items.extend(_procurement_items(plan, currency))

    items.sort(key=lambda i: (i.occurred_on or date.min), reverse=True)

    def _total(tier: str) -> float:
        return round(sum(i.amount or 0.0 for i in items if i.tier == tier), 2)

    def _by_source(tier: str) -> dict:
        out: dict[str, float] = {}
        for item in items:
            if item.tier == tier and item.source:
                out[item.source] = round(out.get(item.source, 0.0) + (item.amount or 0.0), 2)
        return out

    counted = [i for i in items if i.tier != TIER_NOT_CALCULATED]
    return {
        "model_version": MODEL_VERSION,
        "farm_id": getattr(farm, "id", None),
        "currency": currency,
        "scope": scope or {"crop_cycle_id": None},
        "verified": {
            "total": _total(TIER_VERIFIED),
            "by_source": _by_source(TIER_VERIFIED),
            "item_count": sum(1 for i in items if i.tier == TIER_VERIFIED),
        },
        "estimated": {
            "total": _total(TIER_ESTIMATED),
            "by_source": _by_source(TIER_ESTIMATED),
            "item_count": sum(1 for i in items if i.tier == TIER_ESTIMATED),
        },
        "not_calculated_count": sum(
            1 for i in items if i.tier == TIER_NOT_CALCULATED
        ),
        "items": [i.as_payload() for i in items],
        "season_costs": _season_costs(spray_events, operations, currency),
        "season_outcomes": _season_outcomes(block_outcomes),
        "record_scope": record_scope,
        "is_simulated": is_simulated,
        "counted_item_count": len(counted),
        "totals_note": (
            "Verified and estimated totals are reported separately and are never "
            "added together — one is backed by recorded evidence and the other is "
            "not."
        ),
        "disclaimer": LEDGER_DISCLAIMER,
    }


# --------------------------------------------------------- profit-aware decisions
def decision_economics(planned, *, currency: str | None = None) -> dict:
    """The direct cost consequence of each choice open on one planned application.

    Built only from costs already recorded on this decision — no probabilities, no
    rescue-rate model, no expected values. Every scenario is labelled with what it
    does and does not include, because the honest version of "what does delaying
    cost" is *we know what acting costs and we do not know what waiting costs*.
    """
    cost = _cost_of(planned)
    if cost is None:
        return {
            "model_version": MODEL_VERSION,
            "planned_spray_id": getattr(planned, "id", None),
            "available": False,
            "reason": (
                "No estimated cost is recorded on this planned application, so none "
                "of the choices can be costed."
            ),
        }

    return {
        "model_version": MODEL_VERSION,
        "planned_spray_id": getattr(planned, "id", None),
        "available": True,
        "currency": currency,
        "scenarios": [
            {
                "choice": "apply",
                "direct_cost": round(cost, 2),
                "note": "The estimated cost entered for this application.",
            },
            {
                "choice": "avoid",
                "direct_cost": 0.0,
                "note": (
                    "The estimated cost is not spent. Whether the pressure it "
                    "targeted causes a loss later is not known and is not costed "
                    "here."
                ),
            },
            {
                "choice": "delay",
                "direct_cost": 0.0,
                "note": (
                    f"Nothing is spent today, but the cost is deferred rather than "
                    f"avoided — the same application later still costs about "
                    f"{f'{currency} ' if currency else ''}{cost:,.2f}."
                ),
            },
            {
                "choice": "inspect_first",
                "direct_cost": None,
                "note": (
                    "Scouting cost is not recorded on this farm, so the cost of "
                    "inspecting first cannot be stated."
                ),
            },
        ],
        "note": (
            "Direct recorded costs only. These are the cost consequences of each "
            "choice, not a recommendation — the compliance verdict and the PCA "
            "review decide what happens."
        ),
    }
