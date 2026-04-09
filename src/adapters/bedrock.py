"""Amazon Bedrock adapter for VQMS.

All LLM inference (Claude Sonnet 3.5) and embedding (Titan Embed v2)
calls go through this single adapter. No other module should import
boto3 bedrock-runtime directly.

Uses the Bedrock Messages API via invoke_model(). Calls are
synchronous in boto3, so we wrap them in run_in_executor()
to avoid blocking the async event loop (LLM calls take 3-30s).

Credentials come from .env via config/settings.py:
  BEDROCK_MODEL_ID, BEDROCK_REGION, BEDROCK_MAX_TOKENS,
  BEDROCK_TEMPERATURE, BEDROCK_EMBEDDING_MODEL_ID, etc.

For testing, call reset_client() to clear the cached client.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

import boto3
from botocore.exceptions import ClientError
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from config.settings import get_settings

logger = logging.getLogger(__name__)

# Lazy-initialized Bedrock runtime client
_bedrock_client = None


def _get_bedrock_client():
    """Get or create the boto3 bedrock-runtime client.

    Uses the bedrock_region setting (may differ from the general
    aws_region if Bedrock is in a different region).
    """
    global _bedrock_client  # noqa: PLW0603
    if _bedrock_client is None:
        settings = get_settings()
        _bedrock_client = boto3.client(
            "bedrock-runtime",
            region_name=settings.bedrock_region,
        )
    return _bedrock_client


def _is_throttling_error(exc: BaseException) -> bool:
    """Check if the exception is a Bedrock throttling error worth retrying."""
    if isinstance(exc, ClientError):
        code = exc.response["Error"]["Code"]
        return code in ("ThrottlingException", "ModelTimeoutException", "ServiceUnavailableException")
    return False


# --- Cost Estimation ---
# Claude 3.5 Sonnet pricing (us-east-1, on-demand):
#   Input:  $0.003 per 1K tokens
#   Output: $0.015 per 1K tokens
COST_PER_1K_INPUT = 0.003
COST_PER_1K_OUTPUT = 0.015

# Titan Embed v2 pricing:
#   $0.0001 per 1K tokens
COST_PER_1K_EMBED = 0.0001


def _estimate_cost(tokens_in: int, tokens_out: int) -> float:
    """Estimate the cost of a Claude Sonnet 3.5 call."""
    return (tokens_in * COST_PER_1K_INPUT / 1000) + (tokens_out * COST_PER_1K_OUTPUT / 1000)


@retry(
    retry=retry_if_exception(_is_throttling_error),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)
def _invoke_model_sync(
    model_id: str,
    body: dict,
) -> dict:
    """Synchronous invoke_model call with retry on throttling.

    This runs inside run_in_executor so it does NOT block
    the async event loop.
    """
    client = _get_bedrock_client()
    response = client.invoke_model(
        modelId=model_id,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(body),
    )
    return json.loads(response["body"].read())


async def invoke_llm(
    prompt: str,
    *,
    system_prompt: str = "",
    temperature: float | None = None,
    max_tokens: int | None = None,
    correlation_id: str | None = None,
) -> dict:
    """Call Claude Sonnet 3.5 on Amazon Bedrock.

    Uses the Anthropic Messages API format via Bedrock invoke_model.
    Runs the synchronous boto3 call in a thread executor to avoid
    blocking the event loop.

    Args:
        prompt: The user message text to send to Claude.
        system_prompt: Optional system instruction.
        temperature: Sampling temperature (default from settings).
        max_tokens: Max output tokens (default from settings).
        correlation_id: Tracing ID for log correlation.

    Returns:
        Dict with keys: text, tokens_in, tokens_out, cost_usd,
        latency_ms, model_id.

    Raises:
        ClientError: If Bedrock rejects the request (permissions,
            model not available, etc.).
    """
    settings = get_settings()
    model_id = settings.bedrock_model_id
    temp = temperature if temperature is not None else settings.bedrock_temperature
    max_tok = max_tokens if max_tokens is not None else settings.bedrock_max_tokens

    # Build Anthropic Messages API request body
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tok,
        "temperature": temp,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system_prompt:
        body["system"] = system_prompt

    logger.info(
        "Calling Bedrock LLM",
        extra={
            "agent_role": "bedrock",
            "tool": "bedrock_invoke_model",
            "model_id": model_id,
            "temperature": temp,
            "max_tokens": max_tok,
            "prompt_length": len(prompt),
            "correlation_id": correlation_id,
        },
    )

    start_time = time.monotonic()

    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: _invoke_model_sync(model_id, body),
        )
    except ClientError as err:
        error_code = err.response["Error"]["Code"]
        if error_code in ("AccessDeniedException", "UnauthorizedAccess"):
            logger.error(
                "Bedrock permission denied — check IAM policy and model access",
                extra={
                    "model_id": model_id,
                    "error_code": error_code,
                    "correlation_id": correlation_id,
                },
            )
        raise

    latency_ms = (time.monotonic() - start_time) * 1000

    # Parse Anthropic Messages API response
    text = ""
    if response.get("content"):
        text = response["content"][0].get("text", "")

    tokens_in = response.get("usage", {}).get("input_tokens", 0)
    tokens_out = response.get("usage", {}).get("output_tokens", 0)
    cost_usd = _estimate_cost(tokens_in, tokens_out)

    logger.info(
        "Bedrock LLM response received",
        extra={
            "agent_role": "bedrock",
            "tool": "bedrock_invoke_model",
            "provider": "bedrock",
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
        "model_id": model_id,
    }


@retry(
    retry=retry_if_exception(_is_throttling_error),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)
def _embed_sync(model_id: str, body: dict) -> dict:
    """Synchronous embedding call with retry on throttling."""
    client = _get_bedrock_client()
    response = client.invoke_model(
        modelId=model_id,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(body),
    )
    return json.loads(response["body"].read())


async def embed_text(
    text: str,
    *,
    correlation_id: str | None = None,
) -> list[float]:
    """Embed text using Amazon Bedrock Titan Embed v2.

    Returns a 1536-dimensional vector suitable for cosine
    similarity search in pgvector.

    Args:
        text: The text to embed (query or KB article chunk).
        correlation_id: Tracing ID for log correlation.

    Returns:
        List of 1536 floats (the embedding vector).

    Raises:
        ClientError: If Bedrock rejects the request.
    """
    settings = get_settings()
    model_id = settings.bedrock_embedding_model_id

    body = {
        "inputText": text,
        "dimensions": settings.bedrock_embedding_dimensions,
        "normalize": True,
    }

    logger.info(
        "Calling Bedrock embedding",
        extra={
            "agent_role": "bedrock",
            "tool": "bedrock_embed",
            "model_id": model_id,
            "text_length": len(text),
            "correlation_id": correlation_id,
        },
    )

    start_time = time.monotonic()

    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: _embed_sync(model_id, body),
        )
    except ClientError as err:
        error_code = err.response["Error"]["Code"]
        if error_code in ("AccessDeniedException", "UnauthorizedAccess"):
            logger.error(
                "Bedrock embedding permission denied — check IAM policy",
                extra={
                    "model_id": model_id,
                    "error_code": error_code,
                    "correlation_id": correlation_id,
                },
            )
        raise

    latency_ms = (time.monotonic() - start_time) * 1000
    embedding = response.get("embedding", [])

    logger.info(
        "Bedrock embedding received",
        extra={
            "agent_role": "bedrock",
            "tool": "bedrock_embed",
            "provider": "bedrock",
            "model": model_id,
            "dimensions": len(embedding),
            "latency_ms": round(latency_ms, 1),
            "correlation_id": correlation_id,
        },
    )

    return embedding


def reset_client() -> None:
    """Reset the Bedrock client. Used in tests with moto."""
    global _bedrock_client  # noqa: PLW0603
    _bedrock_client = None


# ---------------------------------------------------------------------------
# BedrockProvider: Protocol-compatible wrapper over existing functions
# ---------------------------------------------------------------------------
# The functions above (invoke_llm, embed_text) remain as-is for backward
# compatibility. This class wraps them to match the LLMProvider protocol
# defined in src/llm/protocol.py. The factory (src/llm/factory.py) uses
# this class — nobody else should instantiate it directly.
# ---------------------------------------------------------------------------


class BedrockProvider:
    """Amazon Bedrock provider implementing the LLMProvider protocol.

    Wraps the existing invoke_llm() and embed_text() module-level
    functions. Adds the 'provider' field to responses and normalizes
    the 'model_id' key to 'model' for consistency across providers.
    """

    @property
    def name(self) -> str:
        """Provider identifier."""
        return "bedrock"

    async def complete(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        correlation_id: str | None = None,
    ) -> dict:
        """Call Claude Sonnet 3.5 on Bedrock via invoke_llm().

        Returns dict with: text, tokens_in, tokens_out, cost_usd,
        latency_ms, model, provider.
        """
        result = await invoke_llm(
            prompt,
            system_prompt=system_prompt or "",
            temperature=temperature,
            max_tokens=max_tokens,
            correlation_id=correlation_id,
        )
        # Normalize key: invoke_llm returns 'model_id', protocol uses 'model'
        return {
            "text": result["text"],
            "tokens_in": result["tokens_in"],
            "tokens_out": result["tokens_out"],
            "cost_usd": result["cost_usd"],
            "latency_ms": result["latency_ms"],
            "model": result["model_id"],
            "provider": "bedrock",
        }

    async def embed(
        self,
        text: str,
        *,
        correlation_id: str | None = None,
    ) -> dict:
        """Embed text using Titan Embed v2 via embed_text().

        Returns dict with: vector, dimensions, latency_ms, model, provider.
        """
        settings = get_settings()
        start_time = time.monotonic()
        vector = await embed_text(text, correlation_id=correlation_id)
        latency_ms = (time.monotonic() - start_time) * 1000

        return {
            "vector": vector,
            "dimensions": len(vector),
            "latency_ms": latency_ms,
            "model": settings.bedrock_embedding_model_id,
            "provider": "bedrock",
        }
