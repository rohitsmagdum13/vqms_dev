"""General utility functions for VQMS.

Small helper functions used across the codebase. Keep this file
focused — if a helper grows complex, move it to its own module.
"""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Return the current UTC datetime (timezone-aware).

    Use this instead of datetime.utcnow() which returns a naive
    datetime and is deprecated in Python 3.12+.

    Returns:
        Current UTC time as a timezone-aware datetime.
    """
    return datetime.now(UTC)
