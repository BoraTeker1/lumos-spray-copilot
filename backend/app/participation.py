"""How Lumos participates economically in what a farm records.

Pure and framework-free (no FastAPI / SQLAlchemy imports). Reads a commercial
agreement plus the season's already-built closeout and value ledger, and answers
exactly three things:

    what economic model was agreed
    → what RECORDED evidence is the basis
    → what Lumos's participation calculates to

This is accounting, not a payment rail
--------------------------------------
`Participation` has no `invoice`, `due_date`, `paid`, `settlement_status`, or
`payment_method` field, and there is no route that could set one. That absence is the
guardrail: money movement is inexpressible here, the same way a prescription is
inexpressible on `disease_risk.RiskAssessment`. A figure computed here tells a grower
and Lumos what the agreed model comes to on this season's records. Whatever happens
next happens somewhere else.

Every basis is a number somebody recorded
-----------------------------------------
A share is taken of a figure that already exists in the closeout or the ledger — the
verified value tier, a recorded settlement, a recorded yield, a recorded planted area.
Nothing here estimates a basis, and nothing falls back to a default when the basis is
missing: it refuses with the code naming what is absent. In particular a
`verified_value_share` reads the VERIFIED tier only. Charging against estimated value
would bill for a claim nobody has corroborated, which is the one thing the whole value
ledger exists to keep apart.

Caps are applied and said out loud
----------------------------------
When a cap binds, `cap_applied` is True and the uncapped figure stays visible in
`basis_text`. A cap that silently swallowed the difference would make the agreement
unreadable from its own output.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.refusal import Refusal

MODEL_VERSION = "participation_v1"

# --- The agreed models --------------------------------------------------------
# Flat: a price for the service, unrelated to what the season did.
MODEL_PLATFORM_FEE = "platform_fee"
MODEL_PER_AREA_FEE = "per_area_fee"
MODEL_PER_CYCLE_FEE = "per_cycle_fee"
# Performance: a share of measured value, which is why the ledger's tiers matter.
MODEL_VERIFIED_VALUE_SHARE = "verified_value_share"
MODEL_PERFORMANCE_BONUS = "performance_bonus"
# Financing-linked: priced off a lender's stated figure, never off a computed rate.
MODEL_ORIGINATION_FEE = "origination_fee"
MODEL_MONITORING_FEE = "monitoring_fee"
# Output-linked: computed only from recorded settlements and recorded yield.
MODEL_REVENUE_SHARE = "revenue_share"
MODEL_CROP_SHARE = "crop_share"

AGREEMENT_MODELS = (
    MODEL_PLATFORM_FEE,
    MODEL_PER_AREA_FEE,
    MODEL_PER_CYCLE_FEE,
    MODEL_VERIFIED_VALUE_SHARE,
    MODEL_PERFORMANCE_BONUS,
    MODEL_ORIGINATION_FEE,
    MODEL_MONITORING_FEE,
    MODEL_REVENUE_SHARE,
    MODEL_CROP_SHARE,
)

# Models where participation is taken OUT of a measured pool, so "what the grower
# keeps" is a meaningful second number. A flat fee is a price, not a share of
# anything, and reporting a retention against it would invent a pool.
_SHARE_MODELS = (
    MODEL_VERIFIED_VALUE_SHARE,
    MODEL_PERFORMANCE_BONUS,
    MODEL_REVENUE_SHARE,
    MODEL_CROP_SHARE,
)

# --- Refusal codes ------------------------------------------------------------
NO_AGREEMENT = "no_agreement_on_farm"
NOT_EFFECTIVE = "agreement_not_effective_for_this_cycle"
UNKNOWN_MODEL = "unknown_agreement_model"
TERM_NOT_STATED = "agreement_term_not_stated"
NO_VERIFIED_VALUE = "no_verified_value_this_season"
NO_RECORDED_SETTLEMENT = "no_recorded_settlement"
NO_RECORDED_YIELD = "no_recorded_yield"
NO_PLANTED_AREA = "no_planted_area"
NO_SELECTED_FINANCING = "no_selected_financing_offer"
CAP_REQUIRED = "cap_required_by_this_model"

PARTICIPATION_DISCLAIMER = (
    "An accounting figure computed from this season's recorded evidence and the "
    "agreed commercial terms. Lumos moves no money: nothing here is an invoice, a "
    "charge, or a payment instruction."
)

_SQM_PER_HECTARE = 10_000.0
_SQM_PER_ACRE = 4046.8564224


@dataclass(frozen=True)
class Participation:
    """One agreement applied to one season's records.

    The field list IS the guardrail — see the module docstring. Adding a settlement
    or payment field here is the change that turns this from accounting into billing,
    and it should never happen by accident.
    """

    model_type: str
    agreement_id: int | None
    agreement_name: str
    basis_label: str
    basis_amount: float
    basis_unit: str
    participation_amount: float
    participation_unit: str
    basis_text: str
    rate_pct: float | None = None
    fixed_amount: float | None = None
    cap_amount: float | None = None
    cap_applied: bool = False
    grower_retained_amount: float | None = None
    evidence: tuple[str, ...] = ()

    def as_payload(self) -> dict:
        payload = {
            "model_version": MODEL_VERSION,
            "model_type": self.model_type,
            "agreement_id": self.agreement_id,
            "agreement_name": self.agreement_name,
            "basis_label": self.basis_label,
            "basis_amount": round(self.basis_amount, 2),
            "basis_unit": self.basis_unit,
            "rate_pct": self.rate_pct,
            "fixed_amount": self.fixed_amount,
            "cap_amount": self.cap_amount,
            "cap_applied": self.cap_applied,
            "participation_amount": round(self.participation_amount, 2),
            "participation_unit": self.participation_unit,
            "basis_text": self.basis_text,
            "evidence": list(self.evidence),
            "disclaimer": PARTICIPATION_DISCLAIMER,
        }
        if self.grower_retained_amount is not None:
            payload["grower_retained_amount"] = round(self.grower_retained_amount, 2)
        return payload


# ------------------------------------------------------------------- term access
def _term(agreement, key: str):
    return (getattr(agreement, "terms", None) or {}).get(key)


def _require(agreement, key: str, label: str):
    value = _term(agreement, key)
    if value is None:
        return Refusal(
            code=TERM_NOT_STATED,
            detail=(
                f"This agreement does not state {label}. Lumos never supplies a "
                "default commercial term — the figure comes from the signed "
                "agreement or it does not compute."
            ),
            context={"missing_term": key},
        )
    return float(value)


def _capped(gross: float, cap):
    """Apply a cap if one is stated. Returns (amount, cap_applied)."""
    if cap is None:
        return gross, False
    cap = float(cap)
    return (cap, True) if gross > cap else (gross, False)


def _effective_for(agreement, cycle) -> bool:
    """Does this agreement cover this season?

    Compared against the cycle's planting date when it has one, falling back to the
    season year. An agreement signed after the season it is meant to cover is a real
    case (a mid-season pilot), so the test is inclusive at both ends.
    """
    start = getattr(agreement, "effective_from", None)
    end = getattr(agreement, "effective_to", None)
    anchor = getattr(cycle, "planting_date", None)
    if anchor is None:
        year = getattr(cycle, "season_year", None)
        if year is None:
            return True
        anchor = date(int(year), 12, 31)
    if start and anchor < start:
        return False
    if end and anchor > end:
        return False
    return True


# --------------------------------------------------------------- basis readers
def _verified_value(ledger, currency):
    block = (ledger or {}).get("verified") or {}
    if not block.get("item_count"):
        return Refusal(
            code=NO_VERIFIED_VALUE,
            detail=(
                "No verified value is attributable to a Lumos recommendation in this "
                "season, so a share of it is nothing. Verified value needs a recorded "
                "outcome backed by the follow-up timeline — estimated value is "
                "deliberately not chargeable."
            ),
        )
    return float(block.get("total", 0.0))


def _recorded_revenue(closeout):
    revenue = (closeout.get("metrics") or {}).get("revenue") or {}
    if revenue.get("not_calculated"):
        return Refusal(
            code=revenue.get("code") or NO_RECORDED_SETTLEMENT,
            detail=(
                "A revenue share is computed only from recorded settlements, and "
                + (revenue.get("reason") or "none are on record for this season.")
            ),
        )
    return float(revenue.get("net", 0.0))


def _recorded_yield(closeout):
    harvested = (closeout.get("metrics") or {}).get("harvested_yield") or {}
    if harvested.get("not_calculated"):
        return Refusal(
            code=harvested.get("code") or NO_RECORDED_YIELD,
            detail=(
                "A crop share is computed only from recorded yield, and "
                + (harvested.get("reason") or "none is on record for this season.")
            ),
        )
    return float(harvested.get("value", 0.0))


def _planted_area(closeout, unit: str):
    area = (closeout.get("metrics") or {}).get("planted_area") or {}
    if area.get("not_calculated"):
        return Refusal(
            code=NO_PLANTED_AREA,
            detail=(
                "A per-area fee needs a recorded planted area on the crop cycle, and "
                + (area.get("reason") or "none is recorded.")
            ),
        )
    area_m2 = float(area.get("value", 0.0))
    divisor = _SQM_PER_ACRE if unit in ("acre", "acres") else _SQM_PER_HECTARE
    return area_m2 / divisor


# --------------------------------------------------------------------- compute
def compute(*, agreement, cycle, closeout, ledger=None, financing_offer=None) -> Participation | Refusal:
    """Apply one agreement to one season's recorded evidence.

    `closeout` is a `season_closeout.build_closeout` payload; `ledger` its embedded
    value ledger (or an equivalent). Returns a `Participation` or a `Refusal` naming
    what is missing — never a zero standing in for an absent basis.
    """
    if agreement is None:
        return Refusal(
            code=NO_AGREEMENT,
            detail=(
                "No commercial agreement is on record for this farm, so there is no "
                "model to calculate participation from."
            ),
        )
    if not _effective_for(agreement, cycle):
        return Refusal(
            code=NOT_EFFECTIVE,
            detail=(
                "This agreement's effective dates do not cover this crop cycle, so it "
                "does not price this season."
            ),
        )

    model = getattr(agreement, "model_type", None)
    if model not in AGREEMENT_MODELS:
        return Refusal(
            code=UNKNOWN_MODEL,
            detail=f"{model!r} is not a commercial model Lumos knows how to calculate.",
        )

    ledger = ledger if ledger is not None else (closeout.get("lumos_value") or {})
    currency = (
        getattr(agreement, "currency_code", None)
        or closeout.get("currency")
        or "USD"
    )
    aid = getattr(agreement, "id", None)
    name = getattr(agreement, "name", "") or model
    cid = closeout.get("crop_cycle_id")
    cap = _term(agreement, "cap_amount")

    def _flat(label: str, evidence_ref: str, note: str):
        amount = _require(agreement, "amount", "a fixed amount")
        if isinstance(amount, Refusal):
            return amount
        return Participation(
            model_type=model, agreement_id=aid, agreement_name=name,
            basis_label=label, basis_amount=amount, basis_unit=currency,
            fixed_amount=amount,
            participation_amount=amount, participation_unit=currency,
            basis_text=note,
            evidence=(evidence_ref,),
        )

    # ---- flat models: a price, not a share. No pool, so no retained figure. ----
    if model == MODEL_PLATFORM_FEE:
        return _flat(
            "Fixed platform fee",
            f"commercial_agreement:{aid}:amount",
            "A fixed fee stated in the agreement. It does not vary with what the "
            "season produced, and nothing is taken out of the grower's return.",
        )
    if model == MODEL_PER_CYCLE_FEE:
        return _flat(
            "Fee per crop cycle",
            f"commercial_agreement:{aid}:amount",
            "A fixed fee for this crop cycle, stated in the agreement.",
        )
    if model == MODEL_MONITORING_FEE:
        return _flat(
            "Monitoring fee",
            f"commercial_agreement:{aid}:amount",
            "A fixed fee for monitoring the financed season, stated in the "
            "agreement. It is not derived from any lender's rate.",
        )

    if model == MODEL_PER_AREA_FEE:
        rate = _require(agreement, "rate", "a rate per unit of area")
        if isinstance(rate, Refusal):
            return rate
        unit = _term(agreement, "area_unit") or "ha"
        area = _planted_area(closeout, unit)
        if isinstance(area, Refusal):
            return area
        gross = rate * area
        amount, capped = _capped(gross, cap)
        return Participation(
            model_type=model, agreement_id=aid, agreement_name=name,
            basis_label=f"Planted area ({unit})",
            basis_amount=area, basis_unit=unit,
            rate_pct=None, fixed_amount=rate,
            cap_amount=float(cap) if cap is not None else None, cap_applied=capped,
            participation_amount=amount, participation_unit=currency,
            basis_text=(
                f"{rate:,.2f} {currency} per {unit} on the {area:,.2f} {unit} recorded "
                f"as planted for this crop cycle"
                + (f", capped at {float(cap):,.2f} {currency} (uncapped: "
                   f"{gross:,.2f})." if capped else ".")
            ),
            evidence=(f"crop_cycle:{cid}:planted_area_m2",
                      f"commercial_agreement:{aid}:rate"),
        )

    if model == MODEL_ORIGINATION_FEE:
        if financing_offer is None:
            return Refusal(
                code=NO_SELECTED_FINANCING,
                detail=(
                    "An origination fee is priced off a selected financing offer, and "
                    "no offer has been selected for this season."
                ),
            )
        financed = float(getattr(financing_offer, "financed_amount", 0.0) or 0.0)
        rate = _require(agreement, "rate_pct", "an origination rate")
        if isinstance(rate, Refusal):
            return rate
        gross = financed * rate / 100.0
        amount, capped = _capped(gross, cap)
        return Participation(
            model_type=model, agreement_id=aid, agreement_name=name,
            basis_label="Financed amount on the selected offer",
            basis_amount=financed, basis_unit=currency,
            rate_pct=rate,
            cap_amount=float(cap) if cap is not None else None, cap_applied=capped,
            participation_amount=amount, participation_unit=currency,
            basis_text=(
                f"{rate:g}% of the {financed:,.2f} {currency} financed amount the "
                "lender stated on the offer the grower selected. Lumos derives no "
                "rate of its own and no repayment schedule"
                + (f"; capped at {float(cap):,.2f} {currency}." if capped else ".")
            ),
            evidence=(
                f"financing_offer:{getattr(financing_offer, 'id', None)}:financed_amount",
                f"commercial_agreement:{aid}:rate_pct",
            ),
        )

    # ---- share models: a slice of a measured pool. ----------------------------
    rate = _require(agreement, "rate_pct", "a share percentage")
    if isinstance(rate, Refusal):
        return rate

    if model in (MODEL_VERIFIED_VALUE_SHARE, MODEL_PERFORMANCE_BONUS):
        if model == MODEL_PERFORMANCE_BONUS and cap is None:
            return Refusal(
                code=CAP_REQUIRED,
                detail=(
                    "A performance bonus must state a cap. An uncapped bonus on a "
                    "measured figure is an open-ended claim on the grower's return."
                ),
            )
        basis = _verified_value(ledger, currency)
        if isinstance(basis, Refusal):
            return basis
        basis_label = (
            "Verified Lumos-created value"
            if model == MODEL_VERIFIED_VALUE_SHARE else
            "Verified Lumos-created value (bonus basis)"
        )
        evidence_ref = f"crop_cycle:{cid}:value_ledger:verified"
        tier_note = (
            "Verified value only — value that is merely estimated is deliberately "
            "excluded, because nothing has corroborated it yet."
        )
    elif model == MODEL_REVENUE_SHARE:
        basis = _recorded_revenue(closeout)
        if isinstance(basis, Refusal):
            return basis
        basis_label = "Net recorded revenue"
        evidence_ref = f"crop_cycle:{cid}:sales"
        tier_note = (
            "Computed from settlements actually recorded for this crop cycle, in the "
            "cycle's own currency. Nothing here converts money or projects a price."
        )
    elif model == MODEL_CROP_SHARE:
        basis = _recorded_yield(closeout)
        if isinstance(basis, Refusal):
            return basis
        harvested = (closeout.get("metrics") or {}).get("harvested_yield") or {}
        yield_unit = harvested.get("unit") or "kg"
        gross = basis * rate / 100.0
        amount, capped = _capped(gross, cap)
        return Participation(
            model_type=model, agreement_id=aid, agreement_name=name,
            basis_label="Recorded harvested yield",
            basis_amount=basis, basis_unit=yield_unit,
            rate_pct=rate,
            cap_amount=float(cap) if cap is not None else None, cap_applied=capped,
            participation_amount=amount, participation_unit=yield_unit,
            grower_retained_amount=basis - amount,
            basis_text=(
                f"{rate:g}% of the {basis:,.2f} {yield_unit} recorded as harvested "
                "for this crop cycle. A share of the crop, stated in crop — Lumos "
                "does not price it, and no settlement is implied"
                + (f". Capped at {float(cap):,.2f} {yield_unit}." if capped else ".")
            ),
            evidence=(f"crop_cycle:{cid}:block_outcomes:yield",
                      f"commercial_agreement:{aid}:rate_pct"),
        )
    else:  # pragma: no cover - AGREEMENT_MODELS is exhaustive above
        return Refusal(code=UNKNOWN_MODEL, detail=f"{model!r} has no calculation.")

    gross = basis * rate / 100.0
    amount, capped = _capped(gross, cap)
    return Participation(
        model_type=model, agreement_id=aid, agreement_name=name,
        basis_label=basis_label, basis_amount=basis, basis_unit=currency,
        rate_pct=rate,
        cap_amount=float(cap) if cap is not None else None, cap_applied=capped,
        participation_amount=amount, participation_unit=currency,
        grower_retained_amount=basis - amount,
        basis_text=(
            f"{rate:g}% of {basis:,.2f} {currency}. {tier_note}"
            + (f" Capped at {float(cap):,.2f} {currency} (uncapped: "
               f"{gross:,.2f})." if capped else "")
        ),
        evidence=(evidence_ref, f"commercial_agreement:{aid}:rate_pct"),
    )
