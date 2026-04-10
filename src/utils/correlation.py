"""Correlation and identifier generation for VQMS.

Every query that enters VQMS gets three IDs:
  - correlation_id: UUID4 that follows the query across ALL services
  - execution_id: UUID4 for a single workflow execution
  - query_id: Human-readable ID in VQ-YYYY-NNNN format

These IDs are generated at intake and propagated through every
function call, log entry, database write, and external API request.
"""

from __future__ import annotations

import random
import uuid
from datetime import datetime

from src.utils.helpers import IST


def generate_correlation_id() -> str:
    """Generate a unique correlation ID (UUID4) for tracing.

    This ID follows a query through the entire VQMS pipeline —
    from intake through analysis, routing, drafting, delivery,
    and closure. Every log entry and database write includes it.

    Returns:
        A UUID4 string like '550e8400-e29b-41d4-a716-446655440000'.
    """
    return str(uuid.uuid4())


def generate_execution_id() -> str:
    """Generate a unique execution ID (UUID4) for a workflow run.

    Each time a query enters the LangGraph orchestrator, it gets
    a new execution_id. If a query is re-processed (e.g., after
    Path C human review), it gets a new execution_id but keeps
    the same correlation_id.

    Returns:
        A UUID4 string.
    """
    return str(uuid.uuid4())


def generate_query_id(prefix: str = "VQ") -> str:
    """Generate a human-readable query ID in PREFIX-YYYY-NNNN format.

    This is the ID vendors see in emails and on the portal.
    Format: VQ-2026-0451 (prefix, current year, 4-digit number).

    Note: In production, the 4-digit number should come from a
    database sequence to guarantee uniqueness. For development,
    we use a random number which is sufficient for testing.

    Args:
        prefix: The prefix for the query ID. Defaults to "VQ"
            as specified in PORTAL_QUERY_ID_PREFIX.

    Returns:
        A string like 'VQ-2026-0451'.
    """
    year = datetime.now(IST).strftime("%Y")
    sequence = random.randint(0, 9999)  # noqa: S311 — not used for security
    return f"{prefix}-{year}-{sequence:04d}"
