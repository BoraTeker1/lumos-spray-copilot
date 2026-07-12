"""Shared LLM service for the AI-driven layer (extraction, review briefs).

Design (mirrors `vision.py` / `weather.py`)
-------------------------------------------
* `LlmService` is a small abstraction over one structured call: content blocks in,
  a validated Pydantic object out. `ClaudeLlmService` uses the Anthropic SDK's
  `client.messages.parse(...)` (structured outputs); `MockLlmService` returns
  deterministic canned objects registered per output schema, so tests and demos run
  offline with no API key.
* `default_llm_service` picks the real model only when an `ANTHROPIC_API_KEY` is
  present AND the `anthropic` package is importable; otherwise the mock.
* Never imports FastAPI/SQLAlchemy.

Honesty rules (ENGINEERING_GUIDELINES.md §9–§10)
--------------------------------
* Everything produced through this service is AI-SUGGESTED, NOT CONFIRMED. It is an
  input to humans and to the deterministic decision engine — never the decider.
* The spray decision (approve/block/delay/inspect/review) remains the deterministic
  rule engine + PCA. Nothing routed through here may prescribe a spray or a product.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Callable, Type, TypeVar

from pydantic import BaseModel

# Default model for the AI layer (same tier as the photo copilot). Override with
# LUMOS_LLM_MODEL for cost experiments; read per-call so tests can monkeypatch env.
DEFAULT_LLM_MODEL = "claude-opus-4-8"

M = TypeVar("M", bound=BaseModel)


def llm_model() -> str:
    return os.getenv("LUMOS_LLM_MODEL") or DEFAULT_LLM_MODEL


class LlmError(RuntimeError):
    """The model call failed or could not produce the requested structure."""


class LlmRefusalError(LlmError):
    """The model declined the request (safety refusal) — surface, never retry blindly."""


class LlmService(ABC):
    """One structured call: content blocks in, validated Pydantic object out."""

    is_mock: bool = False

    @abstractmethod
    def parse(
        self,
        system: str,
        content_blocks: list[dict],
        output_model: Type[M],
    ) -> tuple[M, str]:
        """Return (validated output_model instance, model id used)."""


# ---------------------------------------------------------------------- mock
# Deterministic canned outputs, keyed by output schema name. The feature modules
# (extraction, ai_brief) register their own builders at import time so the mock
# knows how to answer for each schema. Builders receive the content blocks so
# tests can exercise input-dependent paths (e.g. abstention).
_MOCK_BUILDERS: dict[str, Callable[[list[dict]], BaseModel]] = {}


def register_mock_builder(
    output_model: Type[BaseModel], builder: Callable[[list[dict]], BaseModel]
) -> None:
    _MOCK_BUILDERS[output_model.__name__] = builder


class MockLlmService(LlmService):
    """Offline deterministic service — clearly marked as a mock everywhere it surfaces."""

    is_mock = True

    def parse(
        self,
        system: str,
        content_blocks: list[dict],
        output_model: Type[M],
    ) -> tuple[M, str]:
        builder = _MOCK_BUILDERS.get(output_model.__name__)
        if builder is None:
            raise LlmError(
                f"No mock builder registered for {output_model.__name__} — register one "
                f"with llm.register_mock_builder()."
            )
        return builder(content_blocks), "mock"  # type: ignore[return-value]


# ---------------------------------------------------------------------- Claude
class ClaudeLlmService(LlmService):
    """Real structured call via the Anthropic SDK. Lazy-imports `anthropic`."""

    is_mock = False

    def __init__(self, api_key: str, model: str | None = None):
        self._api_key = api_key
        self._model = model or llm_model()

    def parse(
        self,
        system: str,
        content_blocks: list[dict],
        output_model: Type[M],
    ) -> tuple[M, str]:
        import anthropic  # lazy: only needed when the real service is used

        client = anthropic.Anthropic(api_key=self._api_key)
        try:
            response = client.messages.parse(
                model=self._model,
                max_tokens=16000,
                thinking={"type": "adaptive"},
                system=system,
                messages=[{"role": "user", "content": content_blocks}],
                output_format=output_model,
            )
        except anthropic.RateLimitError as exc:
            raise LlmError(f"Rate limited by the model API: {exc}") from exc
        except anthropic.APIStatusError as exc:
            raise LlmError(f"Model API error ({exc.status_code}): {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LlmError(f"Could not reach the model API: {exc}") from exc

        if getattr(response, "stop_reason", None) == "refusal":
            raise LlmRefusalError("The model declined this request (safety refusal).")
        if getattr(response, "stop_reason", None) == "max_tokens":
            raise LlmError("The model response was truncated (max_tokens).")
        parsed = getattr(response, "parsed_output", None)
        if parsed is None:
            raise LlmError("The model did not return a parseable structured output.")
        return parsed, self._model


def _build_default_service() -> LlmService:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if api_key:
        try:
            import anthropic  # noqa: F401  (presence check only)

            return ClaudeLlmService(api_key)
        except ImportError:
            pass
    return MockLlmService()


# Default service used by the API. Real Claude when configured, mock otherwise.
default_llm_service: LlmService = _build_default_service()
