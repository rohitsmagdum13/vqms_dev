# ruff: noqa: E402
"""Check PostgreSQL connectivity and list databases.

Quick diagnostic script to verify the SSH tunnel works and
see what databases exist on the RDS instance. Can also create
the VQMS database if it doesn't exist.

Usage:
  uv run python scripts/check_db.py
  uv run python scripts/check_db.py --create
"""

from __future__ import annotations

import argparse
import asyncio
import sys

sys.path.insert(0, ".")

from dotenv import load_dotenv

load_dotenv(override=True)

# asyncpg is used directly here (not SQLAlchemy) because
# CREATE DATABASE cannot run inside a transaction block,
# and we need to connect to the default 'postgres' database
# first to check what databases exist.
import asyncpg

from config.settings import get_settings
from src.db.connection import start_ssh_tunnel, stop_ssh_tunnel


async def main(*, create: bool = False):
    """Connect via SSH tunnel, list databases, optionally create vqm."""
    settings = get_settings()
    target_db = settings.postgres_db

    print(f"Target database name: {target_db}")
    print()

    # --- Establish SSH tunnel ---
    if settings.ssh_host and settings.ssh_private_key_path:
        print("Opening SSH tunnel to bastion...")
        local_host, local_port = start_ssh_tunnel(
            ssh_host=settings.ssh_host,
            ssh_port=settings.ssh_port,
            ssh_username=settings.ssh_username,
            ssh_private_key_path=settings.ssh_private_key_path,
            rds_host=settings.rds_host,
            rds_port=settings.rds_port,
        )
        print(f"SSH tunnel open: {local_host}:{local_port}")
    else:
        local_host = settings.postgres_host
        local_port = settings.postgres_port
        print(f"Direct connection: {local_host}:{local_port}")

    print()

    # --- Connect to default 'postgres' database to list databases ---
    print(f"Connecting to 'postgres' database as {settings.postgres_user}...")
    conn = await asyncpg.connect(
        host=local_host,
        port=local_port,
        user=settings.postgres_user,
        password=settings.postgres_password,
        database="postgres",
    )

    rows = await conn.fetch("SELECT datname FROM pg_database WHERE datistemplate = false ORDER BY datname")
    db_names = [row["datname"] for row in rows]

    print(f"Databases found on RDS: {db_names}")
    print()

    if target_db in db_names:
        print(f"[OK] Database '{target_db}' already exists.")
    else:
        print(f"[MISSING] Database '{target_db}' does NOT exist.")
        if create:
            print(f"Creating database '{target_db}'...")
            # CREATE DATABASE cannot run inside a transaction
            await conn.execute(f'CREATE DATABASE "{target_db}"')
            print(f"[OK] Database '{target_db}' created successfully.")
        else:
            print("Run with --create to create it:")
            print("  uv run python scripts/check_db.py --create")

    await conn.close()

    # --- If DB exists, try connecting to it and check for schemas ---
    if target_db in db_names or create:
        print()
        print(f"Connecting to '{target_db}' database...")
        target_conn = await asyncpg.connect(
            host=local_host,
            port=local_port,
            user=settings.postgres_user,
            password=settings.postgres_password,
            database=target_db,
        )

        schemas = await target_conn.fetch(
            "SELECT schema_name FROM information_schema.schemata "
            "WHERE schema_name NOT IN ('pg_catalog', 'information_schema', 'pg_toast') "
            "ORDER BY schema_name"
        )
        schema_names = [row["schema_name"] for row in schemas]
        print(f"Schemas: {schema_names}")

        # Check for workflow.case_execution table
        tables = await target_conn.fetch(
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_schema NOT IN ('pg_catalog', 'information_schema') "
            "ORDER BY table_schema, table_name"
        )
        if tables:
            print("Tables:")
            for t in tables:
                print(f"  {t['table_schema']}.{t['table_name']}")
        else:
            print("No user tables found. Run migrations to create them:")
            print("  -- Execute the SQL files in src/db/migrations/ in order")

        await target_conn.close()

    # Cleanup
    stop_ssh_tunnel()
    print()
    print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check PostgreSQL connectivity")
    parser.add_argument("--create", action="store_true", help="Create the database if it doesn't exist")
    args = parser.parse_args()
    asyncio.run(main(create=args.create))
