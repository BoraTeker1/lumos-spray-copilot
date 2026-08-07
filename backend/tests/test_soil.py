"""Soil interpretation and nutrient budgeting: the refusals are the contract.

Both modules ship with EMPTY sources, so on today's data every entry point refuses. That
is the designed state, and these tests pin the two things that could quietly erode it:
that a refusal is returned rather than a defaulted value, and that the two modules differ
in *when* they refuse — soil per-analyte, fertilization all-or-nothing — for the stated
reason rather than by accident.

Populated cases are tested against SYNTHETIC tables built here, following
`tests/test_backtest.py`'s treatment of the Botrytis thresholds: the arithmetic can be
proven correct without anyone inventing a real agronomic number and leaving it in the
shipped source.
"""
from datetime import date

import pytest

from app import fertilization, nutrient_tables, soil, soil_thresholds
from app.refusal import (
    NO_DATA_FOR_FARM,
    NO_SOURCE_TRANSCRIBED,
    OUTSIDE_SOURCE_SCOPE,
    Refusal,
)
from app.transcription import Citation

CITATION = Citation(
    document="SYNTHETIC — test fixture, not an agronomic source",
    publisher="tests/test_soil.py",
    section="fixture",
    snippet="values invented for arithmetic testing only",
    transcribed_by="test suite",
    transcribed_on=date(2026, 8, 7),
)


def _threshold(analyte, soil_class, lower, upper, *, method="bray", crop="strawberry"):
    return soil_thresholds.SoilThreshold(
        analyte=analyte, method=method, crop=crop, soil_class=soil_class,
        lower_inclusive=lower, upper_exclusive=upper, citation=CITATION,
    )


# --------------------------------------------------------------- shipped state
def test_the_shipped_soil_thresholds_are_empty():
    """If this fails, someone transcribed real thresholds — or invented them."""
    assert soil_thresholds.TRANSCRIBED == ()


def test_the_shipped_nutrient_table_is_empty():
    assert nutrient_tables.TRANSCRIBED == ()


def test_soil_refuses_with_no_thresholds_rather_than_guessing():
    result = soil.interpret(
        [soil.AnalyteReading("ph", 6.2, "bray")], crop="strawberry"
    )
    assert isinstance(result, Refusal)
    assert result.code == NO_SOURCE_TRANSCRIBED
    assert "app/soil_thresholds.py" in result.detail


def test_fertilization_refuses_with_no_rates_rather_than_guessing():
    result = fertilization.budget(
        crop="strawberry", expected_yield_tonnes=40.0, nutrients=("nitrogen",)
    )
    assert isinstance(result, Refusal)
    assert result.code == NO_SOURCE_TRANSCRIBED


# ------------------------------------------------- soil: per-analyte behaviour
def test_soil_interprets_against_a_transcribed_band(monkeypatch):
    monkeypatch.setattr(soil_thresholds, "TRANSCRIBED", (
        _threshold("ph", "low", None, 6.0),
        _threshold("ph", "adequate", 6.0, 7.0),
        _threshold("ph", "high", 7.0, None),
    ))
    result = soil.interpret([soil.AnalyteReading("ph", 6.2, "bray")], crop="strawberry")

    assert not isinstance(result, Refusal)
    assert result.analytes[0].soil_class == "adequate"
    assert result.interpreted_count == 1


def test_a_missing_analyte_threshold_does_not_block_the_others(monkeypatch):
    """The deliberate departure from all-or-nothing — see the soil.py docstring.

    Nothing is summed here, so a partial panel understates nothing; each answered
    analyte is still correct on its own.
    """
    monkeypatch.setattr(soil_thresholds, "TRANSCRIBED", (
        _threshold("ph", "adequate", 6.0, 7.0),
    ))
    result = soil.interpret([
        soil.AnalyteReading("ph", 6.2, "bray"),
        soil.AnalyteReading("potassium_ppm", 180.0, "bray"),
    ], crop="strawberry")

    assert result.interpreted_count == 1
    uninterpreted = [a for a in result.analytes if not a.interpreted]
    assert uninterpreted[0].analyte == "potassium_ppm"
    assert uninterpreted[0].refusal.code == OUTSIDE_SOURCE_SCOPE


def test_the_extraction_method_must_match(monkeypatch):
    """Bray-P and Olsen-P are different assays; a threshold is tied to its method."""
    monkeypatch.setattr(soil_thresholds, "TRANSCRIBED", (
        _threshold("phosphorus_ppm", "adequate", 15.0, 30.0, method="bray"),
    ))
    result = soil.interpret(
        [soil.AnalyteReading("phosphorus_ppm", 18.0, "olsen")], crop="strawberry"
    )
    assert result.analytes[0].refusal.code == OUTSIDE_SOURCE_SCOPE
    assert "olsen" in result.analytes[0].refusal.detail.lower()


def test_the_crop_must_match(monkeypatch):
    monkeypatch.setattr(soil_thresholds, "TRANSCRIBED", (
        _threshold("ph", "adequate", 6.0, 7.0, crop="strawberry"),
    ))
    result = soil.interpret([soil.AnalyteReading("ph", 6.2, "bray")], crop="tomato")
    assert result.analytes[0].refusal.code == OUTSIDE_SOURCE_SCOPE


def test_a_value_past_the_end_of_the_table_refuses_rather_than_extrapolating(monkeypatch):
    monkeypatch.setattr(soil_thresholds, "TRANSCRIBED", (
        _threshold("ph", "adequate", 6.0, 7.0),
    ))
    result = soil.interpret([soil.AnalyteReading("ph", 9.5, "bray")], crop="strawberry")
    assert result.analytes[0].refusal.code == OUTSIDE_SOURCE_SCOPE
    assert "extrapolation" in result.analytes[0].refusal.detail


def test_a_soil_assessment_carries_no_aggregate_score(monkeypatch):
    """A 'soil score' would be an average across analytes with no agronomic meaning."""
    monkeypatch.setattr(soil_thresholds, "TRANSCRIBED", (
        _threshold("ph", "adequate", 6.0, 7.0),
    ))
    payload = soil.interpret(
        [soil.AnalyteReading("ph", 6.2, "bray")], crop="strawberry"
    ).as_payload()

    for forbidden in ("score", "index", "overall", "grade", "rating"):
        assert not any(forbidden in key.lower() for key in payload), forbidden


def test_no_readings_refuses_as_a_farm_data_gap_not_a_source_gap(monkeypatch):
    """The two refusals send the reader to different people — keep them distinct."""
    monkeypatch.setattr(soil_thresholds, "TRANSCRIBED", (
        _threshold("ph", "adequate", 6.0, 7.0),
    ))
    result = soil.interpret([], crop="strawberry")
    assert result.code == NO_DATA_FOR_FARM


# ------------------------------------------- fertilization: all-or-nothing
def _rate(nutrient, kg, *, crop="strawberry", variety=None):
    return nutrient_tables.RemovalRate(
        nutrient=nutrient, crop=crop, kg_removed_per_tonne_yield=kg,
        yield_basis="tonnes fresh fruit (SYNTHETIC)", variety=variety, citation=CITATION,
    )


def test_removal_is_rate_times_yield(monkeypatch):
    monkeypatch.setattr(nutrient_tables, "TRANSCRIBED", (_rate("nitrogen", 2.5),))
    result = fertilization.budget(
        crop="strawberry", expected_yield_tonnes=40.0, nutrients=("nitrogen",)
    )
    assert result.removals[0].kg_removed == pytest.approx(100.0)
    assert result.removals[0].rate_used_kg_per_tonne == 2.5


def test_one_missing_nutrient_refuses_the_whole_budget(monkeypatch):
    """All-or-nothing, unlike soil: a partial budget reads as a complete answer."""
    monkeypatch.setattr(nutrient_tables, "TRANSCRIBED", (_rate("nitrogen", 2.5),))
    result = fertilization.budget(
        crop="strawberry", expected_yield_tonnes=40.0,
        nutrients=("nitrogen", "potassium"),
    )
    assert isinstance(result, Refusal)
    assert result.code == OUTSIDE_SOURCE_SCOPE
    assert result.context["missing_nutrients"] == ["potassium"]


def test_a_variety_specific_rate_wins_over_the_crop_general_one(monkeypatch):
    monkeypatch.setattr(nutrient_tables, "TRANSCRIBED", (
        _rate("nitrogen", 2.5),
        _rate("nitrogen", 3.1, variety="Albion"),
    ))
    result = fertilization.budget(
        crop="strawberry", expected_yield_tonnes=10.0,
        nutrients=("nitrogen",), variety="Albion",
    )
    assert result.removals[0].rate_used_kg_per_tonne == 3.1


def test_another_varietys_rate_is_never_borrowed(monkeypatch):
    """No fuzzy agronomic matching — the crop-general rate is used, not Albion's."""
    monkeypatch.setattr(nutrient_tables, "TRANSCRIBED", (
        _rate("nitrogen", 2.5),
        _rate("nitrogen", 3.1, variety="Albion"),
    ))
    result = fertilization.budget(
        crop="strawberry", expected_yield_tonnes=10.0,
        nutrients=("nitrogen",), variety="Monterey",
    )
    assert result.removals[0].rate_used_kg_per_tonne == 2.5


def test_missing_expected_yield_refuses_rather_than_assuming_one(monkeypatch):
    monkeypatch.setattr(nutrient_tables, "TRANSCRIBED", (_rate("nitrogen", 2.5),))
    result = fertilization.budget(
        crop="strawberry", expected_yield_tonnes=None, nutrients=("nitrogen",)
    )
    assert isinstance(result, Refusal)
    assert result.code == NO_DATA_FOR_FARM


def test_a_budget_never_states_an_application_rate(monkeypatch):
    """Removal is a fact about the crop; an application rate is advice about an input."""
    monkeypatch.setattr(nutrient_tables, "TRANSCRIBED", (_rate("nitrogen", 2.5),))
    payload = fertilization.budget(
        crop="strawberry", expected_yield_tonnes=40.0, nutrients=("nitrogen",)
    ).as_payload()

    flat = str(payload).lower()
    assert "apply_kg" not in flat
    assert "application_rate" in payload["not_calculated"]
    for removal in payload["removals"]:
        assert "apply" not in " ".join(removal.keys())


# ------------------------------------------------------ transcription contract
def test_both_sources_meet_the_transcription_contract():
    from app import transcription

    for module in ("app.soil_thresholds", "app.nutrient_tables"):
        status = transcription.status_of(module)
        assert status.primary_source
        assert not status.populated


def test_a_removal_rate_without_a_yield_basis_is_refused_at_import_time():
    """Per tonne of FRESH fruit vs DRY matter differ by ~an order of magnitude."""
    with pytest.raises(ValueError, match="yield_basis is blank"):
        nutrient_tables.RemovalRate(
            nutrient="nitrogen", crop="strawberry",
            kg_removed_per_tonne_yield=2.5, yield_basis="  ", citation=CITATION,
        )


def test_a_soil_threshold_without_a_method_is_refused_at_import_time():
    with pytest.raises(ValueError, match="extraction method is blank"):
        soil_thresholds.SoilThreshold(
            analyte="phosphorus_ppm", method="", crop="strawberry",
            soil_class="adequate", lower_inclusive=15.0, upper_exclusive=30.0,
            citation=CITATION,
        )
