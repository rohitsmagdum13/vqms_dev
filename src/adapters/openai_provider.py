"""OpenAI provider for VQMS.

Implements the LLMProvider protocol using the OpenAI Python library.
Supports GPT-4o for LLM inference and text-embedding-3-small for
embeddings. This is the fallback provider when Bedrock is unavailable.

Uses async OpenAI client (AsyncOpenAI). Credentials come from .env
via config/settings.py: OPENAI_API_KEY, OPENAI_MODEL_ID, etc.

CRITICAL: Embedding dimension is explicitly set to 1536 to match
Titan Embed v2 and pgvector column size. Do not change this without
also updating the pgvector schema.

For testing, call reset_client() to clear the cached client.
"""

from __future__ import annotations

import logging
import time

from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    RateLimitError,
)
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config.settings import get_settings

logger = logging.getLogger(__name__)

# Lazy-initialized async OpenAI client
_openai_client: AsyncOpenAI | None = None


def _get_openai_client() -> AsyncOpenAI:
    """Get or create the async OpenAI client.

    Reads API key and base URL from settings on first call.
    """
    global _openai_client  # noqa: PLW0603
    if _openai_client is None:
        settings = get_settings()
        _openai_client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_api_base_url or None,
        )
    return _openai_client


def reset_client() -> None:
    """Reset the OpenAI client. Used in tests."""
    global _openai_client  # noqa: PLW0603
    _openai_client = None


# --- Cost Estimation ---
# GPT-4o pricing (as of 2025):
#   Input:  $0.005 per 1K tokens
#   Output: $0.015 per 1K tokens
COST_PER_1K_INPUT = 0.005
COST_PER_1K_OUTPUT = 0.015

# text-embedding-3-small pricing:
#   $0.00002 per 1K tokens
COST_PER_1K_EMBED = 0.00002


def _estimate_llm_cost(tokens_in: int, tokens_out: int) -> float:
    """Estimate the cost of a GPT-4o call."""
    return (tokens_in * COST_PER_1K_INPUT / 1000) + (tokens_out * COST_PER_1K_OUTPUT / 1000)


def _estimate_embed_cost(tokens: int) -> float:
    """Estimate the cost of an embedding call."""
    return tokens * COST_PER_1K_EMBED / 1000


# Retry on transient errors (rate limit, timeout, connection issues)
_RETRYABLE_EXCEPTIONS = (RateLimitError, APITimeoutError, APIConnectionError)


class OpenAIProvider:
    """OpenAI provider implementing the LLMProvider protocol.

    Uses GPT-4o for LLM calls and text-embedding-3-small for
    embeddings. Intended as a fallback when Bedrock is unavailable.
    """

    @property
    def name(self) -> str:
        """Provider identifier."""
        return "openai"

    @retry(
        retry=retry_if_exception_type(_RETRYABLE_EXCEPTIONS),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def complete(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        correlation_id: str | None = None,
    ) -> dict:
        """Call GPT-4o via the OpenAI Chat Completions API.

        Returns dict with: text, tokens_in, tokens_out, cost_usd,
        latency_ms, model, provider.
        """
        settings = get_settings()
        model_id = settings.openai_model_id

        # Build messages list
        messages: list[dict] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        logger.info(
            "Calling OpenAI LLM",
            extra={
                "agent_role": "openai",
                "tool": "openai_chat_completions",
                "model_id": model_id,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "prompt_length": len(prompt),
                "correlation_id": correlation_id,
            },
        )

        start_time = time.monotonic()

        try:
            client = _get_openai_client()
            # Newer OpenAI models (gpt-4.1, gpt-5.x, o-series) require
            # 'max_completion_tokens' instead of 'max_tokens'.
            # We send both — the API ignores the unsupported one.
            response = await client.chat.completions.create(
                model=model_id,
                messages=messages,
                temperature=temperature,
                max_completion_tokens=max_tokens,
            )
        except AuthenticationError:
            logger.error(
                "OpenAI authentication failed — check OPENAI_API_KEY",
                extra={"correlation_id": correlation_id},
            )
            raise

        latency_ms = (time.monotonic() - start_time) * 1000

        # Extract response
        text = response.choices[0].message.content or ""
        tokens_in = response.usage.prompt_tokens if response.usage else 0
        tokens_out = response.usage.completion_tokens if response.usage else 0
        cost_usd = _estimate_llm_cost(tokens_in, tokens_out)

        logger.info(
            "OpenAI LLM response received",
            extra={
                "agent_role": "openai",
                "tool": "openai_chat_completions",
                "provider": "openai",
                "model": model_id,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "cost_usd": round(cost_usd, 6),
                "latency_ms": round(latency_ms, 1),
                "response_length": len(text),
                "correlation_id": correlation_id,
            },
        )

        return {
            "text": text,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": cost_usd,
            "latency_ms": latency_ms,
            "model": model_id,
            "provider": "openai",
        }

    @retry(
        retry=retry_if_exception_type(_RETRYABLE_EXCEPTIONS),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def embed(
        self,
        text: str,
        *,
        correlation_id: str | None = None,
    ) -> dict:
        """Embed text using OpenAI text-embedding-3-small.

        CRITICAL: dimensions=1536 is passed explicitly to match
        Titan Embed v2 and the pgvector column size. Do not change
        this without also updating the database schema.

        Returns dict with: vector, dimensions, latency_ms, model, provider.
        """
        settings = get_settings()
        model_id = settings.openai_embedding_model_id
        target_dimensions = settings.openai_embedding_dimensions

        logger.info(
            "Calling OpenAI embedding",
            extra={
                "agent_role": "openai",
                "tool": "openai_embeddings",
                "model_id": model_id,
                "text_length": len(text),
                "target_dimensions": target_dimensions,
                "correlation_id": correlation_id,
            },
        )

        start_time = time.monotonic()

        try:
            client = _get_openai_client()
            response = await client.embeddings.create(
                model=model_id,
                input=text,
                dimensions=target_dimensions,
            )
        except AuthenticationError:
            logger.error(
                "OpenAI authentication failed — check OPENAI_API_KEY",
                extra={"correlation_id": correlation_id},
            )
            raise

        latency_ms = (time.monotonic() - start_time) * 1000
        vector = response.data[0].embedding
        tokens_used = response.usage.total_tokens if response.usage else 0

        logger.info(
            "OpenAI embedding received",
            extra={
                "agent_role": "openai",
                "tool": "openai_embeddings",
                "provider": "openai",
                "model": model_id,
                "dimensions": len(vector),
                "tokens_in": tokens_used,
                "cost_usd": round(_estimate_embed_cost(tokens_used), 8),
                "latency_ms": round(latency_ms, 1),
                "correlation_id": correlation_id,
            },
        )

        return {
            "vector": vector,
            "dimensions": len(vector),
            "latency_ms": latency_ms,
            "model": model_id,
            "provider": "openai",
        }
