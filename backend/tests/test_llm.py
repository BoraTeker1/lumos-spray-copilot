"""Shared LLM service: selection, mock determinism, registry errors."""
import pytest
from pydantic import BaseModel

from app import llm


class _UnregisteredOutput(BaseModel):
    value: str = ""


def test_no_key_selects_mock(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    service = llm._build_default_service()
    assert isinstance(service, llm.MockLlmService)
    assert service.is_mock is True


def test_key_selects_real_service(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    service = llm._build_default_service()
    assert isinstance(service, llm.ClaudeLlmService)
    assert service.is_mock is False


def test_model_env_override(monkeypatch):
    monkeypatch.delenv("LUMOS_LLM_MODEL", raising=False)
    assert llm.llm_model() == llm.DEFAULT_LLM_MODEL == "claude-opus-4-8"
    monkeypatch.setenv("LUMOS_LLM_MODEL", "claude-sonnet-5")
    assert llm.llm_model() == "claude-sonnet-5"


def test_mock_is_deterministic():
    from app.extraction import PlannedSprayExtraction  # registers its mock builder

    service = llm.MockLlmService()
    blocks = [{"type": "text", "text": "same input"}]
    a, model_a = service.parse("sys", blocks, PlannedSprayExtraction)
    b, model_b = service.parse("sys", blocks, PlannedSprayExtraction)
    assert model_a == model_b == "mock"
    assert a.model_dump() == b.model_dump()


def test_mock_without_registered_builder_raises():
    service = llm.MockLlmService()
    with pytest.raises(llm.LlmError, match="No mock builder"):
        service.parse("sys", [], _UnregisteredOutput)
