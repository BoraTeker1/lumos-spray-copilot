"""The cross-layer view (pure, framework-free).

The stated thesis is that the three layers feed each other: operational farm data
improves advice and underwriting, approved decisions trigger procurement and finance, and
ongoing monitoring evidences farm performance. Until now that was a claim about
architecture. This module is the place it either holds or does not.

**It abstains per field, and that is the entire design.** A profile is the natural home
for a summary number — a readiness percentage, an overall standing, a single score. Every
one of those would be an aggregate across layers that mostly cannot compute, and an
aggregate over abstentions is not a smaller number, it is a meaningless one. So
`FarmProfile` holds each layer's own result or its own refusal, side by side, and
computes nothing across them.

What it *does* compute is the one genuinely cross-layer fact that is honest today:
`blocking_gaps` — which missing thing is stopping which layer. That is the question a
grower and an operator both actually have, and answering it requires seeing all the
layers at once, which is why this module exists rather than the frontend assembling it.

**The blinding constraint.** Nothing here is added to the PCA-facing decision surface.
The Botrytis shadow study depends on the reviewing PCA not seeing model output, and a
profile card on the decision page would break that. This is farm-level and operator/
grower-facing only — the same boundary `DataReadinessCard` respects.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.refusal import Refusal, is_refusal

MODEL_VERSION = "farm_profile_v1"

# The layers, in the order the thesis reads: operations feed advisory, advisory gates
# procurement, procurement and operations feed finance, finance is monitored.
LAYER_OPERATIONS = "operations"
LAYER_ADVISORY = "advisory"
LAYER_PROCUREMENT = "procurement"
LAYER_FINANCE = "finance"
LAYER_MARKET = "market"

LAYERS = (LAYER_OPERATIONS, LAYER_ADVISORY, LAYER_PROCUREMENT, LAYER_FINANCE, LAYER_MARKET)


@dataclass(frozen=True)
class LayerView:
    """One layer's result, or the reason it has none. Never both, never neither."""

    layer: str
    label: str
    result: object | None = None
    refusal: Refusal | None = None

    def __post_init__(self) -> None:
        if self.layer not in LAYERS:
            raise ValueError(f"unknown layer {self.layer!r}; expected one of {LAYERS}")
        if (self.result is None) == (self.refusal is None):
            raise ValueError(
                f"{self.layer}: a LayerView must carry exactly one of result or "
                "refusal. Both would be ambiguous; neither would render as an empty "
                "card that reads like 'nothing to report' rather than 'not computed'."
            )

    @property
    def available(self) -> bool:
        return self.result is not None

    def as_payload(self) -> dict:
        payload = {"layer": self.layer, "label": self.label, "available": self.available}
        if self.result is not None:
            payload["result"] = (
                self.result.as_payload()
                if hasattr(self.result, "as_payload") else self.result
            )
        if self.refusal is not None:
            payload["refusal"] = self.refusal.as_payload()
        return payload


@dataclass(frozen=True)
class BlockingGap:
    """What is missing, which layer it blocks, and whose job it is to fix.

    `owner` is the useful part and the reason this is computed rather than rendered.
    A grower staring at five empty cards cannot tell which are waiting on them and
    which are waiting on Lumos; the refusal code answers that and nothing else does.
    """

    layer: str
    code: str
    detail: str
    owner: str

    def as_payload(self) -> dict:
        return {
            "layer": self.layer, "code": self.code,
            "detail": self.detail, "owner": self.owner,
        }


# Who unblocks which refusal. The mapping is the point: "no source transcribed" is never
# something a grower can fix, and telling them to go enter more data would be wrong.
OWNER_OPERATOR = "operator"      # someone must read and transcribe a document
OWNER_GROWER = "grower"          # someone must record farm data
OWNER_UNDETERMINED = "undetermined"

_OWNER_BY_CODE = {
    "no_source_transcribed": OWNER_OPERATOR,
    "no_data_for_farm": OWNER_GROWER,
    "inputs_too_stale": OWNER_OPERATOR,
    "outside_source_scope": OWNER_OPERATOR,
    "conversion_not_cited": OWNER_OPERATOR,
    "scorecard_input_abstained": OWNER_GROWER,
    "scorecard_input_missing": OWNER_GROWER,
    "tenure_end_date_unrecorded": OWNER_GROWER,
    "overlap_area_unrecorded": OWNER_GROWER,
    "asset_has_no_assessed_value": OWNER_GROWER,
}


@dataclass(frozen=True)
class FarmProfile:
    """Every layer's view of one farm, side by side. Deliberately not a score."""

    farm_id: int
    model_version: str = MODEL_VERSION
    layers: tuple[LayerView, ...] = field(default_factory=tuple)

    @property
    def blocking_gaps(self) -> tuple[BlockingGap, ...]:
        return tuple(
            BlockingGap(
                layer=view.layer, code=view.refusal.code, detail=view.refusal.detail,
                owner=_OWNER_BY_CODE.get(view.refusal.code, OWNER_UNDETERMINED),
            )
            for view in self.layers if view.refusal is not None
        )

    @property
    def available_layers(self) -> tuple[str, ...]:
        return tuple(v.layer for v in self.layers if v.available)

    def as_payload(self) -> dict:
        gaps = self.blocking_gaps
        return {
            "model_version": self.model_version,
            "farm_id": self.farm_id,
            "layers": [v.as_payload() for v in self.layers],
            "available_layers": list(self.available_layers),
            "blocking_gaps": [g.as_payload() for g in gaps],
            # Grouped so a card can say "3 things you can fix, 2 waiting on us" without
            # the frontend re-deriving ownership from refusal codes.
            "gaps_by_owner": {
                owner: [g.as_payload() for g in gaps if g.owner == owner]
                for owner in (OWNER_GROWER, OWNER_OPERATOR, OWNER_UNDETERMINED)
                if any(g.owner == owner for g in gaps)
            },
            "not_calculated": {
                "overall_score": (
                    "There is no single farm score. Each layer either computed or "
                    "abstained for its own reason, and an average across layers that "
                    "mostly abstain is not a smaller number — it is a meaningless one."
                ),
                "readiness_percentage": (
                    "No percentage of readiness. Counting available layers would "
                    "weight a transcribed price series equally with a credit "
                    "assessment, which is not a comparison anyone should act on."
                ),
            },
        }


def build(*, farm_id: int, views):
    """Assemble a profile from each layer's already-computed result or refusal.

    Takes results rather than fetching them: this module stays pure, and the caller
    (`crud`/`main`) owns the DB access. `views` is an iterable of `(layer, label,
    result_or_refusal)`.
    """
    assembled = []
    for layer, label, outcome in views:
        if is_refusal(outcome):
            assembled.append(LayerView(layer=layer, label=label, refusal=outcome))
        elif outcome is None:
            raise ValueError(
                f"{layer}: a layer must supply a result or a Refusal, never None. None "
                "renders as an empty card that reads like 'nothing to report'."
            )
        else:
            assembled.append(LayerView(layer=layer, label=label, result=outcome))

    return FarmProfile(farm_id=farm_id, layers=tuple(assembled))
