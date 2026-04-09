"""Unit tests for the LLM factory fallback logic.

Tests verify that the factory correctly:
  - Uses the primary provider when it succeeds
  - Falls back to the secondary provider when the primary fails
  - Raises LLMProviderError when all providers fail
  - Respects provider mode configuration
  - Handles embedding calls with the same fallback logic

All tests use mock providers — no real LLM calls are made.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.llm.factory import (
    LLMProviderError,
    llm_complete,
    llm_embed,
    reset_providers,
)

# --- Helper: Mock Provider ---

class MockProvider:
    """A configurable mock LLM provider for testing."""

    def __init__(
        self,
        provider_name: str,
        *,
        complete_result: dict | None = None,
        embed_result: dict | None = None,
        complete_error: Exception | None = None,
        embed_error: Exception | None = None,
    ) -> None:
        self._name = provider_name
        self._complete_result = complete_result
        self._embed_result = embed_result
        self._complete_error = complete_error
        self._embed_error = embed_error

    @property
    def name(self) -> str:
        return self._name

    async def complete(self, prompt, **kwargs) -> dict:
        if self._complete_error:
            raise self._complete_error
        return self._complete_result or {}

    async def embed(self, text, **kwargs) -> dict:
        if self._embed_error:
            raise self._embed_error
        return self._embed_result or {}


# --- Fixtures ---

@pytest.fixture(autouse=True)
def _reset_factory():
    """Reset cached provider singletons before each test."""
    reset_providers()
    yield
    reset_providers()


MOCK_COMPLETE_RESULT = {
    "text": "Hello from primary",
    "tokens_in": 10,
    "tokens_out": 5,
    "cost_usd": 0.001,
    "latency_ms": 100.0,
    "model": "test-model",
    "provider": "primary",
}

MOCK_FALLBACK_COMPLETE_RESULT = {
    "text": "Hello from fallback",
    "tokens_in": 10,
    "tokens_out": 5,
    "cost_usd": 0.002,
    "latency_ms": 200.0,
    "model": "fallback-model",
    "provider": "fallback",
}

MOCK_EMBED_RESULT = {
    "vector": [0.1] * 1536,
    "dimensions": 1536,
    "latency_ms": 50.0,
    "model": "embed-model",
    "provider": "primary",
}

MOCK_FALLBACK_EMBED_RESULT = {
    "vector": [0.2] * 1536,
    "dimensions": 1536,
    "latency_ms": 80.0,
    "model": "fallback-embed-model",
    "provider": "fallback",
}


# --- LLM Complete Tests ---

class TestLlmCompleteHappyPath:
    """Test llm_complete when the primary provider succeeds."""

    @pytest.mark.asyncio
    async def test_primary_succeeds_returns_result_with_was_fallback_false(self):
        """When primary provider succeeds, result has was_fallback=False."""
        primary = MockProvider("primary", complete_result=MOCK_COMPLETE_RESULT)
        fallback = MockProvider("fallback", complete_result=MOCK_FALLBACK_COMPLETE_RESULT)

        with patch("src.llm.factory._get_llm_chain", return_value=[primary, fallback]):
            result = await llm_complete("test prompt")

        assert result["text"] == "Hello from primary"
        assert result["was_fallback"] is False
        assert result["provider"] == "primary"


class TestLlmCompleteFallback:
    """Test llm_complete when the primary fails and fallback is used."""

    @pytest.mark.asyncio
    async def test_primary_fails_falls_back_to_secondary(self):
        """When primary fails, secondary provider is used with was_fallback=True."""
        primary = MockProvider(
            "primary",
            complete_error=RuntimeError("Bedrock down"),
        )
        fallback = MockProvider("fallback", complete_result=MOCK_FALLBACK_COMPLETE_RESULT)

        with patch("src.llm.factory._get_llm_chain", return_value=[primary, fallback]):
            result = await llm_complete("test prompt")

        assert result["text"] == "Hello from fallback"
        assert result["was_fallback"] is True

    @pytest.mark.asyncio
    async def test_both_fail_raises_llm_provider_error(self):
        """When all providers fail, LLMProviderError is raised with both errors."""
        primary = MockProvider(
            "primary",
            complete_error=RuntimeError("Bedrock down"),
        )
        fallback = MockProvider(
            "fallback",
            complete_error=RuntimeError("OpenAI down"),
        )

        with patch("src.llm.factory._get_llm_chain", return_value=[primary, fallback]):
            with pytest.raises(LLMProviderError) as exc_info:
                await llm_complete("test prompt")

        assert len(exc_info.value.errors) == 2
        assert exc_info.value.errors[0][0] == "primary"
        assert exc_info.value.errors[1][0] == "fallback"


class TestLlmCompleteProviderModes:
    """Test that provider modes configure the chain correctly."""

    @pytest.mark.asyncio
    async def test_openai_only_mode_never_tries_bedrock(self):
        """In openai_only mode, only OpenAI provider is in the chain."""
        openai_provider = MockProvider("openai", complete_result=MOCK_COMPLETE_RESULT)

        with patch("src.llm.factory._get_llm_chain", return_value=[openai_provider]):
            result = await llm_complete("test prompt")

        assert result["was_fallback"] is False

    @pytest.mark.asyncio
    async def test_bedrock_only_mode_never_tries_openai(self):
        """In bedrock_only mode, only Bedrock provider is in the chain."""
        bedrock_provider = MockProvider("bedrock", complete_result=MOCK_COMPLETE_RESULT)

        with patch("src.llm.factory._get_llm_chain", return_value=[bedrock_provider]):
            result = await llm_complete("test prompt")

        assert result["was_fallback"] is False


# --- Embedding Tests ---

class TestLlmEmbedHappyPath:
    """Test llm_embed when the primary provider succeeds."""

    @pytest.mark.asyncio
    async def test_primary_embed_succeeds_returns_correct_dimensions(self):
        """Primary embedding succeeds and returns a 1536-dim vector."""
        primary = MockProvider("primary", embed_result=MOCK_EMBED_RESULT)
        fallback = MockProvider("fallback", embed_result=MOCK_FALLBACK_EMBED_RESULT)

        with patch("src.llm.factory._get_embed_chain", return_value=[primary, fallback]):
            result = await llm_embed("test text")

        assert result["dimensions"] == 1536
        assert len(result["vector"]) == 1536
        assert result["was_fallback"] is False


class TestLlmEmbedFallback:
    """Test llm_embed when the primary fails and fallback is used."""

    @pytest.mark.asyncio
    async def test_primary_embed_fails_falls_back(self):
        """When primary embedding fails, fallback provider is used."""
        primary = MockProvider(
            "primary",
            embed_error=RuntimeError("Bedrock embed down"),
        )
        fallback = MockProvider("fallback", embed_result=MOCK_FALLBACK_EMBED_RESULT)

        with patch("src.llm.factory._get_embed_chain", return_value=[primary, fallback]):
            result = await llm_embed("test text")

        assert result["was_fallback"] is True
        assert result["dimensions"] == 1536

    @pytest.mark.asyncio
    async def test_both_embeds_fail_raises_error(self):
        """When all embedding providers fail, LLMProviderError is raised."""
        primary = MockProvider(
            "primary",
            embed_error=RuntimeError("Bedrock down"),
        )
        fallback = MockProvider(
            "fallback",
            embed_error=RuntimeError("OpenAI down"),
        )

        with patch("src.llm.factory._get_embed_chain", return_value=[primary, fallback]):
            with pytest.raises(LLMProviderError) as exc_info:
                await llm_embed("test text")

        assert len(exc_info.value.errors) == 2
