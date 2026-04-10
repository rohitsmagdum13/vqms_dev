"""PostgreSQL-based cache for VQMS.

Provides key-value caching with TTL support using the cache.kv_store
table in PostgreSQL. Used for idempotency checks, JWT token blacklist,
and vendor profile caching.

Key families:
  - idempotency: Prevent duplicate email/query processing (7 days)
  - auth:blacklist: JWT revocation on logout (30 minutes)
  - vendor: Cache Salesforce vendor profiles (1 hour)
"""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import text

from src.db.connection import get_engine
from src.utils.helpers import IST, ist_now

logger = logging.getLogger(__name__)

# --- TTL Constants ---

# 7 days — Exchange Online can redeliver emails up to 5 days
# after the original send in recovery mode, so we keep the
# idempotency key for 7 days to be safe.
IDEMPOTENCY_TTL_SECONDS = 604800

# 30 minutes — matches JWT session_timeout_seconds. A blacklisted
# token only needs to remain blocked until it would have expired
# naturally. After expiry, the token is invalid anyway.
AUTH_BLACKLIST_TTL_SECONDS = 1800

# 1 hour — vendor data changes infrequently in Salesforce,
# but we don't want to serve stale data for more than an hour
# in case tier or risk flags are updated.
VENDOR_TTL_SECONDS = 3600


# --- Key Prefix ---
KEY_PREFIX = "vqms:"


# --- Key Builder Functions ---
# Each returns (key, ttl_seconds) so callers always set the right TTL.


def idempotency_key(message_id: str) -> tuple[str, int]:
    """Build cache key for email/query idempotency check.

    Args:
        message_id: RFC 2822 Message-ID or query submission ID.

    Returns:
        Tuple of (key, ttl_seconds).
    """
    return f"{KEY_PREFIX}idempotency:{message_id}", IDEMPOTENCY_TTL_SECONDS


def auth_blacklist_key(token_jti: str) -> tuple[str, int]:
    """Build cache key for JWT blacklist (logout/revocation).

    When a user logs out, the token's JTI (unique ID) is stored
    here so any subsequent request with that token is rejected.
    The TTL matches the JWT lifetime — after natural expiry,
    the token is invalid anyway and no longer needs blocking.

    Args:
        token_jti: The JTI (JWT ID) claim from the token.

    Returns:
        Tuple of (key, ttl_seconds).
    """
    return f"{KEY_PREFIX}auth:blacklist:{token_jti}", AUTH_BLACKLIST_TTL_SECONDS


def vendor_key(vendor_id: str) -> tuple[str, int]:
    """Build cache key for cached Salesforce vendor profile.

    Args:
        vendor_id: Salesforce Account ID.

    Returns:
        Tuple of (key, ttl_seconds).
    """
    return f"{KEY_PREFIX}vendor:{vendor_id}", VENDOR_TTL_SECONDS


# --- Cache Operations ---


async def set_with_ttl(key: str, value: str, ttl: int) -> None:
    """Set a key with an explicit TTL.

    Uses INSERT ON CONFLICT DO UPDATE to upsert the value.
    If TTL is 0, the key is set without expiration.

    Args:
        key: Cache key.
        value: String value to store.
        ttl: TTL in seconds. 0 means no expiration.
    """
    engine = get_engine()
    if engine is None:
        raise RuntimeError("Database not initialized — cannot write to cache")

    now = ist_now()

    if ttl > 0:
        # Compute expires_at in Python to avoid asyncpg/SQLAlchemy
        # type conflicts with PostgreSQL interval casting
        expires_at = now + timedelta(seconds=ttl)
        sql = text(
            "INSERT INTO cache.kv_store (cache_key, value, expires_at, created_at) "
            "VALUES (:key, :value, :expires_at, :created_at) "
            "ON CONFLICT (cache_key) DO UPDATE "
            "SET value = EXCLUDED.value, "
            "    expires_at = EXCLUDED.expires_at, "
            "    created_at = EXCLUDED.created_at"
        )
        params = {"key": key, "value": value, "expires_at": expires_at, "created_at": now}
    else:
        sql = text(
            "INSERT INTO cache.kv_store (cache_key, value, expires_at, created_at) "
            "VALUES (:key, :value, NULL, :created_at) "
            "ON CONFLICT (cache_key) DO UPDATE "
            "SET value = EXCLUDED.value, "
            "    expires_at = NULL, "
            "    created_at = EXCLUDED.created_at"
        )
        params = {"key": key, "value": value, "created_at": now}

    async with engine.begin() as conn:
        await conn.execute(sql, params)


async def get_value(key: str) -> str | None:
    """Get a value from cache by key.

    Only returns the value if the key has not expired.

    Args:
        key: Cache key.

    Returns:
        The value as a string, or None if the key doesn't exist
        or has expired.
    """
    engine = get_engine()
    if engine is None:
        raise RuntimeError("Database not initialized — cannot read from cache")

    now = ist_now()
    sql = text(
        "SELECT value FROM cache.kv_store "
        "WHERE cache_key = :key "
        "AND (expires_at IS NULL OR expires_at > :now_ist)"
    )

    async with engine.connect() as conn:
        result = await conn.execute(sql, {"key": key, "now_ist": now})
        row = result.first()

    return row[0] if row else None


async def exists_key(key: str) -> bool:
    """Check if a key exists in cache without fetching its value.

    Only returns True if the key has not expired.

    Args:
        key: Cache key to check.

    Returns:
        True if the key exists and is not expired, False otherwise.
    """
    engine = get_engine()
    if engine is None:
        raise RuntimeError("Database not initialized — cannot check cache")

    now = ist_now()
    sql = text(
        "SELECT 1 FROM cache.kv_store "
        "WHERE cache_key = :key "
        "AND (expires_at IS NULL OR expires_at > :now_ist)"
    )

    async with engine.connect() as conn:
        result = await conn.execute(sql, {"key": key, "now_ist": now})
        row = result.first()

    return row is not None


async def delete_key(key: str) -> None:
    """Delete a key from cache.

    Args:
        key: Cache key to delete.
    """
    engine = get_engine()
    if engine is None:
        raise RuntimeError("Database not initialized — cannot delete from cache")

    sql = text("DELETE FROM cache.kv_store WHERE cache_key = :key")

    async with engine.begin() as conn:
        await conn.execute(sql, {"key": key})


async def cleanup_expired() -> int:
    """Delete all expired cache entries.

    Returns:
        Number of rows deleted.
    """
    engine = get_engine()
    if engine is None:
        return 0

    now = ist_now()
    sql = text(
        "DELETE FROM cache.kv_store "
        "WHERE expires_at IS NOT NULL AND expires_at < :now_ist"
    )

    async with engine.begin() as conn:
        result = await conn.execute(sql, {"now_ist": now})

    deleted = result.rowcount
    if deleted > 0:
        logger.info(
            "Cleaned up expired cache entries",
            extra={"tool": "pg_cache", "deleted_count": deleted},
        )
    return deleted
