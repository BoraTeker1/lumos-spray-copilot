"""The declaration layer, and the four mechanisms that keep declaring from becoming inventing.

The user asked for seventeen data domains. Eight of them — credit scoring, underwriting,
collateralization, hedging, pricing, insurance, financing, portfolio monitoring — were
forbidden by `ENGINEERING_GUIDELINES.md` §4 until **2026-08-07**, when they were admitted by explicit
instruction (see `domains.ADMISSION`).

What changed is which failure this file guards against. Before admission the risk was
*building* a credit model at all. After it, the risk is subtler and more likely: building
the structure correctly and then filling the scorecard in from intuition, because the
module is right there and a plausible number passes every other test in this suite.
Mechanism 4 exists for exactly that — an admitted domain must name its EMPTY transcription
source, and the source must still be empty.

The original failure mode has not gone away, it has moved: not someone maliciously adding
a credit model, but someone six months from now writing weights into `scorecard_table.py`
because a demo needed a number.
"""
import inspect
import re
from pathlib import Path

import pytest

from app import transcription
from app.ingest import base, domains, geo, registry

CLAUDE_MD = Path(__file__).resolve().parents[2] / "ENGINEERING_GUIDELINES.md"


def _section(name: str) -> str:
    """One ENGINEERING_GUIDELINES.md section, whitespace-normalized.

    Normalizing matters: §4 is hard-wrapped, so "automated underwriting, credit\\n
    scoring" contains no literal "credit scoring" substring. A test that missed the
    guardrail because of a line break would be worse than no test.
    """
    text = CLAUDE_MD.read_text()
    match = re.search(rf"^## {re.escape(name)}\b.*?(?=^## |\Z)", text, re.M | re.S)
    assert match, f"ENGINEERING_GUIDELINES.md has no section {name!r}"
    return " ".join(match.group(0).split())


SECTION_TEXT = {
    domains.SECTION_GUARDRAILS: _section("4. Hard Guardrails"),
    domains.SECTION_STRATEGY: _section("3. Current Strategic Conclusion"),
}


# --------------------------------------------------------------------------
# Mechanism 1 — no future-finance domain owns a runnable source.
# --------------------------------------------------------------------------


def test_no_future_finance_domain_owns_an_implementable_source():
    """A deferred domain may be declared. It may not be executable.

    If this fails, someone has given a finance domain a working adapter, and the
    §4 guardrail on lending / underwriting / credit scoring / money movement is now
    decorative. The fix is to delete the adapter, not to relax this test.
    """
    for descriptor in registry.describe_all():
        if descriptor.domain in domains.FUTURE_FINANCE_DOMAINS:
            assert descriptor.status == base.SOURCE_DEFERRED_TO_FINANCE_PHASE, (
                f"source {descriptor.source_key!r} is in deferred domain "
                f"{descriptor.domain!r} but has status {descriptor.status!r}. "
                f"ENGINEERING_GUIDELINES.md §4 still forbids building it: "
                f"{domains.get(descriptor.domain).guardrail_ref!r}"
            )
            with pytest.raises(registry.SourceError):
                registry.build_adapter(descriptor.source_key)


def test_the_deferred_boundary_machinery_survives_an_empty_deferred_set():
    """Guards the guard, now that nothing is deferred.

    The eight finance domains were admitted on 2026-08-07, so
    `FUTURE_FINANCE_DOMAINS` is empty and the loop above proves nothing today. That is
    a real weakening and it should be visible rather than silent — which is why the
    machinery is kept rather than deleted: it is how the NEXT domain gets deferred, and
    rebuilding this discipline later, under pressure, is how it ends up not existing.

    If a domain is ever deferred again, the loop above regains its teeth automatically
    and this test should be replaced by the count assertion it had before.
    """
    assert domains.FUTURE_FINANCE_DOMAINS == frozenset(), (
        "a domain is deferred again — restore the count assertion in this test so the "
        "boundary check is proven non-vacuous"
    )
    # The mechanism itself must still work. Constructing a deferred domain without a
    # citation must still raise, so the discipline is intact and merely unused.
    with pytest.raises(ValueError, match="must quote the clause that defers it"):
        domains.Domain(
            "probe", "Probe", domains.PHASE_FUTURE_FINANCE, "rationale with no citation",
        )


# --------------------------------------------------------------------------
# Mechanism 4 — every admitted domain names an EMPTY source, and it is empty.
# --------------------------------------------------------------------------


def test_every_admitted_domain_names_an_importable_empty_source():
    """Admission built the structure. This proves it did not invent the numbers.

    Without this, "the finance layer ships with empty tables" is a claim in a docstring.
    With it, a scorecard quietly filled in from intuition changes a test result.
    """
    assert domains.ADMITTED_DOMAINS, "no admitted domains — this test is vacuous"

    for key, module_path in domains.empty_sources():
        status = transcription.status_of(module_path, title=domains.get(key).title)
        assert status.primary_source, (
            f"{module_path} must name the document that would fill it"
        )
        assert not status.populated, (
            f"{module_path} is populated ({status.row_count} entries). If someone "
            "transcribed a real primary document, that is the intended event — confirm "
            "every row carries a Citation and update this assertion deliberately. If "
            "the values were invented, delete them: a plausible number here passes "
            "every other test in this suite."
        )


def test_an_admitted_domain_must_declare_what_admission_did_not_authorise():
    """A domain admitted without a recorded surviving constraint reads as unconstrained."""
    with pytest.raises(ValueError, match="must record what admission did"):
        domains.Domain(
            "probe", "Probe", domains.PHASE_ADMITTED, "rationale",
            empty_source="app.scorecard_table",
        )


def test_an_admitted_domain_must_name_its_empty_source():
    with pytest.raises(ValueError, match="must name the EMPTY transcription source"):
        domains.Domain(
            "probe", "Probe", domains.PHASE_ADMITTED, "rationale",
            surviving_constraint="no money movement",
        )


def test_no_admitted_source_can_fetch():
    """Admission changed the status vocabulary, not the pipeline's inertness.

    `awaiting_transcription` must be as unrunnable as `deferred_to_finance_phase` was —
    the pipeline asks exactly one question before touching a network, and the answer
    for every one of these must still be no.
    """
    for descriptor in registry.describe_all():
        if descriptor.domain in domains.ADMITTED_DOMAINS:
            assert descriptor.status == base.SOURCE_AWAITING_TRANSCRIPTION
            assert descriptor.can_fetch is False
            with pytest.raises(registry.SourceError):
                registry.build_adapter(descriptor.source_key)


# --------------------------------------------------------------------------
# Mechanism 3 — every deferral still quotes a live guardrail.
# --------------------------------------------------------------------------


def test_every_deferred_domain_cites_the_clause_that_defers_it():
    """Catches drift in both directions.

    If a guardrail is reworded or removed, this fails and someone must decide
    deliberately whether the domain is still deferred — rather than the citation
    quietly becoming a quote of text that no longer exists.
    """
    for key in sorted(domains.FUTURE_FINANCE_DOMAINS):
        domain = domains.get(key)
        haystack = SECTION_TEXT[domain.guardrail_section]
        assert domain.guardrail_ref in haystack, (
            f"domain {key!r} cites {domain.guardrail_ref!r} from ENGINEERING_GUIDELINES.md "
            f"{domain.guardrail_section}, but that text is no longer there. Either the "
            f"guardrail changed and this domain's status must be reconsidered, or the "
            f"citation is wrong."
        )


def test_an_mvp_domain_cannot_carry_a_guardrail_citation():
    """A citation on an in-scope domain reads as though it were forbidden."""
    for key in sorted(domains.MVP_DOMAINS):
        assert domains.get(key).guardrail_ref is None


def test_the_seventeen_domains_are_declared_and_partitioned():
    assert len(domains.DOMAINS) == 17
    assert len(domains.MVP_DOMAINS) == 9
    assert not (domains.MVP_DOMAINS & domains.FUTURE_FINANCE_DOMAINS)


# --------------------------------------------------------------------------
# Structural purity.
# --------------------------------------------------------------------------

# Mirrors tests/test_leakage.py's allowlist approach: name what may be imported
# rather than banning a string, and apply the check to the whole set.
FRAMEWORK_FREE_INGEST_MODULES = (base, domains, geo, registry)


def test_pure_ingest_modules_import_no_framework():
    """These four modules must stay sessionless.

    They are where the domain boundary and the adapter contract live. If any of them
    could reach a database, the boundary would be enforceable only by review — and the
    `describe()`-before-`fetch()` guarantee that keeps a credential-less deployment
    inert would become a matter of call order rather than construction.
    """
    forbidden = ("sqlalchemy", "fastapi", "import crud", "SessionLocal", "get_db", "httpx")
    for module in FRAMEWORK_FREE_INGEST_MODULES:
        source = inspect.getsource(module)
        for token in forbidden:
            assert token not in source, (
                f"{module.__name__} must not reference {token!r}"
            )


def test_a_non_implemented_source_must_say_what_would_unblock_it():
    """`requires_credential` with no next action tells an operator nothing."""
    with pytest.raises(ValueError, match="blocker"):
        base.SourceDescriptor(
            source_key="x", domain="climate", title="t", provider="p",
            status=base.SOURCE_REQUIRES_CREDENTIAL,
        )


def test_every_declared_source_names_a_declared_domain():
    for descriptor in registry.describe_all():
        assert domains.get(descriptor.domain)


def test_building_an_adapter_that_does_not_exist_names_the_blocker():
    """A declared-but-unbuilt source explains itself instead of raising a bare KeyError."""
    with pytest.raises(registry.SourceError, match="a lab report is a document"):
        registry.build_adapter("soil_lab_report")


def test_an_unknown_source_is_distinguishable_from_an_unbuilt_one():
    with pytest.raises(registry.SourceError, match="unknown source"):
        registry.build_adapter("no_such_source")


# --------------------------------------------------------------------------
# geo — small, and load-bearing.
# --------------------------------------------------------------------------


def test_haversine_returns_none_rather_than_zero_when_a_coordinate_is_missing():
    """0.0 would assert the station sits on the field.

    That is the dangerous default: `disease_risk` treats a null distance as in-range
    AND as close, so a fabricated zero would silently earn a better evidence grade than
    the data supports.
    """
    assert geo.haversine_km(None, -121.7, 36.9, -121.8) is None
    assert geo.haversine_km(36.9, None, 36.9, -121.8) is None
    assert geo.haversine_km(36.9, -121.7, None, -121.8) is None
    assert geo.haversine_km(36.9, -121.7, 36.9, None) is None


def test_haversine_matches_a_known_distance():
    # Watsonville, CA to Salinas, CA — about 30 km on the ground.
    km = geo.haversine_km(36.9102, -121.7569, 36.6777, -121.6555)
    assert 25.0 < km < 32.0


def test_haversine_is_zero_for_the_same_point():
    assert geo.haversine_km(36.9, -121.7, 36.9, -121.7) == pytest.approx(0.0, abs=1e-9)
