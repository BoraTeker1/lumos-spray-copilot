"""Land tenure and parcel coverage (pure, framework-free).

`LandParcel`, `TenureRight` and `FieldParcelOverlap` have existed in `models.py` since the
entity-spine phase with **zero references anywhere else in the codebase**. They were built
for exactly two questions, and this module is the first thing to ask them:

1. **Does the grower hold this land for the whole horizon?** The `TenureRight` docstring
   says it outright: *"a lease that expires inside a loan tenor is an underwriting fact."*
   It is also an agronomic one — a perennial planting on a lease expiring next season is a
   different decision from the same planting on owned ground.
2. **How much of a field is actually on a given parcel?** `FieldParcelOverlap` carries an
   area *because the relationship is partial*, and its docstring warns that a coverage
   calculation assuming otherwise would overstate collateral.

**The distinction this module exists to preserve, and the one everything else here is
built around: an absent end date means two opposite things depending on tenure type.**

* `owned` with `effective_to = None` → held indefinitely. Covers any horizon.
* `leased` with `effective_to = None` → *the end date was never recorded.* It does NOT
  mean perpetual, and treating it as such is the single most consequential defaulting
  error available in this file — it would report a farm as holding land through a horizon
  nobody has evidence for, and that claim would flow into collateral and underwriting.

So `covers_horizon()` refuses on an undated non-ownership right rather than answering.
This is the same shape as `label_table`'s rule that a NULL means *the label is silent*,
never *no limit*.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.refusal import NO_DATA_FOR_FARM, Refusal

MODEL_VERSION = "land_tenure_v1"

# Tenure types whose absence of an end date genuinely means "indefinitely". Everything
# else with no end date is an unrecorded date, not a perpetual right.
INDEFINITE_TENURE_TYPES = ("owned",)

# Refusal codes specific to this module.
TENURE_END_DATE_UNRECORDED = "tenure_end_date_unrecorded"
OVERLAP_AREA_UNRECORDED = "overlap_area_unrecorded"


@dataclass(frozen=True)
class TenureCoverage:
    """Whether recorded rights cover a horizon, and which right is the binding one."""

    covers: bool
    horizon_end: date
    binding_tenure_type: str
    binding_expires_on: date | None
    model_version: str = MODEL_VERSION

    def as_payload(self) -> dict:
        return {
            "model_version": self.model_version,
            "covers_horizon": self.covers,
            "horizon_end": self.horizon_end.isoformat(),
            "binding_tenure_type": self.binding_tenure_type,
            "binding_expires_on": (
                self.binding_expires_on.isoformat() if self.binding_expires_on else None
            ),
        }


@dataclass(frozen=True)
class ParcelCoverage:
    """How much of a field sits on parcels, and how that was determined."""

    field_area_m2: float
    covered_area_m2: float
    determination_methods: tuple[str, ...] = field(default_factory=tuple)
    model_version: str = MODEL_VERSION

    @property
    def covered_fraction(self) -> float:
        return self.covered_area_m2 / self.field_area_m2 if self.field_area_m2 else 0.0

    @property
    def fully_covered(self) -> bool:
        # A hair under 1.0 is a rounding artifact of two hand-entered areas, not a
        # sliver of unpledged ground. A hair over is the same. Neither is worth
        # reporting as a discrepancy; anything larger is.
        return abs(self.covered_fraction - 1.0) < 0.005

    def as_payload(self) -> dict:
        return {
            "model_version": self.model_version,
            "field_area_m2": round(self.field_area_m2, 2),
            "covered_area_m2": round(self.covered_area_m2, 2),
            "covered_fraction": round(self.covered_fraction, 4),
            "fully_covered": self.fully_covered,
            "determination_methods": list(self.determination_methods),
        }


def covers_horizon(tenure_rights, *, horizon_end: date, as_of: date):
    """Do recorded rights cover land through `horizon_end`? Returns TenureCoverage | Refusal.

    Considers only rights already in effect at `as_of` — a lease starting next year does
    not cover this season, and counting it would be the tenure equivalent of the
    hindsight leak `risk_snapshot` guards against.
    """
    rights = [
        r for r in (tenure_rights or ())
        if r.effective_from is None or r.effective_from <= as_of
    ]
    if not rights:
        return Refusal(
            NO_DATA_FOR_FARM,
            "No tenure right is recorded as in effect for this parcel. Ownership or a "
            "lease is a document someone must enter; nothing infers it from farming "
            "activity.",
            {"as_of": as_of.isoformat()},
        )

    # An indefinite right covers any horizon. Take it first — if the grower owns the
    # ground, a short lease alongside it is irrelevant to the question.
    indefinite = [r for r in rights if r.tenure_type in INDEFINITE_TENURE_TYPES
                  and r.effective_to is None]
    if indefinite:
        return TenureCoverage(
            covers=True, horizon_end=horizon_end,
            binding_tenure_type=indefinite[0].tenure_type, binding_expires_on=None,
        )

    # The load-bearing refusal. See the module docstring.
    undated = [r for r in rights if r.effective_to is None]
    if undated:
        return Refusal(
            TENURE_END_DATE_UNRECORDED,
            f"A {undated[0].tenure_type} right on this parcel has no end date recorded. "
            "For a non-ownership right that means the date is unknown, not that the "
            "right is perpetual — so whether it covers the horizon cannot be answered. "
            "Record the end date from the lease document.",
            {"tenure_type": undated[0].tenure_type, "horizon_end": horizon_end.isoformat()},
        )

    latest = max(rights, key=lambda r: r.effective_to)
    return TenureCoverage(
        covers=latest.effective_to >= horizon_end,
        horizon_end=horizon_end,
        binding_tenure_type=latest.tenure_type,
        binding_expires_on=latest.effective_to,
    )


def parcel_coverage(overlaps, *, field_area_m2: float | None):
    """How much of a field sits on parcels. Returns ParcelCoverage | Refusal.

    Refuses when any overlap has no recorded area. Summing the ones that do would
    understate coverage; assuming an unrecorded overlap covers the whole field would
    overstate it — and the `FieldParcelOverlap` docstring names overstatement as the
    error that matters, because it inflates pledgeable collateral.
    """
    if field_area_m2 is None or field_area_m2 <= 0:
        return Refusal(
            NO_DATA_FOR_FARM,
            "No field area recorded, so the share sitting on parcels cannot be "
            "expressed as a fraction of anything.",
            {},
        )
    rows = list(overlaps or ())
    if not rows:
        return Refusal(
            NO_DATA_FOR_FARM,
            "No field-to-parcel overlap is recorded. The agronomic field and the legal "
            "parcel are different objects, and the link between them is entered by a "
            "human — it is never inferred.",
            {},
        )

    unrecorded = [o for o in rows if o.overlap_area_m2 is None]
    if unrecorded:
        return Refusal(
            OVERLAP_AREA_UNRECORDED,
            f"{len(unrecorded)} of {len(rows)} field-to-parcel overlaps have no recorded "
            "area. Totalling only the recorded ones would understate coverage, and "
            "assuming an unrecorded overlap covers the whole field would overstate the "
            "pledgeable area.",
            {"unrecorded_count": len(unrecorded), "total_count": len(rows)},
        )

    return ParcelCoverage(
        field_area_m2=field_area_m2,
        covered_area_m2=sum(o.overlap_area_m2 for o in rows),
        determination_methods=tuple(sorted({
            o.determination_method or "declared" for o in rows
        })),
    )
