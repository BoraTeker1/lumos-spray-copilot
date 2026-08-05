"""Unit-system tests: exact definitional conversions, and refusals that stay refusals."""
import pytest

from app import units
from app.units import Converted, Refusal


# ------------------------------------------------------------------ vocabulary

def test_canonical_unit_resolves_aliases_but_never_guesses():
    assert units.canonical_unit("Acres") == "acre"
    assert units.canonical_unit(" HECTARE ") == "ha"
    assert units.canonical_unit("sq  m") == "m2"
    # An unknown unit is None, not a best-effort match. "mt" is a tonne and "m" is a
    # metre; a prefix match between them would be wrong by 1000x and a dimension.
    assert units.canonical_unit("mt") == "t"
    assert units.canonical_unit("m") == "m"
    assert units.canonical_unit("furlong") is None
    assert units.canonical_unit(None) is None
    assert units.canonical_unit("") is None


def test_dimension_of_known_and_unknown_units():
    assert units.dimension_of("acre") == units.AREA
    assert units.dimension_of("lb") == units.MASS
    assert units.dimension_of("gal") == units.VOLUME
    assert units.dimension_of("therm") == units.ENERGY
    assert units.dimension_of("nonsense") is None


# ------------------------------------------------------------------ conversions

@pytest.mark.parametrize(
    "amount,frm,to,expected",
    [
        (1, "acre", "m2", 4046.8564224),        # exact by definition
        (1, "ha", "m2", 10_000.0),
        (1, "lb", "kg", 0.45359237),            # exact by definition
        (16, "oz", "lb", 1.0),
        (1, "gal", "l", 3.785411784),           # exact by definition
        (128, "fl oz", "gal", 1.0),
        (1, "ft", "m", 0.3048),                 # exact by definition
        (1, "mi", "ft", 5280.0),
        (1, "kwh", "mj", 3.6),
        (1, "d", "h", 24.0),
    ],
)
def test_definitional_conversions_are_exact(amount, frm, to, expected):
    result = units.convert(amount, frm, to)
    assert isinstance(result, Converted)
    assert result.amount == pytest.approx(expected, rel=1e-12)
    assert result.unit == units.canonical_unit(to)


def test_conversion_carries_its_citations():
    result = units.convert(1, "acre", "ha")
    assert isinstance(result, Converted)
    assert result.conversion_provenance
    assert any("4840 square yards" in c for c in result.conversion_provenance)


def test_identity_conversion_needs_no_citation():
    result = units.convert(5.0, "acres", "acre")
    assert isinstance(result, Converted)
    assert result.amount == 5.0
    assert result.conversion_provenance == ()


def test_round_trip_is_stable():
    there = units.convert(12.5, "acre", "m2")
    back = units.convert(there.amount, "m2", "acre")
    assert back.amount == pytest.approx(12.5, rel=1e-12)


def test_temperature_is_affine_not_proportional():
    assert units.convert(0, "c", "f").amount == pytest.approx(32.0)
    assert units.convert(100, "c", "f").amount == pytest.approx(212.0)
    assert units.convert(-40, "f", "c").amount == pytest.approx(-40.0)
    assert units.convert(0, "c", "k").amount == pytest.approx(273.15)
    # The bug this guards: treating degF as a scale factor would make 0 degC = 0 degF.
    assert units.convert(0, "c", "f").amount != 0.0


def test_to_canonical_picks_the_dimension_for_you():
    assert units.to_canonical(2, "acre").unit == "m2"
    assert units.to_canonical(2, "lb").unit == "kg"
    assert isinstance(units.to_canonical(2, "furlong"), Refusal)


# -------------------------------------------------------------------- refusals

def test_cross_dimension_conversion_is_refused():
    """kg -> l needs a density: a property of the substance, not of the units."""
    result = units.convert(1, "kg", "l")
    assert isinstance(result, Refusal)
    assert "cross-dimension" in result.reason
    assert "mass" in result.reason and "volume" in result.reason


def test_unknown_units_refuse_on_either_side():
    assert isinstance(units.convert(1, "smoot", "m"), Refusal)
    assert isinstance(units.convert(1, "m", "smoot"), Refusal)


def test_missing_amount_refuses_rather_than_defaulting_to_zero():
    result = units.convert(None, "acre", "m2")
    assert isinstance(result, Refusal)
    assert "no amount" in result.reason


def test_refusal_never_carries_a_number():
    result = units.convert(1, "kg", "l")
    assert not hasattr(result, "amount")


# ---------------------------------------------------------------------- ratios

def test_convert_ratio_composes_both_sides_with_all_citations():
    """1 t/ha -> lb/acre. Both halves convert; both citations survive."""
    result = units.convert_ratio(1.0, "t", "ha", "lb", "acre")
    assert isinstance(result, Converted)
    # 1000 kg/ha = 2204.62... lb / 2.47105... acre
    assert result.amount == pytest.approx(892.1791, rel=1e-4)
    assert result.unit == "lb/acre"
    assert len(result.conversion_provenance) >= 2


def test_convert_ratio_identity():
    result = units.convert_ratio(42.0, "kg", "ha", "kg", "ha")
    assert isinstance(result, Converted)
    assert result.amount == pytest.approx(42.0)


def test_convert_ratio_reports_which_half_refused():
    numerator_bad = units.convert_ratio(1.0, "kg", "ha", "l", "acre")
    assert isinstance(numerator_bad, Refusal)
    assert numerator_bad.reason.startswith("ratio numerator")

    denominator_bad = units.convert_ratio(1.0, "kg", "kg", "kg", "acre")
    assert isinstance(denominator_bad, Refusal)
    assert denominator_bad.reason.startswith("ratio denominator")


# ----------------------------------------------------------------------- money

def test_minor_units_round_trip():
    assert units.to_minor_units(12.34, "USD") == 1234
    assert units.to_minor_units(12.345, "USD") == 1235   # half away from zero
    assert units.to_minor_units(-12.345, "USD") == -1235
    assert units.to_minor_units(500, "JPY") == 500       # zero-exponent currency
    assert units.from_minor_units(1234, "USD").amount == pytest.approx(12.34)


def test_unknown_currency_refuses():
    assert isinstance(units.to_minor_units(1.0, "XYZ"), Refusal)
    assert isinstance(units.from_minor_units(100, None), Refusal)


def test_money_conversion_requires_a_dated_cited_rate():
    """An FX rate is an observation, not a definition. No rate table lives here."""
    no_rate = units.convert_money(1000, "USD", "TRY")
    assert isinstance(no_rate, Refusal)
    assert "dated FX rate" in no_rate.reason

    uncited = units.convert_money(1000, "USD", "TRY", rate=34.0)
    assert isinstance(uncited, Refusal)
    assert "without a source" in uncited.reason

    cited = units.convert_money(1000, "USD", "TRY", rate=34.0, rate_citation="ECB 2026-07-28")
    assert isinstance(cited, Converted)
    assert cited.amount == 34000
    assert cited.conversion_provenance == ("ECB 2026-07-28",)


def test_same_currency_conversion_needs_no_rate():
    result = units.convert_money(1000, "usd", "USD")
    assert isinstance(result, Converted)
    assert result.amount == 1000


# ------------------------------------------------------------------ boundaries

def test_module_is_framework_free():
    """Pure logic modules must stay importable without FastAPI or SQLAlchemy."""
    source = (units.__file__ or "")
    assert source.endswith("units.py")
    text = open(source).read()
    for forbidden in ("import fastapi", "from fastapi", "import sqlalchemy", "from sqlalchemy"):
        assert forbidden not in text
