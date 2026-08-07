"""Collateral valuation (pure, framework-free).

Applies a lender's transcribed advance-rate schedule to registered assets, or refuses.
With `collateral_valuation.TRANSCRIBED` empty, no loan-to-value figure exists anywhere.

**The asymmetry that shapes this module.** A missing advance rate has no safe default:

* Defaulted to 100%, an unvalued asset becomes full coverage and a lender's exposure is
  understated.
* Defaulted to 0%, a borrower is denied collateral they actually hold.

Both errors look like arithmetic, neither announces itself, and they point in opposite
directions — so there is no conservative choice to fall back on. The only honest move is
to refuse, which is what `value_assets` does for any asset whose type has no transcribed
rate.

**Field-to-parcel partiality is respected, not assumed away.** `FieldParcelOverlap`'s
docstring warns that pledging a parcel does not pledge a whole field. `land_selection`
already refuses to compute coverage when an overlap area is unrecorded, and this module
takes `pledgeable_area_m2` as an explicit input rather than deriving it from field area —
so an unmeasured overlap cannot quietly inflate collateral here either.

**Nothing is perfected and nothing moves.** Registering and valuing collateral is
decision support. Filing a security interest, and any money advanced against one, remain
outside this system.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app import collateral_valuation
from app.refusal import NO_DATA_FOR_FARM, NO_SOURCE_TRANSCRIBED, OUTSIDE_SOURCE_SCOPE, Refusal

MODEL_VERSION = "collateral_valuation_v1"

NO_ADVANCE_RATE_SUPPLIED = NO_SOURCE_TRANSCRIBED
ASSET_NOT_VALUED = "asset_has_no_assessed_value"


@dataclass(frozen=True)
class Asset:
    """A registered asset. `assessed_value` comes from the basis the rate assumes."""

    collateral_type: str
    assessed_value: float | None
    currency: str
    valuation_basis: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class AssetValuation:
    """One asset's advanced value, with the rate and basis that produced it."""

    collateral_type: str
    assessed_value: float
    advance_rate_pct: float
    advanced_value: float
    valuation_basis: str
    currency: str

    def as_payload(self) -> dict:
        return {
            "collateral_type": self.collateral_type,
            "assessed_value": round(self.assessed_value, 2),
            "advance_rate_pct": self.advance_rate_pct,
            "advanced_value": round(self.advanced_value, 2),
            "valuation_basis": self.valuation_basis,
            "currency": self.currency,
        }


@dataclass(frozen=True)
class CollateralPosition:
    """Total advanced value across registered assets."""

    currency: str
    model_version: str = MODEL_VERSION
    valuations: tuple[AssetValuation, ...] = field(default_factory=tuple)

    @property
    def total_advanced_value(self) -> float:
        return sum(v.advanced_value for v in self.valuations)

    def loan_to_value(self, exposure_amount: float | None):
        """LTV, or a Refusal. Never returns a number when the denominator is unknown."""
        if exposure_amount is None:
            return Refusal(
                NO_DATA_FOR_FARM,
                "No exposure amount supplied, so loan-to-value has no numerator.",
                {},
            )
        total = self.total_advanced_value
        if total <= 0:
            return Refusal(
                NO_DATA_FOR_FARM,
                "Total advanced value is zero, so loan-to-value is undefined rather "
                "than infinite.",
                {},
            )
        return exposure_amount / total

    def as_payload(self) -> dict:
        return {
            "model_version": self.model_version,
            "currency": self.currency,
            "valuations": [v.as_payload() for v in self.valuations],
            "total_advanced_value": round(self.total_advanced_value, 2),
            "not_calculated": {
                "security_interest": (
                    "Nothing here perfects or files a security interest, and no money "
                    "is advanced against these assets. This is a valuation, not a lien."
                ),
            },
        }


def value_assets(assets, *, currency: str):
    """Apply transcribed advance rates. Returns CollateralPosition | Refusal.

    All-or-nothing: one un-rated or un-valued asset refuses the whole position, because
    a total that silently omits an asset is a total the reader will treat as complete.
    """
    if not collateral_valuation.TRANSCRIBED:
        return Refusal(
            NO_ADVANCE_RATE_SUPPLIED,
            "No collateral advance rates have been transcribed, so no asset can be "
            "valued as security. There is no safe default rate — see "
            "app/collateral_valuation.py.",
            {"model_version": MODEL_VERSION},
        )

    rows = list(assets or ())
    if not rows:
        return Refusal(
            NO_DATA_FOR_FARM,
            "No collateral assets are registered for this farm.",
            {},
        )

    rates = {r.collateral_type: r for r in collateral_valuation.TRANSCRIBED}
    valuations = []
    for asset in rows:
        if asset.currency != currency:
            return Refusal(
                OUTSIDE_SOURCE_SCOPE,
                f"Asset currency {asset.currency} differs from the position currency "
                f"{currency}. Converting between them needs an FX rate this system does "
                "not hold and would not know the date of.",
                {"asset_currency": asset.currency, "position_currency": currency},
            )
        rate = rates.get(asset.collateral_type)
        if rate is None:
            return Refusal(
                OUTSIDE_SOURCE_SCOPE,
                f"No transcribed advance rate covers {asset.collateral_type!r}. There "
                "is no safe default: 100% understates the lender's exposure and 0% "
                "denies the borrower collateral they hold.",
                {"collateral_type": asset.collateral_type},
            )
        if asset.assessed_value is None:
            return Refusal(
                ASSET_NOT_VALUED,
                f"The registered {asset.collateral_type!r} has no assessed value, so an "
                "advance rate has nothing to apply to. The value must come from the "
                f"basis the rate assumes: {rate.valuation_basis}.",
                {
                    "collateral_type": asset.collateral_type,
                    "required_basis": rate.valuation_basis,
                },
            )

        valuations.append(AssetValuation(
            collateral_type=asset.collateral_type,
            assessed_value=asset.assessed_value,
            advance_rate_pct=rate.advance_rate_pct,
            advanced_value=asset.assessed_value * rate.advance_rate_pct / 100.0,
            valuation_basis=rate.valuation_basis,
            currency=currency,
        ))

    return CollateralPosition(currency=currency, valuations=tuple(valuations))
