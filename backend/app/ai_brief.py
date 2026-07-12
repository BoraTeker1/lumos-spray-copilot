"""AI review brief: retrieval-grounded rescue-risk note + next evidence actions.

For one pre-spray decision, an LLM writes a qualitative brief grounded ONLY in the
records it is shown: the decision's own audit payload plus comparable REAL decisions
on the same farm (same target via the explicit alias dictionary, or same chemistry)
with their follow-up summaries. Pure module — prompts, schemas, post-guards; no
FastAPI/SQLAlchemy.

Honesty rules (ENGINEERING_GUIDELINES.md §9–§10 + this milestone's constraints)
---------------------------------------------------------------
* The brief NEVER changes the decision: the compliance verdict stays deterministic.
* No numeric probabilities — a qualitative low/medium/high grounded in retrieved
  records with counts, or ABSTAIN. With fewer than MIN_COMPARABLES real comparable
  decisions, a deterministic post-guard forces abstention regardless of model output.
* The action vocabulary is enum-locked to EVIDENCE GATHERING only — recommending a
  product or a spray is structurally inexpressible.
* Every brief is logged to the append-only AI judgment log so predictions can be
  compared to real outcomes later (calibration). Not validated against outcomes yet.
"""
from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field

from app import llm

PROMPT_VERSION = "ai-brief-v1"

# Below this many real comparable decisions, the risk note MUST abstain.
MIN_COMPARABLES = 2

BRIEF_DISCLAIMER = (
    "AI-suggested, not confirmed. Not validated against outcomes yet (comparable "
    "count shown). The compliance verdict above is deterministic and unchanged by "
    "this brief. Decision support only — final decisions rest with the grower and a "
    "licensed PCA/agronomist."
)

# Evidence-gathering actions ONLY. A product or spray recommendation cannot be
# expressed in this vocabulary — that is the point.
EvidenceActionType = Literal[
    "rescout_target",
    "verify_phi_rei_from_label",
    "confirm_threshold_with_pca",
    "record_follow_up",
    "wait_and_recheck",
    "consult_pca",
]

RescueRisk = Literal["low", "medium", "high", "abstain"]


class EvidenceAction(BaseModel):
    action_type: EvidenceActionType
    detail: str = ""


class AiBrief(BaseModel):
    rescue_risk: RescueRisk = "abstain"
    rationale: str = ""
    next_evidence_actions: list[EvidenceAction] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high", "none"] = "none"
    abstained: bool = False
    abstain_reason: str | None = None


def build_system_prompt() -> str:
    return (
        "You write a short review brief for ONE planned pesticide application in a "
        "specialty-crop decision-support system. You are given (a) the decision's "
        "deterministic audit payload and (b) comparable past decisions on the SAME "
        "farm with their recorded follow-up outcomes.\n"
        "Rules you must never break:\n"
        "1. Ground every statement ONLY in the provided records. No outside "
        "agronomic claims, no general knowledge about pests or products.\n"
        "2. NEVER recommend spraying, never name or suggest any product, rate, or "
        "chemistry. Your action vocabulary is evidence gathering only.\n"
        "3. rescue_risk is a qualitative read of the provided comparables (did "
        "similar holds/delays end in rescue applications?) — never a probability.\n"
        "4. If the comparables are too few, too different, or lack follow-up data, "
        "set rescue_risk='abstain', abstained=true, and say why in abstain_reason.\n"
        "5. rationale must cite the comparable decisions by id and their recorded "
        "outcomes, and mention what is unverified/missing in this decision.\n"
        "You are decision support for a licensed PCA — the deterministic compliance "
        "verdict is not yours to change."
    )


def build_content_blocks(decision_summary: dict, comparables: list[dict]) -> list[dict]:
    body = json.dumps(
        {"decision": decision_summary, "comparables": comparables},
        indent=2, sort_keys=True, default=str,
    )
    return [{
        "type": "text",
        "text": (
            f"{body}\n\nWrite the review brief for `decision` as instructed, "
            f"grounded only in the data above."
        ),
    }]


def input_digest(decision_summary: dict, comparables: list[dict]) -> str:
    h = hashlib.sha256()
    h.update(PROMPT_VERSION.encode())
    h.update(json.dumps(
        {"decision": decision_summary, "comparables": comparables},
        sort_keys=True, default=str,
    ).encode())
    return h.hexdigest()


def apply_post_guards(brief: AiBrief, comparable_count: int) -> AiBrief:
    """Deterministic guards the model cannot talk its way around."""
    if comparable_count < MIN_COMPARABLES and brief.rescue_risk != "abstain":
        brief = brief.model_copy(update={
            "rescue_risk": "abstain",
            "abstained": True,
            "abstain_reason": (
                f"Only {comparable_count} comparable real decision(s) on this farm — "
                f"below the minimum of {MIN_COMPARABLES} required for a grounded risk "
                f"note. Logging this brief so calibration becomes possible as real "
                f"outcomes accrue."
            ),
        })
    if brief.abstained or brief.rescue_risk == "abstain":
        brief = brief.model_copy(update={
            "rescue_risk": "abstain", "abstained": True, "confidence": "none",
        })
    return brief


def brief_payload(
    brief: AiBrief, model_id: str, is_mock: bool, comparable_count: int,
    judgment_ids: list[int], comparables: list[dict],
) -> dict:
    return {
        "rescue_risk": brief.rescue_risk,
        "rationale": brief.rationale,
        "next_evidence_actions": [a.model_dump() for a in brief.next_evidence_actions],
        "confidence": brief.confidence,
        "abstained": brief.abstained,
        "abstain_reason": brief.abstain_reason,
        "comparable_count": comparable_count,
        "comparables": comparables,
        "model": model_id,
        "is_mock": is_mock,
        "prompt_version": PROMPT_VERSION,
        "judgment_ids": judgment_ids,
        "is_ai_generated": True,
        "disclaimer": BRIEF_DISCLAIMER,
    }


# ------------------------------------------------------------------ mock builder
def _mock_brief(content_blocks: list[dict]) -> AiBrief:
    """Deterministic canned brief. Always returns a non-abstaining 'low' so tests can
    prove the MIN_COMPARABLES post-guard forces abstention server-side."""
    text = " ".join(b.get("text", "") for b in content_blocks)
    try:
        data = json.loads(text[: text.rindex("}") + 1][text.index("{"):])
        comparable_ids = [c.get("id") for c in data.get("comparables", [])]
    except (ValueError, json.JSONDecodeError):
        comparable_ids = []
    cited = ", ".join(f"#{i}" for i in comparable_ids) or "none provided"
    return AiBrief(
        rescue_risk="low",
        rationale=(
            f"Mock brief grounded in comparable decision(s): {cited}. Set "
            f"ANTHROPIC_API_KEY for a real model-written brief."
        ),
        next_evidence_actions=[
            EvidenceAction(
                action_type="rescout_target",
                detail="Re-scout the stated target before the intended date.",
            ),
            EvidenceAction(
                action_type="record_follow_up",
                detail="Record follow-up events so this brief can be calibrated.",
            ),
        ],
        confidence="low",
    )


llm.register_mock_builder(AiBrief, _mock_brief)
