"""Email Intake Service for VQMS.

Handles incoming email notifications from Microsoft Graph API.
Fetches the email, checks for duplicates, resolves the vendor,
performs thread correlation, stores the raw email, and queues
the parsed payload for the AI pipeline.

Corresponds to Steps E1-E2 in the VQMS Solution Flow Document.

The email path differs from portal in several ways:
  - Vendor is resolved from sender email (may be UNRESOLVED)
  - Thread correlation checks in_reply_to/references/conversation_id
  - Raw email is stored in S3 for compliance
  - message_id is used for idempotency (not subject+vendor)
"""

from __future__ import annotations

import logging

from config.settings import get_settings
from src.adapters.graph_api import fetch_email_by_resource
from src.cache.pg_cache import get_value, idempotency_key, set_with_ttl
from src.events.eventbridge import publish_event
from src.models.query import QuerySource, UnifiedQueryPayload
from src.models.workflow import CaseExecution, Status
from src.queues.sqs import publish
from src.services.vendor_resolution import resolve_vendor
from src.storage.s3_client import upload_file
from src.utils.correlation import (
    generate_correlation_id,
    generate_execution_id,
    generate_query_id,
)
from src.utils.exceptions import DuplicateQueryError
from src.utils.helpers import ist_now

logger = logging.getLogger(__name__)


async def process_email_notification(
    resource: str,
    *,
    correlation_id: str | None = None,
) -> dict:
    """Process an incoming email notification end-to-end.

    This is the main entry point for email-submitted queries.
    It performs the full email intake pipeline:
      1. Generate correlation_id
      2. Fetch email via Graph API adapter
      3. Idempotency check on message_id via PostgreSQL cache
      4. Vendor resolution via Salesforce adapter
      5. Thread correlation (NEW vs EXISTING_OPEN vs REPLY_TO_CLOSED)
      6. Store raw email in S3
      7. Generate tracking IDs
      8. Build UnifiedQueryPayload
      9. Store CaseExecution in PostgreSQL (graceful)
      10. Publish EmailIngested event
      11. Enqueue to vqms-email-intake-queue via SQS

    Args:
        resource: Graph API resource path (e.g., "messages/AAMk...").
        correlation_id: Optional pre-generated correlation ID.

    Returns:
        Dict with query_id, execution_id, correlation_id, status,
        vendor_id, thread_status.

    Raises:
        DuplicateQueryError: If this email was already processed
            (message_id found in PostgreSQL cache idempotency store).
    """
    correlation_id = correlation_id or generate_correlation_id()
    settings = get_settings()

    logger.info(
        "Processing email notification",
        extra={
            "resource": resource,
            "correlation_id": correlation_id,
        },
    )

    # --- Step 1: Fetch email via Graph API ---
    email = await fetch_email_by_resource(
        resource, correlation_id=correlation_id
    )

    # --- Step 2: Idempotency check on message_id ---
    await _check_email_idempotency(
        email.message_id, correlation_id=correlation_id
    )

    # --- Step 3: Vendor resolution ---
    # None means UNRESOLVED — acceptable for email path.
    # The orchestrator handles unresolved vendors.
    vendor_match = await resolve_vendor(
        sender_email=email.sender_email,
        sender_name=email.sender_name or "",
        body_text=email.body_text or "",
        correlation_id=correlation_id,
    )

    vendor_id = vendor_match.vendor_id if vendor_match else "UNRESOLVED"
    vendor_name = vendor_match.vendor_name if vendor_match else "Unknown Vendor"

    # --- Step 4: Thread correlation ---
    thread_status = _determine_thread_status(email)

    # --- Step 4b: Upload attachments to S3 ---
    await _upload_attachments_to_s3(
        email=email,
        correlation_id=correlation_id,
    )

    # --- Step 5: Store raw email in S3 ---
    raw_email_content = _serialize_email_for_storage(
        email,
        vendor_id=vendor_id,
        thread_status=thread_status,
    )
    s3_key = f"emails/{email.message_id}.json"
    await upload_file(
        bucket=settings.s3_bucket_email_raw,
        key=s3_key,
        content=raw_email_content,
        correlation_id=correlation_id,
    )

    # --- Step 6: Generate tracking IDs ---
    execution_id = generate_execution_id()
    query_id = generate_query_id()

    # --- Step 6b: Store email metadata in PostgreSQL ---
    await _store_email_record(
        email=email,
        s3_key=s3_key,
        correlation_id=correlation_id,
        query_id=query_id,
        execution_id=execution_id,
        vendor_id=vendor_id,
        thread_status=thread_status,
    )

    # --- Step 7: Build UnifiedQueryPayload ---
    payload = UnifiedQueryPayload(
        query_id=query_id,
        execution_id=execution_id,
        correlation_id=correlation_id,
        source=QuerySource.EMAIL,
        vendor_id=vendor_id,
        vendor_name=vendor_name,
        subject=email.subject,
        description=email.body_text or "",
        query_type=None,
        priority=None,
        reference_number=None,
        thread_status=thread_status,
        message_id=email.message_id,
        received_at=email.received_at or ist_now(),
    )

    # --- Step 8: Store CaseExecution (graceful) ---
    await _store_case_execution(
        execution_id=execution_id,
        query_id=query_id,
        correlation_id=correlation_id,
        vendor_id=vendor_id,
        source=QuerySource.EMAIL,
    )

    # --- Step 9: Publish EmailIngested event ---
    await publish_event(
        detail_type="EmailIngested",
        detail={
            "query_id": query_id,
            "execution_id": execution_id,
            "source": "EMAIL",
            "vendor_id": vendor_id,
            "message_id": email.message_id,
            "subject": email.subject,
            "thread_status": thread_status,
            "sender_email": email.sender_email,
        },
        correlation_id=correlation_id,
    )

    # --- Step 10: Enqueue for AI pipeline ---
    await publish(
        queue_name=settings.sqs_email_intake_queue,
        message=payload.model_dump(mode="json"),
        correlation_id=correlation_id,
    )

    logger.info(
        "Email intake completed",
        extra={
            "query_id": query_id,
            "execution_id": execution_id,
            "vendor_id": vendor_id,
            "thread_status": thread_status,
            "correlation_id": correlation_id,
        },
    )

    return {
        "query_id": query_id,
        "execution_id": execution_id,
        "correlation_id": correlation_id,
        "vendor_id": vendor_id,
        "thread_status": thread_status,
        "status": "accepted",
    }


async def _check_email_idempotency(
    message_id: str,
    *,
    correlation_id: str | None = None,
) -> None:
    """Check PostgreSQL cache for duplicate email processing.

    Uses the email message_id as the idempotency key. Exchange Online
    can redeliver emails up to 5 days after the original send in
    recovery mode, so we use a 7-day TTL.
    """
    key, ttl = idempotency_key(f"email:{message_id}")

    try:
        existing = await get_value(key)
        if existing is not None:
            logger.info(
                "Duplicate email detected",
                extra={
                    "message_id": message_id,
                    "correlation_id": correlation_id,
                },
            )
            raise DuplicateQueryError(message_id)

        await set_with_ttl(key, "1", ttl)
    except DuplicateQueryError:
        raise
    except Exception:
        # Cache unavailable — log and continue
        logger.warning(
            "Cache unavailable for email idempotency check",
            extra={
                "message_id": message_id,
                "correlation_id": correlation_id,
            },
        )


def _determine_thread_status(email) -> str:
    """Determine if this email is a new thread or part of an existing one.

    Thread correlation logic:
      - If in_reply_to or references are present → EXISTING_OPEN
        (this is a reply to an existing conversation)
      - If conversation_id is present but no in_reply_to → EXISTING_OPEN
        (Exchange groups related emails by conversation_id)
      - Otherwise → NEW (this is a brand new query)

    NOTE: REPLY_TO_CLOSED detection requires checking if the referenced
    ticket is closed in ServiceNow. This is deferred to Phase 6
    (closure/reopen logic). For now, replies are marked EXISTING_OPEN.
    """
    if email.in_reply_to or email.references:
        return "EXISTING_OPEN"

    if email.conversation_id:
        # conversation_id alone suggests Exchange grouped this email
        # with others, but it could be the first in the conversation.
        # For Phase 2, we treat it as NEW unless there are explicit
        # reply headers. Phase 6 will refine this logic.
        return "NEW"

    return "NEW"


def _serialize_email_for_storage(
    email,
    *,
    vendor_id: str = "UNRESOLVED",
    thread_status: str = "NEW",
) -> bytes:
    """Serialize email to detailed JSON bytes for S3 storage.

    Stores the full email data as a detailed JSON document for
    compliance, debugging, and downstream analytics. Includes
    all fields that are available at intake time.

    Fields like query_type, invoice_ref, po_ref, contract_ref,
    and amount are NULL at intake time — they get populated by
    the Query Analysis Agent in Phase 3.
    """
    import json

    body_text = email.body_text or ""

    # Extract basic references from body text using simple regex
    # These are best-effort at intake time; the Query Analysis Agent
    # will do a thorough extraction in Phase 3
    invoice_ref = _extract_reference(body_text, r"(?:invoice|inv)[#:\s-]*(\S+)", "INV")
    po_ref = _extract_reference(body_text, r"(?:PO|purchase\s*order)[#:\s-]*(\S+)", "PO")
    contract_ref = _extract_reference(body_text, r"(?:contract|agreement)[#:\s-]*(\S+)", "CON")
    amount = _extract_amount(body_text)

    # Determine if this is a reply based on threading headers
    is_reply = bool(email.in_reply_to or email.references)

    email_dict = {
        # Identity
        "email_id": email.message_id,
        "message_id": email.message_id,

        # Sender / recipients
        "from_address": email.sender_email,
        "from_name": email.sender_name,
        "to_address": email.to_addresses if hasattr(email, "to_addresses") else [],
        "cc_addresses": email.cc_addresses if hasattr(email, "cc_addresses") else [],
        "to_recipients_detailed": getattr(email, "to_recipients_detailed", []),
        "cc_recipients_detailed": getattr(email, "cc_recipients_detailed", []),

        # Content
        "subject": email.subject,
        "body_text": body_text,
        "body_html": email.body_html,
        "body_preview": (email.body_preview or body_text[:200]) if body_text else None,

        # Attachments
        "has_attachments": len(email.attachments or []) > 0,
        "attachment_count": len(email.attachments or []),
        "attachments": [
            {
                "filename": att.filename,
                "content_type": att.content_type,
                "size_bytes": att.size_bytes,
                "s3_key": att.s3_key,
            }
            for att in (email.attachments or [])
        ],

        # Timestamps
        "received_at": email.received_at.isoformat() if email.received_at else None,

        # Threading
        "thread_id": email.conversation_id,
        "conversation_id": email.conversation_id,
        "in_reply_to": email.in_reply_to,
        "references": email.references,
        "is_reply": is_reply,

        # Auto-reply detection
        "is_auto_reply": email.is_auto_reply if hasattr(email, "is_auto_reply") else False,

        # Language — detected by Comprehend in Phase 3, NULL at intake
        "language": email.language if hasattr(email, "language") else None,

        # Pipeline status
        "status": "NEW",

        # Vendor — resolved in Step 3 of pipeline
        "vendor_id": vendor_id,

        # Query analysis — populated by Query Analysis Agent (Phase 3)
        # Best-effort regex extraction at intake time
        "query_type": None,
        "invoice_ref": invoice_ref,
        "po_ref": po_ref,
        "contract_ref": contract_ref,
        "amount": amount,
    }
    return json.dumps(email_dict, indent=2, default=str).encode("utf-8")


def _extract_reference(text: str, pattern: str, prefix: str) -> str | None:
    """Extract a reference number from email body using regex.

    Best-effort extraction at intake time. The Query Analysis Agent
    does a thorough extraction in Phase 3 using LLM.
    """
    import re

    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        return match.group(1).strip(".,;:")
    return None


def _extract_amount(text: str) -> float | None:
    """Extract a monetary amount from email body using regex.

    Looks for patterns like $1,234.56 or USD 1234.56.
    Best-effort at intake time.
    """
    import re

    # Match common currency patterns: $1,234.56 or USD 1,234.56
    match = re.search(
        r"(?:\$|USD\s*|INR\s*|EUR\s*|GBP\s*)([\d,]+\.?\d*)", text, re.IGNORECASE
    )
    if match:
        try:
            return float(match.group(1).replace(",", ""))
        except ValueError:
            return None
    return None


async def _upload_attachments_to_s3(
    email,
    *,
    correlation_id: str | None = None,
) -> None:
    """Upload attachment content to the vqms-email-attachments-prod S3 bucket.

    For each attachment that has content_bytes, uploads to S3 and sets
    the s3_key on the attachment object. Attachments without content
    (metadata-only) are skipped.

    S3 key pattern: attachments/<message_id>/<filename>
    """
    settings = get_settings()

    for att in email.attachments or []:
        if att.content_bytes is None:
            logger.info(
                "Skipping attachment without content",
                extra={
                    "attachment_name": att.filename,
                    "correlation_id": correlation_id,
                },
            )
            continue

        # Build S3 key: attachments/<message_id>/<filename>
        # Sanitize message_id to be S3-key-safe
        safe_message_id = email.message_id.replace("<", "").replace(">", "")
        s3_key = f"attachments/{safe_message_id}/{att.filename}"

        try:
            await upload_file(
                bucket=settings.s3_bucket_attachments,
                key=s3_key,
                content=att.content_bytes,
                correlation_id=correlation_id,
            )
            # Set the s3_key on the attachment so it gets saved to DB
            att.s3_key = s3_key

            logger.info(
                "Attachment uploaded to S3",
                extra={
                    "attachment_name": att.filename,
                    "s3_key": s3_key,
                    "size_bytes": att.size_bytes,
                    "correlation_id": correlation_id,
                },
            )
        except Exception:
            logger.warning(
                "Failed to upload attachment to S3 — continuing",
                extra={
                    "attachment_name": att.filename,
                    "correlation_id": correlation_id,
                },
                exc_info=True,
            )


async def _store_email_record(
    *,
    email,
    s3_key: str,
    correlation_id: str,
    query_id: str,
    execution_id: str,
    vendor_id: str = "UNRESOLVED",
    thread_status: str = "NEW",
) -> None:
    """Insert email metadata into intake.email_messages and attachments.

    Stores all parsed email fields in PostgreSQL so we have a
    queryable record of every email that entered the system.
    The raw email body is in S3; this table holds metadata + references.

    Graceful on failure — if DB is unavailable, the pipeline
    continues. The S3 copy is the compliance record of truth.
    """
    import json

    from sqlalchemy import text

    from src.db.connection import get_engine

    engine = get_engine()
    if engine is None:
        logger.warning(
            "Database not available — email record skipped",
            extra={
                "message_id": email.message_id,
                "correlation_id": correlation_id,
            },
        )
        return

    body_text = email.body_text or ""

    # Best-effort reference extraction at intake time
    invoice_ref = _extract_reference(body_text, r"(?:invoice|inv)[#:\s-]*(\S+)", "INV")
    po_ref = _extract_reference(body_text, r"(?:PO|purchase\s*order)[#:\s-]*(\S+)", "PO")
    contract_ref = _extract_reference(body_text, r"(?:contract|agreement)[#:\s-]*(\S+)", "CON")
    amount = _extract_amount(body_text)

    is_reply = bool(email.in_reply_to or email.references)
    has_attachments = len(email.attachments or []) > 0
    attachment_count = len(email.attachments or [])
    body_preview = (email.body_preview or body_text[:200]) if body_text else None
    is_auto_reply = email.is_auto_reply if hasattr(email, "is_auto_reply") else False
    language = email.language if hasattr(email, "language") else None

    # Serialize to/cc as JSON arrays of {name, email} objects.
    # Prefer the detailed recipients (with display names) captured
    # from Graph API. Fall back to plain email strings if the
    # detailed fields are empty (backward compat with older data).
    to_detailed = getattr(email, "to_recipients_detailed", [])
    cc_detailed = getattr(email, "cc_recipients_detailed", [])

    if to_detailed:
        to_address_json = json.dumps(to_detailed)
    else:
        # Fallback: wrap plain strings as {name: email, email: email}
        to_address_json = json.dumps(
            [{"name": e, "email": e} for e in (email.to_addresses or [])]
        )

    if cc_detailed:
        cc_address_json = json.dumps(cc_detailed)
    else:
        cc_address_json = json.dumps(
            [{"name": e, "email": e} for e in (email.cc_addresses or [])]
        )
    recipients_json = json.dumps(
        email.recipients if email.recipients else []
    )

    try:
        async with engine.begin() as conn:
            # Insert into intake.email_messages with all detail columns
            result = await conn.execute(
                text("""
                    INSERT INTO intake.email_messages
                        (message_id, conversation_id, in_reply_to,
                         sender_email, sender_name, recipients,
                         to_address, cc_addresses,
                         subject, body_text, body_html, body_preview,
                         has_attachments, attachment_count,
                         raw_s3_key, received_at,
                         thread_id, is_reply, is_auto_reply, language,
                         status, vendor_id,
                         query_type, invoice_ref, po_ref, contract_ref, amount,
                         correlation_id, query_id, execution_id)
                    VALUES
                        (:message_id, :conversation_id, :in_reply_to,
                         :sender_email, :sender_name, :recipients,
                         :to_address, :cc_addresses,
                         :subject, :body_text, :body_html, :body_preview,
                         :has_attachments, :attachment_count,
                         :raw_s3_key, :received_at,
                         :thread_id, :is_reply, :is_auto_reply, :language,
                         :status, :vendor_id,
                         :query_type, :invoice_ref, :po_ref, :contract_ref, :amount,
                         :correlation_id, :query_id, :execution_id)
                    ON CONFLICT (message_id) DO NOTHING
                    RETURNING id
                """),
                {
                    "message_id": email.message_id,
                    "conversation_id": email.conversation_id,
                    "in_reply_to": email.in_reply_to,
                    "sender_email": email.sender_email,
                    "sender_name": email.sender_name,
                    "recipients": recipients_json,
                    "to_address": to_address_json,
                    "cc_addresses": cc_address_json,
                    "subject": email.subject,
                    "body_text": body_text,
                    "body_html": email.body_html,
                    "body_preview": body_preview,
                    "has_attachments": has_attachments,
                    "attachment_count": attachment_count,
                    "raw_s3_key": s3_key,
                    "received_at": email.received_at,
                    "thread_id": email.conversation_id,
                    "is_reply": is_reply,
                    "is_auto_reply": is_auto_reply,
                    "language": language,
                    "status": "NEW",
                    "vendor_id": vendor_id,
                    "query_type": None,
                    "invoice_ref": invoice_ref,
                    "po_ref": po_ref,
                    "contract_ref": contract_ref,
                    "amount": amount,
                    "correlation_id": correlation_id,
                    "query_id": query_id,
                    "execution_id": execution_id,
                },
            )

            row = result.fetchone()
            if row is None:
                # ON CONFLICT — duplicate message_id, already stored
                logger.info(
                    "Email record already exists (duplicate message_id)",
                    extra={"message_id": email.message_id},
                )
                return

            email_db_id = row[0]

            # Insert attachments if any
            for att in email.attachments or []:
                await conn.execute(
                    text("""
                        INSERT INTO intake.email_attachments
                            (email_id, filename, content_type, size_bytes, s3_key)
                        VALUES
                            (:email_id, :filename, :content_type, :size_bytes, :s3_key)
                    """),
                    {
                        "email_id": email_db_id,
                        "filename": att.filename,
                        "content_type": att.content_type,
                        "size_bytes": att.size_bytes,
                        "s3_key": att.s3_key,
                    },
                )

        logger.info(
            "Email record saved to PostgreSQL",
            extra={
                "message_id": email.message_id,
                "attachments_count": attachment_count,
                "vendor_id": vendor_id,
                "correlation_id": correlation_id,
            },
        )
    except Exception:
        logger.warning(
            "Failed to save email record to PostgreSQL — continuing",
            extra={
                "message_id": email.message_id,
                "correlation_id": correlation_id,
            },
            exc_info=True,
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
