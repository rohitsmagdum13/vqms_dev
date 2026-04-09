# ruff: noqa: E402
"""Run the VQMS Email Intake Pipeline -- end-to-end (Phase 2).

This script exercises the REAL pipeline with REAL cloud services:
  - Microsoft Graph API (fetch latest email from shared mailbox)
  - Redis (idempotency check)
  - Salesforce stub (vendor resolution)
  - AWS S3 (store raw email)
  - PostgreSQL via SSH tunnel or direct connection (CaseExecution write)
  - AWS EventBridge (publish EmailIngested event)
  - AWS SQS (enqueue UnifiedQueryPayload)

Optionally fetch a specific email by resource path:
  --resource "messages/AAMk..."

Usage:
  uv run python scripts/run_email_intake.py
  uv run python scripts/run_email_intake.py --resource "messages/AAMk..."

Prerequisites:
  1. Copy .env.copy to .env and fill in real values
  2. Graph API credentials configured (GRAPH_API_TENANT_ID, CLIENT_ID, etc.)
  3. AWS credentials configured (S3, SQS, EventBridge access)
  4. Redis running (local or cloud)
  5. PostgreSQL reachable (SSH tunnel to RDS or direct connection)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time

# ---------------------------------------------------------------------------
# Bootstrap -- must happen before project imports
# ---------------------------------------------------------------------------
sys.path.insert(0, ".")

from dotenv import load_dotenv

load_dotenv(override=True)

# ---------------------------------------------------------------------------
# All imports -- stdlib, third-party, project
# ---------------------------------------------------------------------------
import boto3

from config.settings import get_settings
from src.adapters.graph_api import (
    _get_access_token,
    fetch_email_by_resource,
    fetch_latest_email,
)
from src.cache.redis_client import (
    close_redis,
    get_value,
    idempotency_key,
    init_redis,
    set_with_ttl,
)
from src.db.connection import (
    close_db,
    get_engine,
    init_db,
    start_ssh_tunnel,
    stop_ssh_tunnel,
)
from src.events.eventbridge import publish_event
from src.models.query import QuerySource, UnifiedQueryPayload
from src.models.workflow import Status
from src.queues.sqs import consume, get_queue_size, publish
from src.services.email_intake import (
    _determine_thread_status,
    _serialize_email_for_storage,
    _store_email_record,
    _upload_attachments_to_s3,
)
from src.services.vendor_resolution import resolve_vendor
from src.storage.s3_client import upload_file
from src.utils.correlation import (
    generate_correlation_id,
    generate_execution_id,
    generate_query_id,
)
from src.utils.helpers import utc_now
from src.utils.logger import setup_logging

# ---------------------------------------------------------------------------
# Logging -- console + file (data/logs/email_intake_YYYY-MM-DD.log)
# ---------------------------------------------------------------------------

setup_logging(
    log_level="INFO",
    log_to_file=True,
    log_filename=None,  # auto-generates vqms_YYYY-MM-DD.log
)
logger = logging.getLogger("run_email_intake")

# Quiet down noisy libraries
logging.getLogger("botocore").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("msal").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def print_banner():
    """Print a visual banner for the pipeline run."""
    print("\n" + "=" * 70)
    print("  VQMS Email Intake Pipeline -- Phase 2 End-to-End Run")
    print("=" * 70)


def print_step(step_num: int | str, title: str):
    """Print a step header."""
    print(f"\n{'-' * 60}")
    print(f"  Step {step_num}: {title}")
    print(f"{'-' * 60}")


def print_result(label: str, value: str, indent: int = 4):
    """Print a key-value result line."""
    print(f"{' ' * indent}{label}: {value}")


# ---------------------------------------------------------------------------
# Pre-flight service connectivity checks
# ---------------------------------------------------------------------------

async def check_prerequisites(settings) -> dict[str, bool]:
    """Check which services are reachable before running the pipeline."""
    checks: dict[str, bool] = {}

    print_step(0, "Pre-flight -- Checking service connectivity")

    # --- Graph API (required -- we always fetch real email) ---
    if settings.graph_api_tenant_id and settings.graph_api_client_id:
        try:
            _get_access_token()
            checks["graph_api"] = True
            print_result("Graph API", "[OK] MSAL token acquired")
        except Exception as e:
            checks["graph_api"] = False
            print_result("Graph API", f"[FAIL] Auth failed ({e})")
    else:
        checks["graph_api"] = False
        print_result("Graph API", "[FAIL] Not configured (GRAPH_API_TENANT_ID, GRAPH_API_CLIENT_ID)")

    # --- Redis ---
    try:
        await init_redis(
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_password,
            db=settings.redis_db,
            ssl=settings.redis_ssl,
        )
        checks["redis"] = True
        print_result("Redis", f"[OK] Connected ({settings.redis_host}:{settings.redis_port})")
    except Exception as e:
        checks["redis"] = False
        print_result("Redis", f"[FAIL] Not available ({e})")

    # --- S3 (raw email bucket) ---
    try:
        s3 = boto3.client("s3", region_name=settings.aws_region)
        s3.head_bucket(Bucket=settings.s3_bucket_email_raw)
        checks["s3"] = True
        print_result("S3 (raw)", f"[OK] Bucket '{settings.s3_bucket_email_raw}' accessible")
    except Exception as e:
        checks["s3"] = False
        print_result("S3 (raw)", f"[FAIL] Bucket not accessible ({e})")

    # --- S3 (attachments bucket) ---
    try:
        s3.head_bucket(Bucket=settings.s3_bucket_attachments)
        checks["s3_attachments"] = True
        print_result("S3 (att)", f"[OK] Bucket '{settings.s3_bucket_attachments}' accessible")
    except Exception as e:
        checks["s3_attachments"] = False
        print_result("S3 (att)", f"[WARN] Bucket not accessible ({e}) -- attachments will skip")

    # --- SQS ---
    try:
        sqs = boto3.client("sqs", region_name=settings.aws_region)
        sqs.get_queue_url(QueueName=settings.sqs_email_intake_queue)
        checks["sqs"] = True
        print_result("SQS", f"[OK] Queue '{settings.sqs_email_intake_queue}' found")
    except Exception as e:
        checks["sqs"] = False
        print_result("SQS", f"[FAIL] Queue not accessible ({e})")

    # --- EventBridge ---
    try:
        eb = boto3.client("events", region_name=settings.aws_region)
        eb.describe_event_bus(Name=settings.eventbridge_bus_name)
        checks["eventbridge"] = True
        print_result("EventBridge", f"[OK] Bus '{settings.eventbridge_bus_name}' found")
    except Exception as e:
        checks["eventbridge"] = False
        print_result("EventBridge", f"[FAIL] Bus not accessible ({e})")

    # --- PostgreSQL ---
    # Strategy: try SSH tunnel first, then fall back to direct connection.
    # This covers both office (bastion->RDS) and local dev (direct postgres).
    checks["postgres"] = False

    # Option 1: SSH tunnel to bastion -> RDS
    if settings.ssh_host and settings.ssh_private_key_path:
        try:
            local_host, local_port = start_ssh_tunnel(
                ssh_host=settings.ssh_host,
                ssh_port=settings.ssh_port,
                ssh_username=settings.ssh_username,
                ssh_private_key_path=settings.ssh_private_key_path,
                rds_host=settings.rds_host,
                rds_port=settings.rds_port,
            )
            tunnel_db_url = (
                f"postgresql+asyncpg://{settings.postgres_user}:"
                f"{settings.postgres_password}@{local_host}:{local_port}"
                f"/{settings.postgres_db}"
            )
            await init_db(
                database_url=tunnel_db_url,
                pool_min=settings.postgres_pool_min,
                pool_max=settings.postgres_pool_max,
            )
            checks["postgres"] = True
            print_result(
                "PostgreSQL",
                f"[OK] Connected via SSH tunnel ({local_host}:{local_port})",
            )
        except Exception as e:
            print_result("PostgreSQL", f"[FAIL] SSH tunnel failed ({e})")

    # Option 2: Direct connection via DATABASE_URL or postgres_* settings
    if not checks["postgres"]:
        db_url = settings.database_url
        if not db_url:
            db_url = (
                f"postgresql+asyncpg://{settings.postgres_user}:"
                f"{settings.postgres_password}@{settings.postgres_host}:"
                f"{settings.postgres_port}/{settings.postgres_db}"
            )
        try:
            await init_db(
                database_url=db_url,
                pool_min=settings.postgres_pool_min,
                pool_max=settings.postgres_pool_max,
            )
            checks["postgres"] = True
            print_result(
                "PostgreSQL",
                f"[OK] Connected directly ({settings.postgres_host}:{settings.postgres_port})",
            )
        except Exception as e:
            print_result("PostgreSQL", f"[FAIL] Direct connection failed ({e})")

    if not checks["postgres"]:
        print_result("", "[ERROR] PostgreSQL is not reachable via SSH tunnel or direct connection")

    return checks


# ---------------------------------------------------------------------------
# Main pipeline runner
# ---------------------------------------------------------------------------

async def run_pipeline(*, resource: str | None):
    """Run the full email intake pipeline.

    Fetches the latest email from the shared mailbox via Graph API
    (or a specific email if --resource is provided), then runs every
    step of the real intake pipeline with detailed console output.
    """
    settings = get_settings()
    print_banner()

    print_result("Mailbox", settings.graph_api_mailbox, indent=2)
    print_result("AWS Region", settings.aws_region, indent=2)
    print_result("S3 Bucket", settings.s3_bucket_email_raw, indent=2)
    print_result("SQS Queue", settings.sqs_email_intake_queue, indent=2)
    print_result("EventBridge Bus", settings.eventbridge_bus_name, indent=2)

    # --- Pre-flight checks ---
    checks = await check_prerequisites(settings)

    # Abort if any critical service is not reachable
    if not checks.get("graph_api"):
        print("\n[ERROR] ABORT: Graph API is not available. Cannot fetch email.")
        print("    Configure GRAPH_API_TENANT_ID, GRAPH_API_CLIENT_ID,")
        print("    GRAPH_API_CLIENT_SECRET, and GRAPH_API_MAILBOX in .env")
        return
    if not checks.get("s3"):
        print("\n[ERROR] ABORT: S3 is not accessible. Cannot store raw email.")
        return
    if not checks.get("sqs"):
        print("\n[ERROR] ABORT: SQS is not accessible. Cannot enqueue payload.")
        return
    if not checks.get("postgres"):
        print("\n[ERROR] ABORT: PostgreSQL is not reachable. Cannot write CaseExecution.")
        print("    Check your SSH tunnel config (SSH_HOST, SSH_PRIVATE_KEY_PATH)")
        print("    or direct DB config (DATABASE_URL or POSTGRES_HOST/PORT/USER/PASSWORD)")
        return

    pipeline_start = time.time()

    # =====================================================================
    # STEP 1: Fetch email from shared mailbox via Graph API
    # =====================================================================
    print_step(1, "Fetch email from shared mailbox (Graph API)")

    if resource:
        print(f"    Fetching specific email: {resource}")
        email = await fetch_email_by_resource(resource)
    else:
        print(f"    Fetching latest email from {settings.graph_api_mailbox}...")
        email = await fetch_latest_email()

    if email is None:
        print("  [ERROR] Mailbox is empty -- no emails found.")
        print("    Send an email to your shared mailbox and try again.")
        return

    print_result("From", f"{email.sender_name} <{email.sender_email}>")
    print_result("To", ", ".join(email.to_addresses) if email.to_addresses else "N/A")
    print_result("CC", ", ".join(email.cc_addresses) if email.cc_addresses else "None")
    print_result("Subject", email.subject)
    print_result("Message-ID", email.message_id)
    print_result("Received", str(email.received_at))
    print_result("Attachments", str(len(email.attachments)))
    print_result("Auto-reply", str(email.is_auto_reply))
    if email.body_preview:
        print_result("Preview", email.body_preview[:100] + "..." if len(email.body_preview) > 100 else email.body_preview)

    # =====================================================================
    # STEP 2: Idempotency check (Redis)
    # =====================================================================
    print_step(2, "Idempotency check (Redis)")

    is_duplicate = False
    if checks.get("redis"):
        key, ttl = idempotency_key(f"email:{email.message_id}")
        existing = await get_value(key)
        if existing is not None:
            is_duplicate = True
            print_result("Result", f"[DUPLICATE] key '{key}' already exists")
            print_result("", "In production this would raise DuplicateQueryError")
        else:
            await set_with_ttl(key, "1", ttl)
            print_result("Result", f"[OK] New email -- idempotency key set (TTL: {ttl}s)")
            print_result("Key", key)
    else:
        print_result("Result", "[WARN] Redis unavailable, skipping idempotency check")

    # =====================================================================
    # STEP 3: Vendor resolution (Salesforce)
    # =====================================================================
    print_step(3, "Vendor resolution (Salesforce)")

    vendor_match = await resolve_vendor(
        sender_email=email.sender_email,
        sender_name=email.sender_name or "",
        body_text=email.body_text or "",
    )

    if vendor_match:
        print_result("Vendor", f"{vendor_match.vendor_name} ({vendor_match.vendor_id})")
        print_result("Tier", vendor_match.vendor_tier.value)
        print_result("Match method", vendor_match.match_method)
        print_result("Confidence", str(vendor_match.match_confidence))
        vendor_id = vendor_match.vendor_id
        vendor_name = vendor_match.vendor_name
    else:
        print_result("Vendor", "UNRESOLVED -- no match found in Salesforce")
        vendor_id = "UNRESOLVED"
        vendor_name = "Unknown Vendor"

    # =====================================================================
    # STEP 4: Thread correlation
    # =====================================================================
    print_step(4, "Thread correlation")

    thread_status = _determine_thread_status(email)

    print_result("in_reply_to", str(email.in_reply_to or "None"))
    print_result("references", str(email.references or "[]"))
    print_result("conversation_id", str(email.conversation_id or "None"))
    print_result("Thread status", thread_status)

    # =====================================================================
    # STEP 5a: Upload attachments to S3
    # =====================================================================
    print_step(5, "Upload attachments to S3")

    if email.attachments:
        await _upload_attachments_to_s3(email=email)
        for att in email.attachments:
            if att.s3_key:
                print_result("Uploaded", f"{att.filename} -> s3://{settings.s3_bucket_attachments}/{att.s3_key}")
                print_result("  Size", f"{att.size_bytes} bytes")
            else:
                print_result("Skipped", f"{att.filename} (no content bytes)")
    else:
        print_result("Result", "No attachments to upload")

    # =====================================================================
    # STEP 5b: Store detailed email JSON in S3
    # =====================================================================
    print_step("5b", "Store detailed email JSON in S3")

    raw_content = _serialize_email_for_storage(
        email,
        vendor_id=vendor_id,
        thread_status=thread_status,
    )
    s3_key = f"emails/{email.message_id}.json"

    s3_uri = await upload_file(
        bucket=settings.s3_bucket_email_raw,
        key=s3_key,
        content=raw_content,
    )
    print_result("Bucket", settings.s3_bucket_email_raw)
    print_result("Key", s3_key)
    print_result("URI", s3_uri)
    print_result("Size", f"{len(raw_content)} bytes")

    # =====================================================================
    # STEP 6: Generate tracking IDs
    # =====================================================================
    print_step(6, "Generate tracking IDs")

    correlation_id = generate_correlation_id()
    execution_id = generate_execution_id()
    query_id = generate_query_id()

    print_result("query_id", query_id)
    print_result("execution_id", execution_id)
    print_result("correlation_id", correlation_id)

    # =====================================================================
    # STEP 7: Store email record in PostgreSQL (intake schema)
    # =====================================================================
    print_step(7, "Store email record in PostgreSQL (intake)")

    await _store_email_record(
        email=email,
        s3_key=s3_key,
        correlation_id=correlation_id,
        query_id=query_id,
        execution_id=execution_id,
        vendor_id=vendor_id,
        thread_status=thread_status,
    )

    engine = get_engine()
    if engine is not None:
        print_result("Result", "[OK] Email record written to intake.email_messages")
        print_result("Vendor ID", vendor_id)
        print_result("Thread Status", thread_status)
        if email.attachments:
            print_result("Attachments", f"{len(email.attachments)} written to intake.email_attachments")
    else:
        print_result("Result", "[FAIL] Engine is None -- email record not written")

    # =====================================================================
    # STEP 8: Build UnifiedQueryPayload
    # =====================================================================
    print_step(8, "Build UnifiedQueryPayload")

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
        received_at=email.received_at or utc_now(),
    )

    print_result("Source", payload.source.value)
    print_result("Vendor", f"{payload.vendor_name} ({payload.vendor_id})")
    print_result("Subject", payload.subject)
    print_result("Thread", payload.thread_status)
    print_result("Payload valid", "[OK] Pydantic validation passed")

    # =====================================================================
    # STEP 9: Store CaseExecution in PostgreSQL (workflow schema)
    # =====================================================================
    print_step(9, "Store CaseExecution in PostgreSQL (workflow)")

    # Calls the REAL _store_case_execution from email_intake.py which
    # does: Pydantic validation -> INSERT INTO workflow.case_execution
    # with ON CONFLICT DO NOTHING for idempotency.
    # The engine was initialized in pre-flight (SSH tunnel or direct).
    #
    # _store_case_execution catches exceptions internally and logs
    # warnings. To detect success/failure here, we do our own INSERT
    # and let any exception propagate so we can report it clearly.
    from sqlalchemy import text

    engine = get_engine()
    db_write_ok = False
    if engine is not None:
        try:
            from src.models.workflow import CaseExecution

            case = CaseExecution(
                execution_id=execution_id,
                query_id=query_id,
                correlation_id=correlation_id,
                status=Status.NEW,
                source=QuerySource.EMAIL,
                vendor_id=vendor_id,
            )
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
            db_write_ok = True
            print_result("Result", "[OK] CaseExecution record written to PostgreSQL")
            print_result("Table", "workflow.case_execution")
        except Exception as e:
            print_result("Result", f"[FAIL] DB write failed: {e}")
            print_result("", "Hint: Run migrations first: uv run python scripts/run_migrations.py")
    else:
        print_result("Result", "[ERROR] Engine is None -- record was NOT written")

    print_result("execution_id", execution_id)
    print_result("status", Status.NEW.value)
    print_result("source", QuerySource.EMAIL.value)

    # =====================================================================
    # STEP 10: Publish EmailIngested event (EventBridge)
    # =====================================================================
    print_step(10, "Publish EmailIngested event (EventBridge)")

    event_id = await publish_event(
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
    print_result("Event bus", settings.eventbridge_bus_name)
    print_result("Detail type", "EmailIngested")
    print_result("Event ID", event_id)

    # =====================================================================
    # STEP 11: Enqueue to SQS
    # =====================================================================
    print_step(11, "Enqueue payload to SQS")

    payload_json = payload.model_dump(mode="json")
    payload_str = json.dumps(payload_json)

    message_id = await publish(
        queue_name=settings.sqs_email_intake_queue,
        message=payload_json,
        correlation_id=correlation_id,
    )
    print_result("Queue", settings.sqs_email_intake_queue)
    print_result("SQS Message ID", message_id)
    print_result("Payload size", f"{len(payload_str)} chars")

    # =====================================================================
    # STEP 12: Verify -- read back from SQS
    # =====================================================================
    print_step(12, "Verify -- read back from SQS")

    queue_size = get_queue_size(settings.sqs_email_intake_queue)
    print_result("Queue depth", f"~{queue_size} messages")

    sqs_message = await consume(settings.sqs_email_intake_queue, wait_time_seconds=1)
    if sqs_message:
        # consume() already parses JSON -- returns a dict directly
        print_result("Read back", "[OK] Message retrieved from SQS")
        print_result("query_id", sqs_message.get("query_id", "?"))
        print_result("vendor_id", sqs_message.get("vendor_id", "?"))
        print_result("source", sqs_message.get("source", "?"))
        print_result("thread_status", sqs_message.get("thread_status", "?"))

        # Validate it parses back into UnifiedQueryPayload
        UnifiedQueryPayload(**sqs_message)
        print_result("Re-parse", "[OK] Valid UnifiedQueryPayload")
    else:
        print_result("Read back", "[WARN] No message received (may need longer wait)")

    # =====================================================================
    # Summary
    # =====================================================================
    elapsed = time.time() - pipeline_start

    print("\n" + "=" * 70)
    print("  PIPELINE COMPLETE")
    print("=" * 70)
    print_result("Query ID", query_id, indent=2)
    print_result("Execution ID", execution_id, indent=2)
    print_result("Correlation ID", correlation_id, indent=2)
    print_result("Vendor", f"{vendor_name} ({vendor_id})", indent=2)
    print_result("Thread", thread_status, indent=2)
    print_result("Duplicate", "Yes" if is_duplicate else "No", indent=2)
    print_result("S3", s3_uri, indent=2)
    print_result("PostgreSQL", "[OK] Written" if db_write_ok else "[FAIL] Not written", indent=2)
    print_result("SQS", f"Enqueued to {settings.sqs_email_intake_queue}", indent=2)
    print_result("Time", f"{elapsed:.2f}s", indent=2)
    print()

    print("  What happens next (Phase 3+):")
    print("    -> SQS consumer picks up message")
    print("    -> LangGraph Orchestrator loads context (Step 7)")
    print("    -> Query Analysis Agent classifies intent (Step 8)")
    print("    -> Routing + KB Search (Step 9)")
    print("    -> Path A (AI-resolved) / Path B (human team) / Path C (low confidence)")
    print()

    # --- Cleanup ---
    if checks.get("redis"):
        await close_redis()
    await close_db()
    stop_ssh_tunnel()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    """Parse CLI args and run the email intake pipeline."""
    parser = argparse.ArgumentParser(
        description="Run the VQMS Email Intake Pipeline end-to-end (Phase 2)",
    )
    parser.add_argument(
        "--resource",
        type=str,
        default=None,
        help="Fetch a specific email by Graph API resource path "
             "(e.g., 'messages/AAMk...'). If omitted, fetches the latest email.",
    )
    args = parser.parse_args()

    asyncio.run(run_pipeline(resource=args.resource))


if __name__ == "__main__":
    main()
