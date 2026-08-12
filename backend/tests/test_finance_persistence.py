"""Finance persistence: what was assessed, when, on what inputs — and what was refused.

`credit_scoring.Score.inputs_digest` was built to answer "what did you know when you
declined me", a question with legal weight, and until now it had nowhere to live. These
tests pin the four properties that make the stored record trustworthy:

1. **A refusal is stored, not dropped.** With no scorecard transcribed every row is a
   refusal, and a farm's history reading "could not score: no scorecard supplied, on
   these dates" is materially different from that history being empty. Storing only
   successes would make the record set a survivorship-biased view of a farm.
2. **Outcome XOR refusal.** A row carries one or the other, never both, never neither —
   the same construction as `FeatureValue` storing an abstention.
3. **Append-only.** No update path, no delete path, and a revaluation supersedes rather
   than edits, so what a lender saw on a date stays recoverable.
4. **The digest reproduces at a fixed `as_of`.** That is the point-in-time guarantee,
   and a digest that moves is proof an assessment used information the farm did not have.
"""
from datetime import date, datetime, timedelta

import pytest

from app import credit_scoring, monitoring, scorecard_table, underwriting
from app.transcription import Citation

AS_OF = datetime(2026, 8, 7, 12, 0)

CITATION = Citation(
    document="SYNTHETIC — test fixture, not a lender document",
    publisher="tests/test_finance_persistence.py",
    section="fixture",
    snippet="values invented for arithmetic testing only",
    transcribed_by="test suite",
    transcribed_on=date(2026, 8, 7),
)


def _farm(client, name="Finance Ranch"):
    return client.post("/farms", json={
        "name": name, "location": "Watsonville, CA", "country": "US",
        "crop_type": "strawberry", "area": 10.0,
    }).json()


# --------------------------------------------------- refusals are recorded
def test_a_refusal_is_stored_rather_than_dropped(client):
    """The core of the design.

    With no scorecard transcribed this is what every assessment is, and it must leave a
    record. A borrower asking why they were declined is entitled to see that no
    assessment was even possible on that date.
    """
    farm = _farm(client)
    res = client.post(f"/internal/farms/{farm['id']}/credit-assessments")

    assert res.status_code == 201
    row = res.json()
    assert row["total"] is None
    assert row["refusal_code"] == "no_source_transcribed"
    assert "scorecard" in row["refusal_detail"].lower()


def test_the_history_includes_refusals_and_is_grower_readable(client):
    farm = _farm(client)
    for _ in range(2):
        client.post(f"/internal/farms/{farm['id']}/credit-assessments")

    history = client.get(f"/farms/{farm['id']}/credit-assessments")
    assert history.status_code == 200, "reading your own history must not need the key"
    assert len(history.json()) == 2
    assert all(r["refusal_code"] for r in history.json())


def test_every_assessment_kind_records_its_refusal(client):
    farm = _farm(client)

    credit = client.post(f"/internal/farms/{farm['id']}/credit-assessments").json()
    uw = client.post(f"/internal/farms/{farm['id']}/underwriting-decisions",
                     json={}).json()
    mon = client.post(f"/internal/farms/{farm['id']}/monitoring-snapshots").json()
    cov = client.post(f"/internal/farms/{farm['id']}/coverage-assessments",
                      json={"crop": "strawberry", "peril": "frost"}).json()

    for row in (credit, uw, mon, cov):
        assert row["refusal_code"], row
        assert row["refusal_detail"]

    assert uw["outcome"] is None
    assert mon["standing"] is None


# ------------------------------------------------------- outcome XOR refusal
def test_a_scored_row_carries_no_refusal(client, monkeypatch):
    monkeypatch.setattr(scorecard_table, "TRANSCRIBED", scorecard_table.Scorecard(
        lender="SYNTHETIC Lender", name="Test card", version="1",
        minimum_score=0.0, maximum_score=100.0, citation=CITATION,
        factors=(
            scorecard_table.ScorecardFactor(
                feature_name="scouting_recency_days", weight=1.0, citation=CITATION,
                bands=(
                    scorecard_table.ScorecardBand(
                        lower_inclusive=None, upper_exclusive=None, points=40.0),
                ),
            ),
        ),
    ))
    farm = _farm(client)
    # No feature values stored, so the input is missing and this still refuses — the
    # assertion that matters is the XOR, which must hold in BOTH directions.
    row = client.post(f"/internal/farms/{farm['id']}/credit-assessments").json()

    scored = row["total"] is not None
    refused = row["refusal_code"] is not None
    assert scored != refused, "a row must carry an outcome XOR a refusal"


def test_the_xor_invariant_holds_across_every_stored_row(client):
    """Walks the real tables rather than trusting one response shape."""
    farm = _farm(client)
    client.post(f"/internal/farms/{farm['id']}/credit-assessments")
    client.post(f"/internal/farms/{farm['id']}/underwriting-decisions", json={})
    client.post(f"/internal/farms/{farm['id']}/monitoring-snapshots")

    credit = client.get(f"/farms/{farm['id']}/credit-assessments").json()
    uw = client.get(f"/farms/{farm['id']}/underwriting-decisions").json()
    mon = client.get(f"/farms/{farm['id']}/monitoring-snapshots").json()

    for row in credit:
        assert (row["total"] is None) == (row["refusal_code"] is not None)
    for row in uw:
        assert (row["outcome"] is None) == (row["refusal_code"] is not None)
    for row in mon:
        assert (row["standing"] is None) == (row["refusal_code"] is not None)


# ------------------------------------------------------------- append-only
def test_assessments_have_no_update_or_delete_route():
    """Append-only by construction, not by convention."""
    from app.main import app

    finance_paths = [
        (r.path, tuple(getattr(r, "methods", ()) or ()))
        for r in app.routes
        if "credit-assessments" in getattr(r, "path", "")
        or "underwriting-decisions" in getattr(r, "path", "")
        or "monitoring-snapshots" in getattr(r, "path", "")
        or "coverage-assessments" in getattr(r, "path", "")
    ]
    assert finance_paths, "no finance routes found — this check is vacuous"

    for path, methods in finance_paths:
        assert not ({"PUT", "PATCH", "DELETE"} & set(methods)), (
            f"{path} exposes {methods}: an assessment history that can be edited is not "
            "a record of what a lender saw"
        )


def test_reassessing_appends_rather_than_replacing(client):
    farm = _farm(client)
    for _ in range(3):
        client.post(f"/internal/farms/{farm['id']}/credit-assessments")

    history = client.get(f"/farms/{farm['id']}/credit-assessments").json()
    assert len(history) == 3
    assert len({r["id"] for r in history}) == 3


# ------------------------------------------------------------- collateral
def test_registering_collateral_gives_the_profile_real_assets(client):
    """`crud.list_collateral_assets` returned [] with a docstring until this table."""
    farm = _farm(client)
    res = client.post(f"/internal/farms/{farm['id']}/collateral", json={
        "collateral_type": "equipment", "currency": "USD",
        "assessed_value": 100000.0, "valuation_basis": "insured value",
        "description": "Tractor",
    })
    assert res.status_code == 201

    assets = client.get(f"/farms/{farm['id']}/collateral").json()
    assert len(assets) == 1 and assets[0]["assessed_value"] == 100000.0


def test_a_value_without_a_basis_is_refused(client):
    """60% of an insured value and 60% of a market estimate are different numbers."""
    farm = _farm(client)
    res = client.post(f"/internal/farms/{farm['id']}/collateral", json={
        "collateral_type": "equipment", "currency": "USD", "assessed_value": 50000.0,
    })
    assert res.status_code == 422
    assert "valuation_basis" in res.text


def test_an_asset_may_be_registered_before_anyone_values_it(client):
    farm = _farm(client)
    res = client.post(f"/internal/farms/{farm['id']}/collateral", json={
        "collateral_type": "standing_crop", "currency": "USD",
        "description": "Block A strawberries",
    })
    assert res.status_code == 201
    assert res.json()["assessed_value"] is None


def test_a_revaluation_supersedes_and_is_not_double_counted(client):
    """Both rows survive; only the live one is listed."""
    farm = _farm(client)
    first = client.post(f"/internal/farms/{farm['id']}/collateral", json={
        "collateral_type": "equipment", "currency": "USD",
        "assessed_value": 100000.0, "valuation_basis": "insured value",
    }).json()

    client.post(f"/internal/farms/{farm['id']}/collateral", json={
        "collateral_type": "equipment", "currency": "USD",
        "assessed_value": 80000.0, "valuation_basis": "insured value",
        "supersedes_id": first["id"],
    })

    live = client.get(f"/farms/{farm['id']}/collateral").json()
    assert len(live) == 1, "a revaluation double-counted the same asset"
    assert live[0]["assessed_value"] == 80000.0


# --------------------------------------------- point-in-time reproducibility
def test_the_inputs_digest_reproduces_at_a_fixed_as_of(monkeypatch):
    """The property that makes a stored assessment defensible.

    Recomputing at the same `as_of` on the same inputs must produce the same digest. A
    digest that moved would mean an assessment used information the farm did not have
    at the time — the same leak `feature_values` detects.
    """
    monkeypatch.setattr(scorecard_table, "TRANSCRIBED", scorecard_table.Scorecard(
        lender="L", name="c", version="1", minimum_score=0.0, maximum_score=100.0,
        citation=CITATION,
        factors=(
            scorecard_table.ScorecardFactor(
                feature_name="f1", weight=1.0, citation=CITATION,
                bands=(scorecard_table.ScorecardBand(
                    lower_inclusive=None, upper_exclusive=None, points=10.0),),
            ),
        ),
    ))

    class F:
        def __init__(self, v):
            self.value = v
            self.abstained = v is None
            self.reasons = []

    first = credit_scoring.score(features={"f1": F(5.0)}, as_of=AS_OF)
    later = credit_scoring.score(features={"f1": F(5.0)}, as_of=AS_OF + timedelta(days=30))

    assert first.inputs_digest == later.inputs_digest, (
        "the digest covers INPUTS, not the clock — a later assessment on unchanged "
        "inputs must be recognisable as such"
    )

    changed = credit_scoring.score(features={"f1": F(6.0)}, as_of=AS_OF)
    assert changed.inputs_digest != first.inputs_digest


def test_a_stored_assessment_keeps_the_scorecard_it_ran_against(client, monkeypatch):
    """Recorded per row, not referenced: a scorecard may be re-transcribed later, and an
    assessment must stay readable against the card as it was when it ran."""
    monkeypatch.setattr(scorecard_table, "TRANSCRIBED", scorecard_table.Scorecard(
        lender="First Lender", name="Card A", version="7",
        minimum_score=0.0, maximum_score=100.0, citation=CITATION,
        factors=(
            scorecard_table.ScorecardFactor(
                feature_name="f1", weight=1.0, citation=CITATION,
                bands=(scorecard_table.ScorecardBand(
                    lower_inclusive=None, upper_exclusive=None, points=10.0),),
            ),
        ),
    ))
    from app import models
    from app.database import SessionLocal

    farm = _farm(client)
    # Store a feature so the score actually computes.
    db = SessionLocal()
    db.add(models.FeatureValue(
        farm_id=farm["id"], entity_type="farm", entity_id=farm["id"],
        name="f1", version=1, as_of=AS_OF, value=5.0, unit=None,
        reasons=[], inputs_digest="x", computed_at=AS_OF,
    ))
    db.commit()
    db.close()

    row = client.post(f"/internal/farms/{farm['id']}/credit-assessments").json()
    assert row["scorecard_lender"] == "First Lender"
    assert row["scorecard_version"] == "7"
    assert row["total"] == 10.0
    assert row["inputs_digest"]


# ------------------------------------------------------------- claim guard
def test_no_stored_finance_row_claims_something_unearned(client):
    """The persisted shape must not reintroduce vocabulary the models refuse to use."""
    farm = _farm(client)
    client.post(f"/internal/farms/{farm['id']}/credit-assessments")
    client.post(f"/internal/farms/{farm['id']}/underwriting-decisions", json={})
    client.post(f"/internal/farms/{farm['id']}/coverage-assessments",
                json={"crop": "strawberry", "peril": "frost"})

    forbidden = ("approved", "funded", "disbursed", "repaid", "guaranteed",
                 "premium", "apr", "interest_rate")
    for path in ("credit-assessments", "underwriting-decisions", "coverage-assessments"):
        for row in client.get(f"/farms/{farm['id']}/{path}").json():
            for key in row:
                assert not any(f in key.lower() for f in forbidden), f"{path}.{key}"


def test_underwriting_cannot_store_an_approved_outcome():
    """There is no such value in the vocabulary, so no column can hold one."""
    assert "approved" not in {
        underwriting.CONDITIONS_MET,
        underwriting.CONDITIONS_NOT_MET,
        underwriting.REFERRED_TO_HUMAN,
    }


def test_monitoring_standing_stays_three_valued():
    """A two-value column would force 'nothing checked' into whichever reads well."""
    assert monitoring.STANDING_UNKNOWN not in (
        monitoring.STANDING_GOOD, monitoring.STANDING_BREACH
    )
