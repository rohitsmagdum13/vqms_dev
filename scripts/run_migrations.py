# ruff: noqa: E402
"""Run all SQL migrations against the VQMS PostgreSQL database.

Connects via SSH tunnel (or direct), then executes each migration
file in src/db/migrations/ in order. Uses IF NOT EXISTS / IF EXISTS
guards so migrations are safe to re-run.

Usage:
  uv run python scripts/run_migrations.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, ".")

from dotenv import load_dotenv

load_dotenv(override=True)

import asyncpg

from config.settings import get_settings
from src.db.connection import start_ssh_tunnel, stop_ssh_tunnel

# Migration files in execution order
MIGRATIONS_DIR = Path("src/db/migrations")


async def main():
    """Connect to PostgreSQL and run all migration SQL files."""
    settings = get_settings()

    # --- Establish connection ---
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

    print(f"Connecting to database '{settings.postgres_db}'...")
    conn = await asyncpg.connect(
        host=local_host,
        port=local_port,
        user=settings.postgres_user,
        password=settings.postgres_password,
        database=settings.postgres_db,
    )
    print(f"Connected to '{settings.postgres_db}'\n")

    # --- Run migrations in order ---
    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not migration_files:
        print(f"No .sql files found in {MIGRATIONS_DIR}")
        await conn.close()
        stop_ssh_tunnel()
        return

    for sql_file in migration_files:
        print(f"Running {sql_file.name}...")
        sql = sql_file.read_text(encoding="utf-8")
        try:
            await conn.execute(sql)
            print(f"  [OK] {sql_file.name}")
        except Exception as e:
            print(f"  [ERROR] {sql_file.name}: {e}")

    print()

    # --- Verify: list schemas and tables ---
    schemas = await conn.fetch(
        "SELECT schema_name FROM information_schema.schemata "
        "WHERE schema_name NOT IN ('pg_catalog', 'information_schema', 'pg_toast', 'public') "
        "ORDER BY schema_name"
    )
    print(f"Schemas: {[r['schema_name'] for r in schemas]}")

    tables = await conn.fetch(
        "SELECT table_schema, table_name FROM information_schema.tables "
        "WHERE table_schema NOT IN ('pg_catalog', 'information_schema', 'public') "
        "ORDER BY table_schema, table_name"
    )
    if tables:
        print("Tables:")
        for t in tables:
            print(f"  {t['table_schema']}.{t['table_name']}")
    else:
        print("No tables found.")

    await conn.close()
    stop_ssh_tunnel()
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
