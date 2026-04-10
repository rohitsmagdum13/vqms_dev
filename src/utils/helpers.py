"""General utility functions for VQMS.

Small helper functions used across the codebase. Keep this file
focused — if a helper grows complex, move it to its own module.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

# IST is UTC+5:30 — all timestamps in VQMS use IST so they
# match the local office time when inspecting the database,
# logs, and API responses.
IST = timezone(timedelta(hours=5, minutes=30))


def ist_now() -> datetime:
    """Return the current IST datetime (naive, no tzinfo).

    Returns a naive datetime representing the current time in
    India Standard Time (UTC+5:30). The tzinfo is stripped so
    PostgreSQL TIMESTAMP columns store the raw IST value
    without converting back to UTC.

    Use this instead of datetime.utcnow() or datetime.now(UTC).

    Returns:
        Current IST time as a naive datetime.
    """
    return datetime.now(IST).replace(tzinfo=None)
