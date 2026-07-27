"""Product identity, rate conversion and label-record resolution.

The load-bearing tests here are the refusals. This module's job is to decide when a
label value may drive a regulatory check on a real farm, and every one of its failure
modes produces something that LOOKS like an answer: a related product's PHI, a converted
rate with an invented density, a transcription nobody checked. So the assertions are
mostly that a plausible-looking answer is withheld and a reason is returned instead.
"""
from datetime import date
from types import SimpleNamespace

import pytest

from app import crop_aliases, label_data


def _record(**overrides):
    """A fully-provenanced transcribed record — the promotable baseline minus a PCA."""
    row = {
        "id": 1,
        "registered_crop": "Strawberries",
        "registered_crop_normalized": "strawberries",
        "pre_harvest_interval_days": 3,
        "re_entry_interval_hours": 24,
        "max_seasonal_rate_amount": None,
        "max_applications_per_season": None,
        "min_retreatment_interval_days": None,
        "label_version": "rev. 2025-03",
        "label_effective_date": date(2025, 3, 1),
        "source_tier": label_data.TIER_TRANSCRIBED,
        "source_document_reference": "EPA Reg. No. 100-1234 label, master rev. 2025-03",
        "source_section_or_page": "Directions for Use, p. 7",
        "source_snippet": "Do not apply within 3 days of harvest.",
        "supersedes_label_record_id": None,
    }
    row.update(overrides)
    return SimpleNamespace(**row)


def _verification(**overrides):
    row = {
        "revoked_at": None,
        "verified_by_credential_id": 5,
        "data_source": "manual_entry",
        "data_confidence": "user_provided",
    }
    row.update(overrides)
    return SimpleNamespace(**row)


# ----------------------------------------------------------------- product identity
def test_normalization_strips_formatting_but_never_the_hyphen_structure():
    assert label_data.normalize_epa_reg_no("  100-1234-5905. ") == "100-1234-5905"
    assert label_data.normalize_epa_reg_no("100-1234") == "100-1234"
    assert label_data.normalize_epa_reg_no(None) == ""


def test_a_supplemental_registration_is_ambiguous_never_a_match():
    """The single most dangerous thing this feature could do is apply the wrong label.

    100-1234 and 100-1234-5905 share a registrant and a product family and have
    DIFFERENT use directions. A base match is a signal for a human, never equivalence.
    """
    assert label_data.match_product_identity("100-1234", "100-1234") == label_data.MATCH
    assert (
        label_data.match_product_identity("100-1234", "100-1234-5905")
        == label_data.AMBIGUOUS
    )
    assert label_data.match_product_identity("100-1234", "352-9999") == label_data.NO_MATCH
    assert label_data.match_product_identity("100-1234", None) == label_data.NO_MATCH


def test_epa_reg_base_is_the_first_two_segments_only():
    assert label_data.epa_reg_base("100-1234-5905") == "100-1234"
    assert label_data.epa_reg_base("100-1234") == "100-1234"
    assert label_data.epa_reg_base("") == ""


# --------------------------------------------------------------------- rate units
def test_only_curated_spellings_resolve_to_a_canonical_unit():
    assert label_data.canonical_rate_unit("oz/A") == "oz/acre"
    assert label_data.canonical_rate_unit("  FL OZ / acre ") == "fl oz/acre"
    # Not in the dictionary. Never pattern-matched into one.
    assert label_data.canonical_rate_unit("oz per hectare") is None
    assert label_data.canonical_rate_unit("widgets/acre") is None


def test_every_conversion_carries_a_citation_and_a_matching_inverse():
    """A factor without a source is indistinguishable from a factor someone recalled."""
    for (source, target), conversion in label_data.RATE_CONVERSIONS.items():
        assert conversion.citation.strip(), f"{source}->{target} has no citation"
        inverse = label_data.RATE_CONVERSIONS.get((target, source))
        assert inverse is not None, f"{source}->{target} has no inverse"
        assert conversion.factor * inverse.factor == pytest.approx(1.0)


def test_mass_to_volume_is_absent_and_is_refused_rather_than_guessed():
    """oz/acre -> fl oz/acre needs a per-product density. It is not on the label."""
    assert ("oz/acre", "fl oz/acre") not in label_data.RATE_CONVERSIONS
    result = label_data.convert_rate(4.0, "oz/acre", "fl oz/acre")
    assert isinstance(result, label_data.Refusal)
    assert "no cited conversion" in result.reason


def test_an_unknown_unit_is_refused_by_name():
    result = label_data.convert_rate(1.0, "scoops/acre", "oz/acre")
    assert isinstance(result, label_data.Refusal)
    assert "scoops/acre" in result.reason


def test_a_definitional_conversion_returns_the_amount_with_its_citation():
    result = label_data.convert_rate(2.0, "lb/A", "oz/acre")
    assert isinstance(result, label_data.Converted)
    assert result.amount == pytest.approx(32.0)
    assert result.unit == "oz/acre"
    assert result.conversion_provenance == (
        "definition: 1 avoirdupois pound = 16 ounces",
    )


def test_an_identical_unit_converts_with_no_provenance_to_report():
    result = label_data.convert_rate(5.0, "oz/acre", "oz/A")
    assert isinstance(result, label_data.Converted)
    assert (result.amount, result.conversion_provenance) == (5.0, ())


# --------------------------------------------------------------- record resolution
def test_a_revision_supersedes_its_predecessor():
    old = _record(id=1, pre_harvest_interval_days=3)
    new = _record(id=2, pre_harvest_interval_days=7, supersedes_label_record_id=1)

    record, reason = label_data.resolve_label_record([old, new], "strawberry")

    assert reason is None
    assert record.id == 2 and record.pre_harvest_interval_days == 7


def test_a_withdrawal_row_resolves_to_nothing_so_the_check_goes_back_to_not_evaluated():
    """A withdrawal is a row with every regulatory value blank — never a delete.

    The point is that the checks return to reporting they did not run, rather than
    silently keeping the withdrawn label's numbers.
    """
    old = _record(id=1)
    withdrawal = _record(
        id=2,
        pre_harvest_interval_days=None,
        re_entry_interval_hours=None,
        supersedes_label_record_id=1,
    )

    record, reason = label_data.resolve_label_record([old, withdrawal], "strawberry")

    assert record is None
    assert "states no regulatory values" in reason


def test_an_alias_matches_but_a_containment_is_refused_as_ambiguous():
    record, reason = label_data.resolve_label_record([_record()], "strawberry")
    assert reason is None and record is not None

    record, reason = label_data.resolve_label_record(
        [_record(registered_crop="strawberry tree")], "strawberry"
    )
    assert record is None
    assert "not the same registration" in reason


def test_no_records_and_no_crop_match_report_different_reasons():
    record, reason = label_data.resolve_label_record([], "strawberry")
    assert record is None and reason == "no label record on file for this product"

    record, reason = label_data.resolve_label_record([_record()], "lettuce")
    assert record is None and "no label record on file for crop" in reason


# ------------------------------------------------------------------- promotability
def test_a_transcription_is_not_promotable_until_a_pca_verifies_it_for_the_farm():
    reason = label_data.promotable_to_authoritative(_record(), verifications=[])
    assert reason is not None
    assert "no licensed PCA has verified" in reason

    assert (
        label_data.promotable_to_authoritative(_record(), [_verification()]) is None
    )


def test_a_revoked_verification_does_not_promote():
    reason = label_data.promotable_to_authoritative(
        _record(), [_verification(revoked_at="2026-07-01T00:00:00")]
    )
    assert "no licensed PCA has verified" in reason


def test_a_simulated_verification_can_never_make_a_value_label_verified():
    """This is what keeps the demo honest with no special case in the engine.

    Verifications are farm records, so `ensure_demo_real_separation` means a demo farm
    can only ever hold a simulated one — and it is refused here.
    """
    reason = label_data.promotable_to_authoritative(
        _record(), [_verification(data_confidence="simulated")]
    )
    assert "simulated demo record" in reason

    reason = label_data.promotable_to_authoritative(
        _record(), [_verification(data_source="demo")]
    )
    assert "simulated demo record" in reason


@pytest.mark.parametrize("missing", label_data.REQUIRED_PROVENANCE_FIELDS)
def test_a_record_missing_any_required_provenance_field_cannot_back_a_check(missing):
    reason = label_data.promotable_to_authoritative(
        _record(**{missing: None}), [_verification()]
    )
    assert reason is not None
    assert missing.replace("_", " ") in reason


def test_an_unrecognized_source_tier_is_refused():
    reason = label_data.promotable_to_authoritative(
        _record(source_tier="looks_official"), [_verification()]
    )
    assert "unrecognized source tier" in reason


def test_a_provider_feed_needs_no_per_farm_verification_but_a_transcription_does():
    assert (
        label_data.promotable_to_authoritative(
            _record(source_tier=label_data.TIER_PROVIDER_FEED), verifications=[]
        )
        is None
    )
    assert (
        label_data.promotable_to_authoritative(
            _record(source_tier=label_data.TIER_AI_EXTRACTED), verifications=[]
        )
        is not None
    )


def test_only_verified_tiers_map_to_the_authoritative_input_source():
    """A human typing from a PDF is `imported_unverified`, however careful they were."""
    assert set(label_data.LABEL_TIER_TO_INPUT_SOURCE) == set(label_data.LABEL_SOURCE_TIERS)
    authoritative = {
        tier
        for tier, source in label_data.LABEL_TIER_TO_INPUT_SOURCE.items()
        if source == label_data.SOURCE_AUTHORITATIVE
    }
    assert authoritative == {label_data.TIER_PCA_VERIFIED, label_data.TIER_PROVIDER_FEED}


# ------------------------------------------------------------------- addressing
def test_the_transcription_digest_ignores_key_order_but_not_values():
    a = label_data.transcription_digest({"phi": 3, "crop": "strawberry"})
    b = label_data.transcription_digest({"crop": "strawberry", "phi": 3})
    c = label_data.transcription_digest({"crop": "strawberry", "phi": 7})

    assert a == b
    assert a != c


def test_crop_aliases_verdict_vocabulary_is_shared_with_this_module():
    """Callers switch on one set of verdicts; two vocabularies would invite a miss."""
    assert (label_data.MATCH, label_data.AMBIGUOUS, label_data.NO_MATCH) == (
        crop_aliases.MATCH,
        crop_aliases.AMBIGUOUS,
        crop_aliases.NO_MATCH,
    )
