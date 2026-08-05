"""Point-in-time correctness tests for the platform-wide admissibility rule.

`tests/test_leakage.py` pins the pilot's snapshot behaviour end to end. This file pins
the shared rule itself, including the surface that is new in `app/pit.py` and has no
caller in the pilot: `partition`.
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

from app import pit, risk_snapshot

AS_OF = datetime(2026, 7, 20, 12, 0)


def obs(**kwargs):
    row = {
        "id": 1,
        "observed_at": AS_OF - timedelta(hours=2),
        "recorded_at": AS_OF - timedelta(hours=1),
        "supersedes_id": None,
        "quality_flag": None,
        "data_source": "manual_entry",
        "data_confidence": "user_provided",
    }
    row.update(kwargs)
    return SimpleNamespace(**row)


# --------------------------------------------------------------- admissibility

def test_an_ordinary_past_observation_is_admissible():
    assert pit.admissible(obs(), AS_OF, set()) is None


def test_an_observation_about_the_future_is_excluded():
    future = obs(observed_at=AS_OF + timedelta(hours=1))
    assert pit.admissible(future, AS_OF, set()) == pit.EXCLUDED_FUTURE_OBSERVATION


def test_a_late_recorded_observation_is_excluded_even_though_it_is_about_the_past():
    """The hindsight guard, and the whole reason `recorded_at` exists.

    This row describes weather from before the decision, so an `observed_at` filter
    admits it. But nobody knew it at `as_of` — using it would score a model on
    information the human could not have had.
    """
    late = obs(
        observed_at=AS_OF - timedelta(hours=6),
        recorded_at=AS_OF + timedelta(days=3),
    )
    assert late.observed_at < AS_OF          # an observed_at filter would admit it
    assert pit.admissible(late, AS_OF, set()) == pit.EXCLUDED_RECORDED_LATE


def test_superseded_quality_flagged_and_demo_rows_are_excluded():
    assert pit.admissible(obs(id=7), AS_OF, {7}) == pit.EXCLUDED_SUPERSEDED
    assert pit.admissible(obs(quality_flag="sensor fault"), AS_OF, set()) == pit.EXCLUDED_QUALITY_FLAG
    assert pit.admissible(obs(data_source="demo"), AS_OF, set()) == pit.EXCLUDED_DEMO_OR_MOCK
    assert pit.admissible(obs(data_confidence="simulated"), AS_OF, set()) == pit.EXCLUDED_DEMO_OR_MOCK


def test_missing_observed_at_is_excluded_not_assumed_current():
    assert pit.admissible(obs(observed_at=None), AS_OF, set()) == pit.EXCLUDED_FUTURE_OBSERVATION


# -------------------------------------------------------------------- partition

def test_partition_computes_the_supersede_set_over_the_whole_input():
    """The step that is easy to forget and impossible to notice missing.

    Row 1 was corrected by row 2. A caller filtering only on timestamps admits both and
    silently double-counts the reading.
    """
    original = obs(id=1)
    correction = obs(id=2, supersedes_id=1)
    admitted, excluded = pit.partition([original, correction], AS_OF)
    assert [r.id for r in admitted] == [2]
    assert excluded == [{"kind": "observation", "id": 1, "reason": pit.EXCLUDED_SUPERSEDED}]


def test_partition_reports_a_reason_for_every_excluded_row():
    rows = [
        obs(id=1),
        obs(id=2, observed_at=AS_OF + timedelta(hours=1)),
        obs(id=3, quality_flag="fault"),
        obs(id=4, data_source="demo"),
    ]
    admitted, excluded = pit.partition(rows, AS_OF, kind="weather")
    assert [r.id for r in admitted] == [1]
    assert {e["id"]: e["reason"] for e in excluded} == {
        2: pit.EXCLUDED_FUTURE_OBSERVATION,
        3: pit.EXCLUDED_QUALITY_FLAG,
        4: pit.EXCLUDED_DEMO_OR_MOCK,
    }
    assert all(e["kind"] == "weather" for e in excluded)


def test_partition_of_nothing_is_empty_not_an_error():
    assert pit.partition(None, AS_OF) == ([], [])


# ---------------------------------------------------------------------- digests

def test_digest_is_stable_across_key_ordering():
    a = pit.digest_of({"x": 1, "y": [2, 3]}, "ns")
    b = pit.digest_of({"y": [2, 3], "x": 1}, "ns")
    assert a == b


def test_namespace_changes_the_digest():
    payload = {"x": 1}
    assert pit.digest_of(payload, "v1") != pit.digest_of(payload, "v2")


def test_risk_snapshot_digests_are_byte_identical_after_the_move():
    """The pilot's stored digests must survive the extraction unchanged.

    A stored assessment references its snapshot by digest; if the hash moved, every
    historical assessment would stop reconciling with its own inputs.
    """
    payload = {"snapshot_version": risk_snapshot.SNAPSHOT_VERSION, "as_of": "2026-07-20", "w": [1]}
    assert risk_snapshot.digest_of(payload) == pit.digest_of(
        payload, risk_snapshot.SNAPSHOT_VERSION
    )


def test_risk_snapshot_still_exports_the_pilot_vocabulary():
    """Re-exports, so BOTRYTIS_PILOT.md's contract and existing imports are unchanged."""
    assert risk_snapshot.admissible is pit.admissible
    assert risk_snapshot.EXCLUDED_RECORDED_LATE == pit.EXCLUDED_RECORDED_LATE
    assert risk_snapshot._superseded_ids is pit.superseded_ids
