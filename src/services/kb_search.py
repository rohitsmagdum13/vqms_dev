"""KB Search Service for VQMS (Step 9B).

Embeds the query text using Amazon Bedrock Titan Embed v2, then
runs cosine similarity search against knowledge base article
chunks stored in the memory.embedding_index table (pgvector).

Results are filtered by category and minimum similarity threshold
(KB_MATCH_THRESHOLD from settings, default 0.80).

Corresponds to Step 9B in the VQMS Solution Flow Document.
"""

from __future__ import annotations

import logging
import re
import time

from sqlalchemy import text

from config.settings import get_settings
from src.db.connection import get_engine
from src.llm.factory import llm_embed
from src.models.kb import KBSearchResponse, KBSearchResult
from src.utils.log_context import LogContext

logger = logging.getLogger(__name__)

# Regex patterns for detecting specific facts in KB articles.
# If a chunk matches any of these, has_specific_facts = True,
# which is a signal that Path A (AI-resolved) is appropriate.
FACT_PATTERNS = [
    re.compile(r"\$[\d,]+\.?\d*"),                  # Dollar amounts ($475,000.00)
    re.compile(r"Rs\.?\s*[\d,]+"),                   # Rupee amounts (Rs. 475,000)
    re.compile(r"\d{1,2}[-/]\d{1,2}[-/]\d{2,4}"),   # Dates (03/17/2026)
    re.compile(r"Net\s+\d+"),                        # Payment terms (Net 30)
    re.compile(r"(?:Step|Phase)\s+\d+", re.IGNORECASE),  # Procedural steps
    re.compile(r"\d+\s*(?:business\s+)?days?", re.IGNORECASE),  # Timeframes
    re.compile(r"\d+%"),                             # Percentages
]


def _has_specific_facts(chunk_text: str) -> bool:
    """Check if a KB article chunk contains specific factual content.

    Looks for patterns like dollar amounts, dates, payment terms,
    procedural steps, and timeframes. These indicate the article
    has actionable facts (not just general guidance).

    Args:
        chunk_text: The text content of the KB article chunk.

    Returns:
        True if at least one fact pattern is found.
    """
    return any(pattern.search(chunk_text) for pattern in FACT_PATTERNS)


async def search_kb(
    query_text: str,
    category: str | None = None,
    *,
    correlation_id: str | None = None,
) -> KBSearchResponse:
    """Search the knowledge base for articles matching the query.

    Steps:
      1. Embed the query text using Titan Embed v2 → vector(1536)
      2. Run cosine similarity search on memory.embedding_index
      3. Filter by category (if provided) and minimum threshold
      4. Check each result for specific facts

    Args:
        query_text: Combined subject + description to search for.
        category: Optional category filter (e.g., "billing").
        correlation_id: Tracing ID.

    Returns:
        KBSearchResponse with ranked results and metadata.
    """
    settings = get_settings()
    start_time = time.monotonic()

    ctx = LogContext(
        correlation_id=correlation_id,
        agent_role="kb_search",
        step="STEP_9B",
    )

    logger.info(
        "Starting KB search",
        extra={**ctx.to_dict(), "query_length": len(query_text), "category": category},
    )

    # Step 1: Embed the query text
    try:
        embed_result = await llm_embed(query_text, correlation_id=correlation_id)
        query_vector = embed_result["vector"]
    except Exception:
        logger.error(
            "Failed to embed query text — returning empty KB results",
            extra=ctx.to_dict(),
            exc_info=True,
        )
        return KBSearchResponse(
            results=[],
            query_text=query_text,
            top_score=0.0,
            search_latency_ms=(time.monotonic() - start_time) * 1000,
        )

    # Step 2: Query pgvector for cosine similarity
    engine = get_engine()
    if engine is None:
        logger.warning(
            "Database not available — returning empty KB results",
            extra=ctx.to_dict(),
        )
        return KBSearchResponse(
            results=[],
            query_text=query_text,
            top_score=0.0,
            search_latency_ms=(time.monotonic() - start_time) * 1000,
        )

    # Format the vector as a pgvector-compatible string: [0.1, 0.2, ...]
    vector_str = "[" + ",".join(str(v) for v in query_vector) + "]"

    # Build SQL with optional category filter
    # The <=> operator computes cosine distance; 1 - distance = similarity
    # NOTE: SQLAlchemy text() treats `:name` as a bind parameter.
    # PostgreSQL's `::vector` cast clashes with that because `::` starts
    # with `:`.  We use `CAST(... AS vector)` instead to avoid the conflict.
    sql = text(
        "SELECT record_id, source_document, chunk_text, metadata, "
        "       1 - (embedding <=> CAST(:vec AS vector)) AS similarity "
        "FROM memory.embedding_index "
        "WHERE (:cat IS NULL OR metadata->>'category' = :cat) "
        "ORDER BY embedding <=> CAST(:vec AS vector) "
        "LIMIT :max_results"
    )

    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                sql,
                {
                    "vec": vector_str,
                    "cat": category,
                    "max_results": settings.kb_max_results,
                },
            )
            rows = result.fetchall()
    except Exception:
        logger.error(
            "pgvector search query failed",
            extra={**ctx.to_dict(), "tool": "postgresql"},
            exc_info=True,
        )
        return KBSearchResponse(
            results=[],
            query_text=query_text,
            top_score=0.0,
            search_latency_ms=(time.monotonic() - start_time) * 1000,
        )

    # Step 3: Filter by minimum similarity threshold and build results
    threshold = settings.kb_match_threshold
    results = []
    for row in rows:
        record_id = row[0]
        source_document = row[1]
        chunk_text = row[2]
        metadata = row[3] if row[3] else {}
        similarity = float(row[4])

        if similarity < threshold:
            continue

        results.append(
            KBSearchResult(
                record_id=record_id,
                source_document=source_document,
                chunk_text=chunk_text,
                category=metadata.get("category", "general"),
                similarity_score=round(similarity, 4),
                has_specific_facts=_has_specific_facts(chunk_text),
            )
        )

    latency_ms = (time.monotonic() - start_time) * 1000
    top_score = results[0].similarity_score if results else 0.0

    logger.info(
        "KB search completed",
        extra={
            **ctx.with_update(latency_ms=round(latency_ms, 1), tool="postgresql").to_dict(),
            "results_count": len(results),
            "top_score": top_score,
            "threshold": threshold,
        },
    )

    return KBSearchResponse(
        results=results,
        query_text=query_text,
        top_score=top_score,
        search_latency_ms=latency_ms,
    )
