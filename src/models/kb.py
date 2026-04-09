"""Pydantic models for Knowledge Base search results in VQMS.

These models define the shape of KB search outputs produced by
the KB Search Service (Step 9B). The service embeds the query
via Titan Embed v2, runs cosine similarity on pgvector, and
returns ranked article matches.

Corresponds to:
  - memory.embedding_index table in PostgreSQL
  - Step 9B in the VQMS Solution Flow Document
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class KBSearchResult(BaseModel):
    """A single KB article match from vector similarity search.

    Each result represents a chunk from a knowledge base article
    that matched the vendor's query based on cosine similarity
    of Titan Embed v2 embeddings.
    """

    record_id: str = Field(description="UUID4 identifier from embedding_index")
    source_document: str = Field(description="KB article filename or ID")
    chunk_text: str = Field(description="Text content of the matched chunk")
    category: str = Field(description="Article category (e.g., billing, general)")
    similarity_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Cosine similarity score (1.0 = perfect match)",
    )
    has_specific_facts: bool = Field(
        default=False,
        description="True if chunk contains dates, amounts, or procedures",
    )


class KBSearchResponse(BaseModel):
    """Aggregated response from the KB Search Service.

    Contains all matching articles plus metadata about the search
    itself. Used by the path decision node to determine Path A vs B.
    """

    results: list[KBSearchResult] = Field(
        default_factory=list,
        description="Ranked list of KB article matches",
    )
    query_text: str = Field(description="The search text that was embedded")
    top_score: float = Field(
        default=0.0,
        description="Highest similarity score among results (0.0 if no results)",
    )
    search_latency_ms: float = Field(
        default=0.0,
        description="Wall-clock time for the search in milliseconds",
    )
