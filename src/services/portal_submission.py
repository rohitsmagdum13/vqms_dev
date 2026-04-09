"""Portal Submission Service for VQMS.

Handles POST /queries from the vendor portal. Validates the
submission, generates tracking IDs, performs idempotency check,
stores the case execution, publishes events, and queues the
query for the AI pipeline.

Corresponds to Steps P1-P6 in the VQMS Solution Flow Document.

Key rule: vendor_id comes from JWT/header, NEVER from the
request body. This service receives vendor_id as a parameter.
"""

from __future__ import annotations

import logging

from config.settings import get_settings
from src.cache.redis_client import get_value, idempotency_key, set_with_ttl
from src.events.eventbridge import publish_event
from src.models.query import QuerySubmission, UnifiedQueryPayload
from src.models.workflow import CaseExecution, QuerySource, Status
from src.queues.sqs import publish
from src.utils.correlation import (
    generate_correlation_id,
    generate_execution_id,
    generate_query_id,
)
from src.utils.exceptions import DuplicateQueryError
from src.utils.helpers import utc_now
from src.utils.log_context import LogContext

logger = logging.getLogger(__name__)


async def submit_portal_query(
    submission: QuerySubmission,
    vendor_id: str,
    vendor_name: str,
    *,
    correlation_id: str | None = None,
) -> dict:
    """Process a portal query submission end-to-end.

    This is the main entry point for portal-submitted queries.
    It performs the full intake pipeline:
      1. Generate tracking IDs
      2. Idempotency check via Redis
      3. Build UnifiedQueryPayload
      4. Store CaseExecution in PostgreSQL (graceful if DB unavailable)
      5. Publish QueryReceived event to EventBridge
      6. Enqueue to vqms-query-intake-queue via SQS
      7. Return acceptance response

    Args:
        submission: Validated portal form data (QuerySubmission model).
        vendor_id: Vendor ID from JWT/header — never from request body.
        vendor_name: Vendor display name from JWT/header.
        correlation_id: Optional pre-generated correlation ID.

    Returns:
        Dict with query_id, execution_id, correlation_id, status.

    Raises:
        DuplicateQueryError: If this query was already submitted
            (idempotency check found existing Redis key).
    """
    correlation_id = correlation_id or generate_correlation_id()
    execution_id = generate_execution_id()
    query_id = generate_query_id()
    now = utc_now()

    ctx = LogContext(
        correlation_id=correlation_id,
        execution_id=execution_id,
        query_id=query_id,
        agent_role="portal_submission",
        step="P6",
        status="OPEN",
    )

    logger.info(
        "Processing portal submission",
        extra={**ctx.to_dict(), "vendor_id": vendor_id},
    )

    # --- Step 1: Idempotency Check ---
    # Use subject + vendor_id as the idempotency key for portal.
    # This prevents the same vendor from submitting the exact same
    # query twice (e.g., double-click on submit button).
    idem_identifier = f"portal:{vendor_id}:{submission.subject}"
    await _check_idempotency(idem_identifier, correlation_id=correlation_id)

    # --- Step 2: Build UnifiedQueryPayload ---
    # This is the converged payload that both email and portal paths
    # produce. The AI pipeline consumes this identical structure
    # regardless of entry point.
    payload = UnifiedQueryPayload(
        query_id=query_id,
        execution_id=execution_id,
        correlation_id=correlation_id,
        source=QuerySource.PORTAL,
        vendor_id=vendor_id,
        vendor_name=vendor_name,
        subject=submission.subject,
        description=submission.description,
        query_type=submission.query_type,
        priority=submission.priority,
        reference_number=submission.reference_number,
        thread_status="NEW",
        received_at=now,
    )

    # --- Step 3: Store CaseExecution ---
    # Graceful if DB is unavailable — the query still gets queued.
    # The orchestrator will create the record if it's missing.
    await _store_case_execution(
        execution_id=execution_id,
        query_id=query_id,
        correlation_id=correlation_id,
        vendor_id=vendor_id,
        source=QuerySource.PORTAL,
    )

    # --- Step 4: Publish QueryReceived event ---
    settings = get_settings()
    await publish_event(
        detail_type="QueryReceived",
        detail={
            "query_id": query_id,
            "execution_id": execution_id,
            "source": "PORTAL",
            "vendor_id": vendor_id,
            "subject": submission.subject,
            "query_type": submission.query_type,
            "submitted_at": now.isoformat(),
        },
        correlation_id=correlation_id,
    )

    # --- Step 5: Enqueue for AI pipeline ---
    await publish(
        queue_name=settings.sqs_query_intake_queue,
        message=payload.model_dump(mode="json"),
        correlation_id=correlation_id,
    )

    logger.info(
        "Portal submission accepted",
        extra=ctx.to_dict(),
    )

    return {
        "query_id": query_id,
        "execution_id": execution_id,
        "correlation_id": correlation_id,
        "status": "accepted",
    }


async def _check_idempotency(
    identifier: str,
    *,
    correlation_id: str | None = None,
) -> None:
    """Check Redis for duplicate submission. Raise if found.

    If Redis is unavailable, we log a warning and allow the
    submission through. Better to process a potential duplicate
    than to reject a valid query because Redis is down.
    """
    key, ttl = idempotency_key(identifier)

    try:
        existing = await get_value(key)
        if existing is not None:
            logger.info(
                "Duplicate submission detected",
                extra={
                    "identifier": identifier,
                    "correlation_id": correlation_id,
                },
            )
            raise DuplicateQueryError(identifier)

        # Mark as processed
        await set_with_ttl(key, "1", ttl)
    except DuplicateQueryError:
        raise
    except Exception:
        # Redis unavailable — log and continue
        logger.warning(
            "Redis unavailable for idempotency check, allowing submission",
            extra={
                "identifier": identifier,
                "correlation_id": correlation_id,
            },
        )


async def _store_case_execution(
    *,
    execution_id: str,
    query_id: str,
    correlation_id: str,
    vendor_id: str,
    source: QuerySource,
) -> None:
    """Insert a CaseExecution record into PostgreSQL.

    Writes a row into workflow.case_execution via the SSH tunnel
    to RDS. Graceful on failure — if the DB is unavailable, the
    query still gets queued to SQS. The orchestrator can create
    the record later if it is missing.

    Uses raw SQL (not ORM) to keep the Phase 2 implementation
    simple. In Phase 3+, we may switch to SQLAlchemy ORM models.
    """
    from sqlalchemy import text

    from src.db.connection import get_engine

    # Validate the model first to catch data issues early
    case = CaseExecution(
        execution_id=execution_id,
        query_id=query_id,
        correlation_id=correlation_id,
        status=Status.NEW,
        source=source,
        vendor_id=vendor_id,
    )

    engine = get_engine()
    if engine is None:
        logger.warning(
            "Database not available — CaseExecution record skipped",
            extra={
                "execution_id": execution_id,
                "query_id": query_id,
                "correlation_id": correlation_id,
            },
        )
        return

    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("""
                    INSERT INTO workflow.case_execution
                        (execution_id, query_id, correlation_id, status,
                         source, vendor_id, created_at, updated_at)
                    VALUES
                        (:execution_id, :query_id, :correlation_id, :status,
                         :source, :vendor_id, :created_at, :updated_at)
                    ON CONFLICT (execution_id) DO NOTHING
                """),
                {
                    "execution_id": case.execution_id,
                    "query_id": case.query_id,
                    "correlation_id": case.correlation_id,
                    "status": case.status.value,
                    "source": case.source.value,
                    "vendor_id": case.vendor_id,
                    "created_at": case.created_at,
                    "updated_at": case.updated_at,
                },
            )
        logger.info(
            "CaseExecution record saved to PostgreSQL",
            extra={
                "execution_id": execution_id,
                "query_id": query_id,
                "correlation_id": correlation_id,
            },
        )
    except Exception:
        # DB write failure must NOT block the pipeline.
        # The query still gets queued to SQS.
        logger.warning(
            "Failed to save CaseExecution to PostgreSQL — continuing",
            extra={
                "execution_id": execution_id,
                "correlation_id": correlation_id,
            },
            exc_info=True,
        )
