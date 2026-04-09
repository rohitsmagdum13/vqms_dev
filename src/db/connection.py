"""PostgreSQL async connection pool for VQMS with SSH tunnel support.

Our RDS instance is NOT directly accessible from local machines.
All database connections go through an SSH tunnel to a bastion host.

Connection flow:
  local machine → SSH tunnel to bastion host → bastion forwards to RDS

The SSH tunnel is established at application startup and stays alive
for the entire app lifetime. SQLAlchemy's async engine connects
through the tunnel's local bind port.

Connection URL and pool settings come from config/settings.py.
SSH tunnel settings come from SSH_HOST, SSH_USERNAME, etc. env vars.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sshtunnel import SSHTunnelForwarder

logger = logging.getLogger(__name__)

# Module-level engine — initialized by init_db(), used by all DB operations
_engine: AsyncEngine | None = None

# Module-level SSH tunnel — initialized by start_ssh_tunnel()
_ssh_tunnel: SSHTunnelForwarder | None = None


def start_ssh_tunnel(
    *,
    ssh_host: str,
    ssh_port: int,
    ssh_username: str,
    ssh_private_key_path: str,
    rds_host: str,
    rds_port: int,
) -> tuple[str, int]:
    """Establish an SSH tunnel to the bastion host for RDS access.

    Opens a local port that forwards traffic through the bastion
    to the RDS endpoint. Returns the local bind address so
    SQLAlchemy can connect through it.

    Args:
        ssh_host: Bastion host IP or DNS name.
        ssh_port: SSH port on the bastion (usually 22).
        ssh_username: SSH username for the bastion.
        ssh_private_key_path: Path to the private key .pem file.
        rds_host: RDS endpoint hostname.
        rds_port: RDS port (usually 5432).

    Returns:
        Tuple of (local_bind_host, local_bind_port) to use in the
        database connection URL.

    Raises:
        Exception: If SSH tunnel cannot be established.
    """
    global _ssh_tunnel  # noqa: PLW0603

    _ssh_tunnel = SSHTunnelForwarder(
        (ssh_host, ssh_port),
        ssh_username=ssh_username,
        ssh_pkey=ssh_private_key_path,
        remote_bind_address=(rds_host, rds_port),
        # Let sshtunnel pick an available local port
        local_bind_address=("127.0.0.1", 0),
    )
    _ssh_tunnel.start()

    local_host = _ssh_tunnel.local_bind_host
    local_port = _ssh_tunnel.local_bind_port

    logger.info(
        "SSH tunnel established",
        extra={
            "tool": "postgresql",
            "ssh_host": ssh_host,
            "rds_host": rds_host,
            "local_bind": f"{local_host}:{local_port}",
        },
    )
    return local_host, local_port


async def init_db(
    database_url: str,
    pool_min: int = 5,
    pool_max: int = 20,
) -> AsyncEngine:
    """Create and test the async database connection pool.

    Call this once at application startup (in main.py lifespan),
    AFTER the SSH tunnel is established. The database_url should
    point to the tunnel's local bind address.

    Args:
        database_url: PostgreSQL connection string
            (e.g., postgresql+asyncpg://user:pass@127.0.0.1:12345/vqms).
        pool_min: Minimum number of connections in the pool.
        pool_max: Maximum number of connections in the pool.

    Returns:
        The created AsyncEngine instance.

    Raises:
        Exception: If the database is unreachable through the tunnel.
    """
    global _engine  # noqa: PLW0603

    _engine = create_async_engine(
        database_url,
        pool_size=pool_min,
        max_overflow=pool_max - pool_min,
        pool_pre_ping=True,
        echo=False,
    )

    # Test the connection to fail fast if DB is unreachable
    async with _engine.connect() as conn:
        await conn.execute(text("SELECT 1"))

    logger.info(
        "Database connection pool initialized (via SSH tunnel)",
        extra={"tool": "postgresql", "pool_min": pool_min, "pool_max": pool_max},
    )
    return _engine


def get_engine() -> AsyncEngine | None:
    """Return the current database engine (or None if not initialized)."""
    return _engine


async def close_db() -> None:
    """Dispose of the database connection pool.

    Call this at application shutdown to release all connections.
    """
    global _engine  # noqa: PLW0603

    if _engine is not None:
        await _engine.dispose()
        logger.info("Database connection pool closed", extra={"tool": "postgresql"})
        _engine = None


def stop_ssh_tunnel() -> None:
    """Close the SSH tunnel.

    Call this at application shutdown AFTER closing the DB pool.
    """
    global _ssh_tunnel  # noqa: PLW0603

    if _ssh_tunnel is not None:
        _ssh_tunnel.stop()
        logger.info("SSH tunnel closed", extra={"tool": "postgresql"})
        _ssh_tunnel = None


async def check_db_health() -> bool:
    """Check if the database connection is healthy.

    Returns:
        True if a simple query succeeds, False otherwise.
    """
    if _engine is None:
        return False

    try:
        async with _engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.warning("Database health check failed", extra={"tool": "postgresql"}, exc_info=True)
        return False
