"""Tests for the authentication service.

Tests JWT creation, validation, blacklisting, and token refresh.
Database and Redis are mocked — no real connections needed.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from jose import jwt

from src.models.auth import TokenPayload
from src.services.auth import (
    AuthenticationError,
    authenticate_user,
    blacklist_token,
    create_access_token,
    refresh_token_if_expiring,
    validate_token,
)

# --- Test Settings ---
# Used by all tests that need JWT settings
TEST_SECRET = "test-secret-key-for-unit-tests"
TEST_ALGORITHM = "HS256"
TEST_TIMEOUT = 1800
TEST_REFRESH_THRESHOLD = 300


@pytest.fixture
def mock_settings():
    """Mock AppSettings with test JWT configuration."""
    settings = MagicMock()
    settings.jwt_secret_key = TEST_SECRET
    settings.jwt_algorithm = TEST_ALGORITHM
    settings.session_timeout_seconds = TEST_TIMEOUT
    settings.token_refresh_threshold_seconds = TEST_REFRESH_THRESHOLD
    return settings


@pytest.fixture
def sample_token(mock_settings):
    """Create a valid JWT token for testing."""
    with patch("src.services.auth.get_settings", return_value=mock_settings):
        return create_access_token(
            user_name="test_user",
            role="VENDOR",
            tenant="test_tenant",
        )


class TestCreateAccessToken:
    """Tests for create_access_token()."""

    def test_creates_valid_jwt(self, mock_settings):
        """Token should be a valid JWT with expected claims."""
        with patch("src.services.auth.get_settings", return_value=mock_settings):
            token = create_access_token("john", "ADMIN", "acme")

        payload = jwt.decode(token, TEST_SECRET, algorithms=[TEST_ALGORITHM])
        assert payload["sub"] == "john"
        assert payload["role"] == "ADMIN"
        assert payload["tenant"] == "acme"
        assert "exp" in payload
        assert "iat" in payload
        assert "jti" in payload

    def test_token_expiry_matches_settings(self, mock_settings):
        """Token exp should be iat + session_timeout_seconds."""
        with patch("src.services.auth.get_settings", return_value=mock_settings):
            token = create_access_token("john", "ADMIN", "acme")

        payload = jwt.decode(token, TEST_SECRET, algorithms=[TEST_ALGORITHM])
        # Allow 2-second tolerance for test execution time
        assert abs((payload["exp"] - payload["iat"]) - TEST_TIMEOUT) < 2

    def test_each_token_has_unique_jti(self, mock_settings):
        """Each token should have a unique JTI for blacklist tracking."""
        with patch("src.services.auth.get_settings", return_value=mock_settings):
            token1 = create_access_token("john", "ADMIN", "acme")
            token2 = create_access_token("john", "ADMIN", "acme")

        p1 = jwt.decode(token1, TEST_SECRET, algorithms=[TEST_ALGORITHM])
        p2 = jwt.decode(token2, TEST_SECRET, algorithms=[TEST_ALGORITHM])
        assert p1["jti"] != p2["jti"]


class TestValidateToken:
    """Tests for validate_token()."""

    @pytest.mark.asyncio(loop_scope="function")
    async def test_valid_token_returns_payload(self, mock_settings, sample_token):
        """A valid, non-blacklisted token should return TokenPayload."""
        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=0)

        with (
            patch("src.services.auth.get_settings", return_value=mock_settings),
            patch("src.services.auth.get_redis_client", return_value=mock_redis),
            patch("src.services.auth.exists_key", new_callable=AsyncMock, return_value=False),
        ):
            result = await validate_token(sample_token)

        assert result is not None
        assert isinstance(result, TokenPayload)
        assert result.sub == "test_user"
        assert result.role == "VENDOR"
        assert result.tenant == "test_tenant"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_invalid_token_returns_none(self, mock_settings):
        """An invalid token string should return None."""
        with patch("src.services.auth.get_settings", return_value=mock_settings):
            result = await validate_token("not-a-real-jwt")

        assert result is None

    @pytest.mark.asyncio(loop_scope="function")
    async def test_expired_token_returns_none(self, mock_settings):
        """An expired token should return None."""
        # Create a token that expired 10 seconds ago
        claims = {
            "sub": "test_user",
            "role": "VENDOR",
            "tenant": "test",
            "exp": time.time() - 10,
            "iat": time.time() - 1810,
            "jti": "test-jti",
        }
        expired_token = jwt.encode(claims, TEST_SECRET, algorithm=TEST_ALGORITHM)

        with patch("src.services.auth.get_settings", return_value=mock_settings):
            result = await validate_token(expired_token)

        assert result is None

    @pytest.mark.asyncio(loop_scope="function")
    async def test_blacklisted_token_returns_none(self, mock_settings, sample_token):
        """A blacklisted token should return None."""
        mock_redis = AsyncMock()

        with (
            patch("src.services.auth.get_settings", return_value=mock_settings),
            patch("src.services.auth.get_redis_client", return_value=mock_redis),
            patch("src.services.auth.exists_key", new_callable=AsyncMock, return_value=True),
        ):
            result = await validate_token(sample_token)

        assert result is None


class TestBlacklistToken:
    """Tests for blacklist_token()."""

    @pytest.mark.asyncio(loop_scope="function")
    async def test_blacklists_token_in_redis(self, mock_settings, sample_token):
        """Blacklisting should store the JTI in Redis."""
        mock_redis = AsyncMock()

        with (
            patch("src.services.auth.get_settings", return_value=mock_settings),
            patch("src.services.auth.get_redis_client", return_value=mock_redis),
            patch("src.services.auth.set_with_ttl", new_callable=AsyncMock) as mock_set,
        ):
            await blacklist_token(sample_token)

        # Verify set_with_ttl was called with a blacklist key
        mock_set.assert_called_once()
        call_args = mock_set.call_args
        assert "auth:blacklist:" in call_args[0][0]
        assert call_args[0][1] == "blacklisted"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_blacklist_invalid_token_raises(self, mock_settings):
        """Blacklisting an invalid token should raise AuthenticationError."""
        with (
            patch("src.services.auth.get_settings", return_value=mock_settings),
            pytest.raises(AuthenticationError, match="Cannot decode token"),
        ):
            await blacklist_token("not-a-real-jwt")


class TestRefreshTokenIfExpiring:
    """Tests for refresh_token_if_expiring()."""

    @pytest.mark.asyncio(loop_scope="function")
    async def test_no_refresh_when_plenty_of_time(self, mock_settings):
        """Token with plenty of time left should NOT be refreshed."""
        payload = TokenPayload(
            sub="test_user",
            role="VENDOR",
            tenant="test",
            exp=time.time() + 1000,  # 1000 seconds left (> 300 threshold)
            iat=time.time(),
            jti="test-jti",
        )

        with patch("src.services.auth.get_settings", return_value=mock_settings):
            result = await refresh_token_if_expiring(payload)

        assert result is None

    @pytest.mark.asyncio(loop_scope="function")
    async def test_refresh_when_near_expiry(self, mock_settings):
        """Token close to expiry should be refreshed with a new token."""
        payload = TokenPayload(
            sub="test_user",
            role="VENDOR",
            tenant="test",
            exp=time.time() + 100,  # 100 seconds left (< 300 threshold)
            iat=time.time() - 1700,
            jti="old-jti",
        )

        mock_redis = AsyncMock()

        with (
            patch("src.services.auth.get_settings", return_value=mock_settings),
            patch("src.services.auth.get_redis_client", return_value=mock_redis),
            patch("src.services.auth.set_with_ttl", new_callable=AsyncMock),
        ):
            new_token = await refresh_token_if_expiring(payload)

        assert new_token is not None
        # Verify the new token has the same user claims
        new_payload = jwt.decode(new_token, TEST_SECRET, algorithms=[TEST_ALGORITHM])
        assert new_payload["sub"] == "test_user"
        assert new_payload["role"] == "VENDOR"
        assert new_payload["tenant"] == "test"
        # But a different JTI
        assert new_payload["jti"] != "old-jti"


class TestAuthenticateUser:
    """Tests for authenticate_user()."""

    @pytest.mark.asyncio(loop_scope="function")
    async def test_raises_when_db_unavailable(self):
        """Should raise AuthenticationError when DB engine is None."""
        with (
            patch("src.services.auth.get_engine", return_value=None),
            pytest.raises(AuthenticationError, match="Database not available"),
        ):
            await authenticate_user("user", "pass")

    @pytest.mark.asyncio(loop_scope="function")
    async def test_raises_when_user_not_found(self, mock_settings):
        """Should raise AuthenticationError for unknown user."""
        # Mock engine with a query that returns no rows
        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value.first.return_value = None
        mock_conn.execute = AsyncMock(return_value=mock_result)

        # Create a proper async context manager for engine.connect()
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_cm

        with (
            patch("src.services.auth.get_engine", return_value=mock_engine),
            pytest.raises(AuthenticationError, match="Invalid credentials"),
        ):
            await authenticate_user("nonexistent", "pass")
