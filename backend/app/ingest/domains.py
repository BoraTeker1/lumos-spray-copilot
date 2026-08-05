"""The seventeen data domains, and which of them this product is allowed to compute.

All seventeen are DECLARED here because the platform's shape is a real thing a reader
should be able to see. Nine are in the MVP. Eight are deferred to a finance phase that
does not exist, and each of those names the `ENGINEERING_GUIDELINES.md` clause that defers it.

Declaring must be provably not building, or this file is just a promise. Three
mechanisms enforce that, and none of them is prose:

1. `tests/test_ingest_registry.py::test_no_future_finance_domain_owns_an_implementable_source`
   — a source under a future-finance domain must have status `deferred_to_finance_phase`.
2. `features.base.register()` refuses a spec whose domain is not in `MVP_DOMAINS`, so
   `debt_service_capacity` and its friends cannot be registered, let alone computed.
3. `tests/test_ingest_registry.py::test_every_deferred_domain_cites_the_clause_that_defers_it`
   — each `guardrail_ref` must still appear in the cited `ENGINEERING_GUIDELINES.md` section, which
   catches drift in EITHER direction: a guardrail quietly reworded, or a domain quietly
   un-deferred.

Framework-free (stdlib only).
"""
from __future__ import annotations

from dataclasses import dataclass

PHASE_MVP = "mvp"
PHASE_FUTURE_FINANCE = "future_finance"

# The two ENGINEERING_GUIDELINES.md sections a deferral may cite. §4 is the hard-guardrail list; §3 is
# the standing "stop building product unless a validation need requires it" conclusion,
# which is the honest citation for a domain §4 never contemplated.
SECTION_GUARDRAILS = "§4"
SECTION_STRATEGY = "§3"


@dataclass(frozen=True)
class Domain:
    key: str
    title: str
    phase: str
    rationale: str
    guardrail_ref: str | None = None
    guardrail_section: str | None = None

    def __post_init__(self):
        if self.phase not in (PHASE_MVP, PHASE_FUTURE_FINANCE):
            raise ValueError(f"{self.key}: unknown phase {self.phase!r}")
        # A deferral without a citation is an opinion. Requiring the quote is what lets
        # mechanism (3) detect the day someone deletes the guardrail and forgets this.
        if self.phase == PHASE_FUTURE_FINANCE:
            if not self.guardrail_ref:
                raise ValueError(
                    f"{self.key}: a deferred domain must quote the clause that defers it"
                )
            if self.guardrail_section not in (SECTION_GUARDRAILS, SECTION_STRATEGY):
                raise ValueError(
                    f"{self.key}: guardrail_section must be "
                    f"{SECTION_GUARDRAILS!r} or {SECTION_STRATEGY!r}"
                )
        elif self.guardrail_ref:
            raise ValueError(
                f"{self.key}: an MVP domain must not carry a guardrail citation; "
                f"it reads as though the domain were forbidden"
            )

    def as_payload(self) -> dict:
        return {
            "key": self.key,
            "title": self.title,
            "phase": self.phase,
            "rationale": self.rationale,
            "guardrail_ref": self.guardrail_ref,
            "guardrail_section": self.guardrail_section,
        }


# ---------------------------------------------------------------------------
# The nine MVP domains. Ordered by how directly each strengthens pesticide
# reduction and pilot validation, which is the stated prioritisation.
# ---------------------------------------------------------------------------
_MVP = (
    Domain(
        "climate", "Climate & weather", PHASE_MVP,
        "The binding data gap in the Botrytis pilot: the disease model abstains with "
        "`no_weather_in_window` because nothing has ever written a weather row. First "
        "and only domain with a working adapter.",
    ),
    Domain(
        "crop_protection", "Crop protection (pesticides & farm drugs)", PHASE_MVP,
        "The product's subject. Already the richest data in the system — sprays, "
        "labels, MoA groups — so the work here is derived features over held data, "
        "not ingestion.",
    ),
    Domain(
        "crop", "Crop & phenology", PHASE_MVP,
        "Crop cycles anchor every per-area figure. Held in the entity spine already; "
        "no external source needed for the MVP.",
    ),
    Domain(
        "soil", "Soil", PHASE_MVP,
        "In scope for the MVP because soil moisture and texture bear on disease "
        "pressure and re-entry, but no adapter is built: a lab report is a document, "
        "and the document path already exists.",
    ),
    Domain(
        "fertilization", "Fertilization & nutrition", PHASE_MVP,
        "Nitrogen status affects canopy density and therefore disease pressure. "
        "Declared so the operation type has a home; no adapter.",
    ),
    Domain(
        "land_selection", "Land selection & tenure", PHASE_MVP,
        "Parcels and tenure rights are in the entity spine because a field that spans "
        "two parcels has two compliance stories. No external adapter.",
    ),
    Domain(
        "seed_selection", "Seed & variety selection", PHASE_MVP,
        "Variety resistance is a real lever on spray count. Held on the crop cycle; "
        "no adapter.",
    ),
    Domain(
        "market", "Market & demand", PHASE_MVP,
        "Destination market determines which residue rules apply. Declared, not "
        "built — and note MRL data stays out of scope entirely (§4, §14).",
    ),
    Domain(
        "energy", "Energy", PHASE_MVP,
        "Irrigation and cold-chain energy are farm costs the platform will eventually "
        "carry. Declared for completeness; nothing computes it.",
    ),
)

# ---------------------------------------------------------------------------
# The eight deferred domains. Every one of these is a thing the user asked for
# and a thing this product may not do yet. The citation is the reason.
# ---------------------------------------------------------------------------
_FUTURE_FINANCE = (
    Domain(
        "financing", "Financing", PHASE_FUTURE_FINANCE,
        "Indicative offers exist in the procurement module; actual lending does not.",
        guardrail_ref="real lending", guardrail_section=SECTION_GUARDRAILS,
    ),
    Domain(
        "credit_scoring", "Credit scoring", PHASE_FUTURE_FINANCE,
        "Scoring a grower from their farm data is the single most tempting thing to "
        "build on this substrate and the most clearly forbidden.",
        guardrail_ref="credit scoring", guardrail_section=SECTION_GUARDRAILS,
    ),
    Domain(
        "underwriting", "Underwriting", PHASE_FUTURE_FINANCE,
        "Point-in-time correctness makes underwriting technically feasible here, which "
        "is precisely why the guardrail matters more, not less.",
        guardrail_ref="automated underwriting", guardrail_section=SECTION_GUARDRAILS,
    ),
    Domain(
        "insurance", "Insurance", PHASE_FUTURE_FINANCE,
        "Pricing a policy from yield and weather history is underwriting wearing a "
        "different word.",
        guardrail_ref="automated underwriting", guardrail_section=SECTION_GUARDRAILS,
    ),
    Domain(
        "collateralization", "Collateralization", PHASE_FUTURE_FINANCE,
        "Valuing a standing crop as collateral requires moving money against it.",
        guardrail_ref="money movement of any kind", guardrail_section=SECTION_GUARDRAILS,
    ),
    Domain(
        "hedging", "Hedging", PHASE_FUTURE_FINANCE,
        "Positions are money movement by definition.",
        guardrail_ref="money movement of any kind", guardrail_section=SECTION_GUARDRAILS,
    ),
    Domain(
        "pricing", "Pricing", PHASE_FUTURE_FINANCE,
        "Ranking or pricing supplier offers is the commission-shaped failure the "
        "procurement module was explicitly built to avoid.",
        guardrail_ref="commission-based quote ranking", guardrail_section=SECTION_GUARDRAILS,
    ),
    Domain(
        "monitoring", "Collateral & portfolio monitoring", PHASE_FUTURE_FINANCE,
        "Lender-facing monitoring of many farms is a different product with a "
        "different buyer, and no validation evidence points at it.",
        guardrail_ref="Stop building product unless a validation need directly requires it",
        guardrail_section=SECTION_STRATEGY,
    ),
)

DOMAINS: tuple[Domain, ...] = _MVP + _FUTURE_FINANCE

DOMAINS_BY_KEY: dict[str, Domain] = {d.key: d for d in DOMAINS}

MVP_DOMAINS: frozenset[str] = frozenset(d.key for d in _MVP)
FUTURE_FINANCE_DOMAINS: frozenset[str] = frozenset(d.key for d in _FUTURE_FINANCE)


def get(key: str) -> Domain:
    try:
        return DOMAINS_BY_KEY[key]
    except KeyError:
        raise KeyError(
            f"unknown domain {key!r}; declared domains are "
            f"{sorted(DOMAINS_BY_KEY)}"
        ) from None


def is_mvp(key: str) -> bool:
    return key in MVP_DOMAINS


def as_payload() -> list[dict]:
    """The operator-facing table. Order is declaration order: MVP first, deferred last."""
    return [d.as_payload() for d in DOMAINS]
