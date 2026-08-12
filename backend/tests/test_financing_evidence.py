"""The lender evidence package: what is on record, and what is not.

The load-bearing tests are the ones asserting the package forms no credit opinion,
and that `present` can never be satisfied by an empty record. A package that counted
a refused metric as evidence would hand a lender a checklist of things that are not
actually there, which is worse than handing them nothing.
"""
from datetime import date
from types import SimpleNamespace

import pytest

from app import financing_evidence

TODAY = date(2026, 6, 1)


def _farm(**overrides):
    payload = {
        "id": 1, "name": "Golden Coast Strawberry Ranch",
        "location": "Watsonville, CA", "country": "US", "currency_code": "USD",
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def _cycle(**overrides):
    payload = {
        "id": 7, "crop": "strawberry", "season_label": "2026 season",
        "season_year": 2026,
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def _refused(code="no_sales_recorded", reason="Nothing is recorded."):
    return {"not_calculated": True, "code": code, "reason": reason}


def _closeout(**overrides):
    metrics = {
        "planted_area": {"value": 72843.0, "basis_text": "b"},
        "harvested_yield": {"value": 12000.0, "unit": "kg", "basis_text": "b"},
        "yield_per_area": {"per_hectare": 1647.0, "unit": "kg", "basis_text": "b"},
        "costs": {
            "total": 21000.0, "applications_counted": 4, "operations_counted": 3,
            "applications_without_cost": 0, "operations_without_cost": 0,
        },
        "cost_per_area": {"per_hectare": 2882.0, "unit": "USD", "basis_text": "b"},
        "revenue": {"net": 48000.0, "gross": 50000.0, "sales_counted": 2, "basis_text": "b"},
        "realised_price_per_yield_unit": {
            "value": 4.17, "unit": "USD/kg", "basis_text": "b",
        },
    }
    metrics.update(overrides.pop("metrics", {}))
    return {"crop_cycle_id": 7, "currency": "USD", "metrics": metrics, **overrides}


def _planned(**overrides):
    payload = {
        "id": 1, "review_required": True, "review_status": "approved",
        "outcome": "sprayed_as_planned", "decision_severity": "none",
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def _build(**overrides):
    kwargs = {
        "farm": _farm(), "cycle": _cycle(), "closeout": _closeout(),
        "performance": {"closed_season_count": 2},
        "decisions": [_planned()], "collateral_assets": [], "today": TODAY,
    }
    kwargs.update(overrides)
    return financing_evidence.build_package(**kwargs)


def _item(package, key):
    return next(i for i in package["items"] if i["key"] == key)


# ------------------------------------------------------- no credit opinion
def test_the_package_forms_no_credit_opinion():
    """Not a score, not a probability, not a rate. The lender decides."""
    package = _build()
    forbidden = {
        "approval_probability", "creditworthiness", "credit_score", "score",
        "interest_rate", "rate", "readiness_percentage", "grade", "rating",
        "recommendation", "likelihood",
    }
    assert not forbidden & set(package)
    assert "forms no credit opinion" in package["disclaimer"]


def test_readiness_is_a_count_of_records_not_a_percentage():
    package = _build()
    assert package["present_count"] + package["missing_count"] == package["total_count"]
    assert "not an assessment of creditworthiness" in package["basis_text"]
    assert "%" not in package["basis_text"]


# ------------------------------------------------------------ presence rules
def test_a_refused_metric_never_counts_as_present():
    """"There is a record that says nothing" must not read as evidence."""
    package = _build(closeout=_closeout(metrics={"revenue": _refused()}))
    assert _item(package, "revenue_record")["present"] is False


def test_a_missing_item_carries_the_metrics_own_reason():
    package = _build(closeout=_closeout(
        metrics={"revenue": _refused(reason="Every settlement is in another currency.")}
    ))
    assert _item(package, "revenue_record")["how"] == (
        "Every settlement is in another currency."
    )


def test_a_present_item_shows_its_value_and_no_gap_fields():
    package = _build()
    item = _item(package, "revenue_record")
    assert item["present"] is True
    assert "48,000.00 USD" in item["value_summary"]
    assert "how" not in item and "who_fixes" not in item


def test_a_missing_item_shows_its_gap_fields_and_no_value():
    package = _build(closeout=_closeout(metrics={"revenue": _refused()}))
    item = _item(package, "revenue_record")
    assert "value_summary" not in item
    assert item["who_fixes"] == financing_evidence.OWNER_GROWER


def test_an_evidence_item_that_is_missing_must_say_how_to_close_it():
    """A gap nobody can act on is a complaint, not evidence."""
    with pytest.raises(ValueError, match="how to close it"):
        financing_evidence.EvidenceItem(
            key="k", label="l", category=financing_evidence.CATEGORY_COST,
            present=False, how="",
        )


# ------------------------------------------------------------- evidence keys
def test_evidence_keys_contain_only_items_actually_backed_by_a_value():
    """These feed a lender's required_evidence rules; an empty record must not pass."""
    package = _build(closeout=_closeout(metrics={"revenue": _refused()}))
    assert "revenue_record" not in package["evidence_keys"]
    assert "spray_log" in package["evidence_keys"]


def test_evidence_keys_and_present_items_agree():
    package = _build()
    present = {i["key"] for i in package["items"] if i["present"]}
    assert set(package["evidence_keys"]) == present


# ---------------------------------------------------------------- cost record
def test_uncosted_activities_make_the_cost_record_incomplete():
    closeout = _closeout()
    closeout["metrics"]["costs"]["applications_without_cost"] = 3
    package = _build(closeout=closeout)
    item = _item(package, "cost_completeness")
    assert item["present"] is False
    assert "3 recorded activity(ies) carry no cost" in item["how"]


def test_a_fully_costed_season_marks_the_cost_record_complete():
    assert _item(_build(), "cost_completeness")["present"] is True


# ------------------------------------------------------------ compliance
def test_an_unresolved_conflict_blocks_the_compliance_item():
    conflicted = _planned(decision_severity="critical", outcome="planned")
    package = _build(decisions=[conflicted])
    item = _item(package, "compliance_record")
    assert item["present"] is False
    assert "unresolved critical finding" in item["how"]


def test_a_farm_with_no_decisions_has_no_spray_log():
    package = _build(decisions=[])
    assert _item(package, "spray_log")["present"] is False


def test_pca_review_is_counted_as_its_own_evidence_item():
    package = _build(decisions=[_planned(review_status="approved")])
    assert _item(package, "decision_record")["present"] is True

    unreviewed = _build(decisions=[_planned(review_status=None)])
    assert _item(unreviewed, "decision_record")["present"] is False


# ----------------------------------------------------------------- collateral
def test_collateral_without_a_valuation_does_not_count():
    assets = [SimpleNamespace(id=1, assessed_value=None)]
    package = _build(collateral_assets=assets)
    item = _item(package, "collateral_register")
    assert item["present"] is False
    assert "never estimates one" in item["how"]


def test_valued_collateral_counts_and_is_the_operators_job_to_enter():
    assets = [SimpleNamespace(id=1, assessed_value=120000.0)]
    package = _build(collateral_assets=assets)
    assert _item(package, "collateral_register")["present"] is True

    empty = _build(collateral_assets=[])
    assert _item(empty, "collateral_register")["who_fixes"] == (
        financing_evidence.OWNER_OPERATOR
    )


# ------------------------------------------------------------------ history
def test_closed_seasons_are_the_production_history_item():
    assert _item(_build(performance={"closed_season_count": 2}), "production_history")[
        "present"
    ] is True
    assert _item(_build(performance={"closed_season_count": 0}), "production_history")[
        "present"
    ] is False


# ---------------------------------------------------------------- categories
def test_items_are_grouped_into_the_categories_a_lender_reads():
    package = _build()
    keys = [c["key"] for c in package["categories"]]
    assert keys == list(financing_evidence.CATEGORY_LABELS)
    assert sum(c["total_count"] for c in package["categories"]) == package["total_count"]


def test_an_empty_farm_produces_a_package_of_gaps_not_an_error():
    package = financing_evidence.build_package(
        farm=_farm(name=None, location=None, country=None),
        cycle=None, closeout={}, performance={}, decisions=[],
        collateral_assets=[], today=TODAY,
    )
    assert package["present_count"] == 0
    assert package["missing_count"] == package["total_count"]
    assert all(i["how"] for i in package["missing"])
