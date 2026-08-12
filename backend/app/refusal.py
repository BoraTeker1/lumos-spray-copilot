"""The shared refusal type for models that decline to answer, and say why.

`units.py` and `label_data.py` each already carry a private `Refusal(reason: str)` with
the same one-line docstring: *"Never carries a number."* That instinct — a refusal is a
distinct return type, not a `None` or a zero — is the right one, and the layers added on
2026-08-07 (soil, fertilization, credit scoring, underwriting, pricing, hedging …) all
need it. Ten more private copies would be ten more chances for one of them to quietly
grow a `value` field.

This is a superset of the two existing types rather than a replacement for them. The
existing two are deliberately left alone: they are load-bearing in the label and unit
paths, they are covered by their own tests, and rewriting them to gain a field neither
uses would be churn in exactly the code least worth disturbing.

What this adds over `Refusal(reason)` is **`code`** — a stable, greppable identifier.
Prose refusal reasons drift the moment two people write them, and the things that need
to react to a refusal cannot match on prose:

* tests asserting a *specific* refusal (a model that refuses for the wrong reason is
  broken, and a prose match hides that),
* API payloads, where the frontend must distinguish "no source transcribed" (an operator
  task) from "farm has no data yet" (a grower task) to say anything useful,
* the operator's readiness surfaces, which group refusals by cause.

Two rules the dataclass enforces, both learned from `features/base.py`:

1. **A refusal never carries a value.** There is no `value` field and no way to add one
   without changing this class. `FeatureResult` has the same invariant expressed as
   `abstained ⟺ no value`; here the type system does it outright.
2. **A refusal always names a cause.** A blank code or blank prose raises. "Could not
   calculate" with no reason attached is indistinguishable from a bug, and it sends the
   reader to the code instead of to the missing document.

Framework-free (stdlib only).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Refusal:
    """Why a model declined to produce a value. Never carries one.

    `code` is the stable identity — match on it in tests and switch on it in payloads.
    `detail` is for a human and may be reworded freely; nothing should ever parse it.
    `context` carries structured specifics (which field, which farm, how stale) for the
    reader who needs them, and is omitted from equality-by-code comparisons in practice
    because two refusals with the same code mean the same thing.
    """

    code: str
    detail: str
    context: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.code or "").strip():
            raise ValueError(
                "Refusal.code is blank. A refusal nothing can match on cannot be "
                "tested for, surfaced differently, or acted on — it is a silent None "
                "wearing a type."
            )
        if not str(self.detail or "").strip():
            raise ValueError(
                f"Refusal({self.code!r}).detail is blank. The code says what happened; "
                "the detail must say what to do about it."
            )

    def as_payload(self) -> dict:
        """The wire form. Note there is no `value` key — see the module docstring.

        Consumers render `detail` and switch on `code`. `context` is included only when
        non-empty so an empty dict never reads as 'we looked and found nothing'.
        """
        payload = {"refused": True, "code": self.code, "detail": self.detail}
        if self.context:
            payload["context"] = dict(self.context)
        return payload


def is_refusal(result: object) -> bool:
    """Narrow a `Result | Refusal` union without importing Refusal at every call site."""
    return isinstance(result, Refusal)


# ---------------------------------------------------------------------------
# Codes shared across more than one model.
#
# Model-specific codes live with their model — `credit_scoring.NO_SCORECARD_SUPPLIED`
# belongs next to the thing that raises it. These are here because several layers refuse
# for the identical reason and a reader comparing two surfaces should see one code, not
# two spellings of it.
# ---------------------------------------------------------------------------

# The source module that governs this model ships EMPTY. An operator task: someone must
# read a primary document. Distinct from NO_DATA_FOR_FARM in the way that matters — this
# one is the same for every farm in the system, and no amount of grower activity fixes it.
NO_SOURCE_TRANSCRIBED = "no_source_transcribed"

# The farm has not recorded the inputs this model needs. A grower task, farm-specific.
NO_DATA_FOR_FARM = "no_data_for_farm"

# Inputs exist but are too old to answer the question honestly. Never falls back to the
# most recent available value — see `pricing.py` for why that failure is invisible.
INPUTS_TOO_STALE = "inputs_too_stale"

# A required unit conversion has no cited basis. Mirrors `label_data.convert_rate`,
# which refuses mass↔volume because it needs a per-product density.
CONVERSION_NOT_CITED = "conversion_not_cited"

# The farm/crop/region is outside what the transcribed source covers. Reading a value
# from outside a table's stated range is extrapolation, not lookup.
OUTSIDE_SOURCE_SCOPE = "outside_source_scope"
