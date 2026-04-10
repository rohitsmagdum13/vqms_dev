-- =============================================================
-- 008_cache_schema.sql -- PostgreSQL cache tables
-- =============================================================
-- Creates the cache schema with a generic key-value store for
-- idempotency, token blacklist, and vendor
-- profile caching. Expired rows are cleaned up lazily on read
-- and periodically via a background task.
-- =============================================================

CREATE SCHEMA IF NOT EXISTS cache;

-- Generic key-value cache with TTL support.
-- Provides SET/GET/EXISTS semantics via PostgreSQL.
--   - Idempotency keys:  cache_key = 'vqms:idempotency:...'
--   - Token blacklist:   cache_key = 'vqms:auth:blacklist:...'
--   - Vendor profiles:   cache_key = 'vqms:vendor:...'
CREATE TABLE IF NOT EXISTS cache.kv_store (
    cache_key   TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    expires_at  TIMESTAMP,
    created_at  TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'Asia/Kolkata')
);

-- Index for periodic cleanup of expired rows.
-- Partial index: only covers rows that have a TTL set.
CREATE INDEX IF NOT EXISTS idx_kv_store_expires_at
    ON cache.kv_store (expires_at)
    WHERE expires_at IS NOT NULL;
