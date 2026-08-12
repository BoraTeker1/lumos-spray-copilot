"""The two surfaces the 2026-08-07 layers are reachable through.

ENGINEERING_GUIDELINES.md §5 records a delivery-gap audit whose lesson was that *the docs described
capabilities the UI could not reach* — `epa_reg_no` was not a field in the primary
workflow at all, so five phases of label work were unreachable. These tests exist so the
same thing cannot be true of the finance and market layers: whatever the modules do,
there is a route that reaches them and a test that proves it responds.
"""


def _farm(client):
    return client.post("/farms", json={
        "name": "Profile Ranch", "location": "Watsonville, CA", "country": "US",
        "crop_type": "strawberry", "area": 10.0,
    }).json()


# --------------------------------------------------- transcription worklist
def test_transcription_status_lists_every_admitted_source(client):
    body = client.get("/internal/transcription-status").json()

    assert body["total_count"] == 8, "one per admitted domain"
    assert body["populated_count"] == 0, (
        "a source is populated — confirm it was transcribed from a primary document "
        "with citations, then update this assertion deliberately"
    )
    assert "2026-08-07" in body["admission"]


def test_every_listed_source_names_the_document_that_would_fill_it(client):
    """An empty source whose emptiness is not actionable is just a gap."""
    for source in client.get("/internal/transcription-status").json()["sources"]:
        assert source["primary_source"], source["module"]
        assert len(source["primary_source"]) > 40, (
            f"{source['module']}: primary_source is too terse to act on"
        )
        assert source["populated"] is False
        assert source["row_count"] == 0


def test_the_worklist_is_generated_not_hand_kept(client):
    """Modules come from the domain registry, so a later domain cannot be forgotten."""
    from app.ingest import domains

    listed = {s["module"] for s in client.get("/internal/transcription-status").json()["sources"]}
    declared = {module for _, module in domains.empty_sources()}
    assert listed == declared


# ------------------------------------------------------- cross-layer profile
def test_the_profile_responds_for_a_real_farm(client):
    farm = _farm(client)
    res = client.get(f"/farms/{farm['id']}/profile")

    assert res.status_code == 200
    body = res.json()
    assert body["farm_id"] == farm["id"]
    assert body["layers"], "the profile must report layers, even when all refuse"


def test_every_layer_refuses_on_todays_data_and_says_why(client):
    """The honest state: empty sources plus an empty farm means nothing computes.

    Each refusal must still carry a code and a detail — five blank cards would be
    strictly worse than no page.
    """
    body = client.get(f"/farms/{_farm(client)['id']}/profile").json()

    assert body["available_layers"] == []
    assert body["blocking_gaps"]
    for gap in body["blocking_gaps"]:
        assert gap["code"] and gap["detail"] and gap["owner"]


def test_every_gap_today_is_an_operator_transcription_gap(client):
    """The sharpest statement of where this product actually stands.

    Every model checks its transcription source BEFORE it checks farm data, so with all
    eight sources empty, not one gap is something a grower can fix. No amount of data
    entry unblocks any of these layers today — someone has to read a document.

    That precedence is correct (telling a grower to enter data when the answer would
    still be unavailable is worse than useless), and this assertion will change the day
    a source is transcribed: the grower-owned gaps behind it appear only then. The
    grouping mechanism itself is unit-tested over both owners in `test_farm_profile.py`.
    """
    body = client.get(f"/farms/{_farm(client)['id']}/profile").json()
    by_owner = body["gaps_by_owner"]

    assert "operator" in by_owner, "no source-transcription gaps surfaced"
    assert set(by_owner) == {"operator"}, (
        "a non-operator gap appeared — if a transcription source was filled, that is "
        "the intended event and this test should be updated to match"
    )
    assert {g["code"] for g in by_owner["operator"]} == {"no_source_transcribed"}


def test_the_profile_reports_no_overall_score(client):
    body = client.get(f"/farms/{_farm(client)['id']}/profile").json()
    assert "overall_score" not in body
    assert "overall_score" in body["not_calculated"]
    assert "readiness_percentage" in body["not_calculated"]


def test_the_profile_is_not_operator_gated(client):
    """'Why can't this tell me anything about my farm' belongs to the grower."""
    assert client.get(f"/farms/{_farm(client)['id']}/profile").status_code == 200


def test_an_unknown_farm_is_a_404(client):
    assert client.get("/farms/999999/profile").status_code == 404


def test_the_profile_is_absent_from_the_pca_decision_surface():
    """Blinding: a cross-layer card on /decisions/{id} would break the shadow study."""
    from app.main import app

    decision_paths = [
        r.path for r in app.routes
        if getattr(r, "path", "").startswith("/planned-sprays")
    ]
    assert decision_paths, "no decision routes found — the check is vacuous"
    assert not any("profile" in p for p in decision_paths)
