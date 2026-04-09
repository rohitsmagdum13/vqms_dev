"""LLM Factory with automatic fallback for VQMS.

This is the ONLY entry point for all LLM and embedding calls in the
project. Nobody should import from src/adapters/bedrock.py or
src/adapters/openai_provider.py directly — all calls go through
the two public functions here:

    from src.llm.factory import llm_complete, llm_embed

    result = await llm_complete("What is 2+2?", correlation_id="abc")
    embed  = await llm_embed("some text", correlation_id="abc")

The factory reads LLM_PROVIDER and EMBEDDING_PROVIDER from settings
to determine the provider chain. On failure of the primary provider,
it automatically falls through to the fallback provider.

Provider modes (set via LLM_PROVIDER / EMBEDDING_PROVIDER env vars):
  - bedrock_with_openai_fallback (default): Try Bedrock first, OpenAI second
  - openai_with_bedrock_fallback: Try OpenAI first, Bedrock second
  - bedrock_only: Bedrock only, no fallback
  - openai_only: OpenAI only, no fallback
"""

from __future__ import annotations

import logging

from config.settings import get_settings
from src.utils.logger import log_llm_call

logger = logging.getLogger(__name__)

# Cached provider instances (singletons, created once on first use)
_llm_providers: list | None = None
_embed_providers: list | None = None


class LLMProviderError(Exception):
    """Raised when all providers in the fallback chain fail.

    Contains the error messages from each provider that failed,
    so the caller can see what went wrong at each step.
    """

    def __init__(self, errors: list[tuple[str, Exception]]) -> None:
        self.errors = errors
        messages = [f"{name}: {err}" for name, err in errors]
        super().__init__(
            f"All LLM providers failed: {'; '.join(messages)}"
        )


def _build_provider_chain(mode: str) -> list:
    """Build an ordered list of provider instances for the given mode.

    Imports are deferred to avoid circular imports and to only
    create providers that are actually needed.

    Args:
        mode: One of 'bedrock_with_openai_fallback',
            'openai_with_bedrock_fallback', 'bedrock_only', 'openai_only'.

    Returns:
        List of provider instances in fallback order.
    """
    from src.adapters.bedrock import BedrockProvider
    from src.adapters.openai_provider import OpenAIProvider

    chains = {
        "bedrock_with_openai_fallback": [BedrockProvider(), OpenAIProvider()],
        "openai_with_bedrock_fallback": [OpenAIProvider(), BedrockProvider()],
        "bedrock_only": [BedrockProvider()],
        "openai_only": [OpenAIProvider()],
    }

    if mode not in chains:
        logger.warning(
            "Unknown provider mode '%s' — defaulting to bedrock_with_openai_fallback",
            mode,
        )
        return chains["bedrock_with_openai_fallback"]

    return chains[mode]


def _get_llm_chain() -> list:
    """Get or build the LLM provider chain (cached singleton)."""
    global _llm_providers  # noqa: PLW0603
    if _llm_providers is None:
        settings = get_settings()
        _llm_providers = _build_provider_chain(settings.llm_provider)
        provider_names = [p.name for p in _llm_providers]
        logger.info("LLM provider chain initialized: %s", provider_names)
    return _llm_providers


def _get_embed_chain() -> list:
    """Get or build the embedding provider chain (cached singleton)."""
    global _embed_providers  # noqa: PLW0603
    if _embed_providers is None:
        settings = get_settings()
        _embed_providers = _build_provider_chain(settings.embedding_provider)
        provider_names = [p.name for p in _embed_providers]
        logger.info("Embedding provider chain initialized: %s", provider_names)
    return _embed_providers


@log_llm_call
async def llm_complete(
    prompt: str,
    *,
    system_prompt: str | None = None,
    temperature: float = 0.1,
    max_tokens: int = 4096,
    correlation_id: str | None = None,
) -> dict:
    """Send a prompt to the LLM with automatic provider fallback.

    Tries each provider in the chain. On failure of the primary,
    logs a warning and falls through to the next provider. If all
    providers fail, raises LLMProviderError.

    Args:
        prompt: User message for the LLM.
        system_prompt: Optional system instruction.
        temperature: Sampling temperature.
        max_tokens: Max output tokens.
        correlation_id: Tracing ID for log correlation.

    Returns:
        Dict with: text, tokens_in, tokens_out, cost_usd, latency_ms,
        model, provider, was_fallback.

    Raises:
        LLMProviderError: If all providers in the chain fail.
    """
    chain = _get_llm_chain()
    errors: list[tuple[str, Exception]] = []

    for i, provider in enumerate(chain):
        try:
            result = await provider.complete(
                prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                correlation_id=correlation_id,
            )
            # Add fallback tracking to the result
            result["was_fallback"] = i > 0
            if i > 0:
                logger.info(
                    "LLM call succeeded on fallback provider",
                    extra={
                        "provider": provider.name,
                        "fallback_index": i,
                        "correlation_id": correlation_id,
                    },
                )
            return result

        except Exception as err:
            errors.append((provider.name, err))
            # Log warning if there are more providers to try
            if i < len(chain) - 1:
                next_provider = chain[i + 1]
                logger.warning(
                    "Primary LLM provider %s failed: %s. Falling back to %s",
                    provider.name,
                    str(err),
                    next_provider.name,
                    extra={"correlation_id": correlation_id},
                )

    raise LLMProviderError(errors)


@log_llm_call
async def llm_embed(
    text: str,
    *,
    correlation_id: str | None = None,
) -> dict:
    """Embed text with automatic provider fallback.

    Both Bedrock Titan Embed v2 and OpenAI text-embedding-3-small
    return 1536-dimensional vectors, so they are compatible with
    the pgvector column.

    Args:
        text: The text to embed.
        correlation_id: Tracing ID for log correlation.

    Returns:
        Dict with: vector (list[float]), dimensions (int), latency_ms,
        model, provider, was_fallback.

    Raises:
        LLMProviderError: If all providers in the chain fail.
    """
    chain = _get_embed_chain()
    errors: list[tuple[str, Exception]] = []

    for i, provider in enumerate(chain):
        try:
            result = await provider.embed(
                text,
                correlation_id=correlation_id,
            )
            result["was_fallback"] = i > 0
            if i > 0:
                logger.info(
                    "Embedding call succeeded on fallback provider",
                    extra={
                        "provider": provider.name,
                        "fallback_index": i,
                        "correlation_id": correlation_id,
                    },
                )
            return result

        except Exception as err:
            errors.append((provider.name, err))
            if i < len(chain) - 1:
                next_provider = chain[i + 1]
                logger.warning(
                    "Primary embedding provider %s failed: %s. Falling back to %s",
                    provider.name,
                    str(err),
                    next_provider.name,
                    extra={"correlation_id": correlation_id},
                )

    raise LLMProviderError(errors)


def reset_providers() -> None:
    """Reset all cached provider instances.

    Used in tests to clear singletons between test cases.
    """
    global _llm_providers, _embed_providers  # noqa: PLW0603
    _llm_providers = None
    _embed_providers = None
