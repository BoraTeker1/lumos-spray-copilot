"""Unit tests for the reduction-measurement engine (pure, no DB)."""
from datetime import date
from types import SimpleNamespace

from app.reduction import compute_reduction

TODAY = date(2026, 6, 28)


def _spray(days_ago):
    return SimpleNamespace(application_date=TODAY.fromordinal(TODAY.toordinal() - days_ago))


def _farm(planting_days_ago=None, harvest_in_days=None):
    return SimpleNamespace(
        planting_date=(
            TODAY.fromordinal(TODAY.toordinal() - planting_days_ago)
            if planting_days_ago is not None
            else None
        ),
        expected_harvest_date=(
            TODAY.fromordinal(TODAY.toordinal() + harvest_in_days)
            if harvest_in_days is not None
            else None
        ),
    )


def _baseline(**kw):
    base = dict(
        method="stated_cadence",
        cadence_days=None,
        season_spray_count=None,
        baseline_period_start=None,
        baseline_period_end=None,
        calendar_program=None,
        data_source="grower_interview",
        data_confidence="user_provided",
        declared_by="PCA",
    )
    base.update(kw)
    return SimpleNamespace(**base)


# --------------------------------------------------------------- no baseline
def test_no_baseline_returns_no_numbers_but_counts_sprays():
    out = compute_reduction(_farm(), [_spray(1), _spray(5)], None, today=TODAY)
    assert out["has_baseline"] is False
    assert out["reduction_pct"] is None
    assert out["baseline_expected_sprays"] is None
    assert out["actual_sprays"] == 2
    assert out["is_headline_safe"] is False
    assert out["confidence_caveats"]  # explains what's missing


# ------------------------------------------------------------ stated cadence
def test_stated_cadence_days():
    sprays = [_spray(28), _spray(14), _spray(0)]  # window = 28 days, 3 sprays
    out = compute_reduction(_farm(), sprays, _baseline(cadence_days=7), today=TODAY)
    assert out["observed_window_days"] == 28
    assert out["baseline_expected_sprays"] == 4.0  # 28 / 7
    assert out["actual_sprays"] == 3
    assert out["sprays_avoided"] == 1.0
    assert out["reduction_pct"] == 25.0
    assert out["is_headline_safe"] is True
    assert out["reduction_statement"] and "controlled trial" in out["reduction_statement"]


def test_stated_season_count_scales_to_window():
    sprays = [_spray(50), _spray(25), _spray(0)]  # window 50 days
    farm = _farm(planting_days_ago=100, harvest_in_days=0)  # season = 100 days
    out = compute_reduction(farm, sprays, _baseline(season_spray_count=20), today=TODAY)
    assert out["baseline_expected_sprays"] == 10.0  # 20 * (50/100)
    assert out["reduction_pct"] == 70.0  # (10-3)/10
    assert out["is_headline_safe"] is True


# -------------------------------------------------------------- prior period
def test_prior_period_scales_unequal_windows():
    # Baseline window [-60, -30] holds 4 sprays; observed window (-30, today] holds 3.
    sprays = [_spray(55), _spray(50), _spray(45), _spray(35), _spray(20), _spray(10), _spray(5)]
    baseline = _baseline(
        method="prior_period",
        baseline_period_start=TODAY.fromordinal(TODAY.toordinal() - 60),
        baseline_period_end=TODAY.fromordinal(TODAY.toordinal() - 30),
    )
    out = compute_reduction(_farm(), sprays, baseline, today=TODAY)
    assert out["observed_window_days"] == 30
    assert out["baseline_expected_sprays"] == 4.0  # 4 prior * (30/30)
    assert out["actual_sprays"] == 3
    assert out["reduction_pct"] == 25.0
    assert out["is_headline_safe"] is True


# ------------------------------------------------------- negative reduction
def test_negative_reduction_reported_honestly():
    sprays = [_spray(28), _spray(21), _spray(14), _spray(7), _spray(0)]  # 5 in 28 days
    out = compute_reduction(_farm(), sprays, _baseline(cadence_days=14), today=TODAY)
    assert out["baseline_expected_sprays"] == 2.0
    assert out["sprays_avoided"] == -3.0
    assert out["reduction_pct"] == -150.0
    assert out["is_headline_safe"] is False
    assert any("INCREASED" in c for c in out["confidence_caveats"])


# ----------------------------------------------------- is_headline_safe gates
def test_simulated_confidence_is_not_headline_safe():
    sprays = [_spray(28), _spray(14), _spray(0)]
    out = compute_reduction(
        _farm(), sprays, _baseline(cadence_days=7, data_confidence="simulated"), today=TODAY
    )
    assert out["reduction_pct"] == 25.0  # still computed
    assert out["is_headline_safe"] is False
    assert out["reduction_statement"].startswith("Illustrative")


def test_short_window_is_not_headline_safe():
    sprays = [_spray(10), _spray(5), _spray(0)]  # window 10 < 21 days
    out = compute_reduction(_farm(), sprays, _baseline(cadence_days=2), today=TODAY)
    assert out["reduction_pct"] is not None
    assert out["is_headline_safe"] is False


def test_too_few_sprays_is_not_headline_safe():
    sprays = [_spray(40), _spray(0)]  # only 2 sprays, long window
    out = compute_reduction(_farm(), sprays, _baseline(cadence_days=10), today=TODAY)
    assert out["actual_sprays"] == 2
    assert out["is_headline_safe"] is False


# ----------------------------------------------------------- calendar program
def test_calendar_program_maps_to_cadence():
    sprays = [_spray(28), _spray(14), _spray(0)]
    out = compute_reduction(
        _farm(),
        sprays,
        _baseline(method="calendar_program", calendar_program="weekly"),
        today=TODAY,
    )
    assert out["baseline_expected_sprays"] == 4.0  # weekly -> 7-day cadence over 28 days
    assert any("Calendar-program" in c for c in out["confidence_caveats"])


# --------------------------------------------------------------- determinism
def test_deterministic_given_today():
    sprays = [_spray(28), _spray(14), _spray(0)]
    b = _baseline(cadence_days=7)
    assert compute_reduction(_farm(), sprays, b, today=TODAY) == compute_reduction(
        _farm(), sprays, b, today=TODAY
    )


# ----------------------------------------------------------- endpoint wiring
from datetime import timedelta  # noqa: E402

TODAY_REAL = date.today()


def _farm_with_sprays(client):
    fid = client.post(
        "/farms",
        json={"name": "Reduction Ranch", "country": "US", "crop_type": "strawberry"},
    ).json()["id"]
    for d in (28, 14, 0):
        client.post(
            f"/farms/{fid}/spray-events",
            json={
                "product_name": "Captan 80 WDG",
                "application_date": (TODAY_REAL - timedelta(days=d)).isoformat(),
                "cost": 120,
            },
        )
    return fid


def test_reduction_endpoint_without_baseline(client):
    fid = _farm_with_sprays(client)
    out = client.get(f"/farms/{fid}/reduction").json()
    assert out["has_baseline"] is False
    assert out["reduction_pct"] is None


def test_set_baseline_then_measure_reduction(client):
    fid = _farm_with_sprays(client)
    put = client.put(
        f"/farms/{fid}/spray-baseline",
        json={"method": "stated_cadence", "cadence_days": 7, "declared_by": "PCA Jane"},
    )
    assert put.status_code == 200
    assert put.json()["cadence_days"] == 7

    out = client.get(f"/farms/{fid}/reduction").json()
    assert out["has_baseline"] is True
    assert out["baseline_expected_sprays"] == 4.0
    assert out["reduction_pct"] == 25.0
    assert out["is_headline_safe"] is True


def test_pilot_evidence_includes_measured_reduction_after_baseline(client):
    fid = _farm_with_sprays(client)
    # Before a baseline: no measured reduction, and a limitation says so.
    ev = client.get(f"/farms/{fid}/pilot-evidence").json()
    assert ev["has_measured_reduction"] is False
    assert any("No baseline captured" in lim for lim in ev["limitations"])

    client.put(
        f"/farms/{fid}/spray-baseline",
        json={"method": "stated_cadence", "cadence_days": 7},
    )
    ev2 = client.get(f"/farms/{fid}/pilot-evidence").json()
    assert ev2["has_measured_reduction"] is True
    assert ev2["reduction"]["reduction_pct"] == 25.0
    assert any("fewer sprays" in line for line in ev2["evidence_summary"])


def test_get_baseline_is_null_until_set(client):
    fid = _farm_with_sprays(client)
    assert client.get(f"/farms/{fid}/spray-baseline").json() is None
    client.put(
        f"/farms/{fid}/spray-baseline",
        json={"method": "calendar_program", "calendar_program": "weekly"},
    )
    got = client.get(f"/farms/{fid}/spray-baseline").json()
    assert got["method"] == "calendar_program"
    assert got["calendar_program"] == "weekly"
