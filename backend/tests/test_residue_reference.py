"""Invariants for the USDA PDP residue reference layer.

Every test here is about a way empirical residue data could turn into something it is
not: a zero standing in for an unmeasured pair, a national statistic reading as a
statement about one farm, a secondary-source tolerance outranking a transcribed label, a
detection rate quoted without the release year that makes it meaningful, or the layer
growing a field that tells somebody whether to spray.

The PDP fixtures below are SYNTHETIC — small hand-built releases that exercise the
machinery. They are not USDA's published figures and must never be copied anywhere that
presents them as measurements. Loading a real release is `python -m app.pdp_sync`.
"""
from types import SimpleNamespace

import pytest

from app import crud, pdp_dataset, residue_reference as rr
from app.database import SessionLocal
from app.refusal import Refusal


def row(**kw):
    """A ResidueRow stand-in. Defaults describe a plausible, fully-populated pair."""
    base = dict(
        commodity_code="ST",
        commodity_name="Strawberries",
        commodity_type="FR",
        pesticide_code="B22",
        pesticide_name="Cyprodinil",
        program_year=2016,
        samples_tested=100,
        samples_with_detection=50,
        max_concentration=1.7,
        median_detected_concentration=0.07,
        concentration_unit="ppm",
        unit_conflict=False,
        domestic_only=True,
        epa_tolerance_value=5.0,
        epa_tolerance_basis=None,
        tolerance_unit="ppm",
        source_reference="USDA PDP 2016 (synthetic fixture)",
        source_digest="deadbeef",
    )
    base.update(kw)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# The invariant that matters most: absence is never zero.
# ---------------------------------------------------------------------------

def test_unanalysed_pair_refuses_rather_than_reporting_zero_detections():
    """A compound that was never on the panel must refuse, not report 0%.

    This is the inversion this layer exists to prevent. "0% of strawberry samples had
    emamectin benzoate" reads as evidence the compound is not a residue concern; the
    truth is that nobody looked. A grower could reasonably spray MORE on the strength of
    the false reading.
    """
    rows = [row(), row(commodity_code="TO", commodity_name="Tomatoes",
                       pesticide_code="A99", pesticide_name="Emamectin benzoate")]

    result = rr.lookup(crop="strawberry", active_ingredient="Emamectin benzoate",
                       rows=rows, current_year=2026)

    assert isinstance(result, Refusal)
    assert result.code == rr.PESTICIDE_NOT_ANALYSED
    assert not hasattr(result, "value")
    # The distinction has to survive into the prose a human reads, not just the code.
    assert "not tested" in result.detail or "not on the analytical panel" in result.detail


def test_aggregate_omits_pairs_that_were_never_assayed():
    """The parser must not emit a 0/0 aggregate for an unanalysed pair."""
    samples = {"1": pdp_dataset.SampleRow(
        sample_pk="1", commodity_code="ST", commodity_type="FR",
        origin="1", country="", grower_state="CA", collected_state="CA",
    )}
    results = [("1", "ST", "FR", "B22", None, "M")]  # one assay, a non-detect

    aggs = pdp_dataset.aggregate(samples, results, program_year=2016)

    assert [a.pesticide_code for a in aggs] == ["B22"]
    only = aggs[0]
    # Assayed once, detected never: the denominator counts the non-detect.
    assert only.samples_tested == 1
    assert only.samples_with_detection == 0
    assert only.detection_rate == 0.0
    # But no maximum is invented for an empty set of detections.
    assert only.max_concentration is None
    assert only.median_detected_concentration is None


def test_non_detects_count_in_the_denominator():
    """Detection rate is detections/assays, not detections/detections.

    Counting only rows with a number would report 100% for every compound ever found —
    the single most misleading figure this dataset can produce.
    """
    samples = {
        str(i): pdp_dataset.SampleRow(
            sample_pk=str(i), commodity_code="ST", commodity_type="FR",
            origin="1", country="", grower_state="CA", collected_state="CA",
        )
        for i in range(1, 5)
    }
    results = [
        ("1", "ST", "FR", "B22", 0.5, "M"),
        ("2", "ST", "FR", "B22", None, "M"),
        ("3", "ST", "FR", "B22", None, "M"),
        ("4", "ST", "FR", "B22", None, "M"),
    ]

    agg = pdp_dataset.aggregate(samples, results, program_year=2016)[0]

    assert agg.samples_tested == 4
    assert agg.samples_with_detection == 1
    assert agg.detection_rate == 0.25


# ---------------------------------------------------------------------------
# The layer must never become a recommendation.
# ---------------------------------------------------------------------------

def test_profile_cannot_express_a_verdict_or_an_action():
    """No field may hold a band, score, verdict, product or action.

    Same technique as `disease_risk.RiskAssessment` (ENGINEERING_GUIDELINES.md §4): the guarantee is that
    there is nowhere to put a prescription, not that nobody currently writes one. If this
    test fails, someone added a field that lets this layer tell a grower what to do.
    """
    profile = rr.lookup(crop="strawberry", active_ingredient="Cyprodinil",
                        rows=[row()], current_year=2026)
    assert isinstance(profile, rr.ResidueProfile)

    # Matched on underscore-separated TOKENS, not substrings: `detection_rate` is a
    # legitimate statistic, while an `application_rate` would be a prescription. A
    # substring check cannot tell those apart and would forbid the honest one.
    forbidden_tokens = {
        "verdict", "band", "risk", "score", "action", "recommendation", "recommended",
        "product", "spray", "safe", "advice", "dose", "prescription", "application",
    }
    for name in vars(profile):
        tokens = set(name.lower().split("_"))
        overlap = tokens & forbidden_tokens
        assert not overlap, (
            f"ResidueProfile.{name} (token {overlap}) lets a national residue statistic "
            f"carry a recommendation. Residue context informs a PCA conversation; it "
            f"never decides an application."
        )


def test_authority_is_weaker_than_a_verified_label():
    """A USDA-transcribed EPA tolerance is a secondary source and must say so."""
    profile = rr.lookup(crop="strawberry", active_ingredient="Cyprodinil",
                        rows=[row()], current_year=2026)
    assert profile.authority == rr.AUTHORITY_REFERENCE_DATASET
    assert profile.authority not in {"verified_label", "pca_entered"}


# ---------------------------------------------------------------------------
# Staleness, tolerances, and units.
# ---------------------------------------------------------------------------

def test_staleness_is_reported_and_reaches_the_rendered_sentence():
    """A 2016 measurement is still real, so this does not refuse — but the age of the
    release cannot be droppable by a caller that only wanted the percentage."""
    profile = rr.lookup(crop="strawberry", active_ingredient="Cyprodinil",
                        rows=[row(program_year=2016)], current_year=2026)

    assert profile.years_since_program == 10
    text = rr.basis_text(profile)
    assert "2016" in text and "10 year" in text


def test_most_recent_release_wins_and_years_are_not_averaged():
    """Blending releases would produce a figure belonging to no analytical panel."""
    rows = [row(program_year=2014, samples_with_detection=10, samples_tested=100),
            row(program_year=2016, samples_with_detection=50, samples_tested=100)]

    profile = rr.lookup(crop="strawberry", active_ingredient="Cyprodinil",
                        rows=rows, current_year=2026)

    assert profile.program_year == 2016
    assert profile.detection_rate == 0.5


def test_non_numeric_tolerance_never_becomes_a_number_or_no_limit():
    """NT means "no tolerance established", which is stricter than a number — not laxer.

    Rendering it as a null/absent limit would invert its meaning entirely.
    """
    profile = rr.lookup(
        crop="strawberry", active_ingredient="Cyprodinil",
        rows=[row(epa_tolerance_value=None, epa_tolerance_basis="NT", tolerance_unit=None)],
        current_year=2026,
    )

    assert profile.epa_tolerance_value is None
    assert profile.epa_tolerance_basis == "NT"
    assert profile.max_as_share_of_tolerance is None
    assert "NO tolerance" in profile.tolerance_note
    assert "not mean there is no limit" in profile.tolerance_note


def test_share_of_tolerance_refuses_a_cross_unit_comparison():
    """ppm against ppb without a cited conversion is a fabricated ratio."""
    profile = rr.lookup(
        crop="strawberry", active_ingredient="Cyprodinil",
        rows=[row(concentration_unit="ppm", tolerance_unit="ppb")],
        current_year=2026,
    )
    assert profile.max_as_share_of_tolerance is None


def test_unit_conflict_suppresses_statistics_entirely():
    profile_or_refusal = rr.lookup(
        crop="strawberry", active_ingredient="Cyprodinil",
        rows=[row(unit_conflict=True, max_concentration=None)],
        current_year=2026,
    )
    assert isinstance(profile_or_refusal, Refusal)
    assert profile_or_refusal.code == rr.UNIT_CONFLICT


def test_aggregate_suppresses_max_when_units_disagree():
    samples = {
        s: pdp_dataset.SampleRow(sample_pk=s, commodity_code="ST", commodity_type="FR",
                                 origin="1", country="", grower_state="CA",
                                 collected_state="CA")
        for s in ("1", "2")
    }
    results = [("1", "ST", "FR", "B22", 1.0, "M"), ("2", "ST", "FR", "B22", 900.0, "B")]

    agg = pdp_dataset.aggregate(samples, results, program_year=2016)[0]

    assert agg.unit_conflict is True
    assert agg.max_concentration is None  # a max across ppm and ppb is not a max


# ---------------------------------------------------------------------------
# Crop and compound matching stay exact-or-refuse.
# ---------------------------------------------------------------------------

def test_containment_is_ambiguous_never_a_match():
    """`strawberry tree` must not inherit strawberry's residue findings."""
    result = rr.lookup(crop="strawberry tree", active_ingredient="Cyprodinil",
                       rows=[row()], current_year=2026)
    assert isinstance(result, Refusal)
    assert result.code in {rr.CROP_MATCH_AMBIGUOUS, rr.CROP_NOT_IN_PROGRAM}


def test_usda_spelling_matches_our_crop_vocabulary():
    """USDA writes "Strawberries"; the farm record says "strawberry"."""
    profile = rr.lookup(crop="strawberry", active_ingredient="Cyprodinil",
                        rows=[row(commodity_name="Strawberries")], current_year=2026)
    assert isinstance(profile, rr.ResidueProfile)
    assert profile.commodity_name == "Strawberries"


def test_crop_outside_the_programme_refuses_distinctly():
    result = rr.lookup(crop="artichoke", active_ingredient="Cyprodinil",
                       rows=[row()], current_year=2026)
    assert isinstance(result, Refusal)
    assert result.code == rr.CROP_NOT_IN_PROGRAM
    assert "not a finding of low residue" in result.detail.lower()


def test_empty_reference_refuses_with_an_operator_actionable_code():
    result = rr.lookup(crop="strawberry", active_ingredient="Cyprodinil",
                       rows=[], current_year=2026)
    assert isinstance(result, Refusal)
    assert result.code == rr.NO_RESIDUE_REFERENCE_LOADED
    assert "pdp_sync" in result.detail


# ---------------------------------------------------------------------------
# Parser contract.
# ---------------------------------------------------------------------------

def test_malformed_release_raises_rather_than_misreading_columns():
    """A release whose layout moved must fail loudly, not map columns by guesswork."""
    with pytest.raises(pdp_dataset.PdpFormatError):
        pdp_dataset.parse_samples(["1|CA|24|01"])  # far too few fields

    with pytest.raises(pdp_dataset.PdpFormatError):
        list(pdp_dataset.iter_results(["1|AL|FR"]))


def test_imported_samples_are_excluded_when_domestic_only():
    """An imported sample reflects another country's practice and another regulator."""
    samples = {
        "1": pdp_dataset.SampleRow(sample_pk="1", commodity_code="ST", commodity_type="FR",
                                   origin="1", country="", grower_state="CA",
                                   collected_state="CA"),
        "2": pdp_dataset.SampleRow(sample_pk="2", commodity_code="ST", commodity_type="FR",
                                   origin="2", country="MEX", grower_state="",
                                   collected_state="CA"),
    }
    results = [("1", "ST", "FR", "B22", None, "M"), ("2", "ST", "FR", "B22", 9.9, "M")]

    agg = pdp_dataset.aggregate(samples, results, program_year=2016, domestic_only=True)[0]

    assert agg.samples_tested == 1
    assert agg.samples_with_detection == 0
    assert agg.domestic_only is True


def test_result_without_its_sample_is_skipped_not_assumed_domestic():
    """Without the sample row we cannot know origin; assuming it inflates the denominator."""
    results = [("999", "ST", "FR", "B22", 1.0, "M")]
    assert pdp_dataset.aggregate({}, results, program_year=2016, domestic_only=True) == []


# ---------------------------------------------------------------------------
# Route behaviour.
# ---------------------------------------------------------------------------

def _load_one_row(**kw):
    db = SessionLocal()
    try:
        agg = pdp_dataset.ResidueAggregate(
            commodity_code="ST", commodity_type="FR", pesticide_code="B22",
            program_year=2016, samples_tested=100, samples_with_detection=50,
            max_concentration=kw.get("max_concentration", 1.7),
            median_detected_concentration=0.07,
            concentration_unit=kw.get("concentration_unit", "ppm"),
            unit_conflict=False, domestic_only=True,
        )
        return crud.load_residue_reference(
            db, [agg],
            commodity_names={"ST": "Strawberries"},
            pesticide_names={"B22": "Cyprodinil"},
            tolerances={("B22", "ST"): (5.0, None, "ppm")},
            source_reference="USDA PDP 2016 (synthetic fixture)",
            source_digest="digest-a",
        )
    finally:
        db.close()


def test_route_returns_profile_with_server_owned_wording(client):
    _load_one_row()

    resp = client.get("/residue-reference",
                      params={"crop": "strawberry", "active_ingredient": "Cyprodinil"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["refused"] is False
    assert body["samples_tested"] == 100
    assert body["max_as_share_of_tolerance"] == pytest.approx(0.34)
    # basis_text is built server-side so the release year has exactly one home.
    assert "2016" in body["basis_text"]
    assert "Decision support only" in body["disclaimer"]


def test_route_omits_concentration_keys_entirely_when_nothing_detected(client):
    """A null numeric key is what a template turns into 0 — so the key is absent.

    Mirrors the `/data-readiness` rule: an abstention renders as its reason, never as a
    number-shaped placeholder.
    """
    db = SessionLocal()
    try:
        agg = pdp_dataset.ResidueAggregate(
            commodity_code="ST", commodity_type="FR", pesticide_code="B22",
            program_year=2016, samples_tested=100, samples_with_detection=0,
            max_concentration=None, median_detected_concentration=None,
            concentration_unit=None, unit_conflict=False, domestic_only=True,
        )
        crud.load_residue_reference(
            db, [agg], commodity_names={"ST": "Strawberries"},
            pesticide_names={"B22": "Cyprodinil"},
            tolerances={}, source_reference="synthetic", source_digest="digest-b",
        )
    finally:
        db.close()

    body = client.get("/residue-reference",
                      params={"crop": "strawberry",
                              "active_ingredient": "Cyprodinil"}).json()

    assert body["samples_with_detection"] == 0
    assert "max_concentration" not in body
    assert "median_detected_concentration" not in body


def test_route_refusal_carries_a_matchable_code(client):
    body = client.get("/residue-reference",
                      params={"crop": "strawberry",
                              "active_ingredient": "Cyprodinil"}).json()
    assert body["refused"] is True
    assert body["code"] == rr.NO_RESIDUE_REFERENCE_LOADED
    assert "value" not in body


def test_loading_the_same_release_twice_creates_no_second_row(client):
    first = _load_one_row()
    second = _load_one_row()
    assert first["records_created"] == 1
    assert second["records_created"] == 0
    assert second["unchanged"] == 1


def test_aggregate_without_a_name_is_skipped_not_written_with_its_code(client):
    """A row named 'B22' cannot be matched by any caller and silently shrinks coverage."""
    db = SessionLocal()
    try:
        agg = pdp_dataset.ResidueAggregate(
            commodity_code="ST", commodity_type="FR", pesticide_code="ZZZ",
            program_year=2016, samples_tested=10, samples_with_detection=1,
            max_concentration=0.1, median_detected_concentration=0.1,
            concentration_unit="ppm", unit_conflict=False, domestic_only=True,
        )
        result = crud.load_residue_reference(
            db, [agg], commodity_names={"ST": "Strawberries"},
            pesticide_names={},  # ZZZ has no published name
            tolerances={}, source_reference="synthetic", source_digest="digest-c",
        )
    finally:
        db.close()

    assert result["records_created"] == 0
    assert result["skipped_unnamed"] == 1


def test_coverage_route_is_operator_gated_by_path_prefix(client):
    """It lives under /internal so the operator-key middleware covers it by construction."""
    resp = client.get("/internal/residue-reference-coverage")
    # Without a configured key the middleware leaves /internal open (dev default), so the
    # assertion that matters is the path, not the status: this route must never be
    # reachable outside /internal.
    assert resp.status_code in (200, 403)
    assert any(
        r.path == "/internal/residue-reference-coverage"
        for r in client.app.routes if hasattr(r, "path")
    )
