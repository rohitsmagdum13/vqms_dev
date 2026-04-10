"""Tests for PostgreSQL cache key builder functions.

Verifies that each key builder produces the correct key format
and TTL value. These tests do NOT require a running database.
"""

from __future__ import annotations

from src.cache.pg_cache import (
    AUTH_BLACKLIST_TTL_SECONDS,
    IDEMPOTENCY_TTL_SECONDS,
    VENDOR_TTL_SECONDS,
    auth_blacklist_key,
    idempotency_key,
    vendor_key,
)


class TestIdempotencyKey:
    """Test idempotency key builder."""

    def test_format(self):
        key, ttl = idempotency_key("<abc123@mail.com>")
        assert key == "vqms:idempotency:<abc123@mail.com>"
        assert ttl == IDEMPOTENCY_TTL_SECONDS

    def test_ttl_is_seven_days(self):
        _, ttl = idempotency_key("test")
        assert ttl == 604800


class TestAuthBlacklistKey:
    """Test auth blacklist key builder."""

    def test_format(self):
        key, ttl = auth_blacklist_key("jti-abc-123")
        assert key == "vqms:auth:blacklist:jti-abc-123"
        assert ttl == AUTH_BLACKLIST_TTL_SECONDS

    def test_ttl_is_thirty_minutes(self):
        _, ttl = auth_blacklist_key("test")
        assert ttl == 1800


class TestVendorKey:
    """Test vendor profile cache key builder."""

    def test_format(self):
        key, ttl = vendor_key("SF-ACC-001")
        assert key == "vqms:vendor:SF-ACC-001"
        assert ttl == VENDOR_TTL_SECONDS

    def test_ttl_is_one_hour(self):
        _, ttl = vendor_key("test")
        assert ttl == 3600


class TestAllKeysHavePrefix:
    """Verify all key builders use the vqms: prefix."""

    def test_all_keys_start_with_prefix(self):
        builders = [
            idempotency_key("x"),
            auth_blacklist_key("x"),
            vendor_key("x"),
        ]
        for key, _ in builders:
            assert key.startswith("vqms:"), f"Key {key} missing vqms: prefix"
