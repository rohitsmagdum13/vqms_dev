"""VQMS Pipeline Runner — starts FastAPI server + SQS consumer.

Runs the full VQMS pipeline:
  1. Bootstraps infrastructure (SSH tunnel, DB, Redis)
  2. Starts the SQS consumer as a background task
  3. Starts the FastAPI server on the configured port

Usage:
    uv run python scripts/run_pipeline.py

To run only the SQS consumer (no HTTP server):
    uv run python scripts/run_pipeline.py --consumer-only

To run only the HTTP server (no consumer):
    uv run python scripts/run_pipeline.py --server-only
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import get_settings
from src.utils.logger import setup_logging

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="VQMS Pipeline Runner")
    parser.add_argument(
        "--consumer-only",
        action="store_true",
        help="Run only the SQS consumer (no HTTP server)",
    )
    parser.add_argument(
        "--server-only",
        action="store_true",
        help="Run only the HTTP server (no SQS consumer)",
    )
    return parser.parse_args()


async def run_consumer_standalone() -> None:
    """Run the SQS consumer as a standalone process."""
    from src.cache.redis_client import init_redis
    from src.db.connection import init_db, start_ssh_tunnel
    from src.orchestration.sqs_consumer import start_consumer

    settings = get_settings()
    setup_logging(settings.log_level)

    logger.info("Starting VQMS SQS consumer (standalone mode)")

    # Bootstrap infrastructure
    db_url = settings.database_url
    try:
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
    except Exception:
        logger.warning("Could not connect to PostgreSQL", exc_info=True)

    try:
        await init_redis(
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_password,
            db=settings.redis_db,
            ssl=settings.redis_ssl,
        )
    except Exception:
        logger.warning("Could not connect to Redis", exc_info=True)

    # Run consumer (infinite loop)
    shutdown_event = asyncio.Event()
    await start_consumer(shutdown_event=shutdown_event)


def main() -> None:
    args = parse_args()
    settings = get_settings()
    setup_logging(settings.log_level)

    if args.consumer_only:
        logger.info("Running SQS consumer only (no HTTP server)")
        asyncio.run(run_consumer_standalone())
    elif args.server_only:
        logger.info("Running HTTP server only (no SQS consumer)")
        uvicorn.run(
            "main:app",
            host="0.0.0.0",
            port=settings.app_port,
            reload=settings.app_debug,
        )
    else:
        logger.info(
            "Running both HTTP server and SQS consumer. "
            "For separate processes, use --consumer-only or --server-only"
        )
        # Run server (it handles consumer startup in lifespan if configured)
        uvicorn.run(
            "main:app",
            host="0.0.0.0",
            port=settings.app_port,
            reload=settings.app_debug,
        )


if __name__ == "__main__":
    main()
