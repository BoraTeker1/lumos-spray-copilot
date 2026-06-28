"""Photo-analysis (computer vision) module for the 'do I really need to spray?' copilot.

Design (mirrors `weather.py`)
-----------------------------
* `build_observation_suggestion(...)` is the pure, testable core: it maps a model *finding*
  to a draft scouting observation the grower/PCA reviews and confirms. CV is an INPUT to the
  existing rule engine, never the decider.
* `VisionService` is a small abstraction. `ClaudeVisionService` calls Claude's multimodal
  model (`claude-opus-4-8`) to describe what's visible in a field photo; `MockVisionService`
  returns a deterministic demo finding so the demo/tests work offline with no API key.
* `default_vision_service` picks the real model only when an `ANTHROPIC_API_KEY` is present
  AND the `anthropic` package is importable; otherwise it falls back to the mock.

Honesty rules (ENGINEERING_GUIDELINES.md §9–§10)
--------------------------------
* This is REAL AI (a multimodal LLM), and it is labelled as AI-suggested, not confirmed.
* It does NOT diagnose disease and NEVER tells anyone to spray. It surfaces what it *appears*
  to see, a confidence, and caveats, and routes to a human (scouting note + PCA review).
* The model can be wrong; every result carries a disclaimer and the field findings must be
  confirmed by in-field scouting and a licensed PCA/agronomist before acting.
"""
from __future__ import annotations

import base64
import json
import os
from abc import ABC, abstractmethod
from datetime import date

# Multimodal model used for photo analysis (latest Claude, per project guidance).
VISION_MODEL = "claude-opus-4-8"

# Image guards (keep uploads small and obviously-images).
ALLOWED_MEDIA_TYPES = ("image/jpeg", "image/png", "image/webp", "image/gif")
MAX_IMAGE_BYTES = 8 * 1024 * 1024  # 8 MB

CONFIDENCE_LEVELS = ("low", "medium", "high")

# Reused, cautious wording (matches the tone of the report/audit disclaimers).
PHOTO_DISCLAIMER = (
    "AI photo analysis is decision support only and can be wrong. It does not diagnose "
    "disease and never tells you to spray. Confirm with in-field scouting and a licensed "
    "PCA / agronomist before acting."
)


def _clamp_severity(value) -> int | None:
    try:
        sev = int(value)
    except (TypeError, ValueError):
        return None
    return max(1, min(5, sev))


def _normalise_confidence(value) -> str:
    v = (str(value or "")).strip().lower()
    return v if v in CONFIDENCE_LEVELS else "low"


def build_observation_suggestion(finding: dict, today: date | None = None) -> dict:
    """Map a vision `finding` to a draft scouting observation for human confirmation.

    The draft is pre-filled, never auto-saved: a grower/PCA reviews/edits it, and only then
    does it become a real scouting observation feeding the rule engine.
    """
    if today is None:
        today = date.today()
    confidence = _normalise_confidence(finding.get("confidence"))
    issue = (finding.get("detected_issue") or "").strip() or None
    severity = _clamp_severity(finding.get("suggested_severity"))
    observations = [o for o in (finding.get("observations") or []) if o]
    model = finding.get("model") or VISION_MODEL

    note_bits = [f"AI photo analysis ({model}, {confidence} confidence)."]
    if observations:
        note_bits.append(" ".join(observations))
    note_bits.append("AI-suggested — review in field and confirm with a PCA before acting.")

    return {
        "observation_date": today.isoformat(),
        "visible_issue": issue,
        "severity_1_to_5": severity,
        "crop_stage": None,
        "notes": " ".join(note_bits),
        # Provenance: came from a photo model, confirmed by the human who saves it.
        "data_source": "photo_ai",
        "data_confidence": "user_provided",
    }


def build_analysis_result(finding: dict, today: date | None = None) -> dict:
    """Wrap a raw service `finding` into the API/UI response (adds suggestion + disclaimer)."""
    confidence = _normalise_confidence(finding.get("confidence"))
    caveats = list(finding.get("caveats") or [])
    # Always include the standing caveat that the model can be wrong.
    standing = "The model may misread the photo, lighting, or look-alike symptoms."
    if standing not in caveats:
        caveats.append(standing)
    return {
        "detected_issue": (finding.get("detected_issue") or "").strip() or None,
        "suggested_severity": _clamp_severity(finding.get("suggested_severity")),
        "confidence": confidence,
        "observations": [o for o in (finding.get("observations") or []) if o],
        "caveats": caveats,
        "model": finding.get("model") or VISION_MODEL,
        "is_ai_generated": True,
        "is_mock": bool(finding.get("is_mock")),
        "disclaimer": PHOTO_DISCLAIMER,
        "suggested_observation": build_observation_suggestion(finding, today),
    }


# Prompt kept here so the wording (and its guardrails) live with the code that sends it.
_SYSTEM_PROMPT = (
    "You are an agronomy scouting assistant looking at a single field photo of a specialty "
    "crop (e.g. strawberry or greenhouse tomato). Describe ONLY what is visible. You are "
    "decision support, not a diagnosis, and you must NEVER tell anyone to spray or name a "
    "pesticide. If you are unsure, say so and use low confidence. Respond with a single JSON "
    "object and nothing else, with keys: detected_issue (short phrase or null), "
    "suggested_severity (integer 1-5 or null, where 1=trace and 5=severe), confidence "
    "(\"low\"|\"medium\"|\"high\"), observations (array of short factual strings about what is "
    "visible), caveats (array of short strings about what could make this wrong)."
)


class VisionService(ABC):
    """Abstraction so the real multimodal model can be swapped for the mock in tests/demo."""

    @abstractmethod
    def analyze(
        self,
        image_bytes: bytes,
        media_type: str,
        crop_type: str | None = None,
        context: str | None = None,
    ) -> dict:
        """Return a raw finding dict (detected_issue/suggested_severity/confidence/...)."""


class MockVisionService(VisionService):
    """Deterministic demo finding — no network, no key. Clearly marked as a mock."""

    def analyze(
        self,
        image_bytes: bytes,
        media_type: str,
        crop_type: str | None = None,
        context: str | None = None,
    ) -> dict:
        crop = (crop_type or "crop").replace("_", " ")
        return {
            "detected_issue": "Possible leaf spotting / early disease signs",
            "suggested_severity": 3,
            "confidence": "low",
            "observations": [
                f"Image appears to show {crop} foliage with some discoloured/spotted leaf areas.",
                "Pattern is non-specific and could be disease, nutrient, or mechanical stress.",
            ],
            "caveats": [
                "Demo/mock analysis — not a real model reading of this photo.",
                "Set ANTHROPIC_API_KEY to enable real Claude photo analysis.",
            ],
            "model": "mock",
            "is_mock": True,
        }


class ClaudeVisionService(VisionService):
    """Real photo analysis via Claude's multimodal model. Lazy-imports `anthropic`."""

    def __init__(self, api_key: str, model: str = VISION_MODEL):
        self._api_key = api_key
        self._model = model

    def analyze(
        self,
        image_bytes: bytes,
        media_type: str,
        crop_type: str | None = None,
        context: str | None = None,
    ) -> dict:
        import anthropic  # lazy: only needed when the real service is actually used

        client = anthropic.Anthropic(api_key=self._api_key)
        crop = (crop_type or "a specialty crop").replace("_", " ")
        user_text = f"This is a field photo of {crop}."
        if context:
            user_text += f" The grower's concern: {context}"
        user_text += " Return the JSON object as instructed."

        message = client.messages.create(
            model=self._model,
            max_tokens=600,
            system=_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": base64.b64encode(image_bytes).decode("ascii"),
                            },
                        },
                        {"type": "text", "text": user_text},
                    ],
                }
            ],
        )
        text = "".join(
            block.text for block in message.content if getattr(block, "type", None) == "text"
        )
        finding = _parse_model_json(text)
        finding["model"] = self._model
        finding["is_mock"] = False
        return finding


def _parse_model_json(text: str) -> dict:
    """Best-effort parse of the model's JSON object (tolerates stray prose around it)."""
    text = (text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
    # Fall back to a low-confidence, honest "couldn't read it" finding.
    return {
        "detected_issue": None,
        "suggested_severity": None,
        "confidence": "low",
        "observations": [],
        "caveats": ["The model response could not be parsed into a structured finding."],
    }


def _build_default_service() -> VisionService:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if api_key:
        try:
            import anthropic  # noqa: F401  (presence check only)

            return ClaudeVisionService(api_key)
        except ImportError:
            pass
    return MockVisionService()


# Default service used by the API. Real Claude when configured, mock otherwise.
default_vision_service: VisionService = _build_default_service()
