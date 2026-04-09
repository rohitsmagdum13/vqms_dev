"""Manual test: Verify KB search via pgvector.

Seeds KB articles (if not already seeded), then searches for
a billing query and prints ranked results with similarity scores.

Usage:
    uv run python tests/manual/test_kb_search.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from config.settings import get_settings
from src.db.connection import init_db, start_ssh_tunnel
from src.services.kb_search import search_kb
from src.utils.logger import setup_logging


async def main() -> None:
    settings = get_settings()
    setup_logging("INFO")

    print("=" * 60)
    print("VQMS — KB Search Test")
    print("=" * 60)

    # Connect to database
    db_url = settings.database_url
    if settings.ssh_host:
        local_host, local_port = start_ssh_tunnel(
            ssh_host=settings.ssh_host,
            ssh_port=settings.ssh_port,
            ssh_username=settings.ssh_username,
            ssh_private_key_path=settings.ssh_private_key_path,
            rds_host=settings.rds_host,
            rds_port=settings.rds_port,
        )
        db_url = (
            f"postgresql+asyncpg://{settings.postgres_user}:{settings.postgres_password}"
            f"@{local_host}:{local_port}/{settings.postgres_db}"
        )

    await init_db(db_url, pool_min=2, pool_max=5)

    # Test searches
    test_queries = [
        ("payment status inquiry for invoice INV-2026-0451", "billing"),
        ("overdue invoice escalation", "billing"),
        ("how to reset my portal password", "general"),
        ("PO mismatch on purchase order PO-HEX-78412", "billing"),
    ]

    for query_text, category in test_queries:
        print(f"\n{'=' * 60}")
        print(f"Query: '{query_text}'")
        print(f"Category filter: {category}")
        print("-" * 60)

        try:
            response = await search_kb(
                query_text,
                category=category,
                correlation_id="test-kb-search",
            )

            if not response.results:
                print("  No results found above threshold.")
                print("  (Have you run the KB seed script?)")
                print("  Run: uv run python -m src.db.seeds.seed_kb_articles")
            else:
                for i, result in enumerate(response.results, 1):
                    print(f"  [{i}] {result.source_document}")
                    print(f"      Score: {result.similarity_score:.4f}")
                    print(f"      Facts: {result.has_specific_facts}")
                    print(f"      Preview: {result.chunk_text[:100]}...")

            print(f"  Top score: {response.top_score:.4f}")
            print(f"  Latency: {response.search_latency_ms:.1f}ms")

        except Exception as e:
            print(f"  ERROR: {e}")

    print(f"\n{'=' * 60}")
    print("KB search test completed.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
