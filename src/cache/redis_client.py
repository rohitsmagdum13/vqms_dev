"""Redis client and key schema for VQMS.

Manages the async Redis connection and provides key builder
functions for all 7 Redis key families. Each key builder returns
a (key, ttl_seconds) tuple so callers always know the correct TTL.

Key families and their purposes:
  - idempotency: Prevent duplicate email/query processing (7 days)
  - session: Cache portal JWT sessions (8 hours)
  - vendor: Cache Salesforce vendor profiles (1 hour)
  - workflow: Track workflow state for fast access (24 hours)
  - sla: SLA timer state (no auto-expire, managed by SLA monitor)
  - dashboard: Cache portal KPI data (5 minutes)
  - thread: Email thread correlation lookup (24 hours)
"""

from __future__ import annotations

import logging

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# --- TTL Constants ---
# Each TTL has a comment explaining why that duration was chosen.

# 7 days — Exchange Online can redeliver emails up to 5 days
# after the original send in recovery mode, so we keep the
# idempotency key for 7 days to be safe.
IDEMPOTENCY_TTL_SECONDS = 604800

# 8 hours — matches a typical work session for portal users.
# Cognito JWTs have configurable expiry; we cache the session
# data for the same duration to avoid re-validating every request.
SESSION_TTL_SECONDS = 28800

# 1 hour — vendor data changes infrequently in Salesforce,
# but we don't want to serve stale data for more than an hour
# in case tier or risk flags are updated.
VENDOR_TTL_SECONDS = 3600

# 24 hours — workflow state is actively updated during processing
# and then becomes stale. Most queries resolve within hours,
# so 24h is a safe upper bound.
WORKFLOW_TTL_SECONDS = 86400

# No auto-expire — SLA state is actively managed by the SLA
# monitoring service which explicitly deletes/updates keys.
# Setting TTL=0 means we use persist (no expiry).
SLA_TTL_SECONDS = 0

# 5 minutes — dashboard KPIs are expensive to compute (aggregate
# queries across multiple tables) but vendors don't need real-time
# data. 5-minute cache is a good balance.
DASHBOARD_TTL_SECONDS = 300

# 24 hours — same as workflow TTL. Thread correlation is needed
# during active processing and becomes irrelevant after resolution.
THREAD_TTL_SECONDS = 86400


# --- Key Prefix ---
KEY_PREFIX = "vqms:"


# --- Key Builder Functions ---
# Each returns (key, ttl_seconds) so callers always set the right TTL.


def idempotency_key(message_id: str) -> tuple[str, int]:
    """Build Redis key for email/query idempotency check.

    Args:
        message_id: RFC 2822 Message-ID or query submission ID.

    Returns:
        Tuple of (key, ttl_seconds).
    """
    return f"{KEY_PREFIX}idempotency:{message_id}", IDEMPOTENCY_TTL_SECONDS


def session_key(token: str) -> tuple[str, int]:
    """Build Redis key for portal JWT session cache.

    Args:
        token: JWT token (or a hash of it) from Cognito.

    Returns:
        Tuple of (key, ttl_seconds).
    """
    return f"{KEY_PREFIX}session:{token}", SESSION_TTL_SECONDS


def vendor_key(vendor_id: str) -> tuple[str, int]:
    """Build Redis key for cached Salesforce vendor profile.

    Args:
        vendor_id: Salesforce Account ID.

    Returns:
        Tuple of (key, ttl_seconds).
    """
    return f"{KEY_PREFIX}vendor:{vendor_id}", VENDOR_TTL_SECONDS


def workflow_key(execution_id: str) -> tuple[str, int]:
    """Build Redis key for workflow state cache.

    Args:
        execution_id: UUID4 workflow execution ID.

    Returns:
        Tuple of (key, ttl_seconds).
    """
    return f"{KEY_PREFIX}workflow:{execution_id}", WORKFLOW_TTL_SECONDS


def sla_key(ticket_id: str) -> tuple[str, int]:
    """Build Redis key for SLA timer state.

    Note: TTL is 0 (no auto-expire). The SLA monitoring service
    manages the lifecycle of these keys explicitly.

    Args:
        ticket_id: ServiceNow ticket sys_id.

    Returns:
        Tuple of (key, ttl_seconds). TTL=0 means no auto-expire.
    """
    return f"{KEY_PREFIX}sla:{ticket_id}", SLA_TTL_SECONDS


def dashboard_key(vendor_id: str) -> tuple[str, int]:
    """Build Redis key for cached portal dashboard KPIs.

    Args:
        vendor_id: Salesforce Account ID.

    Returns:
        Tuple of (key, ttl_seconds).
    """
    return f"{KEY_PREFIX}dashboard:{vendor_id}", DASHBOARD_TTL_SECONDS


def thread_key(message_id: str) -> tuple[str, int]:
    """Build Redis key for email thread correlation.

    Args:
        message_id: RFC 2822 Message-ID of the email.

    Returns:
        Tuple of (key, ttl_seconds).
    """
    return f"{KEY_PREFIX}thread:{message_id}", THREAD_TTL_SECONDS


# --- Connection Management ---

_redis_client: aioredis.Redis | None = None


async def init_redis(
    host: str = "localhost",
    port: int = 6379,
    password: str = "",
    db: int = 0,
    ssl: bool = False,
) -> aioredis.Redis:
    """Create and test the async Redis connection.

    Call this once at application startup (in main.py lifespan).

    Args:
        host: Redis server hostname.
        port: Redis server port.
        password: Redis auth password (empty string if no auth).
        db: Redis database number.
        ssl: Whether to use SSL/TLS.

    Returns:
        The connected Redis client.
    """
    global _redis_client  # noqa: PLW0603

    _redis_client = aioredis.Redis(
        host=host,
        port=port,
        password=password or None,
        db=db,
        ssl=ssl,
        decode_responses=True,
    )

    # Test connection
    await _redis_client.ping()
    logger.info(
        "Redis connection established",
        extra={"tool": "redis", "host": host, "port": port, "db": db},
    )
    return _redis_client


def get_redis_client() -> aioredis.Redis | None:
    """Return the current Redis client (or None if not initialized)."""
    return _redis_client


async def close_redis() -> None:
    """Close the Redis connection.

    Call this at application shutdown.
    """
    global _redis_client  # noqa: PLW0603

    if _redis_client is not None:
        await _redis_client.close()
        logger.info("Redis connection closed", extra={"tool": "redis"})
        _redis_client = None


async def check_redis_health() -> bool:
    """Check if the Redis connection is healthy.

    Returns:
        True if PING succeeds, False otherwise.
    """
    if _redis_client is None:
        return False

    try:
        await _redis_client.ping()
        return True
    except Exception:
        logger.warning("Redis health check failed", extra={"tool": "redis"}, exc_info=True)
        return False


# --- Convenience Helpers ---


async def set_with_ttl(key: str, value: str, ttl: int) -> None:
    """Set a key with an explicit TTL.

    If TTL is 0, the key is set without expiration.

    Args:
        key: Redis key.
        value: String value to store.
        ttl: TTL in seconds. 0 means no expiration.
    """
    if _redis_client is None:
        raise RuntimeError("Redis client not initialized — call init_redis() first")

    if ttl > 0:
        await _redis_client.setex(key, ttl, value)
    else:
        await _redis_client.set(key, value)


async def get_value(key: str) -> str | None:
    """Get a value from Redis by key.

    Args:
        key: Redis key.

    Returns:
        The value as a string, or None if the key doesn't exist.
    """
    if _redis_client is None:
        raise RuntimeError("Redis client not initialized — call init_redis() first")

    return await _redis_client.get(key)
