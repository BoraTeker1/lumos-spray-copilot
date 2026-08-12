"""Season economics for one crop cycle: what it cost, produced, sold for, and was worth.

Pure and framework-free (no FastAPI / SQLAlchemy imports), reading plain objects by duck
typing — the same contract as `value_ledger.py`, whose `_season_costs` this module reuses
rather than re-deriving. The caller owns DB access and crop-cycle scoping.

The question, for ONE `CropCycle`:

    what did this season cost, what did it produce, what did it sell for, and what
    economic value can Lumos credibly attribute to its recommendations?

It answers the same way for an OPEN cycle and a CLOSED one. The arithmetic does not
change; only the framing does — `season_to_date` on an open cycle, `season_closeout` on a
closed one — because a grower mid-season needs the same figures a grower closing the books
does, and building a second surface for that would guarantee the two disagree.

Four rules decide whether a number appears
------------------------------------------
1. **Recorded transactions only.** Revenue comes from `SaleRecord` rows a human entered
   from a settlement. `market.pricing` can quote a price series and this module never
   reads it: a season valued at what the market was doing is a forecast wearing a
   settlement's clothes.

2. **Nothing converts money.** A sale in a currency other than the cycle's is excluded
   and counted, exactly as `_season_costs` already does with operations. An FX rate is a
   number nobody on this farm recorded.

3. **Yield normalises only inside one dimension.** `kg`, `lb` and `t` combine through
   `units.convert`, whose factors are exact by definition. A tray, a flat and a clamshell
   are packaging, not units — there is no cited conversion to a mass, so a season mixing
   them REFUSES rather than reporting a total that silently dropped half the harvest.

4. **Revenue minus recorded costs is exactly that.** It is not profit, not margin, and
   not farm profitability: land, labour outside a recorded operation, overhead, water,
   and depreciation are all absent unless somebody entered them. It therefore never
   travels without `cost_coverage` — the count of records carrying no cost — so a season
   logged half as diligently cannot read as a season that earned more.

Every metric is a value or a `Refusal` with a stable code. A metric that cannot be
computed OMITS its value key rather than nulling it (ENGINEERING_GUIDELINES.md section 9): a zero here
would read as "this season earned nothing", which is the opposite of "nobody has told us
yet", and it is the reading that costs a grower money.
"""
from __future__ import annotations

from datetime import date

from app import units
from app.refusal import Refusal

MODEL_VERSION = "season_closeout_v1"

# The canonical unit a normalised yield is reported in. Mass, because that is what a
# strawberry settlement is written in on both sides of the Atlantic.
YIELD_CANONICAL_UNIT = "kg"

# The block outcome that means "this is how much crop came off". Other outcome types
# (packout, cull, incidence) are shown alongside but never summed into a yield: a
# percentage and a weight do not add.
YIELD_OUTCOME_TYPE = "yield"

CLOSEOUT_DISCLAIMER = (
    "Farm-record economics, not accounting. Every figure is built only from records "
    "entered on this crop cycle; costs and revenue that were never recorded are absent "
    "rather than estimated. Revenue minus recorded costs is not profit. "
    "Decision support only."
)

# ---------------------------------------------------------------- refusal codes
NO_SALES_RECORDED = "no_sales_recorded"
NO_REVENUE_IN_CYCLE_CURRENCY = "no_revenue_in_cycle_currency"
NO_COSTS_RECORDED = "no_costs_recorded"
NO_REVENUE_RECORDED = "no_revenue_recorded"
NO_YIELD_RECORDED = "no_yield_recorded"
INCOMPATIBLE_YIELD_UNITS = "incompatible_yield_units"
NO_PLANTED_AREA = "no_planted_area"
NO_CURRENCY_ON_CYCLE = "no_currency_on_cycle"


def _metric(value, *, unit: str | None = None, basis: str = "", **extra) -> dict:
    """A computed metric. Carries its own sentence; the UI renders that verbatim."""
    payload = {"value": round(value, 2), "basis_text": basis}
    if unit:
        payload["unit"] = unit
    payload.update(extra)
    return payload


def _refused(refusal: Refusal, **extra) -> dict:
    """A metric that could not be computed. NOTE: no `value` key at all, ever.

    Not `{"value": None}` and not `{"value": 0}`. A template that renders whatever it
    is handed cannot turn an absent key into a zero, and that is the entire point —
    `DataReadinessCard` already relies on this shape.
    """
    payload = {
        "not_calculated": True,
        "code": refusal.code,
        "reason": refusal.detail,
    }
    if refusal.context:
        payload["context"] = refusal.context
    payload.update(extra)
    return payload


# ------------------------------------------------------------------------ revenue
def _live_sales(sales):
    """Sales still standing: a superseded settlement is not counted twice."""
    superseded = {
        getattr(s, "supersedes_id", None)
        for s in (sales or [])
        if getattr(s, "supersedes_id", None) is not None
    }
    return [s for s in (sales or []) if getattr(s, "id", None) not in superseded]


def gross_of(sale) -> float | None:
    """The gross amount as stated, or derived from quantity x unit price.

    Returns None when the record states neither. The schema rejects that combination on
    the way in; this stays defensive because the closeout also runs over seeded and
    imported rows.
    """
    stated = getattr(sale, "gross_amount", None)
    if stated is not None:
        return float(stated)
    quantity = getattr(sale, "quantity", None)
    price = getattr(sale, "unit_price", None)
    if quantity is not None and price is not None:
        return float(quantity) * float(price)
    return None


def _revenue(sales, currency: str | None) -> dict:
    """Gross, deductions and net from recorded settlements. Three numbers, never one.

    Gross is what the crop sold for. Net is what the farm received after the buyer
    withheld commission, freight and cooling. Both are true and they answer different
    questions, so neither is allowed to stand in for the other.
    """
    live = _live_sales(sales)
    if not live:
        return _refused(Refusal(
            code=NO_SALES_RECORDED,
            detail=(
                "No sale has been recorded against this crop cycle. Revenue is read "
                "from recorded settlements only — a market price is not revenue."
            ),
        ))

    gross_total = 0.0
    deductions_total = 0.0
    counted = 0
    without_amount = 0
    other_currency = 0
    derived_gross = 0
    for sale in live:
        sale_currency = getattr(sale, "currency_code", None)
        if sale_currency and currency and sale_currency != currency:
            other_currency += 1
            continue
        gross = gross_of(sale)
        if gross is None:
            without_amount += 1
            continue
        if getattr(sale, "gross_amount", None) is None:
            derived_gross += 1
        gross_total += gross
        deductions_total += float(getattr(sale, "deductions_amount", None) or 0.0)
        counted += 1

    if counted == 0:
        return _refused(
            Refusal(
                code=NO_REVENUE_IN_CYCLE_CURRENCY,
                detail=(
                    f"{len(live)} sale(s) are recorded but none could be counted: "
                    f"{other_currency} are in another currency and "
                    f"{without_amount} state no amount. Nothing here converts money."
                ),
                context={
                    "sales_recorded": len(live),
                    "in_other_currency": other_currency,
                    "without_amount": without_amount,
                },
            ),
            sales_recorded=len(live),
        )

    net = gross_total - deductions_total
    note = (
        f"{counted} recorded settlement(s). Gross is what the crop sold for; net is "
        "what the farm received after the buyer's deductions."
    )
    if other_currency:
        note += (
            f" {other_currency} sale(s) in another currency are excluded — nothing "
            "here converts money."
        )
    if without_amount:
        note += f" {without_amount} sale(s) state no amount and are excluded."
    if derived_gross:
        note += (
            f" {derived_gross} gross figure(s) were derived from quantity x unit price "
            "rather than stated outright."
        )
    return {
        "gross": round(gross_total, 2),
        "deductions": round(deductions_total, 2),
        "net": round(net, 2),
        "currency": currency,
        "sales_counted": counted,
        "sales_recorded": len(live),
        "sales_in_other_currency": other_currency,
        "sales_without_amount": without_amount,
        "gross_derived_count": derived_gross,
        "basis_text": note,
    }


# -------------------------------------------------------------------------- yield
def _yield_rows(block_outcomes):
    """Non-superseded `yield` observations. A correction replaces; it does not add."""
    superseded = {
        getattr(o, "supersedes_id", None)
        for o in (block_outcomes or [])
        if getattr(o, "supersedes_id", None) is not None
    }
    return [
        o for o in (block_outcomes or [])
        if getattr(o, "outcome_type", None) == YIELD_OUTCOME_TYPE
        and getattr(o, "id", None) not in superseded
        and getattr(o, "value", None) is not None
    ]


def _harvested_yield(block_outcomes) -> dict:
    """Season yield, normalised to kg — or a refusal naming what could not be combined.

    `units.convert` is the only arithmetic here and every factor in it is exact by
    definition. A unit it does not know is not converted with a rule of thumb: trays and
    flats are packaging whose weight varies by crop, by grower and by season, and
    inventing one would put a fabricated coefficient at the bottom of a yield-per-acre
    figure that a lender might later read.
    """
    rows = _yield_rows(block_outcomes)
    if not rows:
        return _refused(Refusal(
            code=NO_YIELD_RECORDED,
            detail=(
                "No harvest yield has been recorded for this crop cycle. Record a "
                "yield outcome per block to give the season a total."
            ),
        ))

    total_kg = 0.0
    converted_count = 0
    unconvertible: dict[str, dict] = {}
    for row in rows:
        unit = getattr(row, "unit", None)
        value = float(getattr(row, "value"))
        result = units.convert(value, unit, YIELD_CANONICAL_UNIT)
        if isinstance(result, units.Refusal):
            key = (unit or "unstated").strip() or "unstated"
            bucket = unconvertible.setdefault(key, {"unit": key, "total": 0.0, "observations": 0})
            bucket["total"] = round(bucket["total"] + value, 2)
            bucket["observations"] += 1
            continue
        total_kg += result.amount
        converted_count += 1

    if unconvertible:
        groups = sorted(unconvertible.values(), key=lambda g: g["unit"])
        named = ", ".join(f"{g['total']:g} {g['unit']}" for g in groups)
        return _refused(
            Refusal(
                code=INCOMPATIBLE_YIELD_UNITS,
                detail=(
                    f"This season's yield is recorded in units that cannot be combined: "
                    f"{named}. Re-record these in a weight unit (kg, lb, t) — nothing "
                    "here converts packaging to a weight, because that conversion "
                    "varies by crop and by grower and no source states it."
                ),
                context={
                    "groups": groups,
                    "convertible_observations": converted_count,
                },
            ),
            groups=groups,
            convertible_observations=converted_count,
        )

    return _metric(
        total_kg,
        unit=YIELD_CANONICAL_UNIT,
        basis=(
            f"{converted_count} recorded yield observation(s), normalised to "
            f"{YIELD_CANONICAL_UNIT} through exact unit factors."
        ),
        observations=converted_count,
    )


# --------------------------------------------------------------------------- area
def _planted_area(cycle) -> dict:
    """Canonical planted area, plus what the human actually typed.

    Both, because a per-acre figure derived from a converted number should still be able
    to show the grower the acreage they entered.
    """
    area_m2 = getattr(cycle, "planted_area_m2", None)
    if area_m2 is None or float(area_m2) <= 0:
        return _refused(Refusal(
            code=NO_PLANTED_AREA,
            detail=(
                "This crop cycle has no planted area, so nothing can be reported per "
                "acre or per hectare. Set the planted area on the season."
            ),
        ))
    return _metric(
        float(area_m2),
        unit="m2",
        basis="Planted area recorded on the crop cycle.",
        display_area=getattr(cycle, "display_area", None),
        display_area_unit=getattr(cycle, "display_area_unit", None),
    )


def _per_area(amount: float, area_m2: float, display_unit: str | None) -> dict:
    """`amount` per hectare, and per one unit of the area unit the grower entered.

    Both, because "per acre" and "per hectare" are the same fact and only one of them
    is the number a given grower will recognise. The display figure is dropped, not
    approximated, when the entered unit is not a known area unit.
    """
    in_hectares = units.convert(area_m2, "m2", "ha")
    payload: dict = {"per_hectare": round(amount / in_hectares.amount, 2)}
    if display_unit:
        in_display = units.convert(area_m2, "m2", display_unit)
        if not isinstance(in_display, units.Refusal) and in_display.amount > 0:
            payload["per_display_unit"] = round(amount / in_display.amount, 2)
            payload["display_unit"] = units.canonical_unit(display_unit) or display_unit
    return payload


# ---------------------------------------------------------------------- the payload
def build_closeout(
    *,
    cycle,
    farm,
    sales,
    spray_events,
    operations,
    block_outcomes,
    costs,
    ledger,
    scope,
    completeness_extra=None,
) -> dict:
    """Assemble one crop cycle's economics.

    `costs` is `value_ledger._season_costs` output, computed by the caller so the
    closeout and the value ledger can never disagree about what the season cost.
    `ledger` is the full value-ledger payload for the same cycle — embedded, not
    recomputed, for the same reason.
    """
    currency = costs.get("currency")
    is_closed = getattr(cycle, "status", None) in ("closed", "abandoned")

    revenue = _revenue(sales, currency)
    harvested_yield = _harvested_yield(block_outcomes)
    planted_area = _planted_area(cycle)

    metrics: dict = {
        "revenue": revenue,
        "costs": costs,
        "harvested_yield": harvested_yield,
        "planted_area": planted_area,
    }

    # ---- revenue minus recorded costs. Never without its coverage.
    cost_coverage = {
        "applications_without_cost": costs.get("applications_without_cost", 0),
        "operations_without_cost": costs.get("operations_without_cost", 0),
        "applications_counted": costs.get("applications_counted", 0),
        "operations_counted": costs.get("operations_counted", 0),
        "complete": (
            costs.get("applications_without_cost", 0) == 0
            and costs.get("operations_without_cost", 0) == 0
        ),
    }
    records_missing_cost = (
        cost_coverage["applications_without_cost"] + cost_coverage["operations_without_cost"]
    )
    if "not_calculated" in revenue:
        metrics["revenue_minus_recorded_costs"] = _refused(
            Refusal(
                code=NO_REVENUE_RECORDED,
                detail=(
                    "No revenue is recorded for this crop cycle, so there is nothing "
                    "to subtract recorded costs from."
                ),
            ),
            cost_coverage=cost_coverage,
        )
    elif costs.get("total", 0.0) == 0.0 and costs.get("applications_counted", 0) == 0 and costs.get("operations_counted", 0) == 0:
        metrics["revenue_minus_recorded_costs"] = _refused(
            Refusal(
                code=NO_COSTS_RECORDED,
                detail=(
                    "No cost has been recorded against this crop cycle. Revenue on its "
                    "own is not a result — subtracting nothing would present the whole "
                    "settlement as though the season were free."
                ),
            ),
            cost_coverage=cost_coverage,
        )
    else:
        coverage_sentence = (
            "Every recorded application and operation carries a cost."
            if cost_coverage["complete"]
            else (
                f"{records_missing_cost} recorded record(s) carry no cost and are "
                "excluded, so the true cost of this season is higher than the figure "
                "subtracted here."
            )
        )
        metrics["revenue_minus_recorded_costs"] = _metric(
            revenue["net"] - costs.get("total", 0.0),
            basis=(
                "Net revenue minus the costs recorded on this crop cycle. This is not "
                "profit: land, overhead, water, and any labour outside a recorded "
                f"operation are absent unless somebody entered them. {coverage_sentence}"
            ),
            currency=currency,
            cost_coverage=cost_coverage,
        )

    # ---- per-area and per-unit derivations. Each refuses with its denominator's reason.
    area_m2 = planted_area.get("value")
    display_unit = planted_area.get("display_area_unit")
    area_missing = _refused(Refusal(
        code=NO_PLANTED_AREA,
        detail="No planted area is recorded on this crop cycle.",
    ))

    def _rate(numerator_metric: dict, missing_code: str, missing_detail: str, basis: str, unit=None):
        if area_m2 is None:
            return dict(area_missing)
        if "not_calculated" in numerator_metric:
            # The numerator's OWN code, when it has one. "No yield recorded" would be
            # a lie about a season whose yield is recorded in trays: the reader would
            # go looking for missing records instead of fixing the units on the ones
            # that exist. The fallback covers a numerator that is simply absent.
            return _refused(Refusal(
                code=numerator_metric.get("code") or missing_code,
                detail=numerator_metric.get("reason") or missing_detail,
            ))
        rates = _per_area(numerator_metric["value"], area_m2, display_unit)
        return {"basis_text": basis, "unit": unit, **rates}

    metrics["yield_per_area"] = _rate(
        harvested_yield,
        NO_YIELD_RECORDED,
        "No harvest yield is recorded, so yield per area cannot be reported.",
        "Recorded yield divided by the recorded planted area.",
        unit=YIELD_CANONICAL_UNIT,
    )
    metrics["cost_per_area"] = (
        _rate(
            _metric(costs.get("total", 0.0), basis=""),
            NO_COSTS_RECORDED,
            "No cost is recorded, so cost per area cannot be reported.",
            "Recorded costs divided by the recorded planted area. Recorded costs only.",
            unit=currency,
        )
        if (costs.get("applications_counted", 0) or costs.get("operations_counted", 0))
        else _refused(Refusal(
            code=NO_COSTS_RECORDED,
            detail="No cost is recorded on this crop cycle.",
        ))
    )
    # Revenue's value lives under `net`, not `value`, so it takes the rate helper via a
    # one-line metric rather than being special-cased in it.
    metrics["revenue_per_area"] = _rate(
        revenue if "not_calculated" in revenue else _metric(revenue["net"], basis=""),
        NO_REVENUE_RECORDED,
        "No revenue is recorded, so revenue per area cannot be reported.",
        "Net revenue divided by the recorded planted area.",
        unit=currency,
    )

    # ---- cost per unit of crop: the figure a grower compares against a price.
    if "not_calculated" in harvested_yield:
        metrics["cost_per_yield_unit"] = _refused(Refusal(
            code=harvested_yield["code"],
            detail=(
                "Cost per unit of crop needs a season yield, and "
                + harvested_yield["reason"]
            ),
        ))
    elif not (costs.get("applications_counted", 0) or costs.get("operations_counted", 0)):
        metrics["cost_per_yield_unit"] = _refused(Refusal(
            code=NO_COSTS_RECORDED,
            detail="No cost is recorded on this crop cycle.",
        ))
    elif harvested_yield["value"] <= 0:
        metrics["cost_per_yield_unit"] = _refused(Refusal(
            code=NO_YIELD_RECORDED,
            detail="The recorded yield is zero, so a cost per unit cannot be divided out.",
        ))
    else:
        metrics["cost_per_yield_unit"] = _metric(
            costs.get("total", 0.0) / harvested_yield["value"],
            unit=f"{currency or 'currency'}/{YIELD_CANONICAL_UNIT}",
            basis=(
                "Recorded costs divided by recorded yield. Costs that were never "
                "entered are absent, so the true cost per unit is higher."
            ),
            cost_coverage=cost_coverage,
        )

    # ---- realised price per unit, from settlements only.
    if "not_calculated" not in revenue and "not_calculated" not in harvested_yield and harvested_yield["value"] > 0:
        metrics["realised_price_per_yield_unit"] = _metric(
            revenue["gross"] / harvested_yield["value"],
            unit=f"{currency or 'currency'}/{YIELD_CANONICAL_UNIT}",
            basis=(
                "Gross settlement value divided by recorded yield. This is what the "
                "crop actually fetched, not a market quote — and it is only meaningful "
                "if everything harvested was also sold and recorded."
            ),
        )
    else:
        metrics["realised_price_per_yield_unit"] = _refused(Refusal(
            code=(
                revenue.get("code")
                or harvested_yield.get("code")
                or NO_YIELD_RECORDED
            ),
            detail=(
                "A realised price needs both a recorded settlement and a recorded "
                "yield for this cycle."
            ),
        ))

    # ---- what Lumos can credibly attribute to its own recommendations.
    lumos_value = {
        "verified": ledger.get("verified", {}),
        "estimated": ledger.get("estimated", {}),
        "not_calculated_count": ledger.get("not_calculated_count", 0),
        "currency": ledger.get("currency"),
        "basis_text": (
            "Economic value credibly attributable to the recommendations Lumos "
            "documented — not a claim that Lumos caused the outcome, and not a share "
            "of the season's revenue. Verified figures are backed by the recorded "
            "follow-up timeline; estimated figures rest on a recorded outcome and "
            "nothing more. The two are never added together."
        ),
    }

    return {
        "model_version": MODEL_VERSION,
        "crop_cycle_id": getattr(cycle, "id", None),
        "farm_id": getattr(farm, "id", None),
        "crop": getattr(cycle, "crop", None),
        "season_year": getattr(cycle, "season_year", None),
        "season_label": getattr(cycle, "season_label", None),
        "status": getattr(cycle, "status", None),
        "is_closed": is_closed,
        # The same payload serves both states; only the framing differs.
        "view": "season_closeout" if is_closed else "season_to_date",
        "currency": currency,
        "metrics": metrics,
        "lumos_value": lumos_value,
        "completeness": _completeness(
            cycle=cycle,
            costs=costs,
            revenue=revenue,
            harvested_yield=harvested_yield,
            planted_area=planted_area,
            scope=scope,
            extra=completeness_extra or [],
        ),
        "scope": scope,
        "is_simulated": bool(ledger.get("is_simulated")),
        "record_scope": ledger.get("record_scope"),
        "counts": {
            "sales": len(_live_sales(sales)),
            "spray_events": len(spray_events or []),
            "operations": len(operations or []),
            "block_outcomes": len(block_outcomes or []),
        },
        "disclaimer": CLOSEOUT_DISCLAIMER,
    }


# -------------------------------------------------------------------- completeness
def _gap(code: str, detail: str, fix: str, count: int = 0, **extra) -> dict:
    return {"code": code, "detail": detail, "fix": fix, "count": count, **extra}


def _completeness(*, cycle, costs, revenue, harvested_yield, planted_area, scope, extra) -> dict:
    """Every named reason this season's economics are less than complete.

    A list, not a score. A single "82% complete" would be a number nobody can act on,
    and the point of this block is that each entry names a specific record somebody can
    go and enter.
    """
    gaps: list[dict] = []

    missing_spray_costs = costs.get("applications_without_cost", 0)
    if missing_spray_costs:
        gaps.append(_gap(
            "applications_without_cost",
            f"{missing_spray_costs} recorded application(s) carry no cost, so the "
            "season's cost total is lower than what was actually spent.",
            "Add a cost to each application on the Records tab.",
            missing_spray_costs,
        ))

    missing_op_costs = costs.get("operations_without_cost", 0)
    if missing_op_costs:
        gaps.append(_gap(
            "operations_without_cost",
            f"{missing_op_costs} recorded operation(s) carry no cost.",
            "Add a cost to each operation from the Season panel.",
            missing_op_costs,
        ))

    uncategorised = costs.get("operations_uncategorised", 0)
    if uncategorised:
        gaps.append(_gap(
            "operations_uncategorised",
            f"{uncategorised} costed operation(s) have no cost category, so the "
            "breakdown groups them as uncategorised.",
            "Set a cost category on those operations.",
            uncategorised,
        ))

    other_currency = costs.get("operations_in_other_currency", 0)
    if other_currency:
        gaps.append(_gap(
            "costs_in_other_currency",
            f"{other_currency} operation(s) are recorded in another currency and are "
            "excluded — nothing here converts money.",
            "Re-record them in the season's currency.",
            other_currency,
        ))

    if "not_calculated" in revenue:
        gaps.append(_gap(
            revenue["code"],
            revenue["reason"],
            "Record the settlement for this crop from the Season panel.",
        ))
    elif revenue.get("sales_in_other_currency"):
        gaps.append(_gap(
            "sales_in_other_currency",
            f"{revenue['sales_in_other_currency']} sale(s) are in another currency "
            "and are excluded from revenue.",
            "Re-record them in the season's currency.",
            revenue["sales_in_other_currency"],
        ))

    if "not_calculated" in harvested_yield:
        gaps.append(_gap(
            harvested_yield["code"],
            harvested_yield["reason"],
            "Record a yield outcome per block from the Season panel.",
        ))

    if "not_calculated" in planted_area:
        gaps.append(_gap(
            planted_area["code"],
            planted_area["reason"],
            "Set the planted area on this season.",
        ))

    outside = (scope or {}).get("records_outside_cycle") or {}
    outside_total = sum(v for v in outside.values() if isinstance(v, int))
    if outside_total:
        named = ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in outside.items() if v)
        gaps.append(_gap(
            "records_outside_cycle",
            f"{outside_total} farm record(s) are not attributed to this season "
            f"({named}), so they are excluded from every figure above.",
            "Use “Link records” on the Season panel to attach the ones that belong "
            "to this cycle.",
            outside_total,
            breakdown=outside,
        ))

    gaps.extend(extra)

    return {
        "gaps": gaps,
        "gap_count": len(gaps),
        "cost_capture_complete": (
            costs.get("applications_without_cost", 0) == 0
            and costs.get("operations_without_cost", 0) == 0
        ),
        "basis_text": (
            "Each entry names a record somebody can enter. There is deliberately no "
            "single completeness score — a percentage is not something anyone can act "
            "on, and it would let a season look nearly finished while the one figure "
            "that mattered was missing."
            if gaps else
            "Every figure above is backed by recorded data with no named gaps. That is "
            "not a guarantee the records are complete — only that nothing known is "
            "missing."
        ),
    }
