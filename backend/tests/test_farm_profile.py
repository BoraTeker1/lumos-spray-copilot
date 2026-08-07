"""The cross-layer profile: abstains per field, and says whose job each gap is.

On today's data every layer refuses, so the profile is almost entirely `blocking_gaps` —
which is the honest picture and the useful one. These tests pin that it stays that shape
rather than growing an aggregate.
"""
import pytest

from app import farm_profile
from app.refusal import NO_DATA_FOR_FARM, NO_SOURCE_TRANSCRIBED, Refusal


def _refusal(code=NO_SOURCE_TRANSCRIBED):
    return Refusal(code, "detail that explains what to do about it")


class FakeResult:
    def as_payload(self):
        return {"ok": True}


def test_a_layer_view_must_carry_exactly_one_of_result_or_refusal():
    with pytest.raises(ValueError, match="exactly one of result or refusal"):
        farm_profile.LayerView(layer="finance", label="Finance")

    with pytest.raises(ValueError, match="exactly one of result or refusal"):
        farm_profile.LayerView(
            layer="finance", label="Finance", result=FakeResult(), refusal=_refusal()
        )


def test_a_none_outcome_is_rejected_rather_than_rendering_as_an_empty_card():
    with pytest.raises(ValueError, match="never None"):
        farm_profile.build(farm_id=1, views=[("finance", "Finance", None)])


def test_refusals_become_blocking_gaps_with_an_owner():
    profile = farm_profile.build(farm_id=1, views=[
        ("finance", "Finance", _refusal(NO_SOURCE_TRANSCRIBED)),
        ("operations", "Operations", _refusal(NO_DATA_FOR_FARM)),
    ])

    owners = {g.layer: g.owner for g in profile.blocking_gaps}
    assert owners["finance"] == farm_profile.OWNER_OPERATOR
    assert owners["operations"] == farm_profile.OWNER_GROWER


def test_gaps_are_grouped_by_owner_so_a_card_can_split_them():
    """A grower staring at five empty cards cannot tell which are waiting on them."""
    payload = farm_profile.build(farm_id=1, views=[
        ("finance", "Finance", _refusal(NO_SOURCE_TRANSCRIBED)),
        ("operations", "Operations", _refusal(NO_DATA_FOR_FARM)),
    ]).as_payload()

    assert len(payload["gaps_by_owner"][farm_profile.OWNER_GROWER]) == 1
    assert len(payload["gaps_by_owner"][farm_profile.OWNER_OPERATOR]) == 1


def test_an_unmapped_refusal_code_is_undetermined_not_silently_the_growers_problem():
    profile = farm_profile.build(farm_id=1, views=[
        ("market", "Market", Refusal("some_new_code", "a code nobody mapped yet")),
    ])
    assert profile.blocking_gaps[0].owner == farm_profile.OWNER_UNDETERMINED


def test_available_layers_are_listed_separately_from_gaps():
    profile = farm_profile.build(farm_id=1, views=[
        ("operations", "Operations", FakeResult()),
        ("finance", "Finance", _refusal()),
    ])
    assert profile.available_layers == ("operations",)
    assert len(profile.blocking_gaps) == 1


def test_the_profile_computes_nothing_across_layers():
    """No score, no readiness percentage — an average over abstentions is meaningless."""
    payload = farm_profile.build(farm_id=1, views=[
        ("operations", "Operations", FakeResult()),
        ("finance", "Finance", _refusal()),
    ]).as_payload()

    def walk(node, keys=None):
        keys = keys if keys is not None else set()
        if isinstance(node, dict):
            for k, v in node.items():
                keys.add(str(k))
                if k != "not_calculated":
                    walk(v, keys)
        elif isinstance(node, (list, tuple)):
            for item in node:
                walk(item, keys)
        return keys

    for forbidden in ("overall_score", "readiness_pct", "readiness_percentage",
                      "total_score", "health_score", "grade"):
        assert forbidden not in walk(payload), forbidden

    assert "overall_score" in payload["not_calculated"]
    assert "readiness_percentage" in payload["not_calculated"]


def test_an_unknown_layer_is_rejected():
    with pytest.raises(ValueError, match="unknown layer"):
        farm_profile.LayerView(layer="marketing", label="x", result=FakeResult())
