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
    SOURCE_DEFERRED_TO_FINANCE_PHASE,
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
# Every deferred-finance domain gets one, because mechanism (1) of the finance
# boundary is a test asserting that no source under such a domain is
# implementable — and a test over an empty set proves nothing.
# ---------------------------------------------------------------------------
_DEFERRED_BLOCKER = (
    "Deferred to a finance phase that does not exist. See ENGINEERING_GUIDELINES.md §4 and "
    "DATA_PLATFORM.md; this is a governance decision, not a missing library."
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
    # --- Deferred to the finance phase ---
    SourceDescriptor(
        source_key="financing_offer_feed", domain="financing",
        title="Lender offer feed", provider="(none)",
        status=SOURCE_DEFERRED_TO_FINANCE_PHASE, blocker=_DEFERRED_BLOCKER,
    ),
    SourceDescriptor(
        source_key="credit_bureau", domain="credit_scoring",
        title="Credit bureau data", provider="(none)",
        status=SOURCE_DEFERRED_TO_FINANCE_PHASE, blocker=_DEFERRED_BLOCKER,
    ),
    SourceDescriptor(
        source_key="underwriting_rules", domain="underwriting",
        title="Underwriting rule set", provider="(none)",
        status=SOURCE_DEFERRED_TO_FINANCE_PHASE, blocker=_DEFERRED_BLOCKER,
    ),
    SourceDescriptor(
        source_key="insurance_policy_feed", domain="insurance",
        title="Crop insurance policy data", provider="(none)",
        status=SOURCE_DEFERRED_TO_FINANCE_PHASE, blocker=_DEFERRED_BLOCKER,
    ),
    SourceDescriptor(
        source_key="collateral_registry", domain="collateralization",
        title="Collateral registry", provider="(none)",
        status=SOURCE_DEFERRED_TO_FINANCE_PHASE, blocker=_DEFERRED_BLOCKER,
    ),
    SourceDescriptor(
        source_key="futures_curve", domain="hedging",
        title="Futures & options curve", provider="(none)",
        status=SOURCE_DEFERRED_TO_FINANCE_PHASE, blocker=_DEFERRED_BLOCKER,
    ),
    SourceDescriptor(
        source_key="offer_pricing_feed", domain="pricing",
        title="Supplier offer pricing", provider="(none)",
        status=SOURCE_DEFERRED_TO_FINANCE_PHASE, blocker=_DEFERRED_BLOCKER,
    ),
    SourceDescriptor(
        source_key="portfolio_monitoring", domain="monitoring",
        title="Portfolio & collateral monitoring", provider="(none)",
        status=SOURCE_DEFERRED_TO_FINANCE_PHASE, blocker=_DEFERRED_BLOCKER,
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
