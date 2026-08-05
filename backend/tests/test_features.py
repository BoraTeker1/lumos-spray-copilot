"""The feature layer: the abstain-or-value invariant, and six features that use it.

The thing being defended here is narrow and important. A derived farm metric that
returns `0` when it means "no data" is not a bug that shows up as a wrong number — it
shows up as a CLAIM. `0 kg/ha of active ingredient` reads as "this farm sprayed
nothing", and `moa_rotation_diversity = 1.0` computed over the three applications that
happened to have a MoA group recorded reads as "perfect rotation".

So every feature here abstains rather than defaulting, the type makes
value-plus-abstention unrepresentable, and the two all-or-nothing features refuse a
partial answer specifically because partial answers here are biased in the flattering
direction.
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.features import base, pest, pit_view, weather
from app.features.base import FeatureError, FeatureResult
from app.ingest import domains

AS_OF = datetime(2026, 7, 8, 6, 0, 0)


def obs(id=1, observed_at=None, recorded_at=None, **kw):
    observed_at = observed_at or AS_OF - timedelta(hours=1)
    base_row = {
        "id": id, "observed_at": observed_at,
        "recorded_at": recorded_at if recorded_at is not None else observed_at,
        "temperature_c": 15.0, "relative_humidity_pct": 92.0,
        "leaf_wetness_minutes": None, "wetness_is_measured": None,
        "quality_flag": None, "supersedes_id": None,
        "data_source": "provider_api", "data_confidence": "provider_reported",
    }
    base_row.update(kw)
    return SimpleNamespace(**base_row)


def spray(id=1, application_date=None, created_at=None, **kw):
    application_date = application_date or (AS_OF - timedelta(days=5)).date()
    base_row = {
        "id": id, "application_date": application_date,
        "created_at": created_at or datetime.combine(application_date, datetime.min.time()),
        "product_name": "Switch 62.5WG", "epa_reg_no": "100-953",
        "moa_group": "9/12", "rate_amount": 14.0, "rate_unit": "oz/acre",
        "treated_acres": 4.0, "treated_area_unit": "acres",
        "data_source": "manual_entry", "data_confidence": "user_provided",
    }
    base_row.update(kw)
    return SimpleNamespace(**base_row)


def sample(id=1, observed_at=None, recorded_at=None, **kw):
    observed_at = observed_at or AS_OF - timedelta(days=3)
    base_row = {
        "id": id, "observed_at": observed_at,
        "recorded_at": recorded_at if recorded_at is not None else observed_at,
        "quality_flag": None, "supersedes_id": None,
        "data_source": "manual_entry", "data_confidence": "user_provided",
    }
    base_row.update(kw)
    return SimpleNamespace(**base_row)


# --------------------------------------------------------------------------
# The invariant.
# --------------------------------------------------------------------------


def test_a_feature_result_is_abstained_if_and_only_if_it_has_no_value():
    """The single line that makes every downstream surface safe.

    Without it the natural bug is a feature returning 0.0 for "no data", and a card
    rendering that as a real measurement. The type refuses to represent the confusion.
    """
    with pytest.raises(FeatureError, match="if and only if"):
        FeatureResult(value=1.0, abstained=True, reasons=("x",))
    with pytest.raises(FeatureError, match="if and only if"):
        FeatureResult(value=None, abstained=False)


def test_an_abstention_must_say_why():
    with pytest.raises(FeatureError, match="must say why"):
        FeatureResult(value=None, abstained=True)


def test_an_abstention_payload_carries_no_value_key_at_all():
    """An absent key, not a null one.

    A null in a numeric field is precisely what a template turns into `0` or `--`.
    Omitting the key forces a caller to handle the abstention branch explicitly.
    """
    payload = FeatureResult.abstain("no_station_configured_for_this_field").as_payload()
    assert "value" not in payload
    assert payload["abstained"] is True
    assert payload["reasons"] == ["no_station_configured_for_this_field"]


def test_every_registered_feature_obeys_the_invariant_over_empty_inputs():
    """A loop over the registry, so a feature added next year is covered automatically."""
    empty = {
        "observations": [], "applications": [], "samples": [],
        "planted_area_ha": None, "concentrations": {}, "as_of": AS_OF,
    }
    for spec in base.REGISTRY.values():
        result = spec.compute(**empty)
        assert isinstance(result, FeatureResult)
        assert result.abstained == (result.value is None), spec.name
        if result.abstained:
            assert result.reasons, f"{spec.name} abstained without a reason"


# --------------------------------------------------------------------------
# The finance boundary, mechanism (2).
# --------------------------------------------------------------------------


def test_a_feature_in_a_deferred_finance_domain_cannot_be_registered():
    """The guardrail as a line of code rather than a paragraph.

    This is the failure mode the whole domain registry exists for: not a malicious
    credit model, but someone adding `debt_service_capacity` because it was easy, in a
    session where nobody re-read ENGINEERING_GUIDELINES.md §4.
    """
    with pytest.raises(FeatureError, match="not an MVP domain"):
        base.register(
            base.FeatureSpec(
                name="debt_service_capacity", version=1,
                entity_type=base.ENTITY_CROP_CYCLE, domain="credit_scoring",
                unit="ratio", description="", compute=lambda **_: None,
            )
        )


def test_the_registration_refusal_quotes_the_guardrail():
    with pytest.raises(FeatureError, match="credit scoring"):
        base.register(
            base.FeatureSpec(
                name="probe_underwrite", version=1, entity_type=base.ENTITY_FARM,
                domain="credit_scoring", unit=None, description="",
                compute=lambda **_: None,
            )
        )


def test_every_registered_feature_is_in_an_mvp_domain():
    for spec in base.REGISTRY.values():
        assert spec.domain in domains.MVP_DOMAINS, spec.name


def test_resolve_order_detects_a_cycle():
    """No feature declares a dependency today; the detector is here so the first cyclic
    pair fails by name at registration rather than as a recursion error later."""
    a = base.FeatureSpec("a", 1, base.ENTITY_FARM, "climate", None, "", lambda **_: None,
                         depends_on=("b",))
    b = base.FeatureSpec("b", 1, base.ENTITY_FARM, "climate", None, "", lambda **_: None,
                         depends_on=("a",))
    with pytest.raises(FeatureError, match="cycle"):
        base.resolve_order([a, b])


# --------------------------------------------------------------------------
# Weather features.
# --------------------------------------------------------------------------


def test_coverage_abstains_with_no_station_but_reports_a_true_zero_with_one():
    """The one place a zero is not a lie, and the abstention that protects it."""
    assert weather.weather_observation_coverage_pct(
        observations=[], as_of=AS_OF
    ).reasons == (weather.NO_STATION_CONFIGURED,)

    # A station IS configured and returned readings, but all outside the window.
    old = [obs(id=1, observed_at=AS_OF - timedelta(days=30))]
    result = weather.weather_observation_coverage_pct(
        observations=old, as_of=AS_OF, window_hours=24
    )
    assert result.abstained is False
    assert result.value == 0.0


def test_coverage_counts_distinct_hours_in_the_window():
    rows = [obs(id=i, observed_at=AS_OF - timedelta(hours=i)) for i in range(1, 13)]
    result = weather.weather_observation_coverage_pct(
        observations=rows, as_of=AS_OF, window_hours=24
    )
    assert result.value == pytest.approx(50.0)


def test_staleness_abstains_rather_than_returning_a_large_number():
    """'9999 hours stale' and 'no data at all' are different facts."""
    result = weather.weather_data_staleness_hours(observations=[], as_of=AS_OF)
    assert result.abstained
    assert result.reasons == (weather.NO_ADMISSIBLE_WEATHER,)


def test_staleness_measures_from_the_most_recent_admissible_reading():
    rows = [
        obs(id=1, observed_at=AS_OF - timedelta(hours=10)),
        obs(id=2, observed_at=AS_OF - timedelta(hours=3)),
    ]
    result = weather.weather_data_staleness_hours(observations=rows, as_of=AS_OF)
    assert result.value == pytest.approx(3.0)


def test_leaf_wetness_abstains_permanently_on_cimis_shaped_data():
    """The honest centrepiece of this slice.

    CIMIS publishes no leaf-wetness item, so a CIMIS-only farm has no wetness datum and
    this feature says so by name rather than returning 0.0 — which would read as
    'no wetness occurred', the opposite of 'we cannot see wetness'.
    """
    cimis_rows = [obs(id=i, observed_at=AS_OF - timedelta(hours=i)) for i in range(1, 5)]
    result = weather.leaf_wetness_hours(observations=cimis_rows, as_of=AS_OF)
    assert result.abstained
    assert result.reasons == (weather.NO_MEASURED_LEAF_WETNESS,)
    assert result.value is None


def test_leaf_wetness_abstains_wholesale_when_any_row_is_derived_rather_than_measured():
    """It must not drop the derived rows and total the rest.

    That would report a real number computed over an arbitrary subset, which reads as a
    complete measurement of wetness hours.
    """
    rows = [
        obs(id=1, observed_at=AS_OF - timedelta(hours=1),
            leaf_wetness_minutes=60.0, wetness_is_measured=True),
        obs(id=2, observed_at=AS_OF - timedelta(hours=2),
            leaf_wetness_minutes=45.0, wetness_is_measured=False),
    ]
    result = weather.leaf_wetness_hours(observations=rows, as_of=AS_OF)
    assert result.abstained
    assert result.reasons == (weather.DERIVED_WETNESS_PRESENT,)


def test_leaf_wetness_totals_measured_hours_when_a_sensor_exists():
    """The path an on-site sensor would unlock — which is the procurement decision this
    slice turns from a vague blocker into a named one."""
    rows = [
        obs(id=1, observed_at=AS_OF - timedelta(hours=1),
            leaf_wetness_minutes=60.0, wetness_is_measured=True),
        obs(id=2, observed_at=AS_OF - timedelta(hours=2),
            leaf_wetness_minutes=30.0, wetness_is_measured=True),
    ]
    result = weather.leaf_wetness_hours(observations=rows, as_of=AS_OF)
    assert result.value == pytest.approx(1.5)
    assert result.unit == "h"


def test_no_weather_feature_reads_relative_humidity():
    """Structural guard against the tempting derivation.

    Deriving wetness from RH would need a cited source `disease_risk` does not have.
    No climate feature may touch the humidity column at all.
    """
    import inspect

    source = inspect.getsource(weather)
    assert "relative_humidity_pct" not in source.replace(
        '"relative_humidity_pct": 92.0', ""
    )


# --------------------------------------------------------------------------
# Crop-protection features.
# --------------------------------------------------------------------------


CONCENTRATIONS = {"100-953": (62.5, "%w/w")}


def test_ai_kg_per_ha_abstains_when_any_application_refuses_and_names_which():
    """All-or-nothing, and the reason is a bias argument rather than a purity one.

    A total omitting three of eleven applications is not approximate, it is SMALLER.
    Someone reading it has no way to know, and the error runs in the flattering
    direction on a pesticide-reduction number.
    """
    applications = [
        spray(id=1),
        spray(id=2, product_name="Unknown Fungicide", epa_reg_no="99999-1"),
    ]
    result = pest.active_ingredient_kg_per_ha(
        applications=applications, planted_area_ha=1.62,
        concentrations=CONCENTRATIONS, as_of=AS_OF,
    )
    assert result.abstained
    assert result.value is None
    assert any("Unknown Fungicide" in r for r in result.reasons)
    assert any("concentration" in r for r in result.reasons)


def test_ai_kg_per_ha_abstains_without_a_planted_area():
    result = pest.active_ingredient_kg_per_ha(
        applications=[spray()], planted_area_ha=None,
        concentrations=CONCENTRATIONS, as_of=AS_OF,
    )
    assert result.reasons == (pest.NO_PLANTED_AREA,)


def test_ai_kg_per_ha_computes_when_every_application_resolves():
    result = pest.active_ingredient_kg_per_ha(
        applications=[spray(id=1)], planted_area_ha=1.62,
        concentrations=CONCENTRATIONS, as_of=AS_OF,
    )
    assert not result.abstained
    assert result.unit == "kg/ha"
    assert result.value > 0


def test_moa_diversity_abstains_rather_than_scoring_the_subset_that_has_moa_recorded():
    """Partial scoring here is biased toward flattering, not merely incomplete.

    The applications most likely to be missing a MoA group are the carelessly logged
    ones, which are disproportionately repeat sprays of a familiar product — exactly
    the ones that would drag diversity down.
    """
    applications = [
        spray(id=1, moa_group="9"),
        spray(id=2, moa_group="12"),
        spray(id=3, moa_group=None),
    ]
    result = pest.moa_rotation_diversity(applications=applications, as_of=AS_OF)
    assert result.abstained
    assert "1 of 3" in result.reasons[0]
    # The flattering answer this refuses to give:
    assert result.value is None


def test_moa_diversity_scores_a_fully_recorded_set():
    applications = [
        spray(id=1, moa_group="9"),
        spray(id=2, moa_group="12"),
        spray(id=3, moa_group="9"),
    ]
    result = pest.moa_rotation_diversity(applications=applications, as_of=AS_OF)
    assert result.value == pytest.approx(2 / 3, abs=1e-4)


def test_moa_diversity_needs_at_least_two_applications():
    result = pest.moa_rotation_diversity(applications=[spray(id=1)], as_of=AS_OF)
    assert result.reasons == (pest.TOO_FEW_APPLICATIONS_TO_ROTATE,)


def test_scouting_recency_reports_the_number_and_no_verdict():
    """It must NOT re-declare disease_risk.MAX_SCOUTING_AGE_DAYS.

    A second copy of that threshold would drift from the pilot's assessment contract
    the first time either moved.
    """
    import inspect

    result = pest.scouting_recency_days(
        samples=[sample(id=1, observed_at=AS_OF - timedelta(days=4))], as_of=AS_OF
    )
    assert result.value == pytest.approx(4.0)
    assert result.evidence_grade is None

    source = inspect.getsource(pest)
    assert "MAX_SCOUTING_AGE_DAYS" not in source.replace(
        "disease_risk.MAX_SCOUTING_AGE_DAYS", ""
    ) or "14" not in source


def test_scouting_recency_abstains_with_no_sample():
    result = pest.scouting_recency_days(samples=[], as_of=AS_OF)
    assert result.reasons == (pest.NO_SCOUTING_SAMPLE,)


# --------------------------------------------------------------------------
# pit_view: the hindsight rule reaching spray records for the first time.
# --------------------------------------------------------------------------


def test_a_spray_gets_the_two_timestamps_it_never_had():
    row = spray(id=7, application_date=datetime(2026, 7, 1).date(),
                created_at=datetime(2026, 7, 3, 9, 30))
    view = pit_view.spray_view(row)
    assert view.observed_at == datetime(2026, 7, 1, 0, 0)
    assert view.recorded_at == datetime(2026, 7, 3, 9, 30)
    assert view.source is row


def test_a_spray_keyed_in_late_is_excluded_from_an_earlier_as_of():
    """A spray entered Friday about Tuesday is hindsight at a Wednesday as_of.

    This will occasionally surprise someone, and it is correct: a pesticide-use figure
    that includes applications entered after the fact is not one anyone could have
    acted on.
    """
    from app import pit

    tuesday = datetime(2026, 7, 7)
    friday = datetime(2026, 7, 10, 16, 0)
    late = spray(id=1, application_date=tuesday.date(), created_at=friday)
    view = pit_view.spray_view(late)

    wednesday = datetime(2026, 7, 8)
    assert pit.admissible(view, wednesday, set()) == pit.EXCLUDED_RECORDED_LATE
    # And by the following Monday it is admissible.
    assert pit.admissible(view, datetime(2026, 7, 13), set()) is None


def test_the_ai_feature_excludes_a_late_entered_application_from_its_total():
    """The rule reaching a real number, not just a view object."""
    on_time = spray(id=1, application_date=(AS_OF - timedelta(days=5)).date(),
                    created_at=AS_OF - timedelta(days=5))
    late = spray(id=2, application_date=(AS_OF - timedelta(days=4)).date(),
                 created_at=AS_OF + timedelta(days=2), epa_reg_no="99999-1")

    # The late row would have forced an abstention if it were visible ...
    with_late = pest.active_ingredient_kg_per_ha(
        applications=[on_time, late], planted_area_ha=1.62,
        concentrations=CONCENTRATIONS, as_of=AS_OF + timedelta(days=3),
    )
    assert with_late.abstained

    # ... but at an as_of before it was recorded, it is correctly invisible.
    at_the_time = pest.active_ingredient_kg_per_ha(
        applications=[on_time, late], planted_area_ha=1.62,
        concentrations=CONCENTRATIONS, as_of=AS_OF,
    )
    assert not at_the_time.abstained


# --------------------------------------------------------------------------
# Structural: a pesticide recommendation stays inexpressible.
# --------------------------------------------------------------------------


def test_a_pesticide_recommendation_stays_structurally_inexpressible():
    """`FeatureResult` has no product, rate or action field, and cannot acquire one
    without a visible change here. A readiness number must never become a spray prompt."""
    fields = set(FeatureResult.__dataclass_fields__)
    forbidden = {"product", "rate", "dose", "apply", "spray", "tank", "mix",
                 "recommendation", "action"}
    assert not (fields & forbidden)
    for name in fields:
        assert not any(f in name.lower() for f in forbidden), name
