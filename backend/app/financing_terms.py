"""Financing products — EMPTY until a lender's published product terms are transcribed.

`FinancingOffer` in the procurement module predates this file and stays as it is: an
operator-entered, explicitly INDICATIVE offer attached to a supplier quote, with its
cost disclosed as free text. This module is the other half — the lender's actual
published product catalogue, against which an indicative offer can be checked for
plausibility rather than simply believed.

**`disclosed_cost_summary` is a verbatim string, not a structured APR, and that is the
most deliberate decision in this file.** A structured rate invites an amortisation
schedule; an amortisation schedule is a repayment obligation computed by Lumos; and a
repayment obligation computed by Lumos is money math on a real debt, which ENGINEERING_GUIDELINES.md §4
still forbids and this expansion did not lift. Keeping the cost as the lender's own
sentence keeps the disclosure accurate and the temptation structurally out of reach —
the same reason `procurement_status` says `selected` and never `accepted`.

**What fills it:** the lender's published product sheet or term sheet — purpose,
amount range, term, currency, and their own words for what it costs.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.transcription import Citation

PRIMARY_SOURCE = (
    "The lending partner's published product sheet or term sheet: product name, "
    "eligible purpose, minimum and maximum amount, term, currency, and the cost "
    "disclosure in the lender's own wording. Transcribe the cost sentence VERBATIM — "
    "do not restate it as a rate, and do not compute a schedule from it."
)

# What a financing product may be used for. `input_purchase` is the only one the
# procurement chain currently reaches; the rest are declared so the catalogue can
# describe a real lender's range without the code implying Lumos brokers them.
FINANCING_PURPOSES = (
    "input_purchase",
    "working_capital",
    "equipment",
    "land",
)


@dataclass(frozen=True, kw_only=True)
class FinancingProduct:
    """One published financing product. No computed rate, by design."""

    product_code: str
    lender: str
    purpose: str
    currency: str
    disclosed_cost_summary: str
    citation: Citation
    minimum_amount: float | None = None
    maximum_amount: float | None = None
    term_days: int | None = None

    def __post_init__(self) -> None:
        if not self.product_code.strip():
            raise ValueError("FinancingProduct.product_code is blank")
        if self.purpose not in FINANCING_PURPOSES:
            raise ValueError(
                f"{self.product_code}: unknown purpose {self.purpose!r}; "
                f"declared purposes are {FINANCING_PURPOSES}"
            )
        if len(self.currency) != 3:
            raise ValueError(
                f"{self.product_code}: currency must be a 3-letter ISO code"
            )
        if not self.disclosed_cost_summary.strip():
            raise ValueError(
                f"{self.product_code}: disclosed_cost_summary is blank. A financing "
                "product with no stated cost would be presented to a grower as though "
                "it were free."
            )
        if (
            self.minimum_amount is not None
            and self.maximum_amount is not None
            and self.minimum_amount > self.maximum_amount
        ):
            raise ValueError(f"{self.product_code}: minimum_amount exceeds maximum_amount")
        if self.term_days is not None and self.term_days <= 0:
            raise ValueError(f"{self.product_code}: term_days must be positive")


# EMPTY. See the module docstring.
TRANSCRIBED: tuple[FinancingProduct, ...] = ()
