"""Seed script: Create test users in public.tbl_users and public.tbl_user_roles.

Run this script to populate the auth tables with test users so you can
test the login flow. Passwords are hashed with werkzeug — the same
library the auth service uses to verify them.

Usage:
    uv run python -m src.db.seeds.seed_users

The script is idempotent — it uses ON CONFLICT DO NOTHING, so running
it multiple times will not create duplicates or error out.

Users created:
    admin_user / admin123   — ADMIN  role, hexaware tenant
    vendor_user / vendor123 — VENDOR role, acme tenant
    reviewer_user / rev123  — REVIEWER role, hexaware tenant
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from sqlalchemy import text

from src.utils.helpers import IST
from werkzeug.security import generate_password_hash

from src.db.connection import get_engine, init_db, start_ssh_tunnel
from src.utils.logger import get_logger, setup_logging

logger = get_logger(__name__)

# ---------------------------------------------------------------
# Test users to seed — add more here as needed
# ---------------------------------------------------------------
TEST_USERS = [
    {
        "user_name": "admin_user",
        "email_id": "admin@hexaware.com",
        "tenant": "hexaware",
        "password": "admin123",
        "status": "ACTIVE",
        "role": "ADMIN",
        "first_name": "Admin",
        "last_name": "User",
    },
    {
        "user_name": "vendor_user",
        "email_id": "vendor@acme.com",
        "tenant": "acme",
        "password": "vendor123",
        "status": "ACTIVE",
        "role": "VENDOR",
        "first_name": "Vendor",
        "last_name": "User",
    },
    {
        "user_name": "reviewer_user",
        "email_id": "reviewer@hexaware.com",
        "tenant": "hexaware",
        "password": "rev123",
        "status": "ACTIVE",
        "role": "REVIEWER",
        "first_name": "Reviewer",
        "last_name": "User",
    },
]


async def _ensure_auth_tables_exist(engine: object) -> None:
    """Create tbl_users and tbl_user_roles if they don't exist.

    Runs the same DDL as migration 007. Uses CREATE TABLE IF NOT
    EXISTS so it is safe to run on a database where the tables
    already exist — nothing will be modified.
    """
    async with engine.begin() as conn:  # type: ignore[union-attr]
        # Create tbl_users
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS public.tbl_users (
                id              SERIAL PRIMARY KEY,
                user_name       VARCHAR(255) UNIQUE NOT NULL,
                email_id        VARCHAR(255) UNIQUE NOT NULL,
                tenant          VARCHAR(255) NOT NULL,
                password        VARCHAR(512) NOT NULL,
                status          VARCHAR(50) DEFAULT 'ACTIVE',
                security_q1     VARCHAR(512),
                security_a1     VARCHAR(512),
                security_q2     VARCHAR(512),
                security_a2     VARCHAR(512),
                security_q3     VARCHAR(512),
                security_a3     VARCHAR(512)
            )
        """))

        # Create tbl_user_roles
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS public.tbl_user_roles (
                slno            SERIAL PRIMARY KEY,
                first_name      VARCHAR(255),
                last_name       VARCHAR(255),
                email_id        VARCHAR(255),
                user_name       VARCHAR(255),
                tenant          VARCHAR(255),
                role            VARCHAR(100),
                created_by      VARCHAR(255),
                created_date    TIMESTAMP,
                modified_by     VARCHAR(255),
                modified_date   TIMESTAMP,
                deleted_by      VARCHAR(255),
                deleted_date    TIMESTAMP
            )
        """))

        # Indexes for common lookups
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_tbl_users_email "
            "ON public.tbl_users (email_id)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_tbl_users_status "
            "ON public.tbl_users (status)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_tbl_user_roles_username "
            "ON public.tbl_user_roles (user_name)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_tbl_user_roles_tenant "
            "ON public.tbl_user_roles (tenant)"
        ))

    logger.info("Auth tables verified (created if missing)")


async def seed_users() -> None:
    """Insert test users into tbl_users and tbl_user_roles.

    Uses ON CONFLICT DO NOTHING on user_name (unique) so the
    script is safe to run multiple times. Password hashing is
    done with werkzeug.generate_password_hash (pbkdf2:sha256).
    """
    engine = get_engine()
    if engine is None:
        logger.error("Database engine not available — cannot seed users")
        return

    # Step 0: Create tables if they don't exist
    # Runs the same DDL as migration 007 (CREATE TABLE IF NOT EXISTS)
    await _ensure_auth_tables_exist(engine)

    now = datetime.now(IST).replace(tzinfo=None)  # naive IST to match TIMESTAMP column
    created_count = 0

    async with engine.begin() as conn:
        for user in TEST_USERS:
            # Hash the plain-text password with werkzeug
            password_hash = generate_password_hash(user["password"])

            # Insert into tbl_users (skip if user_name already exists)
            result = await conn.execute(
                text(
                    "INSERT INTO public.tbl_users "
                    "(user_name, email_id, tenant, password, status) "
                    "VALUES (:user_name, :email_id, :tenant, :password, :status) "
                    "ON CONFLICT (user_name) DO NOTHING "
                    "RETURNING id"
                ),
                {
                    "user_name": user["user_name"],
                    "email_id": user["email_id"],
                    "tenant": user["tenant"],
                    "password": password_hash,
                    "status": user["status"],
                },
            )
            user_created = result.first() is not None

            # Insert into tbl_user_roles (skip if user_name already has a role)
            await conn.execute(
                text(
                    "INSERT INTO public.tbl_user_roles "
                    "(first_name, last_name, email_id, user_name, tenant, role, "
                    "created_by, created_date) "
                    "VALUES (:first_name, :last_name, :email_id, :user_name, "
                    ":tenant, :role, :created_by, :created_date) "
                    "ON CONFLICT DO NOTHING"
                ),
                {
                    "first_name": user["first_name"],
                    "last_name": user["last_name"],
                    "email_id": user["email_id"],
                    "user_name": user["user_name"],
                    "tenant": user["tenant"],
                    "role": user["role"],
                    "created_by": "seed_script",
                    "created_date": now,
                },
            )

            if user_created:
                created_count += 1
                logger.info(
                    "Created user",
                    extra={
                        "user_name": user["user_name"],
                        "role": user["role"],
                        "tenant": user["tenant"],
                    },
                )
            else:
                logger.info(
                    "User already exists — skipped",
                    extra={"user_name": user["user_name"]},
                )

    print(f"\nSeed complete: {created_count} new user(s) created, "
          f"{len(TEST_USERS) - created_count} already existed.\n")
    print("Test credentials:")
    print("-" * 50)
    for user in TEST_USERS:
        print(f"  {user['user_name']:20s} / {user['password']:12s}  ({user['role']})")
    print("-" * 50)


async def main() -> None:
    """Entry point: start SSH tunnel, init DB, seed users."""
    from config.settings import get_settings

    setup_logging()
    settings = get_settings()

    # Start SSH tunnel if configured (needed for RDS access)
    db_url = settings.database_url
    if settings.ssh_host:
        local_host, local_port = start_ssh_tunnel(
            ssh_host=settings.ssh_host,
            ssh_port=settings.ssh_port,
            ssh_username=settings.ssh_username,
            ssh_private_key_path=settings.ssh_private_key_path,
            rds_host=settings.rds_host,
            rds_port=settings.rds_port,
        )
        # Rewrite DB URL to use the tunnel's local port
        db_url = (
            f"postgresql+asyncpg://{settings.postgres_user}:{settings.postgres_password}"
            f"@{local_host}:{local_port}/{settings.postgres_db}"
        )

    # Initialize async DB engine
    await init_db(db_url, pool_min=2, pool_max=5)

    # Seed the users
    await seed_users()


if __name__ == "__main__":
    asyncio.run(main())
