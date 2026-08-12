"""source_key -> SourceDescriptor, for every source the platform declares.

A source is CODE, never a table row. If it were a table, the database could disagree
with the deployed code about whether an adapter exists — and the disagreement would
surface as a run that hangs waiting for a `fetch` method nobody wrote. Declaring in
code makes "is this buildable" and "is this built" the same question.

Two kinds of entry live here:

* **Registered adapters** — a real object with `describe`/`fetch`/`parse`. Registered by
  the adapter module itself at import time, so adding an adapter is one file plus one
  import, and a registered adapter can never be missing from the operator's table.
* **Declared placeholders** — a `SourceDescriptor` with no adapter behind it, whose
  status says whether the gap is a build task (`not_implemented`) or a governance
  decision (`deferred_to_finance_phase`). These exist so the operator table shows the
  whole intended platform rather than only the one corner that is finished.

Framework-free (stdlib only).
"""
from __future__ import annotations

from app.ingest import domains
from app.ingest.base import (
    SOURCE_AWAITING_TRANSCRIPTION,
    SOURCE_NOT_IMPLEMENTED,
    SourceAdapter,
    SourceDescriptor,
)


class SourceError(KeyError):
    """Asked for a source that is not declared, or an adapter that is not built."""


# Adapter factories, keyed by source_key. A factory rather than an instance so that a
# credential read at construction time is read fresh on each call — an operator who
# exports the key and restarts the worker must not have to reason about when the module
# was first imported.
_ADAPTER_FACTORIES: dict[str, object] = {}


def register(source_key: str, factory) -> None:
    """Called by an adapter module at import time. Last registration wins.

    Overriding is deliberate: a placeholder declared here is superseded by the real
    adapter the moment its module is imported, so the two never have to be kept in sync
    by hand.
    """
    _ADAPTER_FACTORIES[source_key] = factory


def _reset_for_tests() -> None:
    _ADAPTER_FACTORIES.clear()


# ---------------------------------------------------------------------------
# Declared placeholders.
#
# The finance and market sources were `deferred_to_finance_phase` until 2026-08-07.
# They are now `awaiting_transcription`, which is a different and more actionable
# statement: the layer is built, and what is missing is a document someone must read.
# `can_fetch` is False for both, so nothing about the pipeline's inertness changed.
# ---------------------------------------------------------------------------
def _transcription_blocker(module: str) -> str:
    return (
        f"The structure is built and the numbers are absent: `{module}` ships EMPTY, "
        "so every model over it returns a Refusal rather than a value. Unblocked by a "
        "human transcribing the primary document with its citation — not by an adapter, "
        "a credential, or a library. See TRANSCRIPTION_TASKS.md."
    )

PLACEHOLDERS: tuple[SourceDescriptor, ...] = (
    # --- MVP domains, adapters not built ---
    # NOTE: `cimis_hourly` is deliberately NOT here. It has a real adapter
    # (`app/ingest/cimis.py`) which registers itself at import and answers `describe()`
    # for itself — only the adapter knows whether its credential is present, so a
    # placeholder would either duplicate that check or lie about it.
    SourceDescriptor(
        source_key="soil_lab_report",
        domain="soil",
        title="Soil laboratory report",
        provider="(grower's lab of choice)",
        status=SOURCE_NOT_IMPLEMENTED,
        blocker=(
            "No adapter: a lab report is a document, and the document upload path "
            "already exists. Build an adapter only if a pilot farm has a machine-"
            "readable feed."
        ),
    ),
    SourceDescriptor(
        source_key="market_price_feed",
        domain="market",
        title="Commodity price feed",
        provider="(unselected)",
        status=SOURCE_NOT_IMPLEMENTED,
        blocker=(
            "No provider chosen, and no validated need. Prices bear on the finance "
            "phase far more than on a spray decision."
        ),
    ),
    # --- Admitted 2026-08-07; structure built, transcription source EMPTY ---
    SourceDescriptor(
        source_key="financing_offer_feed", domain="financing",
        title="Lender product catalogue", provider="(lending partner)",
        status=SOURCE_AWAITING_TRANSCRIPTION,
        blocker=_transcription_blocker("app/financing_terms.py"),
    ),
    SourceDescriptor(
        source_key="credit_bureau", domain="credit_scoring",
        title="Lender credit scorecard", provider="(lending partner)",
        status=SOURCE_AWAITING_TRANSCRIPTION,
        blocker=_transcription_blocker("app/scorecard_table.py"),
        notes=(
            "Named `credit_bureau` historically; the source that actually governs this "
            "domain is the lender's own scorecard, not a bureau file."
        ),
    ),
    SourceDescriptor(
        source_key="underwriting_rules", domain="underwriting",
        title="Underwriting rule set", provider="(lending partner)",
        status=SOURCE_AWAITING_TRANSCRIPTION,
        blocker=_transcription_blocker("app/underwriting_rules.py"),
    ),
    SourceDescriptor(
        source_key="insurance_policy_feed", domain="insurance",
        title="Crop insurance product terms", provider="(insurer)",
        status=SOURCE_AWAITING_TRANSCRIPTION,
        blocker=_transcription_blocker("app/insurance_products.py"),
        notes="Premium rates are deliberately never transcribed — coverage is matched, not priced.",
    ),
    SourceDescriptor(
        source_key="collateral_registry", domain="collateralization",
        title="Collateral advance-rate schedule", provider="(lending partner)",
        status=SOURCE_AWAITING_TRANSCRIPTION,
        blocker=_transcription_blocker("app/collateral_valuation.py"),
    ),
    SourceDescriptor(
        source_key="futures_curve", domain="hedging",
        title="Exchange settlement prices", provider="(exchange)",
        status=SOURCE_AWAITING_TRANSCRIPTION,
        blocker=_transcription_blocker("app/futures_curve.py"),
        notes="Recording positions only. Nothing executes and nothing is advised.",
    ),
    SourceDescriptor(
        source_key="offer_pricing_feed", domain="pricing",
        title="Reported commodity price series", provider="(reporting service)",
        status=SOURCE_AWAITING_TRANSCRIPTION,
        blocker=_transcription_blocker("app/price_series.py"),
        notes=(
            "Commodity prices for sale timing. Ranking supplier quotes remains "
            "forbidden — quotes stay in entry order."
        ),
    ),
    SourceDescriptor(
        source_key="portfolio_monitoring", domain="monitoring",
        title="Facility covenant schedule", provider="(lending partner)",
        status=SOURCE_AWAITING_TRANSCRIPTION,
        blocker=_transcription_blocker("app/monitoring_covenants.py"),
    ),
)

PLACEHOLDERS_BY_KEY: dict[str, SourceDescriptor] = {p.source_key: p for p in PLACEHOLDERS}


def _validate_declarations() -> None:
    """Every declared source must name a declared domain. Import-time, so a typo in a
    domain key is a startup failure rather than a blank column in the operator table."""
    for descriptor in PLACEHOLDERS:
        domains.get(descriptor.domain)


_validate_declarations()


def source_keys() -> list[str]:
    return sorted(set(PLACEHOLDERS_BY_KEY) | set(_ADAPTER_FACTORIES))


def build_adapter(source_key: str) -> SourceAdapter:
    """The adapter for a source, or SourceError when only a placeholder exists."""
    factory = _ADAPTER_FACTORIES.get(source_key)
    if factory is None:
        if source_key in PLACEHOLDERS_BY_KEY:
            raise SourceError(
                f"{source_key!r} is declared but has no adapter: "
                f"{PLACEHOLDERS_BY_KEY[source_key].blocker}"
            )
        raise SourceError(f"unknown source {source_key!r}")
    return factory()


def describe(source_key: str) -> SourceDescriptor:
    """What this source is and whether it can run right now.

    A registered adapter answers for itself — the credential check has to happen at the
    adapter, because only it knows which environment variable it needs.
    """
    factory = _ADAPTER_FACTORIES.get(source_key)
    if factory is not None:
        return factory().describe()
    try:
        return PLACEHOLDERS_BY_KEY[source_key]
    except KeyError:
        raise SourceError(f"unknown source {source_key!r}") from None


def describe_all() -> list[SourceDescriptor]:
    return [describe(key) for key in source_keys()]


def as_payload() -> dict:
    """The operator view: every source, plus the domain table it is governed by."""
    return {
        "sources": [d.as_payload() for d in describe_all()],
        "domains": domains.as_payload(),
    }
