"""VQMS — Vendor Query Management System.

Entry point for the FastAPI application. Sets up structured logging,
SSH tunnel to bastion/RDS, database connection pool, and Redis client
on startup. Provides a health check endpoint that reports connectivity.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config.settings import get_settings
from src.api.routes.auth import router as auth_router
from src.api.routes.dashboard import router as dashboard_router
from src.api.routes.queries import router as queries_router
from src.api.routes.webhooks import router as webhooks_router
from src.cache.redis_client import check_redis_health, close_redis, init_redis
from src.db.connection import (
    check_db_health,
    close_db,
    init_db,
    start_ssh_tunnel,
    stop_ssh_tunnel,
)
from src.utils.logger import setup_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Application lifespan — startup and shutdown logic.

    On startup:
      1. Configure structured logging
      2. Establish SSH tunnel to bastion host for RDS access
      3. Connect to PostgreSQL through the tunnel
      4. Connect to Redis

    On shutdown:
      1. Close database pool
      2. Close SSH tunnel
      3. Close Redis connection

    Database, tunnel, and Redis failures are logged but do not
    prevent startup — the health check will report disconnected.
    """
    settings = get_settings()

    # --- Startup ---
    setup_logging(settings.log_level)
    logger.info(
        "Starting VQMS",
        extra={
            "app_env": settings.app_env,
            "version": settings.app_version,
        },
    )

    # Step 1: Establish SSH tunnel to bastion → RDS
    # The tunnel must be up before we can connect to PostgreSQL
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
            # Rebuild the database URL to point at the tunnel's local port
            db_url = (
                f"postgresql+asyncpg://{settings.postgres_user}:{settings.postgres_password}"
                f"@{local_host}:{local_port}/{settings.postgres_db}"
            )
        else:
            logger.warning(
                "SSH_HOST not configured — skipping SSH tunnel. "
                "Using database_url directly (for local PostgreSQL or testing).",
            )
    except Exception:
        logger.warning(
            "Could not establish SSH tunnel — running without database",
            exc_info=True,
        )

    # Step 2: Connect to PostgreSQL through the tunnel
    try:
        await init_db(
            database_url=db_url,
            pool_min=settings.postgres_pool_min,
            pool_max=settings.postgres_pool_max,
        )
    except Exception:
        logger.warning(
            "Could not connect to PostgreSQL — running without database",
            exc_info=True,
        )

    # Step 3: Connect to Redis
    try:
        await init_redis(
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_password,
            db=settings.redis_db,
            ssl=settings.redis_ssl,
        )
    except Exception:
        logger.warning(
            "Could not connect to Redis — running without cache",
            exc_info=True,
        )

    yield

    # --- Shutdown ---
    await close_db()
    stop_ssh_tunnel()
    await close_redis()
    logger.info("VQMS shutdown complete")


settings = get_settings()

app = FastAPI(
    title="VQMS",
    description="Vendor Query Management System — Agentic AI Platform",
    version=settings.app_version,
    lifespan=lifespan,
)

# --- CORS: Allow Angular dev server ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Phase 2: Intake Routes ---
app.include_router(queries_router)
app.include_router(webhooks_router)

# --- Portal Frontend Support Routes ---
app.include_router(auth_router)
app.include_router(dashboard_router)


@app.get("/health")
async def health_check() -> dict:
    """Health check endpoint.

    Returns the application status and connectivity to PostgreSQL
    and Redis. Always returns HTTP 200 — the body indicates whether
    backend services are reachable.
    """
    db_healthy = await check_db_health()
    redis_healthy = await check_redis_health()

    return {
        "status": "ok",
        "phase": 2,
        "app_name": settings.app_name,
        "app_env": settings.app_env,
        "version": settings.app_version,
        "database": "connected" if db_healthy else "disconnected",
        "redis": "connected" if redis_healthy else "disconnected",
    }
