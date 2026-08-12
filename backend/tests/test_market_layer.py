"""Pricing and hedging: staleness refusal, and the inexpressibility of advice.

Both modules ship with EMPTY sources. The two behaviours worth pinning are the ones a
later change would find most tempting to "fix": serving the last known price when a
fresh one is unavailable, and adding a "you should hedge more" field next to a coverage
percentage.
"""
from datetime import date

import pytest

from app import futures_curve, hedging, price_series, pricing
from app.refusal import INPUTS_TOO_STALE, NO_SOURCE_TRANSCRIBED, Refusal
from app.transcription import Citation

AS_OF = date(2026, 8, 7)

CITATION = Citation(
    document="SYNTHETIC — test fixture, not a market source",
    publisher="tests/test_market_layer.py",
    section="fixture",
    snippet="values invented for arithmetic testing only",
    transcribed_by="test suite",
    transcribed_on=date(2026, 8, 7),
)


def _point(observed_on, price=12.5, *, commodity="strawberry", market="LA Terminal"):
    return price_series.PricePoint(
        commodity=commodity, market=market, price=price, currency="USD",
        unit="lb", observed_on=observed_on, citation=CITATION,
    )


# --------------------------------------------------------------- shipped state
def test_market_sources_ship_empty():
    assert price_series.TRANSCRIBED == ()
    assert futures_curve.TRANSCRIBED == ()


def test_pricing_refuses_without_a_transcribed_series():
    result = pricing.latest(
        commodity="strawberry", market="LA Terminal", as_of=AS_OF, max_age_days=7
    )
    assert isinstance(result, Refusal)
    assert result.code == NO_SOURCE_TRANSCRIBED


# -------------------------------------------------------------------- pricing
def test_a_fresh_price_is_served_with_its_age(monkeypatch):
    monkeypatch.setattr(price_series, "TRANSCRIBED", (_point(date(2026, 8, 5)),))
    view = pricing.latest(
        commodity="strawberry", market="LA Terminal", as_of=AS_OF, max_age_days=7
    )
    assert view.price == 12.5
    assert view.age_days == 2


def test_a_stale_price_refuses_rather_than_falling_back(monkeypatch):
    """The whole design of this module.

    A three-week-old price and a fresh one look identical on screen. A grower deciding
    whether to sell this week would act on it and be wrong for a reason nothing showed.
    """
    monkeypatch.setattr(price_series, "TRANSCRIBED", (_point(date(2026, 7, 10)),))
    result = pricing.latest(
        commodity="strawberry", market="LA Terminal", as_of=AS_OF, max_age_days=7
    )
    assert isinstance(result, Refusal)
    assert result.code == INPUTS_TOO_STALE
    assert result.context["age_days"] == 28


def test_the_newest_point_within_the_window_wins(monkeypatch):
    monkeypatch.setattr(price_series, "TRANSCRIBED", (
        _point(date(2026, 8, 1), price=10.0),
        _point(date(2026, 8, 6), price=14.0),
    ))
    view = pricing.latest(
        commodity="strawberry", market="LA Terminal", as_of=AS_OF, max_age_days=7
    )
    assert view.price == 14.0


def test_a_future_dated_point_is_never_served(monkeypatch):
    """Point-in-time discipline: a price observed after as_of is not knowable yet."""
    monkeypatch.setattr(price_series, "TRANSCRIBED", (
        _point(date(2026, 8, 5), price=10.0),
        _point(date(2026, 9, 1), price=99.0),
    ))
    view = pricing.latest(
        commodity="strawberry", market="LA Terminal", as_of=AS_OF, max_age_days=7
    )
    assert view.price == 10.0


def test_a_price_view_never_forecasts_or_advises(monkeypatch):
    monkeypatch.setattr(price_series, "TRANSCRIBED", (_point(date(2026, 8, 5)),))
    payload = pricing.latest(
        commodity="strawberry", market="LA Terminal", as_of=AS_OF, max_age_days=7
    ).as_payload()

    assert "forecast" in payload["not_calculated"]
    assert "sell_recommendation" in payload["not_calculated"]
    assert payload["age_days"] == 2  # always beside the price


def test_a_zero_price_is_refused_at_import_time():
    with pytest.raises(ValueError, match="price must be positive"):
        _point(date(2026, 8, 5), price=0.0)


def test_an_ambiguous_currency_is_refused_at_import_time():
    with pytest.raises(ValueError, match="3-letter ISO code"):
        price_series.PricePoint(
            commodity="strawberry", market="LA", price=1.0, currency="$",
            unit="lb", observed_on=AS_OF, citation=CITATION,
        )


# -------------------------------------------------------------------- hedging
def _position(quantity, unit="tonnes", kind="sold_forward"):
    return hedging.Position(
        kind=kind, quantity=quantity, quantity_unit=unit, commodity="strawberry",
    )


def test_no_positions_is_a_true_zero_not_an_abstention():
    """The grower has recorded no positions: none of the crop is priced. Real answer."""
    result = hedging.coverage(
        commodity="strawberry", expected_quantity=100.0, quantity_unit="tonnes",
        positions=[],
    )
    assert not isinstance(result, Refusal)
    assert result.covered_quantity == 0.0
    assert result.exposed_quantity == 100.0


def test_coverage_sums_positions():
    result = hedging.coverage(
        commodity="strawberry", expected_quantity=100.0, quantity_unit="tonnes",
        positions=[_position(30.0), _position(20.0)],
    )
    assert result.covered_fraction == pytest.approx(0.5)
    assert result.position_count == 2


def test_mixed_units_refuse_rather_than_converting():
    result = hedging.coverage(
        commodity="strawberry", expected_quantity=100.0, quantity_unit="tonnes",
        positions=[_position(30.0, unit="cwt")],
    )
    assert isinstance(result, Refusal)
    assert "cited conversion" in result.detail


def test_over_covering_is_reported_not_shown_as_negative_exposure():
    result = hedging.coverage(
        commodity="strawberry", expected_quantity=100.0, quantity_unit="tonnes",
        positions=[_position(130.0)],
    )
    assert result.over_covered is True
    assert result.exposed_quantity == 0.0


def test_missing_expected_quantity_refuses():
    result = hedging.coverage(
        commodity="strawberry", expected_quantity=None, quantity_unit="tonnes",
        positions=[_position(30.0)],
    )
    assert isinstance(result, Refusal)


def test_hedge_coverage_cannot_express_advice():
    """Structural, not merely absent: there is no field to put advice in."""
    result = hedging.coverage(
        commodity="strawberry", expected_quantity=100.0, quantity_unit="tonnes",
        positions=[_position(30.0)],
    )
    forbidden = {"recommended_action", "should_hedge", "suggested_contracts", "signal"}
    assert not (forbidden & set(vars(result)))

    payload = result.as_payload()
    assert "recommended_action" in payload["not_calculated"]
    assert "mark_to_market" in payload["not_calculated"]


def test_an_unknown_position_kind_is_refused():
    with pytest.raises(ValueError, match="unknown position kind"):
        hedging.Position(
            kind="short_straddle", quantity=1.0, quantity_unit="tonnes",
            commodity="strawberry",
        )


def test_a_malformed_contract_month_is_refused_at_import_time():
    with pytest.raises(ValueError, match="ISO year-month"):
        futures_curve.FuturesQuote(
            commodity="strawberry", exchange="SYNTHETIC", contract_month="Nov 2026",
            settlement_price=10.0, currency="USD", unit="lb",
            settled_on=AS_OF, citation=CITATION,
        )
