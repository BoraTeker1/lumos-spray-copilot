"""The Lumos advisory queue: what should this farm do next, and why.

Pure and framework-free (no FastAPI / SQLAlchemy imports), reading plain objects by
duck typing — the same contract as `decision_status.py`, `value_ledger.py` and
`season_closeout.py`, all three of which this module reads FROM rather than
re-deriving. The caller owns the DB access and the crop-cycle scoping.

This is a PROJECTION, not a new source of truth
-----------------------------------------------
Every item here is derived from state some other module already computes:
`decision_status.current_next_action` decides what a decision needs next,
`procurement_status.procurement_overdue` decides what an order needs, the season
closeout already names its own gaps. Nothing is stored. An item's `item_key` is
deterministic — `kind:subject_type:subject_id` — so a client can address one without
persisting it, and every item CLEARS ITSELF when the underlying record moves. A
persisted queue would need dismissal, snooze, and reconciliation machinery, and would
still go stale the first time somebody recorded an outcome outside the queue.

Selective on purpose
--------------------
A queue that lists every missing field is a data-completion checklist, and a farmer
reading one learns nothing about which action matters. So a gap becomes an item only
when it materially affects **crop outcome, compliance, farm economics, follow-up
verification, procurement, or financing readiness**. The season closeout's
`completeness` list is still the exhaustive record of what is unentered — that is the
right home for it. The queue names the few things worth doing today.

The economics rule
------------------
`economic_consequence` carries a figure only where a documented baseline exists —
which today means an application that was planned and costed. Everything else refuses
with a reason. "You should inspect this block" has no defensible dollar value, and
attaching one would be the same mistake as calling an unsprayed field a saving: it
would credit Lumos for the weather. See `value_ledger` for the same rule applied to
realised value.

Nothing here is a prescription. An item may say *review this before spraying*; it
never says what to spray. That decision belongs to the licensed PCA, and there is no
field on `AdvisoryItem` to put a product in.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app import decision_status, procurement_status
from app.value_ledger import currency_for

MODEL_VERSION = "advisory_queue_v1"

# --- Urgency ------------------------------------------------------------------
# Three bands, deliberately not five: the point is to separate "today" from "this
# week" from "before the season closes", and a farmer cannot act on finer grain.
URGENCY_CRITICAL = "critical"
URGENCY_SOON = "soon"
URGENCY_ROUTINE = "routine"
URGENCY_ORDER = (URGENCY_CRITICAL, URGENCY_SOON, URGENCY_ROUTINE)
_URGENCY_RANK = {name: i for i, name in enumerate(URGENCY_ORDER)}

# --- Item kinds ---------------------------------------------------------------
KIND_RESOLVE_CONFLICT = "resolve_conflict"
KIND_AWAIT_PCA_REVIEW = "await_pca_review"
KIND_INSPECT_FIELD = "inspect_field"
KIND_RECORD_OUTCOME = "record_outcome"
KIND_RECORD_FOLLOW_UP = "record_follow_up"
KIND_HARVEST_WINDOW_CHANGED = "harvest_window_changed"
KIND_SCOUTING_STALE = "scouting_stale"
KIND_WEATHER_RISK = "weather_risk"
KIND_SEASON_ECONOMICS = "season_economics"
KIND_PROCUREMENT_OPPORTUNITY = "procurement_opportunity"
KIND_PROCUREMENT_ACTION = "procurement_action"
KIND_FINANCING_ACTION = "financing_action"

# How many days without a scouting record before the queue asks for one. Taken from
# `disease_risk.MAX_SCOUTING_AGE_DAYS` rather than invented here, so the queue and the
# risk model cannot disagree about what "recently scouted" means.
SCOUTING_STALE_DAYS = 14

# A procurement opportunity is only worth raising while there is still time to buy.
PROCUREMENT_HORIZON_DAYS = 21

# Materiality floor for the one cost gap that reaches the queue. A single uncosted
# application is a data-entry chore; several of them mean the season's cost total is
# wrong enough to mislead, which is an economics problem.
UNCOSTED_APPLICATIONS_FLOOR = 2

QUEUE_DISCLAIMER = (
    "Decision support only. Always confirm PHI, REI, rates, crop use, and "
    "restrictions with the product label and a licensed PCA / agronomist."
)


@dataclass(frozen=True)
class AdvisoryItem:
    """One thing worth doing, with the evidence that says so.

    There is deliberately no product, rate, or application field — the same technique
    `disease_risk.RiskAssessment` uses. An advisory item can say *a decision needs
    review*; a prescription is inexpressible.
    """

    item_key: str
    kind: str
    subject_type: str
    subject_id: int | None
    title: str
    recommendation: str
    why: str
    urgency: str = URGENCY_ROUTINE
    due_on: date | None = None
    agronomic_consequence: str = ""
    # {"amount", "currency", "basis"} or {"not_calculated", "code", "reason"} —
    # the `season_closeout._refused` shape, so a template cannot render a gap as 0.
    economic_consequence: dict | None = None
    # Reference strings in the same vocabulary as `ValueItem.evidence`.
    evidence: tuple[str, ...] = ()
    next_action: dict | None = None

    def __post_init__(self) -> None:
        if self.urgency not in _URGENCY_RANK:
            raise ValueError(f"{self.item_key}: unknown urgency {self.urgency!r}")
        if not self.recommendation:
            raise ValueError(
                f"{self.item_key}: an item with no recommendation is a notification, "
                "not advice."
            )

    @property
    def sort_key(self) -> tuple:
        # Urgency first, then the nearest deadline. A dated item outranks an undated
        # one of the same urgency; `date.max` keeps the undated ones last without a
        # branch, and the key keeps the order stable across equal items.
        return (
            _URGENCY_RANK[self.urgency],
            self.due_on or date.max,
            self.kind,
            self.subject_id or 0,
        )

    def as_payload(self) -> dict:
        return {
            "item_key": self.item_key,
            "kind": self.kind,
            "subject_type": self.subject_type,
            "subject_id": self.subject_id,
            "title": self.title,
            "recommendation": self.recommendation,
            "why": self.why,
            "urgency": self.urgency,
            "due_on": self.due_on.isoformat() if self.due_on else None,
            "agronomic_consequence": self.agronomic_consequence,
            "economic_consequence": self.economic_consequence,
            "evidence": list(self.evidence),
            "next_action": self.next_action,
        }


# ------------------------------------------------------------------- economics
def _money(amount: float, currency: str | None, basis: str) -> dict:
    return {"amount": round(float(amount), 2), "currency": currency, "basis": basis}


def _no_money(code: str, reason: str) -> dict:
    """No defensible figure. Same shape as `season_closeout._refused` — no value key."""
    return {"not_calculated": True, "code": code, "reason": reason}


NO_COST_ON_DECISION = "no_estimated_cost_on_decision"
NO_BASELINE_FOR_ACTION = "no_documented_baseline_for_this_action"


def _decision_economics(planned, currency: str | None) -> dict:
    """What this application costs if it goes ahead — the one figure with a baseline."""
    cost = getattr(planned, "estimated_cost", None)
    if cost is None:
        return _no_money(
            NO_COST_ON_DECISION,
            "No estimated cost was entered on this application, so Lumos has no "
            "baseline to price the decision against.",
        )
    return _money(
        cost,
        currency,
        "The estimated cost entered on this planned application. It is what the "
        "spray costs if it goes ahead, and what an avoidance would be measured "
        "against — not a claimed saving.",
    )


def _no_baseline(reason: str) -> dict:
    return _no_money(NO_BASELINE_FOR_ACTION, reason)


# ------------------------------------------------------------------- decisions
def _decision_label(planned) -> str:
    product = getattr(planned, "product_name", None) or "Planned application"
    block = getattr(planned, "field_block", None)
    return f"{product} — {block}" if block else product


def _decision_items(decisions, follow_ups_by_decision, currency, today) -> list[AdvisoryItem]:
    """One item per decision that has a next step, keyed off the canonical helper.

    `decision_status.current_next_action` already answers "what does this decision
    need now" for every surface in the app. Re-deriving it here would be a fifth
    implementation of the predicate that module exists to centralise.
    """
    items: list[AdvisoryItem] = []
    for planned in decisions or []:
        events = (follow_ups_by_decision or {}).get(getattr(planned, "id", None), [])
        step = decision_status.current_next_action(planned, events)
        if step == decision_status.NEXT_NONE:
            continue

        pid = getattr(planned, "id", None)
        intended = getattr(planned, "intended_date", None)
        label = _decision_label(planned)
        severity = getattr(planned, "decision_severity", None)
        verdict = getattr(planned, "decision_outcome", None)
        evidence = (f"planned_spray:{pid}:decision_outcome",)

        if step == decision_status.NEXT_AWAIT_PCA_REVIEW:
            items.append(AdvisoryItem(
                item_key=f"{KIND_AWAIT_PCA_REVIEW}:planned_spray:{pid}",
                kind=KIND_AWAIT_PCA_REVIEW,
                subject_type="planned_spray",
                subject_id=pid,
                title=f"PCA review outstanding — {label}",
                recommendation=(
                    "Send this planned application to your PCA for review. It cannot "
                    "be recorded as applied until they approve or edit it."
                ),
                why=(
                    f"The pre-spray check returned {verdict or 'a verdict'} and "
                    "requires a licensed review before the application proceeds."
                ),
                urgency=(
                    URGENCY_CRITICAL if severity == "critical" else URGENCY_SOON
                ),
                due_on=intended,
                agronomic_consequence=(
                    "Spraying before the review is recorded leaves the application "
                    "undocumented against the check that flagged it."
                ),
                economic_consequence=_decision_economics(planned, currency),
                evidence=evidence + (f"planned_spray:{pid}:review_status",),
                next_action={
                    "label": "Open decision",
                    "href": f"/decisions/{pid}",
                    "action_key": decision_status.NEXT_AWAIT_PCA_REVIEW,
                },
            ))
        elif step == decision_status.NEXT_RESOLVE_CONFLICT:
            items.append(AdvisoryItem(
                item_key=f"{KIND_RESOLVE_CONFLICT}:planned_spray:{pid}",
                kind=KIND_RESOLVE_CONFLICT,
                subject_type="planned_spray",
                subject_id=pid,
                title=f"Unresolved timing conflict — {label}",
                recommendation=(
                    "Resolve this conflict before the intended date: change the "
                    "product, move the date, or record why it went ahead."
                ),
                why=(
                    "The check returned a critical finding and no real-world outcome "
                    "has been recorded, so the conflict is still open."
                ),
                urgency=URGENCY_CRITICAL,
                due_on=intended,
                agronomic_consequence=(
                    "A harvest-interval or re-entry conflict left unresolved risks a "
                    "residue detection or an unsafe re-entry."
                ),
                economic_consequence=_decision_economics(planned, currency),
                evidence=evidence + (f"planned_spray:{pid}:decision_severity",),
                next_action={
                    "label": "Resolve conflict",
                    "href": f"/decisions/{pid}",
                    "action_key": decision_status.NEXT_RESOLVE_CONFLICT,
                },
            ))
        elif step == decision_status.NEXT_INSPECT:
            items.append(AdvisoryItem(
                item_key=f"{KIND_INSPECT_FIELD}:planned_spray:{pid}",
                kind=KIND_INSPECT_FIELD,
                subject_type="planned_spray",
                subject_id=pid,
                title=f"Inspect before deciding — {label}",
                recommendation=(
                    "Scout the block and record what you find, then record the "
                    "outcome of this planned application."
                ),
                why=(
                    "The check returned inspect-first: there is not enough scouting "
                    "evidence on record to support spraying or skipping."
                ),
                urgency=URGENCY_SOON,
                due_on=intended,
                agronomic_consequence=(
                    "Inspecting first is what turns a calendar spray into an "
                    "evidence-backed one — or documents that it was not needed."
                ),
                economic_consequence=_decision_economics(planned, currency),
                evidence=evidence,
                next_action={
                    "label": "Log scouting",
                    "href": f"/scouting?planned_spray={pid}",
                    "action_key": decision_status.NEXT_INSPECT,
                },
            ))
        elif step == decision_status.NEXT_RECORD_OUTCOME:
            overdue = bool(intended and intended < today)
            items.append(AdvisoryItem(
                item_key=f"{KIND_RECORD_OUTCOME}:planned_spray:{pid}",
                kind=KIND_RECORD_OUTCOME,
                subject_type="planned_spray",
                subject_id=pid,
                title=f"Record what happened — {label}",
                recommendation=(
                    "Record the real-world outcome: sprayed as planned, changed "
                    "product, delayed, avoided, or inspected first."
                ),
                why=(
                    "The intended date has passed and no outcome is recorded."
                    if overdue else
                    "This decision is cleared to proceed but has no recorded outcome."
                ),
                urgency=URGENCY_SOON if overdue else URGENCY_ROUTINE,
                due_on=intended,
                agronomic_consequence=(
                    "Without a recorded outcome the application does not enter the "
                    "spray history the next check reads."
                ),
                economic_consequence=_decision_economics(planned, currency),
                evidence=evidence + (f"planned_spray:{pid}:outcome",),
                next_action={
                    "label": "Record outcome",
                    "href": f"/decisions/{pid}",
                    "action_key": decision_status.NEXT_RECORD_OUTCOME,
                },
            ))
        elif step == decision_status.NEXT_RECORD_FOLLOW_UP:
            outcome = getattr(planned, "outcome", None)
            items.append(AdvisoryItem(
                item_key=f"{KIND_RECORD_FOLLOW_UP}:planned_spray:{pid}",
                kind=KIND_RECORD_FOLLOW_UP,
                subject_type="planned_spray",
                subject_id=pid,
                title=f"Confirm the outcome — {label}",
                recommendation=(
                    "Add a follow-up event recording what happened after this "
                    "decision — what you saw, and whether anything was needed later."
                ),
                why=(
                    f"The recorded outcome is {outcome!r} but no follow-up evidence "
                    "supports it yet, so any value stays estimated rather than "
                    "verified."
                ),
                urgency=URGENCY_SOON,
                due_on=None,
                agronomic_consequence=(
                    "Follow-up is what separates a documented decision from an "
                    "asserted one; without it the block's story has a gap."
                ),
                economic_consequence=_decision_economics(planned, currency),
                evidence=evidence + (f"planned_spray:{pid}:evidence_state",),
                next_action={
                    "label": "Add follow-up",
                    "href": f"/decisions/{pid}",
                    "action_key": decision_status.NEXT_RECORD_FOLLOW_UP,
                },
            ))
    return items


def _harvest_window_items(decisions, farm, cycle, today) -> list[AdvisoryItem]:
    """Decisions checked against a harvest date that has since moved.

    Not covered by the per-decision next action: the decision may be perfectly
    resolved and still have been checked against the wrong date. This is the one
    genuinely silent compliance failure in the loop.

    The comparison is against `Farm.expected_harvest_date`, because that is the field
    `decision_engine` actually reads — comparing against the crop cycle's own harvest
    window would report staleness the engine never had, and miss the staleness it did.
    """
    harvest = getattr(farm, "expected_harvest_date", None)
    if harvest is None:
        return []
    items: list[AdvisoryItem] = []
    for planned in decisions or []:
        if not decision_status.harvest_date_changed_since_check(planned, harvest):
            continue
        pid = getattr(planned, "id", None)
        items.append(AdvisoryItem(
            item_key=f"{KIND_HARVEST_WINDOW_CHANGED}:planned_spray:{pid}",
            kind=KIND_HARVEST_WINDOW_CHANGED,
            subject_type="planned_spray",
            subject_id=pid,
            title=f"Harvest date moved since the check — {_decision_label(planned)}",
            recommendation=(
                "Re-run the pre-spray check. The pre-harvest interval was measured "
                "against a harvest date that has since changed."
            ),
            why=(
                "This decision's harvest-interval arithmetic used the date recorded "
                f"at check time; the farm now expects harvest on "
                f"{harvest.isoformat()}."
            ),
            urgency=URGENCY_CRITICAL,
            due_on=harvest,
            agronomic_consequence=(
                "A pre-harvest interval cleared against an older date may no longer "
                "clear, which is a residue risk at picking."
            ),
            economic_consequence=_no_baseline(
                "Re-running a check has no cost baseline of its own; the cost at "
                "stake is a rejected load, which nothing on record prices."
            ),
            evidence=(
                f"planned_spray:{pid}:expected_harvest_date",
                f"farm:{getattr(farm, 'id', None)}:expected_harvest_date",
            ),
            next_action={
                "label": "Re-check decision",
                "href": f"/decisions/{pid}",
                "action_key": decision_status.NEXT_RESOLVE_CONFLICT,
            },
        ))
    return items


# -------------------------------------------------------------------- scouting
def _scouting_items(blocks, scout_observations, cycle, today) -> list[AdvisoryItem]:
    """Blocks with no recent scouting record, while the cycle is still growing."""
    status = getattr(cycle, "status", None) if cycle else None
    if status in ("closed", "abandoned", None):
        return []

    latest: dict[int, date] = {}
    for obs in scout_observations or []:
        bid = getattr(obs, "block_id", None)
        seen = getattr(obs, "observation_date", None)
        if bid is None or seen is None:
            continue
        if bid not in latest or seen > latest[bid]:
            latest[bid] = seen

    items: list[AdvisoryItem] = []
    for block in blocks or []:
        bid = getattr(block, "id", None)
        last_seen = latest.get(bid)
        if last_seen is not None and (today - last_seen).days <= SCOUTING_STALE_DAYS:
            continue
        age = f"{(today - last_seen).days} days ago" if last_seen else "never"
        items.append(AdvisoryItem(
            item_key=f"{KIND_SCOUTING_STALE}:block:{bid}",
            kind=KIND_SCOUTING_STALE,
            subject_type="block",
            subject_id=bid,
            title=f"No recent scouting — {getattr(block, 'name', f'block {bid}')}",
            recommendation="Scout this block and record what you find.",
            why=(
                f"The most recent scouting record for this block is {age}, beyond the "
                f"{SCOUTING_STALE_DAYS}-day window the risk model will read."
            ),
            urgency=URGENCY_ROUTINE,
            due_on=None,
            agronomic_consequence=(
                "Without a recent observation a pre-spray check cannot use scouting "
                "evidence, so it escalates to review instead of clearing."
            ),
            economic_consequence=_no_baseline(
                "Scouting has no recorded cost on this farm, so Lumos cannot price "
                "the action."
            ),
            evidence=(f"block:{bid}:last_scouted",),
            next_action={
                "label": "Log scouting",
                "href": f"/scouting?block={bid}",
                "action_key": decision_status.NEXT_INSPECT,
            },
        ))
    return items


# --------------------------------------------------------------------- weather
def _weather_items(weather_risk, farm) -> list[AdvisoryItem]:
    """A weather item only when the existing risk surface actually flagged something.

    Abstention produces no item. "We cannot see the weather" is a data-coverage fact
    and belongs in the coverage list, not in a farmer's action queue.
    """
    if not weather_risk or weather_risk.get("not_calculated"):
        return []
    level = weather_risk.get("risk_level")
    if level not in ("elevated", "high"):
        return []
    fid = getattr(farm, "id", None)
    return [AdvisoryItem(
        item_key=f"{KIND_WEATHER_RISK}:farm:{fid}",
        kind=KIND_WEATHER_RISK,
        subject_type="farm",
        subject_id=fid,
        title="Weather conditions raise disease pressure",
        recommendation=(
            "Review upcoming applications against the forecast, and scout before "
            "committing to a spray date."
        ),
        why=weather_risk.get("summary") or (
            f"The weather risk surface reports {level} risk for this farm."
        ),
        urgency=URGENCY_SOON,
        due_on=None,
        agronomic_consequence=(
            "Wet or humid conditions extend infection windows; a spray applied "
            "before rain may also be lost to wash-off."
        ),
        economic_consequence=_no_baseline(
            "Weather risk changes the odds, not a recorded cost — nothing on file "
            "prices the outcome it points at."
        ),
        evidence=(f"farm:{fid}:weather_risk",),
        next_action={
            "label": "View conditions",
            "href": f"/farms/{fid}?tab=conditions",
            "action_key": "review_conditions",
        },
    )]


# ------------------------------------------------------------------- economics
# The ONLY closeout gaps that reach the queue. Everything else stays in the
# closeout's own completeness list, which is the exhaustive record by design.
_QUEUED_GAP_CODES = (
    "avoided_decisions_without_estimated_cost",
    "orders_delivered_without_recorded_cost",
)


def _economics_items(closeout, cycle, today) -> list[AdvisoryItem]:
    if not closeout:
        return []
    cid = getattr(cycle, "id", None)
    items: list[AdvisoryItem] = []
    gaps = {g.get("code"): g for g in (closeout.get("completeness") or {}).get("gaps", [])}

    for code in _QUEUED_GAP_CODES:
        gap = gaps.get(code)
        if not gap:
            continue
        items.append(AdvisoryItem(
            item_key=f"{KIND_SEASON_ECONOMICS}:crop_cycle:{cid}:{code}",
            kind=KIND_SEASON_ECONOMICS,
            subject_type="crop_cycle",
            subject_id=cid,
            title="Value cannot be attributed yet",
            recommendation=gap.get("fix", ""),
            why=gap.get("detail", ""),
            urgency=URGENCY_SOON,
            due_on=None,
            agronomic_consequence="",
            economic_consequence=_no_money(
                code,
                "This is the gap that blocks the figure, so there is no figure to "
                "show until it is closed.",
            ),
            evidence=(f"crop_cycle:{cid}:completeness:{code}",),
            next_action={
                "label": "Open season economics",
                "href": f"/crop-cycles/{cid}",
                "action_key": "close_economics_gap",
            },
        ))

    # Uncosted applications, but only once enough have piled up to move the total.
    uncosted = gaps.get("applications_without_cost")
    if uncosted and uncosted.get("count", 0) >= UNCOSTED_APPLICATIONS_FLOOR:
        items.append(AdvisoryItem(
            item_key=f"{KIND_SEASON_ECONOMICS}:crop_cycle:{cid}:applications_without_cost",
            kind=KIND_SEASON_ECONOMICS,
            subject_type="crop_cycle",
            subject_id=cid,
            title="Season cost total is understated",
            recommendation=uncosted.get("fix", ""),
            why=uncosted.get("detail", ""),
            urgency=URGENCY_ROUTINE,
            due_on=None,
            agronomic_consequence="",
            economic_consequence=_no_money(
                "applications_without_cost",
                "Cost per area and cost per unit read low until these are entered.",
            ),
            evidence=(f"crop_cycle:{cid}:completeness:applications_without_cost",),
            next_action={
                "label": "Open season economics",
                "href": f"/crop-cycles/{cid}",
                "action_key": "close_economics_gap",
            },
        ))

    # Revenue: only worth asking for once there is a crop to have sold.
    revenue = (closeout.get("metrics") or {}).get("revenue") or {}
    status = getattr(cycle, "status", None) if cycle else None
    if revenue.get("not_calculated") and status in ("harvesting", "closed"):
        items.append(AdvisoryItem(
            item_key=f"{KIND_SEASON_ECONOMICS}:crop_cycle:{cid}:revenue",
            kind=KIND_SEASON_ECONOMICS,
            subject_type="crop_cycle",
            subject_id=cid,
            title="No settlement recorded for this season",
            recommendation=(
                "Record what the crop actually sold for. Revenue, revenue per area "
                "and realised price all wait on it."
            ),
            why=revenue.get("reason", ""),
            urgency=URGENCY_SOON,
            due_on=None,
            agronomic_consequence="",
            economic_consequence=_no_money(
                revenue.get("code", "no_sales_recorded"),
                "Nothing prices the harvest until a settlement is on record.",
            ),
            evidence=(f"crop_cycle:{cid}:sales",),
            next_action={
                "label": "Record sale",
                "href": f"/crop-cycles/{cid}",
                "action_key": "record_sale",
            },
        ))
    return items


# ----------------------------------------------------------------- procurement
def _procurement_items(decisions, input_plans, orders, currency, today) -> list[AdvisoryItem]:
    items: list[AdvisoryItem] = []

    # A cleared decision with nothing on order and the date approaching.
    sourced = {
        getattr(item, "planned_spray_id", None)
        for plan in input_plans or []
        for item in getattr(plan, "items", []) or []
    }
    for planned in decisions or []:
        pid = getattr(planned, "id", None)
        if pid in sourced:
            continue
        if not decision_status.procurement_eligible(planned):
            continue
        if not decision_status.is_open(planned):
            continue
        intended = getattr(planned, "intended_date", None)
        if intended is None or (intended - today).days > PROCUREMENT_HORIZON_DAYS:
            continue
        items.append(AdvisoryItem(
            item_key=f"{KIND_PROCUREMENT_OPPORTUNITY}:planned_spray:{pid}",
            kind=KIND_PROCUREMENT_OPPORTUNITY,
            subject_type="planned_spray",
            subject_id=pid,
            title=f"Input not yet sourced — {_decision_label(planned)}",
            recommendation=(
                "Add this product to an input plan to collect supplier quotes "
                "before the intended date."
            ),
            why=(
                "This application is cleared to proceed and its intended date is "
                f"within {PROCUREMENT_HORIZON_DAYS} days, but no input plan covers it."
            ),
            urgency=URGENCY_SOON,
            due_on=intended,
            agronomic_consequence=(
                "An input that arrives after the window has closed forces either a "
                "substitute product or a missed application."
            ),
            economic_consequence=_decision_economics(planned, currency),
            evidence=(f"planned_spray:{pid}:procurement_eligible",),
            next_action={
                "label": "Create input plan",
                "href": f"/inputs?planned_spray={pid}",
                "action_key": "create_input_plan",
            },
        ))

    # Quotes in, nobody has chosen.
    for plan in input_plans or []:
        plid = getattr(plan, "id", None)
        if getattr(plan, "status", None) == procurement_status.PLAN_QUOTED:
            items.append(AdvisoryItem(
                item_key=f"{KIND_PROCUREMENT_ACTION}:input_plan:{plid}",
                kind=KIND_PROCUREMENT_ACTION,
                subject_type="input_plan",
                subject_id=plid,
                title="Supplier quotes ready to compare",
                recommendation=(
                    "Compare the quotes and select one, with the reason for the "
                    "choice."
                ),
                why=(
                    f"{getattr(plan, 'quote_count', 0)} quote(s) are on this plan and "
                    "none has been selected, so no order can be placed."
                ),
                urgency=URGENCY_SOON,
                due_on=getattr(plan, "needed_by", None),
                agronomic_consequence="",
                economic_consequence=_no_baseline(
                    "The spread between quotes is visible on the plan; it is a "
                    "dispersion, not a saving, until one is selected against the "
                    "intended cost."
                ),
                evidence=(f"input_plan:{plid}:quotes",),
                next_action={
                    "label": "Compare quotes",
                    "href": f"/inputs/plans/{plid}",
                    "action_key": "select_quote",
                },
            ))

    # Overdue orders.
    for order in orders or []:
        oid = getattr(order, "id", None)
        if not getattr(order, "overdue", False):
            continue
        items.append(AdvisoryItem(
            item_key=f"{KIND_PROCUREMENT_ACTION}:purchase_order:{oid}",
            kind=KIND_PROCUREMENT_ACTION,
            subject_type="purchase_order",
            subject_id=oid,
            title=f"Order overdue — {getattr(order, 'supplier_name', 'supplier')}",
            recommendation="Chase the supplier, or record the delivery if it arrived.",
            why=(
                "The needed-by date has passed and the order is not recorded as "
                "delivered."
            ),
            urgency=URGENCY_SOON,
            due_on=None,
            agronomic_consequence=(
                "A late input either delays the application or forces a substitute."
            ),
            economic_consequence=_no_baseline(
                "A late delivery has no recorded cost consequence on this farm."
            ),
            evidence=(f"purchase_order:{oid}:status",),
            next_action={
                "label": "Open order",
                "href": f"/inputs/orders/{oid}",
                "action_key": "update_order",
            },
        ))
    return items


# ------------------------------------------------------------------- financing
def _financing_items(financing_requests, today) -> list[AdvisoryItem]:
    items: list[AdvisoryItem] = []
    for req in financing_requests or []:
        rid = getattr(req, "id", None)
        status = getattr(req, "status", None)
        offers = [
            o for o in getattr(req, "offers", []) or []
            if procurement_status.offer_decidable(o, today)
        ]
        if offers:
            items.append(AdvisoryItem(
                item_key=f"{KIND_FINANCING_ACTION}:financing_request:{rid}",
                kind=KIND_FINANCING_ACTION,
                subject_type="financing_request",
                subject_id=rid,
                title="Indicative financing terms awaiting a decision",
                recommendation=(
                    "Compare the indicative terms and select one, or decline them."
                ),
                why=(
                    f"{len(offers)} indicative offer(s) are on this request and none "
                    "has been decided."
                ),
                urgency=URGENCY_SOON,
                due_on=min(
                    (o.expires_on for o in offers if getattr(o, "expires_on", None)),
                    default=None,
                ),
                agronomic_consequence="",
                economic_consequence=_no_baseline(
                    "Indicative terms are a lender's stated cost, not a computed "
                    "one — Lumos never derives a rate or a repayment."
                ),
                evidence=(f"financing_request:{rid}:offers",),
                next_action={
                    "label": "Review terms",
                    "href": f"/financing/{rid}",
                    "action_key": "decide_financing_offer",
                },
            ))
        elif status in ("draft", "evidence_assembled"):
            missing = getattr(req, "missing_evidence_count", None)
            if not missing:
                continue
            items.append(AdvisoryItem(
                item_key=f"{KIND_FINANCING_ACTION}:financing_request:{rid}:evidence",
                kind=KIND_FINANCING_ACTION,
                subject_type="financing_request",
                subject_id=rid,
                title="Financing evidence incomplete",
                recommendation=(
                    "Close the missing evidence items before sharing this request "
                    "with a lender."
                ),
                why=(
                    f"{missing} evidence item(s) a lender will ask for are not on "
                    "record for this farm."
                ),
                urgency=URGENCY_ROUTINE,
                due_on=None,
                agronomic_consequence="",
                economic_consequence=_no_baseline(
                    "Evidence completeness is a record count, not a price."
                ),
                evidence=(f"financing_request:{rid}:evidence_package",),
                next_action={
                    "label": "Open request",
                    "href": f"/financing/{rid}",
                    "action_key": "complete_financing_evidence",
                },
            ))
    return items


# ------------------------------------------------------------------------ build
def build_queue(
    *,
    farm,
    cycle=None,
    decisions=(),
    follow_ups_by_decision=None,
    blocks=(),
    scout_observations=(),
    input_plans=(),
    orders=(),
    financing_requests=(),
    closeout=None,
    weather_risk=None,
    today: date,
) -> dict:
    """The ranked action queue for one farm, optionally scoped to one crop cycle.

    Everything is derived. Call it as often as you like; it holds no state and the
    same inputs always produce the same item keys.
    """
    currency = currency_for(farm)

    items: list[AdvisoryItem] = []
    items += _decision_items(decisions, follow_ups_by_decision, currency, today)
    items += _harvest_window_items(decisions, farm, cycle, today)
    items += _scouting_items(blocks, scout_observations, cycle, today)
    items += _weather_items(weather_risk, farm)
    items += _economics_items(closeout, cycle, today)
    items += _procurement_items(decisions, input_plans, orders, currency, today)
    items += _financing_items(financing_requests, today)

    items.sort(key=lambda i: i.sort_key)

    counts = {name: 0 for name in URGENCY_ORDER}
    for item in items:
        counts[item.urgency] += 1

    return {
        "model_version": MODEL_VERSION,
        "farm_id": getattr(farm, "id", None),
        "crop_cycle_id": getattr(cycle, "id", None) if cycle else None,
        "currency": currency,
        "as_of": today.isoformat(),
        "items": [i.as_payload() for i in items],
        "item_count": len(items),
        "counts_by_urgency": counts,
        "disclaimer": QUEUE_DISCLAIMER,
    }
