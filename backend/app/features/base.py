"""What a feature is, and the one invariant that makes every consumer safe.

Framework-free (stdlib plus `app.pit`, which is itself framework-free).

A feature is a named, versioned, point-in-time-correct number over held data. The
interesting design decision is that it may refuse to be one: a `FeatureResult` is either
a value or an abstention with reasons, never both and never neither.

    if self.abstained != (self.value is None): raise
    if self.abstained and not self.reasons:    raise

That pair of lines is the whole safety argument. Without it, the natural failure mode is
a feature that returns `0.0` when it means "no data" — and `0 kg/ha of active ingredient`
is not a data gap, it is a pesticide-reduction claim. The type makes the confusion
impossible rather than discouraged.

`register()` refuses any spec whose domain is not an MVP domain. That is enforcement
mechanism (2) of the finance boundary described in `app/ingest/domains.py`:
`debt_service_capacity` and its relatives cannot be REGISTERED, so they cannot be
scheduled, computed, stored or rendered.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from app.ingest import domains

# Entity kinds a feature can be computed for. Small and closed: a feature keyed to
# something with no stable identity cannot be recomputed reproducibly.
ENTITY_FIELD = "field"
ENTITY_CROP_CYCLE = "crop_cycle"
ENTITY_BLOCK = "block"
ENTITY_FARM = "farm"

ENTITY_TYPES: tuple[str, ...] = (ENTITY_FIELD, ENTITY_CROP_CYCLE, ENTITY_BLOCK, ENTITY_FARM)


class FeatureError(RuntimeError):
    """A feature was declared or resolved incorrectly. Never a data problem."""


@dataclass(frozen=True)
class FeatureResult:
    """A computed value, or a refusal to compute one. Never both.

    `excluded` carries the point-in-time exclusions (`pit.partition`'s second return)
    so a result can say not only what it used but what it deliberately did not, and why.
    That is what makes a stored feature explainable years later.
    """

    value: float | None
    unit: str | None = None
    as_of: datetime | None = None
    inputs_digest: str | None = None
    evidence_grade: str | None = None
    abstained: bool = False
    reasons: tuple[str, ...] = ()
    excluded: tuple[dict, ...] = ()

    def __post_init__(self):
        if self.abstained != (self.value is None):
            raise FeatureError(
                "a FeatureResult is abstained if and only if it has no value; got "
                f"abstained={self.abstained!r} with value={self.value!r}. A number "
                "returned alongside an abstention will be rendered as data."
            )
        if self.abstained and not self.reasons:
            raise FeatureError("an abstention must say why")

    @classmethod
    def abstain(cls, *reasons: str, as_of=None, excluded=(), inputs_digest=None):
        return cls(
            value=None, abstained=True, reasons=tuple(reasons), as_of=as_of,
            excluded=tuple(excluded), inputs_digest=inputs_digest,
        )

    @classmethod
    def computed(cls, value: float, unit: str, *, as_of=None, inputs_digest=None,
                 evidence_grade=None, excluded=()):
        return cls(
            value=float(value), unit=unit, as_of=as_of, inputs_digest=inputs_digest,
            evidence_grade=evidence_grade, excluded=tuple(excluded),
        )

    def as_payload(self) -> dict:
        """The shape a surface renders.

        An abstention carries NO `value` key at all, rather than a null one. A null in a
        numeric field is exactly what a template turns into `0` or `--`; an absent key
        forces the caller to handle the abstention branch.
        """
        if self.abstained:
            return {"abstained": True, "reasons": list(self.reasons)}
        return {
            "value": self.value,
            "unit": self.unit,
            "evidence_grade": self.evidence_grade,
        }


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    version: int
    entity_type: str
    domain: str
    unit: str | None
    description: str
    compute: Callable
    depends_on: tuple[str, ...] = field(default_factory=tuple)

    @property
    def key(self) -> str:
        return f"{self.name}:v{self.version}"


REGISTRY: dict[str, FeatureSpec] = {}


def register(spec: FeatureSpec) -> FeatureSpec:
    """Add a feature, or refuse to.

    The domain check is a guardrail, not a typo check. `ENGINEERING_GUIDELINES.md` §4 forbids credit
    scoring, underwriting, collateral valuation and money movement; this is the line of
    code that makes "we declared those domains but did not build them" true by
    construction rather than by intention.
    """
    if spec.entity_type not in ENTITY_TYPES:
        raise FeatureError(
            f"{spec.name}: unknown entity_type {spec.entity_type!r}; "
            f"expected one of {ENTITY_TYPES}"
        )
    if spec.domain not in domains.MVP_DOMAINS:
        domain = domains.DOMAINS_BY_KEY.get(spec.domain)
        citation = (
            f" ENGINEERING_GUIDELINES.md {domain.guardrail_section} still forbids it: "
            f"{domain.guardrail_ref!r}."
            if domain is not None and domain.guardrail_ref
            else " That domain is not declared at all."
        )
        raise FeatureError(
            f"{spec.name}: domain {spec.domain!r} is not an MVP domain, so this "
            f"feature may not be registered.{citation}"
        )
    if spec.key in REGISTRY:
        raise FeatureError(f"{spec.key} is already registered")
    REGISTRY[spec.key] = spec
    return spec


def feature(name: str, *, version: int, entity_type: str, domain: str, unit: str | None,
            description: str = "", depends_on: tuple[str, ...] = ()):
    """Decorator form of `register`."""

    def decorate(fn):
        register(
            FeatureSpec(
                name=name, version=version, entity_type=entity_type, domain=domain,
                unit=unit, description=description or (fn.__doc__ or "").strip(),
                compute=fn, depends_on=tuple(depends_on),
            )
        )
        return fn

    return decorate


def _reset_for_tests() -> None:
    REGISTRY.clear()


def get(name: str, version: int | None = None) -> FeatureSpec:
    if version is not None:
        return REGISTRY[f"{name}:v{version}"]
    matches = [s for s in REGISTRY.values() if s.name == name]
    if not matches:
        raise FeatureError(f"unknown feature {name!r}")
    return max(matches, key=lambda s: s.version)


def resolve_order(specs=None) -> list[FeatureSpec]:
    """Topological order over `depends_on`, with cycle detection (Kahn).

    Every feature today declares no dependencies, so this is currently an elaborate
    way to sort a flat list. It is here anyway because retrofitting a cycle detector
    onto a dependency graph that already exists is a rewrite, and because the first
    cyclic pair would otherwise present as a recursion error at 3am rather than as a
    named failure at registration time.
    """
    specs = list(specs if specs is not None else REGISTRY.values())
    by_name = {s.name: s for s in specs}
    indegree = {s.name: 0 for s in specs}
    dependents: dict[str, list[str]] = {s.name: [] for s in specs}

    for spec in specs:
        for dependency in spec.depends_on:
            if dependency not in by_name:
                raise FeatureError(
                    f"{spec.name} depends on {dependency!r}, which is not registered"
                )
            indegree[spec.name] += 1
            dependents[dependency].append(spec.name)

    ready = sorted(n for n, d in indegree.items() if d == 0)
    ordered: list[FeatureSpec] = []
    while ready:
        name = ready.pop(0)
        ordered.append(by_name[name])
        for dependent in dependents[name]:
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                ready.append(dependent)
        ready.sort()

    if len(ordered) != len(specs):
        cyclic = sorted(set(indegree) - {s.name for s in ordered})
        raise FeatureError(f"dependency cycle among features: {cyclic}")
    return ordered
