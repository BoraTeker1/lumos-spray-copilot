"""Seed selection, irrigation, and land tenure.

Same discipline as `test_soil.py`: shipped sources are empty so every entry point
refuses today, and the populated cases run against SYNTHETIC tables built here rather
than real agronomic numbers left in the shipped modules.

The tests worth reading are the ones pinning behaviour that a later change would find
tempting to "improve": that varieties are never ranked, that a Kc is never borrowed from
an adjacent growth stage, and that an undated lease is never treated as perpetual.
"""
from dataclasses import dataclass
from datetime import date

import pytest

from app import (
    irrigation,
    irrigation_coefficients,
    land_selection,
    seed_selection,
    variety_table,
)
from app.refusal import NO_DATA_FOR_FARM, NO_SOURCE_TRANSCRIBED, OUTSIDE_SOURCE_SCOPE, Refusal
from app.transcription import Citation

CITATION = Citation(
    document="SYNTHETIC — test fixture, not an agronomic source",
    publisher="tests/test_agronomy.py",
    section="fixture",
    snippet="values invented for arithmetic testing only",
    transcribed_by="test suite",
    transcribed_on=date(2026, 8, 7),
)


# --------------------------------------------------------------- shipped state
def test_every_agronomic_source_ships_empty():
    assert variety_table.TRANSCRIBED == ()
    assert irrigation_coefficients.TRANSCRIBED == ()


# ------------------------------------------------------------- seed selection
def _rating(variety, rating, *, trait="botrytis", scale="1-5 field", conditions="Watsonville 2025"):
    return variety_table.TraitRating(
        variety=variety, crop="strawberry", trait=trait, rating=rating,
        rating_scale=scale, trial_conditions=conditions, citation=CITATION,
    )


def test_variety_traits_refuse_with_no_transcribed_trials():
    result = seed_selection.traits_for(variety="Albion", crop="strawberry")
    assert isinstance(result, Refusal)
    assert result.code == NO_SOURCE_TRANSCRIBED


def test_traits_are_returned_with_their_trial_attached(monkeypatch):
    monkeypatch.setattr(variety_table, "TRANSCRIBED", (_rating("Albion", "resistant"),))
    traits = seed_selection.traits_for(variety="Albion", crop="strawberry")

    assert traits[0].rating == "resistant"
    assert traits[0].trial_conditions == "Watsonville 2025"
    assert traits[0].source_document.startswith("SYNTHETIC")


def test_same_scale_and_conditions_are_comparable(monkeypatch):
    monkeypatch.setattr(variety_table, "TRANSCRIBED", (
        _rating("Albion", "resistant"),
        _rating("Monterey", "intermediate"),
    ))
    result = seed_selection.compare(
        varieties=("Albion", "Monterey"), crop="strawberry", trait="botrytis"
    )
    assert result.comparable is True
    assert result.incomparable_reason is None


def test_different_scales_are_reported_as_not_comparable(monkeypatch):
    """Ranking across incommensurable scales is how a variety wins on a generous rater."""
    monkeypatch.setattr(variety_table, "TRANSCRIBED", (
        _rating("Albion", "resistant", scale="1-5 field"),
        _rating("Monterey", "resistant", scale="1-9 greenhouse"),
    ))
    result = seed_selection.compare(
        varieties=("Albion", "Monterey"), crop="strawberry", trait="botrytis"
    )
    assert result.comparable is False
    assert "different scales" in result.incomparable_reason


def test_different_trial_conditions_are_reported_as_not_comparable(monkeypatch):
    monkeypatch.setattr(variety_table, "TRANSCRIBED", (
        _rating("Albion", "resistant", conditions="Watsonville 2025"),
        _rating("Monterey", "resistant", conditions="Florida 2024 plasticulture"),
    ))
    result = seed_selection.compare(
        varieties=("Albion", "Monterey"), crop="strawberry", trait="botrytis"
    )
    assert result.comparable is False
    assert "different conditions" in result.incomparable_reason


def test_a_comparison_never_ranks_or_recommends(monkeypatch):
    monkeypatch.setattr(variety_table, "TRANSCRIBED", (
        _rating("Albion", "resistant"),
        _rating("Monterey", "susceptible"),
    ))
    payload = seed_selection.compare(
        varieties=("Albion", "Monterey"), crop="strawberry", trait="botrytis"
    ).as_payload()

    # Assert on KEYS, not on flattened prose: the not_calculated disclosure legitimately
    # contains the word "ranked", and a substring scan over the whole payload would
    # forbid explaining the very thing it is checking for.
    keys = set(payload) | {k for v in payload["varieties"] for k in v}
    for forbidden in ("best", "recommended", "rank", "winner", "score", "order"):
        assert not any(forbidden in key.lower() for key in keys), forbidden

    assert "ranking" in payload["not_calculated"]
    # And no implicit ranking by ordering: the susceptible variety is not sorted last.
    assert [v["variety"] for v in payload["varieties"]] == ["Albion", "Monterey"]


def test_a_rating_without_trial_conditions_is_refused_at_import_time():
    with pytest.raises(ValueError, match="trial_conditions is blank"):
        variety_table.TraitRating(
            variety="Albion", crop="strawberry", trait="botrytis", rating="resistant",
            rating_scale="1-5", trial_conditions="", citation=CITATION,
        )


# ----------------------------------------------------------------- irrigation
def _kc(stage, start, end, value):
    return irrigation_coefficients.CropCoefficient(
        crop="strawberry", growth_stage=stage, days_after_planting_from=start,
        days_after_planting_to=end, kc=value, citation=CITATION,
    )


def test_water_balance_refuses_without_a_transcribed_kc():
    result = irrigation.balance(
        crop="strawberry", days_after_planting=45, eto_mm=100.0,
        effective_rainfall_mm=10.0, applied_irrigation_mm=60.0,
    )
    assert isinstance(result, Refusal)
    assert result.code == NO_SOURCE_TRANSCRIBED


def test_etc_is_eto_times_kc(monkeypatch):
    monkeypatch.setattr(irrigation_coefficients, "TRANSCRIBED", (_kc("mid", 30, 90, 0.85),))
    result = irrigation.balance(
        crop="strawberry", days_after_planting=45, eto_mm=100.0,
        effective_rainfall_mm=10.0, applied_irrigation_mm=60.0,
    )
    assert result.etc_mm == pytest.approx(85.0)
    assert result.deficit_mm == pytest.approx(15.0)
    assert result.growth_stage == "mid"


def test_a_kc_is_never_borrowed_from_an_adjacent_stage(monkeypatch):
    """Kc varies through the season by a factor of two or more."""
    monkeypatch.setattr(irrigation_coefficients, "TRANSCRIBED", (_kc("mid", 30, 90, 0.85),))
    result = irrigation.coefficient_for(crop="strawberry", days_after_planting=15)
    assert isinstance(result, Refusal)
    assert result.code == OUTSIDE_SOURCE_SCOPE


def test_missing_rainfall_refuses_rather_than_defaulting_to_zero(monkeypatch):
    """Zero rainfall overstates the deficit — an error toward over-irrigating."""
    monkeypatch.setattr(irrigation_coefficients, "TRANSCRIBED", (_kc("mid", 30, 90, 0.85),))
    result = irrigation.balance(
        crop="strawberry", days_after_planting=45, eto_mm=100.0,
        effective_rainfall_mm=None, applied_irrigation_mm=60.0,
    )
    assert isinstance(result, Refusal)
    assert result.code == NO_DATA_FOR_FARM
    assert "effective_rainfall_mm" in result.context["missing"]


def test_a_water_balance_never_states_an_irrigation_amount(monkeypatch):
    monkeypatch.setattr(irrigation_coefficients, "TRANSCRIBED", (_kc("mid", 30, 90, 0.85),))
    payload = irrigation.balance(
        crop="strawberry", days_after_planting=45, eto_mm=100.0,
        effective_rainfall_mm=10.0, applied_irrigation_mm=60.0,
    ).as_payload()

    assert "apply_mm" not in str(payload)
    assert "irrigation_recommendation" in payload["not_calculated"]


def test_an_implausible_kc_is_refused_at_import_time():
    with pytest.raises(ValueError, match="physically plausible range"):
        _kc("mid", 30, 90, 12.0)


# ---------------------------------------------------------------- land tenure
@dataclass(frozen=True)
class FakeRight:
    tenure_type: str
    effective_from: date | None = None
    effective_to: date | None = None


@dataclass(frozen=True)
class FakeOverlap:
    overlap_area_m2: float | None
    determination_method: str = "declared"


AS_OF = date(2026, 8, 7)
HORIZON = date(2027, 6, 30)


def test_ownership_with_no_end_date_covers_any_horizon():
    result = land_selection.covers_horizon(
        [FakeRight("owned")], horizon_end=HORIZON, as_of=AS_OF
    )
    assert result.covers is True
    assert result.binding_expires_on is None


def test_an_undated_lease_refuses_rather_than_reading_as_perpetual():
    """The load-bearing refusal in this module.

    An absent end date means 'held indefinitely' for ownership and 'nobody recorded it'
    for a lease. Conflating them would report land as held through a horizon nobody has
    evidence for, and that claim flows into collateral and underwriting.
    """
    result = land_selection.covers_horizon(
        [FakeRight("leased")], horizon_end=HORIZON, as_of=AS_OF
    )
    assert isinstance(result, Refusal)
    assert result.code == land_selection.TENURE_END_DATE_UNRECORDED


def test_a_lease_expiring_inside_the_horizon_does_not_cover_it():
    result = land_selection.covers_horizon(
        [FakeRight("leased", effective_to=date(2027, 1, 31))],
        horizon_end=HORIZON, as_of=AS_OF,
    )
    assert result.covers is False
    assert result.binding_expires_on == date(2027, 1, 31)


def test_a_lease_beyond_the_horizon_covers_it():
    result = land_selection.covers_horizon(
        [FakeRight("leased", effective_to=date(2028, 1, 31))],
        horizon_end=HORIZON, as_of=AS_OF,
    )
    assert result.covers is True


def test_a_future_right_does_not_count_toward_todays_coverage():
    """A lease starting next year does not cover this season."""
    result = land_selection.covers_horizon(
        [FakeRight("leased", effective_from=date(2027, 1, 1),
                   effective_to=date(2029, 1, 1))],
        horizon_end=HORIZON, as_of=AS_OF,
    )
    assert isinstance(result, Refusal)
    assert result.code == NO_DATA_FOR_FARM


def test_parcel_coverage_sums_recorded_overlaps():
    result = land_selection.parcel_coverage(
        [FakeOverlap(4000.0), FakeOverlap(6000.0)], field_area_m2=10000.0
    )
    assert result.covered_area_m2 == 10000.0
    assert result.fully_covered is True


def test_a_partially_covered_field_is_reported_as_such():
    result = land_selection.parcel_coverage(
        [FakeOverlap(4000.0)], field_area_m2=10000.0
    )
    assert result.fully_covered is False
    assert result.covered_fraction == pytest.approx(0.4)


def test_an_unrecorded_overlap_area_refuses_rather_than_assuming(monkeypatch):
    """Assuming an unrecorded overlap covers the field overstates pledgeable collateral."""
    result = land_selection.parcel_coverage(
        [FakeOverlap(4000.0), FakeOverlap(None)], field_area_m2=10000.0
    )
    assert isinstance(result, Refusal)
    assert result.code == land_selection.OVERLAP_AREA_UNRECORDED
    assert result.context["unrecorded_count"] == 1
