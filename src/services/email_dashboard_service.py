"""Email Dashboard Service — database query layer.

Reads from PostgreSQL (intake.email_messages, intake.email_attachments,
workflow.case_execution) and builds the response models for the email
dashboard API endpoints.

Key responsibilities:
  - Fetch paginated mail chains with filtering and sorting
  - Group emails into threads using conversation_id
  - Build UserResponse, AttachmentResponse, MailItemResponse, MailChainResponse
  - Map workflow status to dashboard display status
  - Generate presigned S3 URLs for attachment downloads
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from config.settings import get_settings
from src.db.connection import get_engine
from src.models.email_dashboard import (
    AttachmentDownloadResponse,
    AttachmentResponse,
    EmailStatsResponse,
    MailChainListResponse,
    MailChainResponse,
    MailItemResponse,
    UserResponse,
)

logger = logging.getLogger(__name__)


# --- Status Mapping ---
# Map workflow.case_execution.status values to dashboard display strings.
# The frontend expects exactly: "New", "Reopened", "Resolved"
_STATUS_MAP: dict[str, str] = {
    "new": "New",
    "analyzing": "New",
    "routing": "New",
    "drafting": "New",
    "validating": "New",
    "sending": "New",
    "awaiting_human_review": "New",
    "awaiting_team_resolution": "New",
    "failed": "New",
    "draft_rejected": "New",
    "reopened": "Reopened",
    "resolved": "Resolved",
    "closed": "Resolved",
}

# Map workflow priority (from case_execution or routing_decision)
# to dashboard display strings. Defaults to "Medium" if unknown.
_PRIORITY_MAP: dict[str, str] = {
    "critical": "High",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
}


def _map_status(db_status: str | None) -> str:
    """Convert a workflow.case_execution.status to a dashboard display status."""
    if db_status is None:
        return "New"
    return _STATUS_MAP.get(db_status.lower(), "New")


def _map_priority(db_priority: str | None) -> str:
    """Convert a priority value to a dashboard display priority."""
    if db_priority is None:
        return "Medium"
    return _PRIORITY_MAP.get(db_priority.lower(), "Medium")


def _file_format_from_filename(filename: str) -> str:
    """Extract uppercase file extension from a filename.

    Examples:
        'invoice.pdf'   -> 'PDF'
        'report.docx'   -> 'DOCX'
        'image.jpg'     -> 'JPG'
        'no_extension'  -> 'UNKNOWN'
    """
    _, _, extension = filename.rpartition(".")
    if not extension or extension == filename:
        return "UNKNOWN"
    return extension.upper()


def _build_attachment_url(s3_key: str | None) -> str:
    """Build an S3 URI for an attachment.

    Returns the s3:// URI. The /download endpoint provides
    presigned HTTPS URLs for actual browser downloads.
    """
    if not s3_key:
        return ""
    settings = get_settings()
    return f"s3://{settings.s3_bucket_attachments}/{s3_key}"


def _parse_recipients_json(raw_json: str | list | None) -> list[dict]:
    """Parse a JSONB recipients column into a list of dicts.

    The DB stores recipients as a JSON array. Values can be:
      - Simple strings: ["user@example.com", ...]
      - Objects with name+email: [{"name": "...", "email": "..."}, ...]

    We normalize both forms into [{"name": ..., "email": ...}].
    """
    if raw_json is None:
        return []

    # If it's already a list (SQLAlchemy may auto-deserialize JSONB)
    if isinstance(raw_json, list):
        items = raw_json
    elif isinstance(raw_json, str):
        try:
            items = json.loads(raw_json)
        except (json.JSONDecodeError, TypeError):
            return []
    else:
        return []

    result = []
    for item in items:
        if isinstance(item, dict):
            result.append({
                "name": item.get("name", item.get("email", "")),
                "email": item.get("email", ""),
            })
        elif isinstance(item, str):
            # Plain email string — use email as both name and email
            result.append({"name": item, "email": item})
    return result


def _build_user_responses(parsed: list[dict]) -> list[UserResponse]:
    """Convert parsed recipient dicts to UserResponse models."""
    return [
        UserResponse(name=r.get("name", r.get("email", "")), email=r.get("email", ""))
        for r in parsed
    ]


def _format_timestamp(dt: datetime | None) -> str:
    """Format a datetime to ISO 8601 with timezone.

    If the datetime has no timezone info, assumes UTC.
    """
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


# --- Status filter to SQL conditions ---
def _status_filter_sql(status: str) -> str:
    """Return a SQL IN clause for workflow statuses matching a dashboard status."""
    if status == "New":
        return (
            "('new', 'analyzing', 'routing', 'drafting', 'validating', "
            "'sending', 'awaiting_human_review', 'awaiting_team_resolution', "
            "'failed', 'draft_rejected')"
        )
    if status == "Reopened":
        return "('reopened')"
    if status == "Resolved":
        return "('resolved', 'closed')"
    return "('new')"


async def fetch_mail_chains(
    *,
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    priority: str | None = None,
    search: str | None = None,
    sort_by: str = "timestamp",
    sort_order: str = "desc",
    correlation_id: str | None = None,
) -> MailChainListResponse:
    """Fetch paginated email chains for the dashboard.

    Thread grouping strategy:
      - Primary: group by conversation_id (Graph API assigns the
        same conversation_id to all emails in a thread)
      - Fallback: if conversation_id is NULL, each email becomes
        its own chain (grouped by query_id)

    This means a vendor's original email and all replies share
    one MailChain, instead of each email being a separate chain.

    Status and priority come from workflow.case_execution.
    NOTE: Until Phase 3 (AI pipeline), status is always "New"
    and priority defaults to "Medium" because routing_decision
    is not yet populated.

    Args:
        page: Page number (1-based).
        page_size: Items per page.
        status: Filter by dashboard status: "New", "Reopened", "Resolved".
        priority: Filter by priority: "High", "Medium", "Low".
        search: Search term for subject and body_text.
        sort_by: Sort field: "timestamp", "status", "priority".
        sort_order: "asc" or "desc".
        correlation_id: Tracing ID.

    Returns:
        MailChainListResponse with paginated mail chains.
    """
    engine = get_engine()
    if engine is None:
        logger.warning(
            "Database not connected — returning empty mail chain list",
            extra={"correlation_id": correlation_id},
        )
        return MailChainListResponse(total=0, page=page, page_size=page_size, mail_chains=[])

    try:
        async with engine.connect() as conn:
            # Build WHERE clauses for filtering
            where_clauses = ["em.query_id = ce.query_id"]
            params: dict = {}

            if status:
                status_values = _status_filter_sql(status)
                where_clauses.append(f"ce.status IN {status_values}")

            if priority:
                priority_db_values = {
                    "High": "('critical', 'high')",
                    "Medium": "('medium')",
                    "Low": "('low')",
                }
                pv = priority_db_values.get(priority, "('medium')")
                where_clauses.append(
                    f"COALESCE((ce.routing_decision->>'urgency_level'), 'medium') IN {pv}"
                )

            if search:
                where_clauses.append(
                    "(em.subject ILIKE :search OR em.body_text ILIKE :search)"
                )
                params["search"] = f"%{search}%"

            where_sql = " AND ".join(where_clauses)
            sort_dir = "ASC" if sort_order.lower() == "asc" else "DESC"

            # Thread grouping key: use conversation_id if available,
            # otherwise fall back to query_id. This groups related
            # emails (original + replies) into the same chain.
            thread_key = "COALESCE(em.conversation_id, em.query_id)"

            # Count total distinct threads matching filters
            count_sql = f"""
                SELECT COUNT(DISTINCT {thread_key})
                FROM intake.email_messages em
                JOIN workflow.case_execution ce ON {where_sql}
            """
            count_result = await conn.execute(text(count_sql), params)
            total = count_result.scalar() or 0

            if total == 0:
                return MailChainListResponse(
                    total=0, page=page, page_size=page_size, mail_chains=[],
                )

            # Get distinct thread keys for this page, ordered by
            # the latest email timestamp in each thread
            offset = (page - 1) * page_size
            threads_sql = f"""
                SELECT {thread_key} AS thread_key,
                       MAX(em.received_at) AS latest_received
                FROM intake.email_messages em
                JOIN workflow.case_execution ce ON {where_sql}
                GROUP BY thread_key
                ORDER BY latest_received {sort_dir}
                LIMIT :limit OFFSET :offset
            """
            params["limit"] = page_size
            params["offset"] = offset
            thread_result = await conn.execute(text(threads_sql), params)
            thread_keys = [row.thread_key for row in thread_result]

            if not thread_keys:
                return MailChainListResponse(
                    total=total, page=page, page_size=page_size, mail_chains=[],
                )

            # Fetch all emails whose thread_key is in our page.
            # An email's thread_key = conversation_id if present, else query_id.
            tk_placeholders = ", ".join(f":tk_{i}" for i in range(len(thread_keys)))
            tk_params = {f"tk_{i}": tk for i, tk in enumerate(thread_keys)}

            emails_sql = f"""
                SELECT em.id, em.query_id, em.conversation_id, em.message_id,
                       em.sender_name, em.sender_email,
                       em.to_address, em.cc_addresses, em.recipients,
                       em.subject, em.body_text,
                       em.received_at,
                       {thread_key} AS thread_key,
                       ce.status AS case_status,
                       ce.routing_decision
                FROM intake.email_messages em
                JOIN workflow.case_execution ce ON em.query_id = ce.query_id
                WHERE {thread_key} IN ({tk_placeholders})
                ORDER BY em.received_at DESC
            """
            email_result = await conn.execute(text(emails_sql), tk_params)
            email_rows = email_result.fetchall()

            # Fetch attachments for all email IDs in one batch query
            email_db_ids = [row.id for row in email_rows]
            attachments_by_email: dict[int, list] = {}

            if email_db_ids:
                att_placeholders = ", ".join(f":eid_{i}" for i in range(len(email_db_ids)))
                eid_params = {f"eid_{i}": eid for i, eid in enumerate(email_db_ids)}

                att_sql = f"""
                    SELECT ea.id AS attachment_id, ea.email_id,
                           ea.filename, ea.content_type, ea.size_bytes, ea.s3_key
                    FROM intake.email_attachments ea
                    WHERE ea.email_id IN ({att_placeholders})
                """
                att_result = await conn.execute(text(att_sql), eid_params)
                for att_row in att_result:
                    attachments_by_email.setdefault(att_row.email_id, []).append(att_row)

            # Group emails by thread_key and build MailChainResponse objects
            chains_by_thread: dict[str, dict] = {}
            for row in email_rows:
                tk = row.thread_key

                if tk not in chains_by_thread:
                    routing = row.routing_decision or {}
                    raw_priority = (
                        routing.get("urgency_level")
                        if isinstance(routing, dict)
                        else None
                    )
                    chains_by_thread[tk] = {
                        "status": _map_status(row.case_status),
                        "priority": _map_priority(raw_priority),
                        "mail_items": [],
                    }

                # Build to/cc UserResponse lists from JSONB columns
                to_parsed = _parse_recipients_json(row.to_address)
                cc_parsed = _parse_recipients_json(row.cc_addresses)

                # Fallback: if to_address is empty, try recipients
                if not to_parsed:
                    to_parsed = _parse_recipients_json(row.recipients)

                to_users = _build_user_responses(to_parsed)
                cc_users = _build_user_responses(cc_parsed)

                # Build attachment list
                email_atts = attachments_by_email.get(row.id, [])
                att_responses = [
                    AttachmentResponse(
                        name=att.filename,
                        size=att.size_bytes or 0,
                        file_format=_file_format_from_filename(att.filename),
                        url=_build_attachment_url(att.s3_key),
                    )
                    for att in email_atts
                ]

                mail_item = MailItemResponse.model_validate({
                    "from": UserResponse(
                        name=row.sender_name or row.sender_email,
                        email=row.sender_email,
                    ),
                    "to": to_users,
                    "cc": cc_users,
                    "subject": row.subject or "",
                    "body": row.body_text or "",
                    "timestamp": _format_timestamp(row.received_at),
                    "attachments": att_responses,
                })

                chains_by_thread[tk]["mail_items"].append(mail_item)

            # Build final list preserving page order
            mail_chains = []
            for tk in thread_keys:
                if tk in chains_by_thread:
                    chain_data = chains_by_thread[tk]
                    mail_chains.append(
                        MailChainResponse(
                            mail_items=chain_data["mail_items"],
                            status=chain_data["status"],
                            priority=chain_data["priority"],
                        )
                    )

            return MailChainListResponse(
                total=total,
                page=page,
                page_size=page_size,
                mail_chains=mail_chains,
            )

    except Exception:
        logger.warning(
            "Failed to fetch mail chains — returning empty list",
            extra={"correlation_id": correlation_id},
            exc_info=True,
        )
        return MailChainListResponse(total=0, page=page, page_size=page_size, mail_chains=[])


async def fetch_single_mail_chain(
    query_id: str,
    *,
    correlation_id: str | None = None,
) -> MailChainResponse | None:
    """Fetch a single email chain by query_id.

    Finds the email for this query_id, then loads ALL emails
    that share the same conversation_id (the full thread).
    This includes the original email plus all replies, sorted
    newest first.

    If the email has no conversation_id, returns just that
    single email as the only item in the chain.

    NOTE: Status defaults to "New" and priority to "Medium"
    until Phase 3 (AI pipeline + routing) populates
    case_execution.status and routing_decision.

    Args:
        query_id: The VQMS query ID (e.g., "VQ-2026-0001").
        correlation_id: Tracing ID.

    Returns:
        MailChainResponse or None if not found.
    """
    engine = get_engine()
    if engine is None:
        logger.warning(
            "Database not connected — cannot fetch mail chain",
            extra={"query_id": query_id, "correlation_id": correlation_id},
        )
        return None

    try:
        async with engine.connect() as conn:
            # Fetch case_execution for status and priority
            case_sql = """
                SELECT status, routing_decision
                FROM workflow.case_execution
                WHERE query_id = :qid
            """
            case_result = await conn.execute(text(case_sql), {"qid": query_id})
            case_row = case_result.first()

            if case_row is None:
                return None

            routing = case_row.routing_decision or {}
            raw_priority = (
                routing.get("urgency_level") if isinstance(routing, dict) else None
            )
            chain_status = _map_status(case_row.status)
            chain_priority = _map_priority(raw_priority)

            # Step 1: Find the conversation_id for this query_id
            conv_sql = """
                SELECT conversation_id
                FROM intake.email_messages
                WHERE query_id = :qid
                LIMIT 1
            """
            conv_result = await conn.execute(text(conv_sql), {"qid": query_id})
            conv_row = conv_result.first()

            # Step 2: Fetch all emails in the thread
            # If conversation_id exists, get ALL emails with that
            # conversation_id (the full thread across multiple query_ids).
            # If no conversation_id, just get the email for this query_id.
            if conv_row and conv_row.conversation_id:
                emails_sql = """
                    SELECT em.id, em.message_id,
                           em.sender_name, em.sender_email,
                           em.to_address, em.cc_addresses, em.recipients,
                           em.subject, em.body_text,
                           em.received_at
                    FROM intake.email_messages em
                    WHERE em.conversation_id = :conv_id
                    ORDER BY em.received_at DESC
                """
                email_result = await conn.execute(
                    text(emails_sql),
                    {"conv_id": conv_row.conversation_id},
                )
            else:
                emails_sql = """
                    SELECT em.id, em.message_id,
                           em.sender_name, em.sender_email,
                           em.to_address, em.cc_addresses, em.recipients,
                           em.subject, em.body_text,
                           em.received_at
                    FROM intake.email_messages em
                    WHERE em.query_id = :qid
                    ORDER BY em.received_at DESC
                """
                email_result = await conn.execute(text(emails_sql), {"qid": query_id})

            email_rows = email_result.fetchall()

            if not email_rows:
                # Case exists in workflow but no email record (portal query)
                return MailChainResponse(
                    mail_items=[],
                    status=chain_status,
                    priority=chain_priority,
                )

            # Fetch attachments
            email_db_ids = [row.id for row in email_rows]
            att_placeholders = ", ".join(f":eid_{i}" for i in range(len(email_db_ids)))
            eid_params = {f"eid_{i}": eid for i, eid in enumerate(email_db_ids)}

            att_sql = f"""
                SELECT ea.id AS attachment_id, ea.email_id,
                       ea.filename, ea.content_type, ea.size_bytes, ea.s3_key
                FROM intake.email_attachments ea
                WHERE ea.email_id IN ({att_placeholders})
            """
            att_result = await conn.execute(text(att_sql), eid_params)
            attachments_by_email: dict[int, list] = {}
            for att_row in att_result:
                attachments_by_email.setdefault(att_row.email_id, []).append(att_row)

            # Build MailItemResponse for each email
            mail_items = []
            for row in email_rows:
                to_parsed = _parse_recipients_json(row.to_address)
                cc_parsed = _parse_recipients_json(row.cc_addresses)
                if not to_parsed:
                    to_parsed = _parse_recipients_json(row.recipients)

                email_atts = attachments_by_email.get(row.id, [])
                att_responses = [
                    AttachmentResponse(
                        name=att.filename,
                        size=att.size_bytes or 0,
                        file_format=_file_format_from_filename(att.filename),
                        url=_build_attachment_url(att.s3_key),
                    )
                    for att in email_atts
                ]

                mail_item = MailItemResponse.model_validate({
                    "from": UserResponse(
                        name=row.sender_name or row.sender_email,
                        email=row.sender_email,
                    ),
                    "to": _build_user_responses(to_parsed),
                    "cc": _build_user_responses(cc_parsed),
                    "subject": row.subject or "",
                    "body": row.body_text or "",
                    "timestamp": _format_timestamp(row.received_at),
                    "attachments": att_responses,
                })
                mail_items.append(mail_item)

            return MailChainResponse(
                mail_items=mail_items,
                status=chain_status,
                priority=chain_priority,
            )

    except Exception:
        logger.warning(
            "Failed to fetch mail chain",
            extra={"query_id": query_id, "correlation_id": correlation_id},
            exc_info=True,
        )
        return None


async def fetch_email_stats(
    *,
    correlation_id: str | None = None,
) -> EmailStatsResponse:
    """Aggregate email statistics for the dashboard summary.

    Counts are based on email-sourced queries in workflow.case_execution
    (source = 'email'). Status and priority are mapped to dashboard
    display values.

    Args:
        correlation_id: Tracing ID.

    Returns:
        EmailStatsResponse with counts and breakdowns.
    """
    engine = get_engine()
    if engine is None:
        logger.warning(
            "Database not connected — returning zero stats",
            extra={"correlation_id": correlation_id},
        )
        return EmailStatsResponse(
            total_emails=0,
            new_count=0,
            reopened_count=0,
            resolved_count=0,
            priority_breakdown={"High": 0, "Medium": 0, "Low": 0},
            today_count=0,
            this_week_count=0,
        )

    try:
        now_utc = datetime.now(timezone.utc)
        today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=7)

        async with engine.connect() as conn:
            # Total email-sourced queries
            total_result = await conn.execute(
                text(
                    "SELECT COUNT(*) FROM workflow.case_execution "
                    "WHERE source = 'email'"
                ),
            )
            total = total_result.scalar() or 0

            # Count by status category
            # "New" = all active statuses
            new_statuses = (
                "'new', 'analyzing', 'routing', 'drafting', 'validating', "
                "'sending', 'awaiting_human_review', 'awaiting_team_resolution', "
                "'failed', 'draft_rejected'"
            )
            new_result = await conn.execute(
                text(
                    f"SELECT COUNT(*) FROM workflow.case_execution "
                    f"WHERE source = 'email' AND status IN ({new_statuses})"
                ),
            )
            new_count = new_result.scalar() or 0

            reopened_result = await conn.execute(
                text(
                    "SELECT COUNT(*) FROM workflow.case_execution "
                    "WHERE source = 'email' AND status = 'reopened'"
                ),
            )
            reopened_count = reopened_result.scalar() or 0

            resolved_result = await conn.execute(
                text(
                    "SELECT COUNT(*) FROM workflow.case_execution "
                    "WHERE source = 'email' AND status IN ('resolved', 'closed')"
                ),
            )
            resolved_count = resolved_result.scalar() or 0

            # Priority breakdown from routing_decision JSONB
            # Most emails won't have routing_decision yet (Phase 3+),
            # so we default unrouted queries to "Medium"
            priority_sql = """
                SELECT
                    COALESCE(routing_decision->>'urgency_level', 'medium') AS urgency,
                    COUNT(*) AS cnt
                FROM workflow.case_execution
                WHERE source = 'email'
                GROUP BY urgency
            """
            priority_result = await conn.execute(text(priority_sql))
            priority_breakdown = {"High": 0, "Medium": 0, "Low": 0}
            for row in priority_result:
                display_priority = _map_priority(row.urgency)
                priority_breakdown[display_priority] = (
                    priority_breakdown.get(display_priority, 0) + row.cnt
                )

            # Today count
            today_result = await conn.execute(
                text(
                    "SELECT COUNT(*) FROM workflow.case_execution "
                    "WHERE source = 'email' AND created_at >= :today"
                ),
                {"today": today_start},
            )
            today_count = today_result.scalar() or 0

            # This week count
            week_result = await conn.execute(
                text(
                    "SELECT COUNT(*) FROM workflow.case_execution "
                    "WHERE source = 'email' AND created_at >= :week_start"
                ),
                {"week_start": week_start},
            )
            this_week_count = week_result.scalar() or 0

        return EmailStatsResponse(
            total_emails=total,
            new_count=new_count,
            reopened_count=reopened_count,
            resolved_count=resolved_count,
            priority_breakdown=priority_breakdown,
            today_count=today_count,
            this_week_count=this_week_count,
        )

    except Exception:
        logger.warning(
            "Failed to fetch email stats — returning zeros",
            extra={"correlation_id": correlation_id},
            exc_info=True,
        )
        return EmailStatsResponse(
            total_emails=0,
            new_count=0,
            reopened_count=0,
            resolved_count=0,
            priority_breakdown={"High": 0, "Medium": 0, "Low": 0},
            today_count=0,
            this_week_count=0,
        )


async def generate_attachment_download_url(
    query_id: str,
    attachment_id: int,
    *,
    correlation_id: str | None = None,
) -> AttachmentDownloadResponse | None:
    """Generate a presigned S3 URL for downloading an attachment.

    Looks up the attachment in intake.email_attachments, verifies
    it belongs to the given query_id, and generates a 1-hour
    presigned URL.

    Args:
        query_id: VQMS query ID for ownership verification.
        attachment_id: Database ID of the attachment.
        correlation_id: Tracing ID.

    Returns:
        AttachmentDownloadResponse with presigned URL, or None if
        the attachment is not found or doesn't belong to this query.
    """
    engine = get_engine()
    if engine is None:
        logger.warning(
            "Database not connected — cannot generate download URL",
            extra={
                "query_id": query_id,
                "attachment_id": attachment_id,
                "correlation_id": correlation_id,
            },
        )
        return None

    try:
        async with engine.connect() as conn:
            # Verify attachment belongs to this query
            att_sql = """
                SELECT ea.s3_key, ea.filename
                FROM intake.email_attachments ea
                JOIN intake.email_messages em ON ea.email_id = em.id
                WHERE ea.id = :att_id AND em.query_id = :qid
            """
            result = await conn.execute(
                text(att_sql),
                {"att_id": attachment_id, "qid": query_id},
            )
            row = result.first()

        if row is None or not row.s3_key:
            return None

        # Generate presigned URL
        import boto3

        settings = get_settings()
        s3_client = boto3.client("s3", region_name=settings.aws_region)

        presigned_url = s3_client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": settings.s3_bucket_attachments,
                "Key": row.s3_key,
                "ResponseContentDisposition": f'attachment; filename="{row.filename}"',
            },
            ExpiresIn=3600,  # 1 hour
        )

        logger.info(
            "Generated presigned download URL",
            extra={
                "query_id": query_id,
                "attachment_id": attachment_id,
                "s3_key": row.s3_key,
                "correlation_id": correlation_id,
            },
        )

        return AttachmentDownloadResponse(download_url=presigned_url)

    except Exception:
        logger.warning(
            "Failed to generate attachment download URL",
            extra={
                "query_id": query_id,
                "attachment_id": attachment_id,
                "correlation_id": correlation_id,
            },
            exc_info=True,
        )
        return None
