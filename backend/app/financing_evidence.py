"""The lender-ready evidence package, assembled from what the farm already records.

Pure and framework-free (no FastAPI / SQLAlchemy imports). The caller owns the DB
access and hands in the season closeout, the performance profile, and the farm's
decisions — all already built elsewhere. Nothing here recomputes a number.

The product insight this module exists to make visible
------------------------------------------------------
The same operational records that let Lumos advise a grower are the records a lender
asks for. A farm that logs its sprays, costs, settlements and decisions is not just
better advised, it is more legible to credit. This module does the assembling so the
grower does not have to reconstruct three years of paperwork by hand.

Readiness is a checklist, not a score
-------------------------------------
The output is which evidence a lender typically asks for, which of it this farm has
on record, and who can close each gap. There is no percentage, no rating, and no
approval likelihood — those would be Lumos forming a credit opinion, which is the
lender's job and nobody has given Lumos the policy to form one with. What Lumos can
say honestly is "here is what is recorded and here is what is not", and that is
genuinely useful on its own.

An item is present only when a real value backs it
--------------------------------------------------
`present` is never set from the existence of a row; it is set from a metric that
actually computed. A crop cycle with a planted area of zero, or a revenue figure the
closeout refused because every settlement was in another currency, counts as missing.
The whole package is worthless to a lender if "present" can mean "there is a record
that says nothing".
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app import decision_status

MODEL_VERSION = "financing_evidence_v1"

# Who can close a gap. Same vocabulary as `farm_profile`, so one legend serves both.
OWNER_GROWER = "grower"
OWNER_OPERATOR = "operator"

# Categories, in the order a lender reads them.
CATEGORY_IDENTITY = "identity"
CATEGORY_PRODUCTION = "production"
CATEGORY_COST = "cost"
CATEGORY_REVENUE = "revenue"
CATEGORY_COMPLIANCE = "compliance"
CATEGORY_COLLATERAL = "collateral"

CATEGORY_LABELS = {
    CATEGORY_IDENTITY: "Farm and land",
    CATEGORY_PRODUCTION: "Production record",
    CATEGORY_COST: "Cost record",
    CATEGORY_REVENUE: "Revenue record",
    CATEGORY_COMPLIANCE: "Compliance and decision record",
    CATEGORY_COLLATERAL: "Collateral",
}

PACKAGE_DISCLAIMER = (
    "Assembled from records this farm entered. Lumos states what is on record and "
    "what is not; it forms no credit opinion, estimates no approval likelihood, and "
    "quotes no rate. Any lending decision is the lender's."
)


@dataclass(frozen=True)
class EvidenceItem:
    """One thing a lender asks for, and whether this farm can show it."""

    key: str
    label: str
    category: str
    present: bool
    value_summary: str | None = None
    source: str = ""
    who_fixes: str = OWNER_GROWER
    how: str = ""

    def __post_init__(self) -> None:
        if not self.present and not self.how:
            raise ValueError(
                f"{self.key}: a missing evidence item must say how to close it — "
                "a gap nobody can act on is just a complaint."
            )

    def as_payload(self) -> dict:
        payload = {
            "key": self.key,
            "label": self.label,
            "category": self.category,
            "present": self.present,
            "source": self.source,
        }
        if self.present:
            payload["value_summary"] = self.value_summary
        else:
            payload["who_fixes"] = self.who_fixes
            payload["how"] = self.how
        return payload


# ------------------------------------------------------------------- helpers
def _computed(metric) -> bool:
    """A metric counts as evidence only when it actually produced a number."""
    return bool(metric) and not metric.get("not_calculated")


def _fmt(value, unit=None) -> str:
    if value is None:
        return ""
    text = f"{value:,.2f}" if isinstance(value, (int, float)) else str(value)
    return f"{text} {unit}".strip() if unit else text


def _metric_item(metric, *, key, label, category, summary_key, unit=None,
                 source="", how="", who=OWNER_GROWER, prefix=""):
    """Build an item from a closeout metric, present iff the metric computed."""
    if _computed(metric):
        return EvidenceItem(
            key=key, label=label, category=category, present=True,
            value_summary=prefix + _fmt(metric.get(summary_key), unit or metric.get("unit")),
            source=source,
        )
    return EvidenceItem(
        key=key, label=label, category=category, present=False,
        source=source, who_fixes=who,
        how=metric.get("reason") if metric else how or "Not recorded.",
    )


# ------------------------------------------------------------------- the build
def build_package(
    *,
    farm,
    cycle=None,
    closeout=None,
    performance=None,
    decisions=(),
    collateral_assets=(),
    today: date,
) -> dict:
    """Everything a lender typically asks for, and whether this farm has it."""
    closeout = closeout or {}
    performance = performance or {}
    metrics = closeout.get("metrics") or {}
    currency = closeout.get("currency") or getattr(farm, "currency_code", None)
    decisions = list(decisions or [])

    items: list[EvidenceItem] = []

    # ---- identity and land ---------------------------------------------------
    items.append(EvidenceItem(
        key="farm_identity", label="Registered farm and location",
        category=CATEGORY_IDENTITY,
        present=bool(getattr(farm, "name", None)),
        value_summary=", ".join(filter(None, [
            getattr(farm, "name", None),
            getattr(farm, "location", None),
            getattr(farm, "country", None),
        ])),
        source="Farm record",
        how="Create the farm record with its location.",
    ))
    items.append(_metric_item(
        metrics.get("planted_area"),
        key="land_area", label="Planted area for the season",
        category=CATEGORY_IDENTITY, summary_key="value", unit="m2",
        source="Crop cycle", how="Set the planted area on the crop cycle.",
    ))
    items.append(EvidenceItem(
        key="crop_plan", label="Crop and season on record",
        category=CATEGORY_IDENTITY,
        present=bool(cycle is not None and getattr(cycle, "crop", None)),
        value_summary=(
            f"{getattr(cycle, 'crop', '')} — {getattr(cycle, 'season_label', '')}"
            if cycle else None
        ),
        source="Crop cycle",
        how="Start a crop cycle for the season being financed.",
    ))

    # ---- production ----------------------------------------------------------
    items.append(_metric_item(
        metrics.get("harvested_yield"),
        key="yield_record", label="Recorded harvest yield",
        category=CATEGORY_PRODUCTION, summary_key="value",
        source="Block outcome observations",
        how="Record the harvest as a block outcome from the Season panel.",
    ))
    items.append(_metric_item(
        metrics.get("yield_per_area"),
        key="yield_per_area", label="Yield per area",
        category=CATEGORY_PRODUCTION, summary_key="per_hectare", unit="/ha",
        source="Derived from recorded yield and planted area",
        how="Needs both a recorded yield and a planted area.",
    ))

    season_count = performance.get("closed_season_count", 0)
    items.append(EvidenceItem(
        key="production_history", label="Closed seasons on record",
        category=CATEGORY_PRODUCTION,
        present=bool(season_count),
        value_summary=f"{season_count} closed season(s)",
        source="Crop cycle history",
        how=(
            "A lender reads history. Close each finished crop cycle so its "
            "economics become part of the record."
        ),
    ))

    # ---- cost ----------------------------------------------------------------
    costs = metrics.get("costs") or {}
    counted = costs.get("applications_counted", 0) + costs.get("operations_counted", 0)
    items.append(EvidenceItem(
        key="cost_record", label="Recorded operating costs",
        category=CATEGORY_COST,
        present=bool(counted),
        value_summary=_fmt(costs.get("total"), currency),
        source="Applications and operations",
        how="Record costs against applications and operations for the season.",
    ))
    items.append(_metric_item(
        metrics.get("cost_per_area"),
        key="cost_per_area", label="Cost per area",
        category=CATEGORY_COST, summary_key="per_hectare",
        source="Derived from recorded costs and planted area",
        how="Needs recorded costs and a planted area.",
    ))
    uncosted = (
        costs.get("applications_without_cost", 0) + costs.get("operations_without_cost", 0)
    )
    items.append(EvidenceItem(
        key="cost_completeness", label="Every recorded activity carries a cost",
        category=CATEGORY_COST,
        present=bool(counted) and uncosted == 0,
        value_summary="All recorded activities carry a cost",
        source="Applications and operations",
        how=(
            f"{uncosted} recorded activity(ies) carry no cost, so the cost record is "
            "incomplete. Add a cost to each."
            if uncosted else "Record the season's activities and their costs."
        ),
    ))

    # ---- revenue -------------------------------------------------------------
    revenue = metrics.get("revenue") or {}
    items.append(EvidenceItem(
        key="revenue_record", label="Recorded settlements",
        category=CATEGORY_REVENUE,
        present=_computed(revenue),
        value_summary=(
            f"{_fmt(revenue.get('net'), currency)} net from "
            f"{revenue.get('sales_counted', 0)} settlement(s)"
            if _computed(revenue) else None
        ),
        source="Sale records",
        how=revenue.get("reason") or "Record what the crop sold for.",
    ))
    items.append(_metric_item(
        metrics.get("realised_price_per_yield_unit"),
        key="realised_price", label="Realised price per unit",
        category=CATEGORY_REVENUE, summary_key="value",
        source="Derived from settlements and recorded yield",
        how="Needs both a recorded settlement and a recorded yield.",
    ))

    # ---- compliance and decisions -------------------------------------------
    items.append(EvidenceItem(
        key="spray_log", label="Pesticide application log",
        category=CATEGORY_COMPLIANCE,
        present=bool(decisions),
        value_summary=f"{len(decisions)} decision(s) checked before spraying",
        source="Planned sprays and applications",
        how="Log applications through the pre-spray check so they carry a record.",
    ))
    open_conflicts = sum(1 for d in decisions if decision_status.open_conflict(d))
    items.append(EvidenceItem(
        key="compliance_record", label="No unresolved timing conflicts",
        category=CATEGORY_COMPLIANCE,
        present=bool(decisions) and open_conflicts == 0,
        value_summary="No unresolved harvest-interval or re-entry conflicts",
        source="Decision record",
        how=(
            f"{open_conflicts} decision(s) carry an unresolved critical finding. "
            "Resolve or document each."
            if open_conflicts else "Run applications through the pre-spray check."
        ),
    ))
    reviewed = sum(
        1 for d in decisions
        if decision_status.review_state(d) in decision_status.RESOLVED_REVIEW_STATUSES
    )
    items.append(EvidenceItem(
        key="decision_record", label="Licensed adviser review on record",
        category=CATEGORY_COMPLIANCE,
        present=bool(reviewed),
        value_summary=f"{reviewed} decision(s) reviewed by a PCA / agronomist",
        source="PCA review record",
        how="Have your PCA review decisions in Lumos so the sign-off is recorded.",
    ))

    # ---- collateral ----------------------------------------------------------
    valued = [
        a for a in (collateral_assets or [])
        if getattr(a, "assessed_value", None) is not None
    ]
    items.append(EvidenceItem(
        key="collateral_register", label="Registered collateral with a valuation",
        category=CATEGORY_COLLATERAL,
        present=bool(valued),
        value_summary=f"{len(valued)} asset(s) registered with an assessed value",
        source="Collateral register",
        how=(
            "Register the assets being offered as security, each with the valuation "
            "and who made it. Lumos records a valuation; it never estimates one."
        ),
        who_fixes=OWNER_OPERATOR,
    ))

    # ---- assemble ------------------------------------------------------------
    present = [i for i in items if i.present]
    missing = [i for i in items if not i.present]

    categories = []
    for key, label in CATEGORY_LABELS.items():
        in_category = [i for i in items if i.category == key]
        categories.append({
            "key": key,
            "label": label,
            "present_count": sum(1 for i in in_category if i.present),
            "total_count": len(in_category),
            "items": [i.as_payload() for i in in_category],
        })

    return {
        "model_version": MODEL_VERSION,
        "farm_id": getattr(farm, "id", None),
        "crop_cycle_id": getattr(cycle, "id", None) if cycle else None,
        "currency": currency,
        "as_of": today.isoformat(),
        "categories": categories,
        "items": [i.as_payload() for i in items],
        "present_count": len(present),
        "missing_count": len(missing),
        "total_count": len(items),
        # The keys a lender's `required_evidence` rules are matched against. Only
        # items actually backed by a value appear, so an unmet condition can never be
        # satisfied by an empty record.
        "evidence_keys": [i.key for i in present],
        "missing": [i.as_payload() for i in missing],
        "is_simulated": closeout.get("is_simulated", False),
        "basis_text": (
            f"{len(present)} of {len(items)} evidence items a lender typically asks "
            "for are on record for this farm. This is a count of records, not an "
            "assessment of creditworthiness."
        ),
        "disclaimer": PACKAGE_DISCLAIMER,
    }
