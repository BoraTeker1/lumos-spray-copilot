"""Lumos economic participation: agreement + recorded evidence → a figure.

Two things are load-bearing here.

First, the FIELD SET. `Participation` must never acquire an invoice, a due date, a
paid flag, or a settlement status — that absence is what keeps this accounting rather
than billing, and it is the one structural guardrail this layer ships with.

Second, the refusals. Every basis is a number somebody recorded, so an agreement over
a season with no verified value, no settlement, or no recorded yield must refuse by
name rather than quietly computing a share of zero — a zero would read as "Lumos is
owed nothing", when the truth is "nothing has been measured yet".
"""
from datetime import date
from types import SimpleNamespace

import pytest

from app import participation
from app.refusal import Refusal, is_refusal


def _agreement(model_type=participation.MODEL_VERIFIED_VALUE_SHARE, **overrides):
    payload = {
        "id": 3, "name": "Pilot terms 2026", "model_type": model_type,
        "currency_code": "USD", "effective_from": None, "effective_to": None,
        "terms": {"rate_pct": 15.0},
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def _cycle(**overrides):
    payload = {"id": 7, "season_year": 2026, "planting_date": date(2026, 1, 15)}
    payload.update(overrides)
    return SimpleNamespace(**payload)


def _closeout(*, verified=20000.0, verified_items=3, revenue_net=48000.0,
              yield_kg=12000.0, area_m2=72843.0):
    metrics = {
        "revenue": {"gross": 50000.0, "net": revenue_net, "basis_text": "b"},
        "harvested_yield": {"value": yield_kg, "unit": "kg", "basis_text": "b"},
        "planted_area": {"value": area_m2, "basis_text": "b"},
    }
    return {
        "crop_cycle_id": 7,
        "currency": "USD",
        "metrics": metrics,
        "lumos_value": {
            "verified": {"total": verified, "item_count": verified_items},
            "estimated": {"total": 9000.0, "item_count": 4},
        },
    }


def _refused_metric(code):
    return {"not_calculated": True, "code": code, "reason": "nothing is recorded"}


_DEFAULT = object()


def _compute(agreement=_DEFAULT, closeout=None, **kwargs):
    """`agreement=None` is a real case under test, so the default is a sentinel."""
    return participation.compute(
        agreement=_agreement() if agreement is _DEFAULT else agreement,
        cycle=kwargs.pop("cycle", _cycle()),
        closeout=closeout if closeout is not None else _closeout(),
        **kwargs,
    )


# ----------------------------------------------------------- the one guardrail
def test_participation_cannot_express_a_payment():
    """The field set IS the boundary between accounting and billing."""
    fields = set(participation.Participation.__dataclass_fields__)
    assert not fields & {
        "invoice", "invoice_id", "invoice_number", "due_date", "paid", "paid_at",
        "settlement_status", "payment_method", "payment_reference", "collected",
        "disbursed", "apr", "interest_rate", "amortisation",
    }


def test_the_disclaimer_says_no_money_moves():
    result = _compute()
    assert "moves no money" in result.as_payload()["disclaimer"]


# ------------------------------------------------------- verified value share
def test_a_verified_value_share_is_the_headline_calculation():
    """The example from the brief: 15% of $20,000 verified = $3,000 / $17,000."""
    result = _compute(_agreement(terms={"rate_pct": 15.0}), _closeout(verified=20000.0))
    assert result.basis_amount == 20000.0
    assert result.participation_amount == 3000.0
    assert result.grower_retained_amount == 17000.0
    assert result.rate_pct == 15.0
    assert result.basis_unit == "USD"


def test_a_verified_value_share_never_touches_estimated_value():
    """Estimated value is a claim nobody has corroborated; billing it is the error."""
    closeout = _closeout(verified=20000.0)
    assert closeout["lumos_value"]["estimated"]["total"] == 9000.0
    result = _compute(closeout=closeout)
    assert result.basis_amount == 20000.0  # not 29000.0
    assert "deliberately excluded" in result.basis_text


def test_a_season_with_no_verified_value_refuses_rather_than_charging_zero():
    result = _compute(closeout=_closeout(verified=0.0, verified_items=0))
    assert is_refusal(result)
    assert result.code == participation.NO_VERIFIED_VALUE


def test_a_cap_binds_and_says_so():
    result = _compute(
        _agreement(terms={"rate_pct": 15.0, "cap_amount": 2000.0}),
        _closeout(verified=20000.0),
    )
    assert result.participation_amount == 2000.0
    assert result.cap_applied is True
    assert "uncapped: 3,000.00" in result.basis_text


def test_a_cap_above_the_computed_figure_does_not_bind():
    result = _compute(
        _agreement(terms={"rate_pct": 15.0, "cap_amount": 9000.0}),
        _closeout(verified=20000.0),
    )
    assert result.participation_amount == 3000.0
    assert result.cap_applied is False


# ---------------------------------------------------------- performance bonus
def test_a_performance_bonus_must_state_a_cap():
    """An uncapped bonus is an open-ended claim on the grower's return."""
    result = _compute(_agreement(
        participation.MODEL_PERFORMANCE_BONUS, terms={"rate_pct": 10.0}
    ))
    assert is_refusal(result) and result.code == participation.CAP_REQUIRED


def test_a_capped_performance_bonus_computes():
    result = _compute(_agreement(
        participation.MODEL_PERFORMANCE_BONUS,
        terms={"rate_pct": 10.0, "cap_amount": 5000.0},
    ))
    assert result.participation_amount == 2000.0
    assert result.cap_amount == 5000.0


# ------------------------------------------------------------- revenue share
def test_a_revenue_share_computes_from_recorded_settlements_only():
    result = _compute(_agreement(
        participation.MODEL_REVENUE_SHARE, terms={"rate_pct": 5.0}
    ))
    assert result.basis_amount == 48000.0
    assert result.participation_amount == 2400.0
    assert result.grower_retained_amount == 45600.0
    assert "settlements actually recorded" in result.basis_text


def test_a_revenue_share_refuses_when_no_settlement_is_recorded():
    closeout = _closeout()
    closeout["metrics"]["revenue"] = _refused_metric("no_sales_recorded")
    result = _compute(
        _agreement(participation.MODEL_REVENUE_SHARE, terms={"rate_pct": 5.0}),
        closeout,
    )
    assert is_refusal(result) and result.code == "no_sales_recorded"


def test_a_revenue_share_carries_the_closeouts_own_currency_refusal_through():
    closeout = _closeout()
    closeout["metrics"]["revenue"] = _refused_metric("no_revenue_in_cycle_currency")
    result = _compute(
        _agreement(participation.MODEL_REVENUE_SHARE, terms={"rate_pct": 5.0}),
        closeout,
    )
    assert result.code == "no_revenue_in_cycle_currency"


# ---------------------------------------------------------------- crop share
def test_a_crop_share_is_stated_in_crop_not_in_money():
    """Pricing the share would need a projected price nobody recorded."""
    result = _compute(_agreement(
        participation.MODEL_CROP_SHARE, terms={"rate_pct": 8.0}
    ))
    assert result.basis_unit == "kg"
    assert result.participation_unit == "kg"
    assert result.participation_amount == 960.0
    assert result.grower_retained_amount == 11040.0
    assert "no settlement is implied" in result.basis_text


def test_a_crop_share_refuses_without_a_recorded_yield():
    closeout = _closeout()
    closeout["metrics"]["harvested_yield"] = _refused_metric("incompatible_yield_units")
    result = _compute(
        _agreement(participation.MODEL_CROP_SHARE, terms={"rate_pct": 8.0}), closeout
    )
    assert is_refusal(result) and result.code == "incompatible_yield_units"


# ----------------------------------------------------------------- flat fees
@pytest.mark.parametrize("model", [
    participation.MODEL_PLATFORM_FEE,
    participation.MODEL_PER_CYCLE_FEE,
    participation.MODEL_MONITORING_FEE,
])
def test_a_flat_fee_is_a_price_and_reports_no_retained_pool(model):
    result = _compute(_agreement(model, terms={"amount": 1200.0}))
    assert result.participation_amount == 1200.0
    assert result.grower_retained_amount is None
    assert "grower_retained_amount" not in result.as_payload()


def test_a_flat_fee_without_a_stated_amount_refuses():
    result = _compute(_agreement(participation.MODEL_PLATFORM_FEE, terms={}))
    assert is_refusal(result) and result.code == participation.TERM_NOT_STATED


def test_lumos_never_supplies_a_default_commercial_term():
    result = _compute(_agreement(terms={}))
    assert is_refusal(result)
    assert "never supplies a default" in result.detail


# -------------------------------------------------------------- per-area fee
def test_a_per_area_fee_uses_the_recorded_planted_area():
    result = _compute(_agreement(
        participation.MODEL_PER_AREA_FEE,
        terms={"rate": 40.0, "area_unit": "acre"},
    ))
    assert result.basis_unit == "acre"
    assert round(result.basis_amount) == 18  # 72,843 m2
    assert round(result.participation_amount) == 720


def test_a_per_area_fee_defaults_to_hectares_when_no_unit_is_stated():
    result = _compute(_agreement(
        participation.MODEL_PER_AREA_FEE, terms={"rate": 100.0}
    ))
    assert result.basis_unit == "ha"
    assert round(result.basis_amount, 2) == 7.28


def test_a_per_area_fee_refuses_without_a_planted_area():
    closeout = _closeout()
    closeout["metrics"]["planted_area"] = _refused_metric("no_planted_area")
    result = _compute(
        _agreement(participation.MODEL_PER_AREA_FEE, terms={"rate": 40.0}), closeout
    )
    assert is_refusal(result) and result.code == participation.NO_PLANTED_AREA


# ------------------------------------------------------------ financing fees
def test_an_origination_fee_prices_off_the_lenders_stated_financed_amount():
    offer = SimpleNamespace(id=12, financed_amount=30000.0)
    result = _compute(
        _agreement(participation.MODEL_ORIGINATION_FEE, terms={"rate_pct": 2.0}),
        financing_offer=offer,
    )
    assert result.basis_amount == 30000.0
    assert result.participation_amount == 600.0
    assert "derives no rate of its own" in result.basis_text


def test_an_origination_fee_refuses_without_a_selected_offer():
    result = _compute(
        _agreement(participation.MODEL_ORIGINATION_FEE, terms={"rate_pct": 2.0})
    )
    assert is_refusal(result) and result.code == participation.NO_SELECTED_FINANCING


# --------------------------------------------------------------- eligibility
def test_no_agreement_refuses_by_name():
    result = _compute(agreement=None)
    assert is_refusal(result) and result.code == participation.NO_AGREEMENT


def test_an_unknown_model_refuses_rather_than_guessing():
    result = _compute(_agreement("percentage_of_vibes"))
    assert is_refusal(result) and result.code == participation.UNKNOWN_MODEL


def test_an_agreement_that_does_not_cover_the_season_refuses():
    agreement = _agreement(
        effective_from=date(2027, 1, 1), effective_to=date(2027, 12, 31)
    )
    result = _compute(agreement)
    assert is_refusal(result) and result.code == participation.NOT_EFFECTIVE


def test_an_agreement_covering_the_season_computes():
    agreement = _agreement(
        effective_from=date(2026, 1, 1), effective_to=date(2026, 12, 31)
    )
    assert not is_refusal(_compute(agreement))


def test_a_cycle_with_no_planting_date_falls_back_to_the_season_year():
    agreement = _agreement(effective_from=date(2026, 1, 1))
    result = _compute(agreement, cycle=_cycle(planting_date=None))
    assert not is_refusal(result)


# ------------------------------------------------------------------- payload
def test_the_payload_carries_the_basis_and_its_evidence():
    result = _compute()
    payload = result.as_payload()
    assert payload["basis_label"] == "Verified Lumos-created value"
    assert "crop_cycle:7:value_ledger:verified" in payload["evidence"]
    assert "commercial_agreement:3:rate_pct" in payload["evidence"]
    assert payload["model_version"] == participation.MODEL_VERSION


def test_every_declared_model_either_computes_or_refuses_by_name():
    """No model may fall through to an exception on a well-formed agreement."""
    offer = SimpleNamespace(id=1, financed_amount=1000.0)
    terms = {"rate_pct": 10.0, "rate": 10.0, "amount": 100.0, "cap_amount": 5000.0}
    for model in participation.AGREEMENT_MODELS:
        result = _compute(_agreement(model, terms=terms), financing_offer=offer)
        assert isinstance(result, (participation.Participation, Refusal)), model
