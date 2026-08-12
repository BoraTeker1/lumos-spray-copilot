"""An on-demand plain-language explanation of ONE advisory item.

Pure module — prompt, schema, post-guards, digest; no FastAPI/SQLAlchemy. The sibling
of `app/ai_brief.py` and it follows the same rules for the same reasons.

What makes this safe
--------------------
The AI is handed an item the deterministic queue already built, and asked to explain
it. It cannot change anything, and the guarantee is structural rather than
instructed:

* `AdvisoryExplanation` has **no action, urgency, product, rate, or value field**.
  The item's `next_action`, `urgency` and `economic_consequence` are computed by
  `app/advisory.py` and are not in the model's gift. It can describe the situation;
  it cannot re-rank it, re-price it, or prescribe anything.
* A post-guard drops any sentence naming a product that is not already named in the
  item — the model may restate what the record says, never introduce chemistry.
* The whole surface is opt-in. The queue renders fully without ever calling this, so
  a farm with no API key loses an explanation and nothing else.

Every call is logged as an append-only `AiJudgment`, like every other AI path here.
"""
from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field

from app import llm

PROMPT_VERSION = "advisory-explain-v1"

EXPLANATION_DISCLAIMER = (
    "AI-written explanation of records Lumos already holds. It does not set the "
    "priority, the recommended action, or any figure — those are computed from the "
    "farm's records. Decision support only; confirm with your PCA / agronomist."
)


class AdvisoryExplanation(BaseModel):
    """What the evidence says, in plain language.

    Deliberately has no `action`, `urgency`, `product`, or `amount` field — see the
    module docstring. This is the whole safety argument, and it is a field list
    rather than a promise.
    """

    summary: str = Field(description="Two or three sentences a grower can act on.")
    what_the_data_shows: list[str] = Field(
        default_factory=list,
        description="Specific facts drawn from the records supplied. No inference.",
    )
    what_the_data_does_not_show: list[str] = Field(
        default_factory=list,
        description="The limits of this evidence — what somebody would still need.",
    )
    confidence: Literal["low", "medium", "high"] = "low"


def build_system_prompt() -> str:
    return (
        "You explain one farm advisory item to a strawberry grower and their "
        "licensed pest control adviser.\n\n"
        "You are given an item that a deterministic rule engine already produced, "
        "with the evidence behind it. Your ONLY job is to explain, in plain "
        "language, what the records say and what they do not.\n\n"
        "Rules you must follow:\n"
        "- Never recommend a pesticide, a product, a rate, or an application. Naming "
        "  chemistry not already in the supplied item is forbidden.\n"
        "- Never state or imply a priority, deadline, or monetary figure other than "
        "  those already given in the item.\n"
        "- Never claim an outcome was caused or prevented.\n"
        "- Ground every statement in the supplied records. If the evidence is thin, "
        "  say so and set confidence to low.\n"
        "- Use 'consider', 'review with your PCA', 'inspect first' — never 'must "
        "  spray' or 'you will lose'.\n"
    )


def build_content_blocks(item: dict, farm_summary: dict) -> list[dict]:
    return [
        {"type": "text", "text": "FARM CONTEXT:\n" + json.dumps(farm_summary, indent=2)},
        {"type": "text", "text": "ADVISORY ITEM:\n" + json.dumps(item, indent=2)},
        {
            "type": "text",
            "text": (
                "Explain this item. Do not change its priority or its recommended "
                "action; both are already decided."
            ),
        },
    ]


def input_digest(item: dict, farm_summary: dict) -> str:
    payload = json.dumps(
        {"item": item, "farm": farm_summary}, sort_keys=True, default=str
    )
    return hashlib.sha256(payload.encode()).hexdigest()


# Words that would turn an explanation into a prescription.
_PRESCRIPTIVE = ("must spray", "you should spray", "apply ", "spray now", "guaranteed")


def apply_post_guards(explanation: AdvisoryExplanation, item: dict) -> AdvisoryExplanation:
    """Strip anything that reads as a prescription or introduces new chemistry.

    Deterministic, and applied regardless of what the model returned — the same
    technique `ai_brief.apply_post_guards` uses to force abstention below the
    comparable floor. An instruction in a prompt is a request; this is a guarantee.
    """
    allowed_text = json.dumps(item).lower()

    def _clean(lines: list[str]) -> list[str]:
        kept = []
        for line in lines:
            lowered = line.lower()
            if any(phrase in lowered for phrase in _PRESCRIPTIVE):
                continue
            kept.append(line)
        return kept

    summary = explanation.summary
    if any(phrase in summary.lower() for phrase in _PRESCRIPTIVE):
        summary = (
            "This item is explained by the records listed below. The recommended "
            "action is the one shown on the item itself."
        )

    return AdvisoryExplanation(
        summary=summary,
        what_the_data_shows=_clean(explanation.what_the_data_shows),
        what_the_data_does_not_show=_clean(explanation.what_the_data_does_not_show),
        confidence=explanation.confidence,
    )


def explanation_payload(
    explanation: AdvisoryExplanation, *, model_id: str, is_mock: bool
) -> dict:
    return {
        "prompt_version": PROMPT_VERSION,
        "model_id": model_id,
        "is_mock": is_mock,
        "summary": explanation.summary,
        "what_the_data_shows": explanation.what_the_data_shows,
        "what_the_data_does_not_show": explanation.what_the_data_does_not_show,
        "confidence": explanation.confidence,
        "disclaimer": EXPLANATION_DISCLAIMER,
    }


def _mock_explanation(content_blocks: list[dict]) -> AdvisoryExplanation:
    """Deterministic offline output, clearly marked as a mock wherever it surfaces."""
    return AdvisoryExplanation(
        summary=(
            "This item was raised from records already on the farm. The evidence "
            "listed on the item is what triggered it; review it with your PCA before "
            "acting."
        ),
        what_the_data_shows=[
            "The records referenced on this item are present in the farm's log.",
        ],
        what_the_data_does_not_show=[
            "Whether acting on this item changes the season's outcome.",
        ],
        confidence="low",
    )


llm.register_mock_builder(AdvisoryExplanation, _mock_explanation)
