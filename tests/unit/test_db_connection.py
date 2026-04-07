"""Tests for PostgreSQL database connection with SSH tunnel support.

Tests verify:
  - SSH tunnel establishment and teardown
  - Database engine initialization via tunnel
  - Connection health checks
  - Engine lifecycle (init → get → close)
  - Error handling when tunnel or DB is unreachable

All tests mock the SSH tunnel and SQLAlchemy engine — no real
PostgreSQL or bastion host connection is needed to run these tests.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.db import connection

# ---------------------------------------------------------------------------
# Helpers — reset module-level state between tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_connection_state():
    """Reset module-level _engine and _ssh_tunnel before each test.

    The connection module uses module-level globals for the engine
    and SSH tunnel. We need to clear them between tests to avoid
    state leaking from one test to the next.
    """
    connection._engine = None
    connection._ssh_tunnel = None
    yield
    connection._engine = None
    connection._ssh_tunnel = None


# ---------------------------------------------------------------------------
# SSH Tunnel Tests
# ---------------------------------------------------------------------------

class TestSSHTunnel:
    """Test SSH tunnel establishment and teardown."""

    @patch("src.db.connection.SSHTunnelForwarder")
    def test_start_ssh_tunnel_returns_local_bind(self, mock_forwarder_cls):
        """start_ssh_tunnel() should return (host, port) from the tunnel."""
        mock_tunnel = MagicMock()
        mock_tunnel.local_bind_host = "127.0.0.1"
        mock_tunnel.local_bind_port = 54321
        mock_forwarder_cls.return_value = mock_tunnel

        host, port = connection.start_ssh_tunnel(
            ssh_host="bastion.example.com",
            ssh_port=22,
            ssh_username="ec2-user",
            ssh_private_key_path="/path/to/key.pem",
            rds_host="mydb.cluster-abc123.us-east-1.rds.amazonaws.com",
            rds_port=5432,
        )

        assert host == "127.0.0.1"
        assert port == 54321
        mock_tunnel.start.assert_called_once()

    @patch("src.db.connection.SSHTunnelForwarder")
    def test_start_ssh_tunnel_creates_forwarder_with_correct_args(
        self, mock_forwarder_cls
    ):
        """SSHTunnelForwarder should be created with the right bastion and RDS config."""
        mock_tunnel = MagicMock()
        mock_tunnel.local_bind_host = "127.0.0.1"
        mock_tunnel.local_bind_port = 12345
        mock_forwarder_cls.return_value = mock_tunnel

        connection.start_ssh_tunnel(
            ssh_host="bastion.example.com",
            ssh_port=2222,
            ssh_username="admin",
            ssh_private_key_path="/keys/bastion.pem",
            rds_host="mydb.rds.amazonaws.com",
            rds_port=5432,
        )

        mock_forwarder_cls.assert_called_once_with(
            ("bastion.example.com", 2222),
            ssh_username="admin",
            ssh_pkey="/keys/bastion.pem",
            remote_bind_address=("mydb.rds.amazonaws.com", 5432),
            local_bind_address=("127.0.0.1", 0),
        )

    @patch("src.db.connection.SSHTunnelForwarder")
    def test_start_ssh_tunnel_stores_tunnel_in_module(self, mock_forwarder_cls):
        """After start, the module-level _ssh_tunnel should hold the tunnel instance."""
        mock_tunnel = MagicMock()
        mock_tunnel.local_bind_host = "127.0.0.1"
        mock_tunnel.local_bind_port = 11111
        mock_forwarder_cls.return_value = mock_tunnel

        connection.start_ssh_tunnel(
            ssh_host="bastion.example.com",
            ssh_port=22,
            ssh_username="ec2-user",
            ssh_private_key_path="/path/to/key.pem",
            rds_host="mydb.rds.amazonaws.com",
            rds_port=5432,
        )

        assert connection._ssh_tunnel is mock_tunnel

    @patch("src.db.connection.SSHTunnelForwarder")
    def test_start_ssh_tunnel_raises_on_connection_failure(self, mock_forwarder_cls):
        """If the tunnel fails to start, the error should propagate."""
        mock_tunnel = MagicMock()
        mock_tunnel.start.side_effect = ConnectionRefusedError("SSH connection refused")
        mock_forwarder_cls.return_value = mock_tunnel

        with pytest.raises(ConnectionRefusedError, match="SSH connection refused"):
            connection.start_ssh_tunnel(
                ssh_host="unreachable.example.com",
                ssh_port=22,
                ssh_username="ec2-user",
                ssh_private_key_path="/path/to/key.pem",
                rds_host="mydb.rds.amazonaws.com",
                rds_port=5432,
            )

    def test_stop_ssh_tunnel_closes_active_tunnel(self):
        """stop_ssh_tunnel() should call stop() on the active tunnel."""
        mock_tunnel = MagicMock()
        connection._ssh_tunnel = mock_tunnel

        connection.stop_ssh_tunnel()

        mock_tunnel.stop.assert_called_once()
        assert connection._ssh_tunnel is None

    def test_stop_ssh_tunnel_does_nothing_when_no_tunnel(self):
        """stop_ssh_tunnel() should not raise when no tunnel exists."""
        assert connection._ssh_tunnel is None

        # Should not raise
        connection.stop_ssh_tunnel()

        assert connection._ssh_tunnel is None


# ---------------------------------------------------------------------------
# Database Engine Tests
# ---------------------------------------------------------------------------

class TestInitDb:
    """Test async database engine initialization."""

    @pytest.mark.asyncio
    @patch("src.db.connection.create_async_engine")
    async def test_init_db_creates_engine_and_tests_connection(
        self, mock_create_engine
    ):
        """init_db() should create an engine and run SELECT 1 to verify connectivity."""
        # Set up mock engine with async context manager for connect()
        mock_engine = MagicMock()
        mock_conn = AsyncMock()
        mock_engine.connect.return_value.__aenter__ = AsyncMock(
            return_value=mock_conn
        )
        mock_engine.connect.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_create_engine.return_value = mock_engine

        result = await connection.init_db(
            "postgresql+asyncpg://user:pass@127.0.0.1:54321/vqms"
        )

        assert result is mock_engine
        mock_create_engine.assert_called_once()
        # Verify SELECT 1 health check was executed
        mock_conn.execute.assert_called_once()

    @pytest.mark.asyncio
    @patch("src.db.connection.create_async_engine")
    async def test_init_db_uses_pool_settings(self, mock_create_engine):
        """init_db() should pass pool_min and pool_max to the engine."""
        mock_engine = MagicMock()
        mock_conn = AsyncMock()
        mock_engine.connect.return_value.__aenter__ = AsyncMock(
            return_value=mock_conn
        )
        mock_engine.connect.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_create_engine.return_value = mock_engine

        await connection.init_db(
            "postgresql+asyncpg://user:pass@127.0.0.1:54321/vqms",
            pool_min=3,
            pool_max=10,
        )

        call_kwargs = mock_create_engine.call_args.kwargs
        assert call_kwargs["pool_size"] == 3
        assert call_kwargs["max_overflow"] == 7  # pool_max - pool_min
        assert call_kwargs["pool_pre_ping"] is True

    @pytest.mark.asyncio
    @patch("src.db.connection.create_async_engine")
    async def test_init_db_stores_engine_in_module(self, mock_create_engine):
        """After init, get_engine() should return the created engine."""
        mock_engine = MagicMock()
        mock_conn = AsyncMock()
        mock_engine.connect.return_value.__aenter__ = AsyncMock(
            return_value=mock_conn
        )
        mock_engine.connect.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_create_engine.return_value = mock_engine

        await connection.init_db(
            "postgresql+asyncpg://user:pass@127.0.0.1:54321/vqms"
        )

        assert connection.get_engine() is mock_engine

    @pytest.mark.asyncio
    @patch("src.db.connection.create_async_engine")
    async def test_init_db_raises_on_unreachable_database(self, mock_create_engine):
        """If the DB is unreachable, init_db() should raise immediately."""
        mock_engine = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.execute.side_effect = ConnectionRefusedError(
            "Cannot connect to RDS"
        )
        mock_engine.connect.return_value.__aenter__ = AsyncMock(
            return_value=mock_conn
        )
        mock_engine.connect.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_create_engine.return_value = mock_engine

        with pytest.raises(ConnectionRefusedError, match="Cannot connect to RDS"):
            await connection.init_db(
                "postgresql+asyncpg://user:pass@127.0.0.1:54321/vqms"
            )


# ---------------------------------------------------------------------------
# Engine Lifecycle Tests
# ---------------------------------------------------------------------------

class TestEngineLifecycle:
    """Test get_engine() and close_db() lifecycle."""

    def test_get_engine_returns_none_before_init(self):
        """Before init_db(), get_engine() should return None."""
        assert connection.get_engine() is None

    @pytest.mark.asyncio
    async def test_close_db_disposes_engine(self):
        """close_db() should dispose the engine and set it to None."""
        mock_engine = AsyncMock()
        connection._engine = mock_engine

        await connection.close_db()

        mock_engine.dispose.assert_called_once()
        assert connection._engine is None
        assert connection.get_engine() is None

    @pytest.mark.asyncio
    async def test_close_db_does_nothing_when_no_engine(self):
        """close_db() should not raise when no engine exists."""
        assert connection._engine is None

        # Should not raise
        await connection.close_db()

        assert connection._engine is None


# ---------------------------------------------------------------------------
# Health Check Tests
# ---------------------------------------------------------------------------

class TestDbHealthCheck:
    """Test database health check function."""

    @pytest.mark.asyncio
    async def test_health_check_returns_false_when_no_engine(self):
        """If the engine is not initialized, health check returns False."""
        assert connection._engine is None

        result = await connection.check_db_health()

        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_returns_true_on_successful_query(self):
        """If SELECT 1 succeeds, health check returns True."""
        mock_engine = MagicMock()
        mock_conn = AsyncMock()
        mock_engine.connect.return_value.__aenter__ = AsyncMock(
            return_value=mock_conn
        )
        mock_engine.connect.return_value.__aexit__ = AsyncMock(return_value=False)
        connection._engine = mock_engine

        result = await connection.check_db_health()

        assert result is True
        mock_conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_health_check_returns_false_on_query_failure(self):
        """If SELECT 1 fails, health check returns False (not an exception)."""
        mock_engine = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.execute.side_effect = ConnectionError("Connection lost")
        mock_engine.connect.return_value.__aenter__ = AsyncMock(
            return_value=mock_conn
        )
        mock_engine.connect.return_value.__aexit__ = AsyncMock(return_value=False)
        connection._engine = mock_engine

        result = await connection.check_db_health()

        assert result is False


# ---------------------------------------------------------------------------
# Full Lifecycle Integration Test (SSH Tunnel → DB → Close → Stop)
# ---------------------------------------------------------------------------

class TestFullLifecycle:
    """Test the complete startup-to-shutdown sequence."""

    @pytest.mark.asyncio
    @patch("src.db.connection.create_async_engine")
    @patch("src.db.connection.SSHTunnelForwarder")
    async def test_full_startup_and_shutdown_sequence(
        self, mock_forwarder_cls, mock_create_engine
    ):
        """Verify the full lifecycle: tunnel start → db init → health → close → tunnel stop."""
        # --- Setup SSH tunnel mock ---
        mock_tunnel = MagicMock()
        mock_tunnel.local_bind_host = "127.0.0.1"
        mock_tunnel.local_bind_port = 54321
        mock_forwarder_cls.return_value = mock_tunnel

        # --- Setup DB engine mock ---
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        mock_conn = AsyncMock()
        mock_engine.connect.return_value.__aenter__ = AsyncMock(
            return_value=mock_conn
        )
        mock_engine.connect.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_create_engine.return_value = mock_engine

        # --- Step 1: Start SSH tunnel ---
        host, port = connection.start_ssh_tunnel(
            ssh_host="bastion.example.com",
            ssh_port=22,
            ssh_username="ec2-user",
            ssh_private_key_path="/path/to/key.pem",
            rds_host="mydb.rds.amazonaws.com",
            rds_port=5432,
        )
        assert host == "127.0.0.1"
        assert port == 54321
        mock_tunnel.start.assert_called_once()

        # --- Step 2: Init database through tunnel ---
        tunnel_db_url = (
            f"postgresql+asyncpg://user:pass@{host}:{port}/vqms"
        )
        engine = await connection.init_db(tunnel_db_url)
        assert engine is mock_engine
        assert connection.get_engine() is mock_engine

        # --- Step 3: Health check ---
        is_healthy = await connection.check_db_health()
        assert is_healthy is True

        # --- Step 4: Close database ---
        await connection.close_db()
        assert connection.get_engine() is None
        mock_engine.dispose.assert_called_once()

        # --- Step 5: Stop SSH tunnel ---
        connection.stop_ssh_tunnel()
        mock_tunnel.stop.assert_called_once()
        assert connection._ssh_tunnel is None
