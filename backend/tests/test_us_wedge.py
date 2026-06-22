"""Tests for the U.S. specialty-crop wedge: REI logic, US analytics, and PCA wording."""
from datetime import date, timedelta
from types import SimpleNamespace

from app.analytics import compute_cost_analytics
from app.recommendation_engine import (
    ACTION_REVIEW_AGRONOMIST,
    generate_recommendation,
)

TODAY = date(2026, 6, 21)


def farm(harvest_offset_days=None, country="US"):
    harvest = TODAY + timedelta(days=harvest_offset_days) if harvest_offset_days is not None else None
    return SimpleNamespace(expected_harvest_date=harvest, country=country, crop_type="strawberry")


def spray(ai="captan", days_ago=1, phi=None, rei=None, product="Captan 80 WDG", cost=120.0):
    return SimpleNamespace(
        active_ingredient=ai,
        application_date=TODAY - timedelta(days=days_ago),
        pre_harvest_interval_days=phi,
        re_entry_interval_hours=rei,
        product_name=product,
        cost=cost,
    )


# ------------------------------------------------ Harvest-date consistency
def test_phi_flag_text_uses_the_farm_expected_harvest_date():
    # The header and the recommendation both read farm.expected_harvest_date, so the date
    # shown in the header must appear verbatim in the PHI flag text. Deterministic guard.
    harvest_farm = farm(harvest_offset_days=2)        # harvest = TODAY + 2
    sprays = [spray(days_ago=1, phi=4)]               # clears TODAY + 3 -> after harvest
    result = generate_recommendation(harvest_farm, sprays, [], today=TODAY)
    assert result.signals["phi_risk"] is True
    expected = harvest_farm.expected_harvest_date.isoformat()
    assert expected == (TODAY + timedelta(days=2)).isoformat()
    assert expected in result.recommendation_text
    # And no autonomous / overclaiming language sneaks into the generated text.
    lowered = result.recommendation_text.lower()
    assert "must spray" not in lowered
    assert "guaranteed" not in lowered and "always reduces" not in lowered


# ----------------------------------------------------------------- REI logic
def test_active_rei_is_flagged():
    # REI 24h applied today -> clears ~tomorrow -> still active today.
    sprays = [spray(days_ago=0, rei=24)]
    result = generate_recommendation(farm(), sprays, [], today=TODAY)
    assert result.signals["rei_risk"] is True
    assert any("re-entry interval" in f.lower() for f in result.flags)


def test_active_rei_drives_review_action_when_no_phi():
    sprays = [spray(days_ago=0, rei=48)]
    result = generate_recommendation(farm(), sprays, [], today=TODAY)
    assert result.next_action == ACTION_REVIEW_AGRONOMIST


def test_cleared_rei_is_not_flagged():
    # REI 24h applied 5 days ago -> long cleared.
    sprays = [spray(days_ago=5, rei=24)]
    result = generate_recommendation(farm(), sprays, [], today=TODAY)
    assert result.signals["rei_risk"] is False
    assert not any("re-entry interval" in f.lower() for f in result.flags)


def test_no_rei_hours_means_no_rei_flag():
    sprays = [spray(days_ago=0, rei=None)]
    result = generate_recommendation(farm(), sprays, [], today=TODAY)
    assert result.signals["rei_risk"] is False


def test_rei_wording_is_cautious_never_definitive():
    sprays = [spray(days_ago=0, rei=24)]
    result = generate_recommendation(farm(), sprays, [], today=TODAY)
    text = " ".join(result.flags).lower()
    assert "may still be active" in text
    assert "safe" not in text and "unsafe" not in text


# ------------------------------------------------------- US seeded analytics
def test_us_strawberry_analytics():
    # Mirrors the Golden Coast seed: captan x3 @120 + bifenthrin @180.
    sprays = [
        spray(ai="captan", days_ago=1, cost=120.0),
        spray(ai="captan", days_ago=10, cost=120.0),
        spray(ai="captan", days_ago=20, cost=120.0),
        spray(ai="bifenthrin", days_ago=6, cost=180.0, product="Brigade WSB"),
    ]
    a = compute_cost_analytics(sprays, today=TODAY)
    assert a["total_spend"] == 540.0
    assert a["spray_count"] == 4
    assert a["most_used_active_ingredient"] == "captan"
    assert a["most_used_count"] == 3
    assert a["repeated_ingredient_cost"] == 240.0  # 2 extra captan sprays @120
    assert a["potential_avoidable_cost"] == a["average_cost_per_spray"] == 135.0


# ----------------------------------------------- API: PCA vs agronomist wording
def _make_farm(client, country, location):
    resp = client.post(
        "/farms",
        json={
            "name": f"Test {country} Farm",
            "location": location,
            "country": country,
            "crop_type": "strawberry" if country == "US" else "greenhouse_tomato",
            "expected_harvest_date": "2026-06-24",
        },
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def test_us_report_uses_pca_wording_and_usd(client):
    farm_id = _make_farm(client, "US", "Watsonville, California")
    report = client.get(f"/farms/{farm_id}/weekly-report").json()["text"]
    assert "pca" in report.lower()
    assert "$" in report
    assert "REI" in report or "rei" in report.lower()


def test_turkey_report_uses_agronomist_not_pca(client):
    farm_id = _make_farm(client, "TR", "Antalya, Türkiye")
    report = client.get(f"/farms/{farm_id}/weekly-report").json()["text"]
    assert "agronomist" in report.lower()
    assert "pca" not in report.lower()
    assert "₺" in report


def test_compliance_endpoint_exposes_structured_flags(client):
    farm_id = _make_farm(client, "US", "Watsonville, California")
    comp = client.get(f"/farms/{farm_id}/compliance").json()
    for key in ("phi_risk", "rei_risk", "repeated_active_ingredient_risk",
                "weather_risk_level", "review_status", "advisor_label"):
        assert key in comp
    assert comp["advisor_label"] == "PCA / agronomist"


def test_us_seeded_strawberry_farm_triggers_all_flags(client):
    # Recreate the seed scenario via the API and confirm PHI + REI + repeat all fire.
    farm_id = _make_farm(client, "US", "Watsonville, California")
    base = {"product_name": "Captan 80 WDG", "active_ingredient": "captan",
            "pre_harvest_interval_days": 4, "re_entry_interval_hours": 24, "cost": 120}
    today = date.today()
    for d in (1, 10, 20):
        client.post(f"/farms/{farm_id}/spray-events",
                    json={**base, "application_date": (today - timedelta(days=d)).isoformat()})
    # Harvest in 2 days so the day-1 spray's PHI (4d) clears after harvest.
    client.put(f"/farms/{farm_id}",
               json={"expected_harvest_date": (today + timedelta(days=2)).isoformat()})
    comp = client.get(f"/farms/{farm_id}/compliance").json()
    assert comp["phi_risk"] is True
    assert comp["rei_risk"] is True
    assert comp["repeated_active_ingredient_risk"] is True
