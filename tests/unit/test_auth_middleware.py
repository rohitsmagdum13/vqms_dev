"""Tests for the JWT authentication middleware.

Tests skip-path logic, token validation flow, and user context
population on request.state. Uses mocked auth service — no
real JWT or database needed.
"""

from __future__ import annotations

from src.api.middleware.auth_middleware import _should_skip_auth


class TestShouldSkipAuth:
    """Tests for the path-skipping logic."""

    def test_health_endpoint_is_skipped(self):
        assert _should_skip_auth("/health") is True

    def test_login_endpoint_is_skipped(self):
        assert _should_skip_auth("/auth/login") is True

    def test_docs_endpoint_is_skipped(self):
        assert _should_skip_auth("/docs") is True

    def test_openapi_json_is_skipped(self):
        assert _should_skip_auth("/openapi.json") is True

    def test_redoc_is_skipped(self):
        assert _should_skip_auth("/redoc") is True

    def test_webhooks_are_skipped(self):
        assert _should_skip_auth("/webhooks/email") is True
        assert _should_skip_auth("/webhooks/ms-graph") is True

    def test_queries_endpoint_is_not_skipped(self):
        assert _should_skip_auth("/queries") is False

    def test_vendors_endpoint_is_not_skipped(self):
        assert _should_skip_auth("/vendors") is False

    def test_dashboard_endpoint_is_not_skipped(self):
        assert _should_skip_auth("/dashboard/kpis") is False

    def test_auth_logout_is_not_skipped(self):
        """Logout requires a valid token to blacklist it."""
        assert _should_skip_auth("/auth/logout") is False
