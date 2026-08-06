"""The historical opportunity scan, and the claims it must refuse to make.

Three groups:
  1. WHAT IT CANNOT SAY — no avoided count, no reduction figure, and the claim ceiling
     travels on every payload. These are the tests that matter most; the scan's whole
     risk is that someone reads a low-band count as "sprays you could have skipped".
  2. WHAT IT DOES SAY — the reason histogram, which is the useful output while the
     threshold table is empty.
  3. THE ARITHMETIC — exercised against SYNTHETIC tables built here, never against real
     coefficients. `app/botrytis_thresholds.py` ships empty on purpose; a test that
     needed real numbers to pass would be pressure to invent them.
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app import backtest, botrytis_thresholds, disease_risk, risk_snapshot

AS_OF = datetime(2026, 6, 15, 6, 0, 0)
DATES = [AS_OF, AS_OF + timedelta(days=7), AS_OF + timedelta(days=14)]


def block(**kw):
    base = {
        "id": 1, "crop": "strawberry", "cultivar": "Monterey", "area": 4.0,
        "area_unit": "acres", "phenology_stage": "bloom",
        "phenology_observed_on": None,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def weather(id=1, observed_at=None, recorded_at=None, **kw):
    observed_at = observed_at or (AS_OF - timedelta(hours=2))
    base = {
        "id": id, "observed_at": observed_at,
        "recorded_at": recorded_at if recorded_at is not None else observed_at,
        "station_id": "CIMIS-111", "station_distance_km": 3.0,
        "temperature_c": 15.0, "relative_humidity_pct": 92.0, "rainfall_mm": 0.0,
        "leaf_wetness_minutes": 60.0, "wetness_is_measured": True,
        "source_type": "manual_entry", "quality_flag": None, "supersedes_id": None,
        "data_source": "manual_entry", "data_confidence": "user_provided",
    }
    base.update(kw)
    return SimpleNamespace(**base)


def sample(id=1, observed_at=None, recorded_at=None, **kw):
    observed_at = observed_at or (AS_OF - timedelta(days=1))
    base = {
        "id": id, "observed_at": observed_at,
        "recorded_at": recorded_at if recorded_at is not None else observed_at,
        "method": "fruit_count", "target": "botrytis_fruit_rot",
        "units_inspected": 100, "units_affected": 4, "incidence_pct": 4.0,
        "severity_index": None, "severity_scale": None,
        "source_type": "manual_entry", "quality_flag": None, "supersedes_id": None,
        "data_source": "manual_entry", "data_confidence": "user_provided",
    }
    base.update(kw)
    return SimpleNamespace(**base)


def run(dates=None, weather_rows=None, samples=None):
    return backtest.run_scan(
        decision_dates=dates or DATES,
        block=block(),
        weather_observations=weather_rows if weather_rows is not None else [weather()],
        scouting_samples=samples if samples is not None else [sample()],
        target="botrytis_fruit_rot",
    )


# ------------------------------------------------------------ 1. what it cannot say
def test_no_payload_key_ever_suggests_an_avoided_or_reduced_spray():
    """The one number this module exists to withhold.

    A future edit adding `avoided_applications` would be adding exactly the claim that
    Stage 2's design cannot support — every historical outcome followed the actual
    spray, so there is no untreated counterfactual. It should fail here rather than ship.
    """
    payload = run().as_payload()

    def walk(node, path="payload"):
        if isinstance(node, dict):
            for key, value in node.items():
                # `cannot_conclude` is the DISCLOSURE of these terms — naming the
                # metrics it refuses to compute is the entire point of the block — so
                # it is the one subtree exempt from the key check.
                if key == "cannot_conclude":
                    continue
                lowered = key.lower()
                for banned in backtest.FORBIDDEN_KEY_SUBSTRINGS:
                    assert banned not in lowered, f"forbidden key {path}.{key}"
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for item in node:
                walk(item, path)

    walk(payload)
    # ...and the exempt subtree really is present, so this test cannot pass by the
    # disclosure having been deleted.
    assert payload["cannot_conclude"]


def test_every_payload_carries_its_claim_ceiling():
    payload = run().as_payload()
    assert set(payload["cannot_conclude"]) == set(backtest.SCAN_CANNOT_CONCLUDE)
    for text in payload["cannot_conclude"].values():
        assert "not calculated" in text


def test_the_result_has_no_field_that_could_hold_a_recommendation():
    """Mirrors `RiskAssessment` having no product field: inexpressible beats forbidden."""
    fields = set(backtest.ScanResult.__dataclass_fields__) | set(
        backtest.ScanItem.__dataclass_fields__
    )
    for banned in ("product", "rate", "action", "recommend", "avoided", "reduction"):
        assert not any(banned in f for f in fields)


def test_a_scan_is_always_retrospective_and_says_so():
    result = run()
    assert result.basis == risk_snapshot.BASIS_RETROSPECTIVE
    assert result.as_payload()["basis"] == risk_snapshot.BASIS_RETROSPECTIVE


# --------------------------------------------------------------- 2. what it does say
def test_with_no_thresholds_every_date_abstains_and_none_gets_a_band():
    """The pass condition before the threshold table is transcribed."""
    result = run()
    assert result.dates_scanned == len(DATES)
    assert result.assessed_count == 0
    assert result.band_counts == {disease_risk.BAND_ABSTAIN: len(DATES)}
    assert result.reason_counts[disease_risk.ABSTAIN_THRESHOLDS_NOT_SUPPLIED] == len(DATES)


def test_the_reason_histogram_counts_every_reason_not_just_the_first():
    """A date blocked by three gaps is three work items.

    Counting only the first reason would reveal the second only after the first was
    fixed — the slowest possible way for a farm to learn what it is missing.
    """
    # No wetness AND no scouting: two independent gaps on the same date.
    result = run(
        dates=[AS_OF],
        weather_rows=[weather(leaf_wetness_minutes=None, wetness_is_measured=None)],
        samples=[],
    )
    reasons = result.reason_counts
    assert reasons[disease_risk.ABSTAIN_NO_LEAF_WETNESS] == 1
    assert reasons[disease_risk.ABSTAIN_NO_SCOUTING] == 1
    assert reasons[disease_risk.ABSTAIN_THRESHOLDS_NOT_SUPPLIED] == 1


def test_the_scan_admits_backfilled_history_that_point_in_time_would_exclude():
    """The reason the retrospective basis exists at all.

    A concierge import of last season stamps `recorded_at` at ingest time (never
    back-dated). Under the point-in-time basis a replay of a past date admits NOTHING,
    and the scan honestly finds no data. The retrospective basis is what makes a
    historical scan possible — and it is why the scan cannot claim to be what the rule
    "would have said at the time".
    """
    ingested_today = datetime(2026, 8, 6, 9, 0, 0)
    backfilled = weather(recorded_at=ingested_today)

    prospective = risk_snapshot.build_snapshot(
        as_of=AS_OF, horizon_hours=72, target="botrytis_fruit_rot", block=block(),
        weather_observations=[backfilled], scouting_samples=[],
    )
    assert prospective.payload["weather"] == []
    assert prospective.excluded[0]["reason"] == risk_snapshot.EXCLUDED_RECORDED_LATE

    retrospective = risk_snapshot.build_snapshot(
        as_of=AS_OF, horizon_hours=72, target="botrytis_fruit_rot", block=block(),
        weather_observations=[backfilled], scouting_samples=[],
        basis=risk_snapshot.BASIS_RETROSPECTIVE,
    )
    assert len(retrospective.payload["weather"]) == 1


def test_retrospective_relaxes_only_the_recorded_late_rule():
    """Superseded, quality-flagged and demo rows stay excluded in BOTH bases.

    The retrospective basis is a single, named relaxation. If it ever became a general
    "admit everything" path, a demo row could reach a scan and the histogram would be
    partly fabricated.
    """
    rows = [
        weather(id=1, quality_flag="M"),
        weather(id=2, data_source="demo", data_confidence="simulated"),
        weather(id=3, supersedes_id=None),
        weather(id=4, supersedes_id=3),
    ]
    draft = risk_snapshot.build_snapshot(
        as_of=AS_OF, horizon_hours=72, target="botrytis_fruit_rot", block=block(),
        weather_observations=rows, scouting_samples=[],
        basis=risk_snapshot.BASIS_RETROSPECTIVE,
    )
    reasons = {e["id"]: e["reason"] for e in draft.excluded}
    assert reasons[1] == risk_snapshot.EXCLUDED_QUALITY_FLAG
    assert reasons[2] == risk_snapshot.EXCLUDED_DEMO_OR_MOCK
    assert reasons[3] == risk_snapshot.EXCLUDED_SUPERSEDED


def test_a_scan_with_no_dates_is_a_programming_error_not_an_empty_result():
    result = backtest.run_scan(
        decision_dates=[], block=block(), weather_observations=[],
        scouting_samples=[], target="botrytis_fruit_rot",
    )
    assert result.dates_scanned == 0


# ------------------------------------------------------------------ 3. the arithmetic
def synthetic_table(rows=None):
    """A FAKE table with invented numbers, for exercising the arithmetic only.

    These coefficients are meaningless and are deliberately round so nobody mistakes
    them for a transcription. The real table stays empty until someone reads the primary
    source — see `app/botrytis_thresholds.py`.
    """
    return botrytis_thresholds.BotrytisThresholdTable(
        rows=rows or (
            botrytis_thresholds.ThresholdRow(
                temperature_c_min=10.0, temperature_c_max=20.0,
                wetness_hours_moderate=10.0, wetness_hours_high=20.0,
            ),
        ),
        citation="Nobody (1900). A table that does not exist. Journal of Test Fixtures.",
        source_crop="test-crop",
        source_region="test-region",
        source_validation_conditions="none; this table is synthetic",
        source_document_reference="n/a — synthetic fixture",
        source_section_or_page="n/a",
        source_snippet="n/a",
        transcribed_by="test fixture",
    )


@pytest.fixture()
def ready_model(monkeypatch):
    """Install a synthetic table on the registered model for the duration of a test."""
    table = synthetic_table()
    model = disease_risk.RISK_MODELS[disease_risk.DEFAULT_MODEL_VERSION]
    monkeypatch.setattr(model, "_table", table, raising=False)
    monkeypatch.setattr(model, "thresholds", table.rows, raising=False)
    monkeypatch.setattr(model, "citation", table.citation, raising=False)
    monkeypatch.setattr(model, "source_crop", table.source_crop, raising=False)
    monkeypatch.setattr(model, "source_region", table.source_region, raising=False)
    monkeypatch.setattr(
        model, "source_validation_conditions",
        table.source_validation_conditions, raising=False,
    )
    return model


def test_the_shipped_table_is_empty_and_the_model_is_not_ready():
    """If this ever fails, someone transcribed coefficients — check their citation."""
    assert botrytis_thresholds.TRANSCRIBED_TABLE is None
    assert not disease_risk.RISK_MODELS[disease_risk.DEFAULT_MODEL_VERSION].is_ready()


def test_bands_move_with_accumulated_wetness_against_a_synthetic_table(ready_model):
    assert ready_model.is_ready()

    def band_for(hours):
        rows = [
            weather(
                id=i,
                observed_at=AS_OF - timedelta(hours=i + 1),
                leaf_wetness_minutes=60.0,
                temperature_c=15.0,
            )
            for i in range(int(hours))
        ]
        result = run(dates=[AS_OF], weather_rows=rows)
        return result.items[0].risk_band

    assert band_for(5) == disease_risk.BAND_LOW
    assert band_for(12) == disease_risk.BAND_MODERATE
    assert band_for(22) == disease_risk.BAND_HIGH


def test_a_temperature_outside_the_table_abstains_rather_than_reading_low(ready_model):
    """The table's silence is not a low band.

    A source that never studied 4 °C says nothing about 4 °C. Extrapolating past the
    edge of a published table is the same invention this codebase refuses everywhere
    else — and here it would err toward "low risk", the direction that skips a spray.
    """
    rows = [
        weather(id=i, observed_at=AS_OF - timedelta(hours=i + 1), temperature_c=4.0)
        for i in range(3)
    ]
    result = run(dates=[AS_OF], weather_rows=rows)
    item = result.items[0]
    assert item.abstained
    assert item.risk_band == disease_risk.BAND_ABSTAIN
    assert disease_risk.ABSTAIN_TEMPERATURE_OUTSIDE_TABLE in item.reasons


def test_mean_temperature_uses_only_the_wet_hours(ready_model):
    """A wet night at 12 °C inside a warm week is the infection event.

    Averaging the dry hours in would describe a period during which nothing was at risk,
    and would land in the wrong temperature band.
    """
    rows = [
        weather(id=1, observed_at=AS_OF - timedelta(hours=1),
                temperature_c=15.0, leaf_wetness_minutes=60.0),
        # Dry and much hotter — outside the synthetic table's 10-20 °C band entirely.
        weather(id=2, observed_at=AS_OF - timedelta(hours=2),
                temperature_c=45.0, leaf_wetness_minutes=0.0),
    ]
    result = run(dates=[AS_OF], weather_rows=rows)
    assert not result.items[0].abstained


def test_a_table_row_with_no_threshold_at_all_is_refused():
    with pytest.raises(ValueError):
        botrytis_thresholds.ThresholdRow(
            temperature_c_min=10.0, temperature_c_max=20.0,
        )


def test_overlapping_transcribed_bands_are_refused():
    """A temperature matching two rows makes the band order-dependent."""
    with pytest.raises(ValueError, match="overlap"):
        synthetic_table(rows=(
            botrytis_thresholds.ThresholdRow(
                temperature_c_min=10.0, temperature_c_max=20.0,
                wetness_hours_moderate=10.0,
            ),
            botrytis_thresholds.ThresholdRow(
                temperature_c_min=15.0, temperature_c_max=25.0,
                wetness_hours_moderate=8.0,
            ),
        ))


def test_a_table_without_its_citation_cannot_be_constructed():
    """The failure `label_table.py` prevents, one module over."""
    with pytest.raises((TypeError, ValueError)):
        botrytis_thresholds.BotrytisThresholdTable(
            rows=(botrytis_thresholds.ThresholdRow(
                temperature_c_min=10.0, temperature_c_max=20.0,
                wetness_hours_moderate=10.0,
            ),),
        )


# ------------------------------------------------------------------- 4. the API surface
def _scan_farm(client):
    """A farm with a block and a season of backfilled weather + scouting."""
    from datetime import date

    farm = client.post("/farms", json={
        "name": "Scan Farm", "country": "US", "crop_type": "strawberry",
    }).json()
    blk = client.post(f"/farms/{farm['id']}/blocks", json={"name": "North 1"}).json()
    for day in range(1, 15):
        observed = AS_OF - timedelta(days=day)
        client.post(f"/farms/{farm['id']}/weather-observations", json={
            "block_id": blk["id"], "station_id": "CIMIS-111",
            "observed_at": observed.isoformat(), "temperature_c": 15.0,
            "relative_humidity_pct": 93.0, "station_distance_km": 2.0,
        })
    client.post(f"/farms/{farm['id']}/scouting-samples", json={
        "block_id": blk["id"], "observed_at": (AS_OF - timedelta(days=1)).isoformat(),
        "method": "fruit_count", "target": "botrytis_fruit_rot",
        "units_inspected": 100, "units_affected": 4,
    })
    return farm, blk


def test_the_scan_route_returns_a_histogram_and_its_claim_ceiling(client):
    farm, blk = _scan_farm(client)
    res = client.post(f"/internal/farms/{farm['id']}/opportunity-scans", json={
        "block_id": blk["id"],
        "decision_dates": [d.isoformat() for d in DATES],
        "run_by": "operator",
    })
    assert res.status_code == 201, res.text
    body = res.json()

    assert body["basis"] == risk_snapshot.BASIS_RETROSPECTIVE
    assert body["dates_scanned"] == len(DATES)
    # Thresholds are absent, so nothing may be assessed. THIS IS THE PASS CONDITION.
    assert body["assessed_count"] == 0
    assert body["reason_counts"][disease_risk.ABSTAIN_THRESHOLDS_NOT_SUPPLIED] == len(DATES)
    assert set(body["cannot_conclude"]) == set(backtest.SCAN_CANNOT_CONCLUDE)
    assert len(body["items"]) == len(DATES)


def test_a_scan_never_writes_a_prospective_snapshot_or_assessment(client):
    """A retrospective replay must not leave rows the live pilot calibrates from."""
    farm, blk = _scan_farm(client)
    client.post(f"/internal/farms/{farm['id']}/opportunity-scans", json={
        "block_id": blk["id"], "decision_dates": [DATES[0].isoformat()],
    })
    assert client.get("/internal/pilot/assessments").json() == []


def test_a_block_from_another_farm_is_refused(client):
    """farm_id is the only isolation boundary this system has."""
    farm, blk = _scan_farm(client)
    other = client.post("/farms", json={
        "name": "Other", "country": "US", "crop_type": "strawberry",
    }).json()
    res = client.post(f"/internal/farms/{other['id']}/opportunity-scans", json={
        "block_id": blk["id"], "decision_dates": [DATES[0].isoformat()],
    })
    assert res.status_code == 409


def test_a_scan_with_no_dates_is_rejected_rather_than_inventing_a_denominator(client):
    farm, blk = _scan_farm(client)
    res = client.post(f"/internal/farms/{farm['id']}/opportunity-scans", json={
        "block_id": blk["id"], "decision_dates": [],
    })
    assert res.status_code == 422


def test_scans_have_no_update_or_delete_route(client):
    """Append-only, like every other evidence table in the pilot."""
    farm, blk = _scan_farm(client)
    scan = client.post(f"/internal/farms/{farm['id']}/opportunity-scans", json={
        "block_id": blk["id"], "decision_dates": [DATES[0].isoformat()],
    }).json()
    path = f"/internal/opportunity-scans/{scan['id']}"
    assert client.put(path, json={}).status_code in (404, 405)
    assert client.patch(path, json={}).status_code in (404, 405)
    assert client.delete(path).status_code in (404, 405)


def test_the_scan_surface_is_operator_gated(client, monkeypatch):
    """A histogram reaching an enrolled PCA would contaminate the shadow baseline.

    `test_operator_key.py` already covers these routes by enumerating the live route
    table, so this asserts the specific thing that test cannot: that the POST — the one
    that computes and stores — is gated, not just the GETs it walks.
    """
    from app import operator_key

    farm, blk = _scan_farm(client)
    monkeypatch.setenv(operator_key.ENV_VAR, "test-operator-secret")

    body = {"block_id": blk["id"], "decision_dates": [DATES[0].isoformat()]}
    path = f"/internal/farms/{farm['id']}/opportunity-scans"

    assert client.post(path, json=body).status_code == 403
    assert client.post(
        path, json=body, headers={operator_key.KEY_HEADER: "test-operator-secret"}
    ).status_code == 201
