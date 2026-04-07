"""Tests for Redis key builder functions.

Verifies that each key builder produces the correct key format
and TTL value. These tests do NOT require a running Redis server.
"""

from __future__ import annotations

from src.cache.redis_client import (
    DASHBOARD_TTL_SECONDS,
    IDEMPOTENCY_TTL_SECONDS,
    SESSION_TTL_SECONDS,
    SLA_TTL_SECONDS,
    THREAD_TTL_SECONDS,
    VENDOR_TTL_SECONDS,
    WORKFLOW_TTL_SECONDS,
    dashboard_key,
    idempotency_key,
    session_key,
    sla_key,
    thread_key,
    vendor_key,
    workflow_key,
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


class TestSessionKey:
    """Test session key builder."""

    def test_format(self):
        key, ttl = session_key("jwt-token-abc")
        assert key == "vqms:session:jwt-token-abc"
        assert ttl == SESSION_TTL_SECONDS

    def test_ttl_is_eight_hours(self):
        _, ttl = session_key("test")
        assert ttl == 28800


class TestVendorKey:
    """Test vendor profile cache key builder."""

    def test_format(self):
        key, ttl = vendor_key("SF-ACC-001")
        assert key == "vqms:vendor:SF-ACC-001"
        assert ttl == VENDOR_TTL_SECONDS

    def test_ttl_is_one_hour(self):
        _, ttl = vendor_key("test")
        assert ttl == 3600


class TestWorkflowKey:
    """Test workflow state key builder."""

    def test_format(self):
        key, ttl = workflow_key("exec-001")
        assert key == "vqms:workflow:exec-001"
        assert ttl == WORKFLOW_TTL_SECONDS

    def test_ttl_is_24_hours(self):
        _, ttl = workflow_key("test")
        assert ttl == 86400


class TestSlaKey:
    """Test SLA timer key builder."""

    def test_format(self):
        key, ttl = sla_key("ticket-001")
        assert key == "vqms:sla:ticket-001"
        assert ttl == SLA_TTL_SECONDS

    def test_ttl_is_zero_no_auto_expire(self):
        _, ttl = sla_key("test")
        assert ttl == 0


class TestDashboardKey:
    """Test dashboard KPI cache key builder."""

    def test_format(self):
        key, ttl = dashboard_key("SF-ACC-001")
        assert key == "vqms:dashboard:SF-ACC-001"
        assert ttl == DASHBOARD_TTL_SECONDS

    def test_ttl_is_five_minutes(self):
        _, ttl = dashboard_key("test")
        assert ttl == 300


class TestThreadKey:
    """Test thread correlation key builder."""

    def test_format(self):
        key, ttl = thread_key("<msg123@mail.com>")
        assert key == "vqms:thread:<msg123@mail.com>"
        assert ttl == THREAD_TTL_SECONDS

    def test_ttl_is_24_hours(self):
        _, ttl = thread_key("test")
        assert ttl == 86400


class TestAllKeysHavePrefix:
    """Verify all key builders use the vqms: prefix."""

    def test_all_keys_start_with_prefix(self):
        builders = [
            idempotency_key("x"),
            session_key("x"),
            vendor_key("x"),
            workflow_key("x"),
            sla_key("x"),
            dashboard_key("x"),
            thread_key("x"),
        ]
        for key, _ in builders:
            assert key.startswith("vqms:"), f"Key {key} missing vqms: prefix"
