"""LLM Provider Protocol for VQMS.

Defines the interface that all LLM providers (Bedrock, OpenAI, etc.)
must implement. Uses Python's structural subtyping via typing.Protocol
so providers don't need to import or inherit from this file — they
just need to have the right methods with the right signatures.

The two methods are:
  - complete(): Send a prompt to an LLM, get back text + usage metadata
  - embed(): Convert text to a vector for similarity search

Both methods return dicts with a 'provider' field so the factory
can track which provider actually served the request (important
for fallback monitoring and cost tracking).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMProvider(Protocol):
    """Interface for LLM + embedding providers.

    Any class that implements these two async methods qualifies
    as an LLMProvider via structural subtyping. No need to inherit.

    The factory (src/llm/factory.py) calls these methods and handles
    fallback between providers automatically.
    """

    @property
    def name(self) -> str:
        """Short identifier for this provider (e.g., 'bedrock', 'openai')."""
        ...

    async def complete(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        correlation_id: str | None = None,
    ) -> dict:
        """Send a prompt to the LLM and get a text response.

        Returns:
            Dict with keys:
              - text: str — the LLM's response text
              - tokens_in: int — input tokens consumed
              - tokens_out: int — output tokens produced
              - cost_usd: float — estimated cost for this call
              - latency_ms: float — wall-clock time in milliseconds
              - model: str — actual model ID used
              - provider: str — provider name ('bedrock' or 'openai')
        """
        ...

    async def embed(
        self,
        text: str,
        *,
        correlation_id: str | None = None,
    ) -> dict:
        """Convert text into a vector embedding.

        Returns:
            Dict with keys:
              - vector: list[float] — the embedding vector
              - dimensions: int — length of the vector (must be 1536)
              - latency_ms: float — wall-clock time in milliseconds
              - model: str — actual model ID used
              - provider: str — provider name ('bedrock' or 'openai')
        """
        ...
