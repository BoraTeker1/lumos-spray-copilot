"""Post-decision data must never reach a risk assessment.

If any of these fail, every calibration number the pilot produces is worthless: the
model would be scored on information the PCA could not have had at the moment they
decided, which makes it look skilful and makes the pilot a lie.

Two defences are tested here:
  1. STRUCTURAL — `build_snapshot` has no parameter through which post-decision data
     could arrive, and its output contains none of it even when all of it exists.
  2. TEMPORAL — admissibility is checked on BOTH `observed_at` and `recorded_at`.
     Filtering on `observed_at` alone looks correct and silently leaks.
"""
import inspect
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app import risk_snapshot

AS_OF = datetime(2026, 7, 19, 6, 0, 0)
BEFORE = AS_OF - timedelta(hours=2)
AFTER = AS_OF + timedelta(hours=2)


def block(**kw):
    base = {
        "id": 1, "crop": "strawberry", "cultivar": "Monterey", "area": 4.0,
        "area_unit": "acres", "phenology_stage": "bloom",
        "phenology_observed_on": None,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def weather(id=1, observed_at=BEFORE, recorded_at=None, **kw):
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


def sample(id=1, observed_at=BEFORE, recorded_at=None, **kw):
    base = {
        "id": id, "observed_at": observed_at,
        "recorded_at": recorded_at if recorded_at is not None else observed_at,
        "method": "fruit_count", "target": "botrytis",
        "units_inspected": 100, "units_affected": 4, "incidence_pct": 4.0,
        "severity_index": None, "severity_scale": None,
        "source_type": "manual_entry", "quality_flag": None, "supersedes_id": None,
        "data_source": "manual_entry", "data_confidence": "user_provided",
    }
    base.update(kw)
    return SimpleNamespace(**base)


def build(weather_rows=(), sample_rows=(), **kw):
    return risk_snapshot.build_snapshot(
        as_of=kw.pop("as_of", AS_OF),
        horizon_hours=kw.pop("horizon_hours", 72),
        target=kw.pop("target", "botrytis_fruit_rot"),
        block=kw.pop("block", block()),
        weather_observations=list(weather_rows),
        scouting_samples=list(sample_rows),
        **kw,
    )


# ---------------------------------------------------- structural containment
def test_snapshot_signature_admits_no_post_decision_inputs():
    """The contract itself is the defence: there is no parameter to leak through.

    If this fails because a parameter was added, that is the review signal — a
    disposition, outcome, application, or harvest argument must never appear here.
    """
    params = set(inspect.signature(risk_snapshot.build_snapshot).parameters)
    assert params == {
        "as_of", "horizon_hours", "target", "block",
        "weather_observations", "scouting_samples", "lookback_hours",
    }
    forbidden = (
        "disposition", "outcome", "application", "sprayed", "harvest", "packout",
        "rescue", "yield", "planned_spray", "review",
    )
    for name in params:
        assert not any(f in name for f in forbidden), f"leaky parameter: {name}"


def test_module_cannot_reach_a_database_or_the_app_at_all():
    """Framework-free by construction — it cannot query for what it must not see."""
    source = inspect.getsource(risk_snapshot)
    for forbidden in ("sqlalchemy", "fastapi", "from app import", "import crud"):
        assert forbidden not in source, f"risk_snapshot must not import {forbidden}"


def test_no_post_decision_value_appears_in_the_payload_even_when_all_of_it_exists():
    """Simulates the real hazard: the decision is long resolved and every downstream
    record exists. None of it may appear."""
    poisoned = weather(id=1)
    # Attributes a careless refactor might carry along on the same row object.
    poisoned.outcome = "avoided"
    poisoned.pca_disposition = "defer"
    poisoned.rescue_required = True
    poisoned.marketable_packout = 91.4
    poisoned.actual_application_date = "2026-07-20"

    snap = build([poisoned], [sample()])
    body = json.dumps(snap.as_payload())

    for leaked in ("avoided", "defer", "rescue", "packout", "91.4", "2026-07-20"):
        assert leaked not in body, f"post-decision value leaked into the snapshot: {leaked}"


# --------------------------------------------------------- temporal filtering
def test_weather_observed_after_as_of_is_excluded():
    snap = build([weather(id=1, observed_at=BEFORE), weather(id=2, observed_at=AFTER)])
    assert len(snap.payload["weather"]) == 1
    assert {"kind": "weather", "id": 2,
            "reason": risk_snapshot.EXCLUDED_FUTURE_OBSERVATION} in snap.excluded


def test_reading_about_the_past_entered_after_the_decision_is_excluded():
    """THE subtle leak: filtering on observed_at alone would admit this row.

    A reading about 04:00 that was keyed in at 08:00 is hindsight — the PCA deciding
    at 06:00 did not have it, and scoring the model as if they did is fabrication.
    """
    hindsight = weather(id=2, observed_at=BEFORE, recorded_at=AFTER)
    snap = build([weather(id=1), hindsight])

    assert [w["observed_at"] for w in snap.payload["weather"]] == [BEFORE.isoformat()]
    assert {"kind": "weather", "id": 2,
            "reason": risk_snapshot.EXCLUDED_RECORDED_LATE} in snap.excluded


def test_late_recorded_scouting_sample_is_excluded_too():
    snap = build([], [sample(id=1), sample(id=2, recorded_at=AFTER)])
    assert len(snap.payload["scouting_samples"]) == 1
    assert {"kind": "scouting_sample", "id": 2,
            "reason": risk_snapshot.EXCLUDED_RECORDED_LATE} in snap.excluded


def test_superseded_rows_are_excluded_and_the_correction_is_used():
    original = weather(id=1, temperature_c=15.0)
    correction = weather(id=2, temperature_c=19.9, supersedes_id=1)
    snap = build([original, correction])

    temps = [w["temperature_c"] for w in snap.payload["weather"]]
    assert temps == [19.9]
    assert {"kind": "weather", "id": 1,
            "reason": risk_snapshot.EXCLUDED_SUPERSEDED} in snap.excluded


def test_quality_flagged_and_demo_rows_are_excluded_with_reasons():
    flagged = weather(id=2, quality_flag="sensor fault")
    demo = weather(id=3, data_source="demo", data_confidence="simulated")
    snap = build([weather(id=1), flagged, demo])

    assert len(snap.payload["weather"]) == 1
    reasons = {e["id"]: e["reason"] for e in snap.excluded}
    assert reasons[2] == risk_snapshot.EXCLUDED_QUALITY_FLAG
    assert reasons[3] == risk_snapshot.EXCLUDED_DEMO_OR_MOCK


# ------------------------------------------------------------ reproducibility
def test_same_as_of_yields_an_identical_digest_after_later_data_arrives():
    """The audit property: an assessment must be reproducible from its record.

    Re-running the same `as_of` a week later, with a week of new readings and every
    outcome recorded, must produce the byte-identical snapshot it produced then.
    """
    original_rows = [weather(id=1), weather(id=2, observed_at=BEFORE + timedelta(hours=1))]
    first = build(list(original_rows), [sample()])

    later_rows = original_rows + [
        weather(id=3, observed_at=AFTER),
        weather(id=4, observed_at=BEFORE, recorded_at=AFTER),
    ]
    second = build(later_rows, [sample(), sample(id=2, recorded_at=AFTER)])

    assert first.input_digest == second.input_digest
    assert first.as_payload() == second.as_payload()


def test_digest_changes_when_an_admitted_input_changes():
    """The digest must actually be sensitive — a constant hash proves nothing."""
    a = build([weather(id=1, temperature_c=15.0)])
    b = build([weather(id=1, temperature_c=15.1)])
    assert a.input_digest != b.input_digest


def test_digest_is_stable_across_input_ordering():
    early = weather(id=1, observed_at=BEFORE)
    late = weather(id=2, observed_at=BEFORE + timedelta(hours=1))
    assert build([early, late]).input_digest == build([late, early]).input_digest


def test_history_window_is_declared_in_the_snapshot():
    """Two assessments of the same hour must see the same history, so the window is
    part of the snapshot rather than an implicit constant."""
    old = weather(id=9, observed_at=AS_OF - timedelta(hours=200))
    snap = build([old, weather(id=1)])
    assert snap.payload["lookback_hours"] == 168
    assert len(snap.payload["weather"]) == 1


# ------------------------------------------------- end-to-end through the API
def _pilot_farm(client):
    """A farm with a block, a weather reading, and a sample — the pilot shape."""
    from datetime import date

    farm = client.post("/farms", json={
        "name": "Leak Farm", "country": "US", "crop_type": "strawberry",
        "expected_harvest_date": (date.today() + timedelta(days=30)).isoformat(),
    }).json()
    blk = client.post(f"/farms/{farm['id']}/blocks", json={"name": "North 1"}).json()
    client.post(f"/farms/{farm['id']}/weather-observations", json={
        "station_id": "CIMIS-111", "observed_at": BEFORE.isoformat(),
        "temperature_c": 15.0, "relative_humidity_pct": 93.0,
        "leaf_wetness_minutes": 120, "wetness_is_measured": True,
        "station_distance_km": 2.0,
    })
    client.post(f"/farms/{farm['id']}/scouting-samples", json={
        "block_id": blk["id"], "observed_at": BEFORE.isoformat(),
        "method": "fruit_count", "target": "botrytis",
        "units_inspected": 100, "units_affected": 4,
    })
    planned = client.post(f"/farms/{farm['id']}/planned-sprays", json={
        "intended_date": (date.today() + timedelta(days=2)).isoformat(),
        "product_name": "Switch 62.5 WG", "active_ingredient": "cyprodinil",
        "target_pest_or_disease": "botrytis", "block_id": blk["id"],
        "pre_harvest_interval_days": 1, "re_entry_interval_hours": 12,
    }).json()
    return farm, blk, planned


def test_api_snapshot_excludes_everything_recorded_after_as_of(client):
    """The full stack, not just the pure module: readings entered after the decision
    moment are excluded even though they describe an earlier time."""
    farm, blk, planned = _pilot_farm(client)

    # `as_of` in the past: the rows above were RECORDED now, i.e. after it.
    res = client.post(
        f"/planned-sprays/{planned['id']}/risk-snapshot",
        json={"as_of": (BEFORE - timedelta(days=1)).isoformat(), "horizon_hours": 72},
    )
    assert res.status_code == 201
    snap = res.json()
    assert snap["payload"]["weather"] == []
    assert snap["payload"]["scouting_samples"] == []
    assert any(e["reason"] == risk_snapshot.EXCLUDED_RECORDED_LATE
               or e["reason"] == risk_snapshot.EXCLUDED_FUTURE_OBSERVATION
               for e in snap["excluded"])


def test_api_snapshot_is_reproducible_and_records_its_digest(client):
    farm, blk, planned = _pilot_farm(client)
    first = client.post(f"/planned-sprays/{planned['id']}/risk-snapshot",
                        json={"horizon_hours": 72}).json()

    # More data arrives, and the decision gets resolved.
    client.patch(f"/planned-sprays/{planned['id']}/review",
                 json={"action": "approved", "reviewed_by": "PCA"})
    client.post(f"/farms/{farm['id']}/weather-observations", json={
        "station_id": "CIMIS-111", "observed_at": AFTER.isoformat(),
        "temperature_c": 22.0, "station_distance_km": 2.0,
    })

    second = client.post(
        f"/planned-sprays/{planned['id']}/risk-snapshot",
        json={"as_of": first["as_of"], "horizon_hours": 72},
    ).json()

    assert second["input_digest"] == first["input_digest"], (
        "re-snapshotting the same moment after later data and a recorded review must "
        "reproduce the original snapshot exactly"
    )
    assert first["input_digest"] and len(first["input_digest"]) == 64


def test_snapshot_requires_a_block_rather_than_guessing_one(client):
    from datetime import date

    farm = client.post("/farms", json={
        "name": "No Block Farm", "country": "US", "crop_type": "strawberry",
    }).json()
    planned = client.post(f"/farms/{farm['id']}/planned-sprays", json={
        "intended_date": date.today().isoformat(),
        "product_name": "Switch 62.5 WG", "target_pest_or_disease": "botrytis",
        "field_block": "north 3",  # free text only — not a Block
    }).json()

    res = client.post(f"/planned-sprays/{planned['id']}/risk-snapshot", json={})
    assert res.status_code == 422
    assert "never guessed" in res.json()["detail"]


def test_snapshots_have_no_update_or_delete_route(client):
    farm, blk, planned = _pilot_farm(client)
    snap = client.post(f"/planned-sprays/{planned['id']}/risk-snapshot", json={}).json()
    path = f"/planned-sprays/{planned['id']}/risk-snapshots/{snap['id']}"
    assert client.put(path, json={}).status_code in (404, 405)
    assert client.patch(path, json={}).status_code in (404, 405)
    assert client.delete(path).status_code in (404, 405)
