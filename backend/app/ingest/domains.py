"""The seventeen data domains, and which of them this product is allowed to compute.

All seventeen are DECLARED here because the platform's shape is a real thing a reader
should be able to see. Nine are MVP. The other eight — the finance and market domains —
were deferred until **2026-08-07**, when they were ADMITTED by explicit instruction to
build the full three-layer product.

Admission is not the same as permission to invent. Each admitted domain must name the
EMPTY transcription source that governs it, and the numbers in those sources arrive only
by a human transcribing a primary document. The structure is built; the coefficients are
absent; every model over them refuses rather than defaults. `app/transcription.py`
explains the pattern and `TRANSCRIPTION_TASKS.md` lists what remains to be read.

Declaring must be provably not building, or this file is just a promise. Four mechanisms
enforce that, and none of them is prose:

1. `tests/test_ingest_registry.py::test_no_deferred_domain_owns_an_implementable_source`
   — a source under a still-deferred domain must have status `deferred_to_finance_phase`.
2. `features.base.register()` refuses a spec whose domain is not in `COMPUTABLE_DOMAINS`,
   so a feature in a domain nobody admitted cannot be registered, let alone computed.
3. `tests/test_ingest_registry.py::test_every_deferred_domain_cites_the_clause_that_defers_it`
   — each `guardrail_ref` must still appear in the cited `ENGINEERING_GUIDELINES.md` section, which
   catches drift in EITHER direction: a guardrail quietly reworded, or a domain quietly
   un-deferred. Still live for whatever remains deferred.
4. `tests/test_ingest_registry.py::test_every_admitted_domain_names_an_empty_source`
   — each admitted domain's `empty_source` must import and meet the transcription
   contract. This is the mechanism that makes "we built the structure, not the numbers"
   checkable rather than asserted.

Note what admission did NOT lift, recorded on each domain as `surviving_constraint`:
money movement, hardware, commission-based ranking, and inventing any number that belongs
in a transcription source.

Framework-free (stdlib only).
"""
from __future__ import annotations

from dataclasses import dataclass

PHASE_MVP = "mvp"
PHASE_FUTURE_FINANCE = "future_finance"
# Admitted 2026-08-07 by explicit instruction: structure built, sources empty.
PHASE_ADMITTED = "admitted"

# The instruction that admitted the finance and market domains. Recorded once and
# referenced by each admitted domain, so there is exactly one place to read what was
# authorised and when.
ADMISSION = (
    "2026-08-07 — explicit session instruction to implement the full three-layer "
    "business idea (advisory + procurement + finance), using the empty-source pattern: "
    "real structure and workflows, coefficient tables shipped EMPTY, every model "
    "returning Result | Refusal rather than a fabricated number."
)

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
    # Admitted domains only. `empty_source` is the dotted path of the transcription
    # module that governs the domain; `surviving_constraint` is what admission did NOT
    # authorise, recorded next to the admission so the two cannot drift apart.
    empty_source: str | None = None
    surviving_constraint: str | None = None

    def __post_init__(self):
        if self.phase not in (PHASE_MVP, PHASE_FUTURE_FINANCE, PHASE_ADMITTED):
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
                f"{self.key}: a non-deferred domain must not carry a guardrail "
                f"citation; it reads as though the domain were forbidden"
            )

        # An admitted domain without an empty source is just an un-deferred one — the
        # exact outcome the empty-source pattern exists to prevent. Requiring both
        # fields here is what stops "we built the finance layer" from quietly becoming
        # "we invented the finance layer's numbers".
        if self.phase == PHASE_ADMITTED:
            if not self.empty_source:
                raise ValueError(
                    f"{self.key}: an admitted domain must name the EMPTY transcription "
                    "source that governs it, so its emptiness is checkable"
                )
            if not self.surviving_constraint:
                raise ValueError(
                    f"{self.key}: an admitted domain must record what admission did "
                    "NOT authorise"
                )
        elif self.empty_source:
            raise ValueError(
                f"{self.key}: only an admitted domain carries an empty_source"
            )

    def as_payload(self) -> dict:
        return {
            "key": self.key,
            "title": self.title,
            "phase": self.phase,
            "rationale": self.rationale,
            "guardrail_ref": self.guardrail_ref,
            "guardrail_section": self.guardrail_section,
            "empty_source": self.empty_source,
            "surviving_constraint": self.surviving_constraint,
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
# The eight admitted domains (2026-08-07). Each was deferred until the instruction
# recorded in ADMISSION; each now names the EMPTY source that governs it and the
# constraint that admission did not lift.
# ---------------------------------------------------------------------------
_ADMITTED = (
    Domain(
        "financing", "Financing", PHASE_ADMITTED,
        "Indicative offers already existed in the procurement module. This admits the "
        "lender's published product catalogue they can be checked against.",
        empty_source="app.financing_terms",
        surviving_constraint=(
            "No money movement: no disbursement, no repayment collection, no computed "
            "amortisation. Cost stays the lender's own verbatim sentence, never a rate "
            "this system derives a schedule from."
        ),
    ),
    Domain(
        "credit_scoring", "Credit scoring", PHASE_ADMITTED,
        "Scoring a grower from farm data is the most tempting thing to build on this "
        "substrate; the scorecard is therefore transcribed from a lender, never designed "
        "here. Lumos executes a scorecard auditably; it does not author one.",
        empty_source="app.scorecard_table",
        surviving_constraint=(
            "No Lumos-authored weights, factors or bands. A feature that abstains "
            "abstains the whole score — partial scoring reads as a lower score, not an "
            "incomplete one."
        ),
    ),
    Domain(
        "underwriting", "Underwriting", PHASE_ADMITTED,
        "Point-in-time correctness makes an auditable underwriting trail genuinely "
        "valuable here — which is exactly why the policy must come from the lender.",
        empty_source="app.underwriting_rules",
        surviving_constraint=(
            "No Lumos-authored credit policy, and no outcome named 'approved': the "
            "strongest affirmative result is that a transcribed policy's conditions "
            "were met."
        ),
    ),
    Domain(
        "insurance", "Insurance", PHASE_ADMITTED,
        "Whether a farm's operational records satisfy a policy's evidence requirements "
        "is a real, checkable question growers currently answer by hand at claim time.",
        empty_source="app.insurance_products",
        surviving_constraint=(
            "No premium estimation. Pricing a policy from yield and weather history is "
            "underwriting wearing a different word; coverage terms are matched, never "
            "priced."
        ),
    ),
    Domain(
        "collateralization", "Collateralization", PHASE_ADMITTED,
        "Registering and valuing collateral is decision support. The advance rate that "
        "turns an asset into a credit line belongs to the lender.",
        empty_source="app.collateral_valuation",
        surviving_constraint=(
            "No default advance rate — there is no safe default, since a missing rate "
            "defaulted either way misstates exposure silently. No perfecting of a "
            "security interest and no money moved against it."
        ),
    ),
    Domain(
        "hedging", "Hedging", PHASE_ADMITTED,
        "Recording positions a grower took elsewhere lets the platform describe their "
        "real exposure instead of ignoring it.",
        empty_source="app.futures_curve",
        surviving_constraint=(
            "Nothing executes and nothing is advised: no broker connection, no orders, "
            "and no outcome that recommends taking or closing a position — that is "
            "regulated investment advice, and the outcome enum makes it inexpressible."
        ),
    ),
    Domain(
        "pricing", "Pricing", PHASE_ADMITTED,
        "A reported price series lets a grower time a sale. Distinct from ranking "
        "supplier offers, which remains forbidden.",
        empty_source="app.price_series",
        surviving_constraint=(
            "No commission-based ranking of supplier quotes — quotes stay in entry "
            "order. No stale price served as current: a point outside the freshness "
            "window refuses rather than falling back to the last known value."
        ),
    ),
    Domain(
        "monitoring", "Collateral & portfolio monitoring", PHASE_ADMITTED,
        "The append-only, point-in-time-correct substrate makes covenant checking "
        "verifiable in a way a spreadsheet is not.",
        empty_source="app.monitoring_covenants",
        surviving_constraint=(
            "No Lumos-authored covenant thresholds — a threshold determines breach, and "
            "breach has consequences. An empty schedule reports 'nothing checked', "
            "never 'compliant'."
        ),
    ),
)

# Still deferred: nothing. Kept as a declared, enforced-empty tuple rather than deleted,
# because mechanisms (1) and (3) are the machinery for deferring the NEXT domain, and
# deleting them would mean rebuilding that discipline from scratch under pressure.
_FUTURE_FINANCE: tuple[Domain, ...] = ()

DOMAINS: tuple[Domain, ...] = _MVP + _ADMITTED + _FUTURE_FINANCE

DOMAINS_BY_KEY: dict[str, Domain] = {d.key: d for d in DOMAINS}

MVP_DOMAINS: frozenset[str] = frozenset(d.key for d in _MVP)
ADMITTED_DOMAINS: frozenset[str] = frozenset(d.key for d in _ADMITTED)
FUTURE_FINANCE_DOMAINS: frozenset[str] = frozenset(d.key for d in _FUTURE_FINANCE)

# What `features.base.register()` gates on. Separate from MVP_DOMAINS so the two
# admission routes stay legible: a domain in the original MVP, or one admitted by the
# instruction in ADMISSION.
COMPUTABLE_DOMAINS: frozenset[str] = MVP_DOMAINS | ADMITTED_DOMAINS


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


def is_computable(key: str) -> bool:
    """May a feature be registered in this domain? MVP or admitted, both count."""
    return key in COMPUTABLE_DOMAINS


def empty_sources() -> list[tuple[str, str]]:
    """(domain key, dotted module path) for every domain governed by a transcription
    source. Consumed by the registry test and by the TRANSCRIPTION_TASKS.md generator,
    so the handoff doc cannot drift from what the code actually declares.
    """
    return [(d.key, d.empty_source) for d in DOMAINS if d.empty_source]


def as_payload() -> list[dict]:
    """The operator-facing table. Order is declaration order: MVP first, deferred last."""
    return [d.as_payload() for d in DOMAINS]
