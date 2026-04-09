"""Seed script: Embed and insert KB articles into pgvector.

Reads markdown files from data/knowledge_base/, splits them
into chunks (~500 tokens each), embeds each chunk using
Amazon Bedrock Titan Embed v2, and inserts into the
memory.embedding_index table.

Usage:
    uv run python -m src.db.seeds.seed_kb_articles

Requires:
    - PostgreSQL with pgvector extension (memory schema)
    - Amazon Bedrock access (Titan Embed v2)
    - .env configured with DB and AWS credentials
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from pathlib import Path

from sqlalchemy import text

from src.db.connection import get_engine, init_db, start_ssh_tunnel
from src.llm.factory import llm_embed
from src.utils.logger import setup_logging

logger = logging.getLogger(__name__)

# Directory containing KB article markdown files
KB_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "knowledge_base"

# Target chunk size in characters (~500 tokens ≈ 2000 characters)
CHUNK_SIZE_CHARS = 2000
CHUNK_OVERLAP_CHARS = 200


def _extract_category(content: str) -> str:
    """Extract the category from a KB article's metadata line.

    Looks for a line like 'Category: billing' near the top of the file.
    """
    for line in content.split("\n")[:10]:
        match = re.match(r"^Category:\s*(.+)$", line.strip(), re.IGNORECASE)
        if match:
            return match.group(1).strip().lower()
    return "general"


def _chunk_text(text_content: str, chunk_size: int, overlap: int) -> list[str]:
    """Split text into overlapping chunks by paragraph boundaries.

    Tries to split on double newlines (paragraphs) first.
    Falls back to hard character splits if paragraphs are too long.
    """
    # Split on double newlines (paragraphs)
    paragraphs = re.split(r"\n\n+", text_content)

    chunks = []
    current_chunk = ""

    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue

        # If adding this paragraph exceeds chunk size, save current and start new
        if len(current_chunk) + len(paragraph) + 2 > chunk_size and current_chunk:
            chunks.append(current_chunk.strip())
            # Keep overlap from end of current chunk
            if overlap > 0 and len(current_chunk) > overlap:
                current_chunk = current_chunk[-overlap:]
            else:
                current_chunk = ""

        current_chunk += paragraph + "\n\n"

    # Don't forget the last chunk
    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks


async def seed_kb_articles() -> None:
    """Read, chunk, embed, and insert all KB articles."""
    from config.settings import get_settings

    settings = get_settings()
    setup_logging(settings.log_level)

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
    engine = get_engine()

    if engine is None:
        logger.error("Database not available — cannot seed KB articles")
        return

    # Find all markdown files
    md_files = sorted(KB_DIR.glob("*.md"))
    if not md_files:
        logger.warning("No .md files found in %s", KB_DIR)
        return

    logger.info("Found %d KB article files to process", len(md_files))

    total_chunks = 0
    total_embedded = 0

    for md_file in md_files:
        content = md_file.read_text(encoding="utf-8")
        category = _extract_category(content)
        source_document = md_file.name

        logger.info(
            "Processing KB article: %s (category: %s)",
            source_document,
            category,
        )

        # Chunk the article
        chunks = _chunk_text(content, CHUNK_SIZE_CHARS, CHUNK_OVERLAP_CHARS)
        total_chunks += len(chunks)

        for i, chunk_text_content in enumerate(chunks):
            record_id = str(uuid.uuid4())

            # Embed the chunk
            try:
                embed_result = await llm_embed(
                    chunk_text_content,
                    correlation_id=f"kb-seed-{source_document}-{i}",
                )
                embedding = embed_result["vector"]
            except Exception:
                logger.error(
                    "Failed to embed chunk %d of %s — skipping",
                    i,
                    source_document,
                    exc_info=True,
                )
                continue

            # Format vector for pgvector
            vector_str = "[" + ",".join(str(v) for v in embedding) + "]"

            # Insert into memory.embedding_index
            sql = text(
                "INSERT INTO memory.embedding_index "
                "(record_id, source_document, chunk_text, embedding, metadata) "
                "VALUES (:record_id, :source_document, :chunk_text, "
                "        :embedding::vector, :metadata) "
                "ON CONFLICT (record_id) DO NOTHING"
            )

            metadata = {
                "category": category,
                "chunk_index": i,
                "total_chunks": len(chunks),
                "source_file": source_document,
            }

            try:
                async with engine.begin() as conn:
                    await conn.execute(
                        sql,
                        {
                            "record_id": record_id,
                            "source_document": source_document,
                            "chunk_text": chunk_text_content,
                            "embedding": vector_str,
                            "metadata": str(metadata).replace("'", '"'),
                        },
                    )
                total_embedded += 1
            except Exception:
                logger.error(
                    "Failed to insert chunk %d of %s",
                    i,
                    source_document,
                    exc_info=True,
                )

    logger.info(
        "KB seeding complete: %d chunks processed, %d embedded successfully",
        total_chunks,
        total_embedded,
    )


if __name__ == "__main__":
    asyncio.run(seed_kb_articles())
