# ruff: noqa: E402
"""VQMS End-to-End Email Pipeline: Fetch Email → Query Analysis Agent.

This script runs the COMPLETE email pipeline in a single process:

  Step E1:  Fetch email from shared mailbox (MS Graph API)
  Step E2a: Idempotency check (Redis)
  Step E2b: Vendor resolution (Salesforce 3-step fallback)
  Step E2c: Thread correlation (NEW / EXISTING_OPEN)
  Step E2d: Store raw email + attachments in S3
  Step E2e: Store email metadata in PostgreSQL
  Step E2f: Store CaseExecution in PostgreSQL
  Step E2g: Publish EmailIngested event (EventBridge)
  Step 7:   Context loading (vendor profile, history, budget)
  Step 8:   Query Analysis Agent (LLM call → intent, entities, confidence)
  Step 8.5: Confidence check (≥0.85 → pass, <0.85 → Path C)
  Step 9A:  Routing (deterministic rules → team, SLA)
  Step 9B:  KB Search (embed → pgvector cosine similarity)
  Step 9.5: Path decision (KB match ≥80% → Path A, else → Path B)

The script runs the LangGraph pipeline DIRECTLY (no SQS hop),
so you can see the full flow from email fetch to path decision
in a single terminal.

Usage:
  uv run python scripts/run_email_to_analysis.py
  uv run python scripts/run_email_to_analysis.py --resource "messages/AAMk..."

Prerequisites:
  1. .env configured with Graph API, AWS, Redis, PostgreSQL credentials
  2. Pipeline is NOT required to be running separately
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time

# ---------------------------------------------------------------------------
# Bootstrap — must happen before project imports
# ---------------------------------------------------------------------------
sys.path.insert(0, ".")

from dotenv import load_dotenv

load_dotenv(override=True)

# ---------------------------------------------------------------------------
# Project imports
# ---------------------------------------------------------------------------
from config.settings import get_settings
from src.adapters.graph_api import (
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
    init_db,
    start_ssh_tunnel,
    stop_ssh_tunnel,
)
from src.events.eventbridge import publish_event
from src.models.query import QuerySource, UnifiedQueryPayload
from src.orchestration.graph import PipelineState, build_pipeline_graph
from src.services.email_intake import (
    _determine_thread_status,
    _serialize_email_for_storage,
    _store_case_execution,
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
# Logging
# ---------------------------------------------------------------------------
setup_logging(log_level="INFO", log_to_file=True)
logger = logging.getLogger("run_email_to_analysis")

# Silence noisy third-party loggers
for noisy in ("botocore", "urllib3", "msal", "httpx", "httpcore", "openai._base_client"):
    logging.getLogger(noisy).setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

DIVIDER = "=" * 70
SUBDIV = "-" * 60


def banner(text: str) -> None:
    """Print a section banner."""
    print(f"\n{DIVIDER}")
    print(f"  {text}")
    print(DIVIDER)


def step(num: str, title: str) -> None:
    """Print a step header."""
    print(f"\n{SUBDIV}")
    print(f"  Step {num}: {title}")
    print(SUBDIV)


def result(label: str, value: str, indent: int = 4) -> None:
    """Print a key-value result line."""
    print(f"{' ' * indent}{label}: {value}")


# ---------------------------------------------------------------------------
# Infrastructure bootstrap
# ---------------------------------------------------------------------------

async def bootstrap_infra() -> dict[str, bool]:
    """Connect to all required services. Returns connectivity status."""
    settings = get_settings()
    status: dict[str, bool] = {}

    step("0", "Connecting to infrastructure")

    # --- PostgreSQL via SSH tunnel ---
    try:
        if settings.ssh_host and settings.ssh_private_key_path:
            local_host, local_port = start_ssh_tunnel(
                ssh_host=settings.ssh_host,
                ssh_port=settings.ssh_port,
                ssh_username=settings.ssh_username,
                ssh_private_key_path=settings.ssh_private_key_path,
                rds_host=settings.rds_host,
                rds_port=settings.rds_port,
            )
            db_url = (
                f"postgresql+asyncpg://{settings.postgres_user}:"
                f"{settings.postgres_password}@{local_host}:{local_port}"
                f"/{settings.postgres_db}"
            )
        else:
            db_url = settings.database_url

        await init_db(database_url=db_url, pool_min=2, pool_max=5)
        status["postgres"] = True
        result("PostgreSQL", "[OK]")
    except Exception as e:
        status["postgres"] = False
        result("PostgreSQL", f"[FAIL] {e}")

    # --- Redis ---
    try:
        await init_redis(
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_password,
            db=settings.redis_db,
            ssl=settings.redis_ssl,
        )
        status["redis"] = True
        result("Redis", "[OK]")
    except Exception as e:
        status["redis"] = False
        result("Redis", f"[FAIL] {e}")

    return status


async def teardown_infra() -> None:
    """Close all infrastructure connections."""
    try:
        await close_redis()
    except Exception:
        pass
    try:
        await close_db()
    except Exception:
        pass
    stop_ssh_tunnel()


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

async def run_full_email_pipeline(*, resource: str | None) -> None:
    """Run the entire email-to-analysis pipeline in a single process.

    Fetches an email from the shared mailbox, runs the full intake
    pipeline (Steps E1-E2), then feeds the result directly into
    the LangGraph AI pipeline (Steps 7-9) without an SQS hop.
    """
    settings = get_settings()
    pipeline_start = time.time()

    banner("VQMS Email → Query Analysis Pipeline")
    result("Mailbox", settings.graph_api_mailbox, indent=2)
    result("AWS Region", settings.aws_region, indent=2)

    # =====================================================================
    # Step 0: Bootstrap infrastructure
    # =====================================================================
    infra = await bootstrap_infra()

    # =====================================================================
    # Step E1: Fetch email from shared mailbox via Graph API
    # =====================================================================
    step("E1", "Fetch email from shared mailbox (Graph API)")

    try:
        if resource:
            print(f"    Fetching specific email: {resource}")
            email = await fetch_email_by_resource(resource)
        else:
            print(f"    Fetching latest email from {settings.graph_api_mailbox}...")
            email = await fetch_latest_email()
    except Exception as e:
        print(f"\n  [ERROR] Failed to fetch email: {e}")
        print("    Check GRAPH_API_TENANT_ID, CLIENT_ID, CLIENT_SECRET, MAILBOX in .env")
        await teardown_infra()
        return

    if email is None:
        print("  [ERROR] Mailbox is empty — no emails found.")
        print("    Send an email to your shared mailbox and try again.")
        await teardown_infra()
        return

    result("From", f"{email.sender_name} <{email.sender_email}>")
    result("Subject", email.subject)
    result("Message-ID", email.message_id[:60] + "...")
    result("Received", str(email.received_at))
    result("Attachments", str(len(email.attachments or [])))
    body_preview = (email.body_text or "")[:150].replace("\n", " ")
    result("Body preview", body_preview + "..." if len(body_preview) == 150 else body_preview)

    # =====================================================================
    # Step E2a: Idempotency check (Redis)
    # =====================================================================
    step("E2a", "Idempotency check (Redis)")

    if infra.get("redis"):
        key, ttl = idempotency_key(f"email:{email.message_id}")
        existing = await get_value(key)
        if existing is not None:
            result("Result", "[DUPLICATE] Already processed — clearing for re-run")
            # For testing, we clear the key so the pipeline can re-run
            from src.cache.redis_client import get_redis_client
            redis = get_redis_client()
            if redis:
                await redis.delete(key)
                result("Action", "Idempotency key cleared for testing")
        await set_with_ttl(key, "1", ttl)
        result("Key", key)
        result("TTL", f"{ttl}s (7 days)")
    else:
        result("Result", "[SKIP] Redis unavailable")

    # =====================================================================
    # Step E2b: Vendor resolution (Salesforce)
    # =====================================================================
    step("E2b", "Vendor resolution (Salesforce)")

    correlation_id = generate_correlation_id()

    vendor_match = await resolve_vendor(
        sender_email=email.sender_email,
        sender_name=email.sender_name or "",
        body_text=email.body_text or "",
        correlation_id=correlation_id,
    )

    if vendor_match:
        vendor_id = vendor_match.vendor_id
        vendor_name = vendor_match.vendor_name
        result("Vendor", f"{vendor_name} ({vendor_id})")
        result("Tier", vendor_match.vendor_tier.value)
        result("Match method", vendor_match.match_method)
        result("Confidence", str(vendor_match.match_confidence))
    else:
        vendor_id = "UNRESOLVED"
        vendor_name = "Unknown Vendor"
        result("Vendor", "UNRESOLVED — no match found in Salesforce")

    # =====================================================================
    # Step E2c: Thread correlation
    # =====================================================================
    step("E2c", "Thread correlation")

    thread_status = _determine_thread_status(email)
    result("in_reply_to", str(email.in_reply_to or "None"))
    result("references", str(email.references or "[]"))
    result("conversation_id", str(email.conversation_id or "None")[:60])
    result("Thread status", thread_status)

    # =====================================================================
    # Step E2d: Store raw email + attachments in S3
    # =====================================================================
    step("E2d", "Store raw email + attachments in S3")

    # Upload attachments
    if email.attachments:
        await _upload_attachments_to_s3(email=email, correlation_id=correlation_id)
        for att in email.attachments:
            status_str = f"s3://{settings.s3_bucket_attachments}/{att.s3_key}" if att.s3_key else "skipped"
            result("Attachment", f"{att.filename} → {status_str}")
    else:
        result("Attachments", "None")

    # Upload raw email JSON
    raw_content = _serialize_email_for_storage(email, vendor_id=vendor_id, thread_status=thread_status)
    s3_key = f"emails/{email.message_id}.json"
    s3_uri = await upload_file(
        bucket=settings.s3_bucket_email_raw,
        key=s3_key,
        content=raw_content,
        correlation_id=correlation_id,
    )
    result("Raw email", f"{s3_uri} ({len(raw_content)} bytes)")

    # =====================================================================
    # Step E2e: Generate tracking IDs
    # =====================================================================
    execution_id = generate_execution_id()
    query_id = generate_query_id()

    step("E2e", "Generate tracking IDs")
    result("query_id", query_id)
    result("execution_id", execution_id)
    result("correlation_id", correlation_id)

    # =====================================================================
    # Step E2f: Store email record + CaseExecution in PostgreSQL
    # =====================================================================
    step("E2f", "Store records in PostgreSQL")

    await _store_email_record(
        email=email,
        s3_key=s3_key,
        correlation_id=correlation_id,
        query_id=query_id,
        execution_id=execution_id,
        vendor_id=vendor_id,
        thread_status=thread_status,
    )
    result("Email record", "intake.email_messages")

    await _store_case_execution(
        execution_id=execution_id,
        query_id=query_id,
        correlation_id=correlation_id,
        vendor_id=vendor_id,
        source=QuerySource.EMAIL,
    )
    result("CaseExecution", "workflow.case_execution")

    # =====================================================================
    # Step E2g: Publish EmailIngested event
    # =====================================================================
    step("E2g", "Publish EmailIngested event (EventBridge)")

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
    result("Event ID", event_id)
    result("Detail type", "EmailIngested")

    email_intake_elapsed = time.time() - pipeline_start

    banner(f"Email Intake Complete — {email_intake_elapsed:.1f}s")
    print("    Now running AI pipeline (Steps 7 → 8 → 9 → Path Decision)...")

    # =====================================================================
    # BUILD UNIFIED PAYLOAD — same format as portal path
    # =====================================================================
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

    # =====================================================================
    # RUN LANGGRAPH PIPELINE DIRECTLY (Steps 7 → 8 → 9 → Path A/B/C)
    # =====================================================================
    step("7-9", "LangGraph AI Pipeline (context → analysis → routing → path)")

    graph = build_pipeline_graph()

    initial_state: PipelineState = {
        "payload": payload.model_dump(mode="json"),
        "correlation_id": correlation_id,
        "execution_id": execution_id,
        "query_id": query_id,
        "vendor_profile": None,
        "vendor_history": [],
        "budget": {},
        "analysis_result": None,
        "routing_decision": None,
        "kb_search_response": None,
        "selected_path": None,
        "error": None,
    }

    ai_start = time.time()

    try:
        pipeline_result = await graph.ainvoke(initial_state)
    except Exception as e:
        print(f"\n  [ERROR] Pipeline failed: {e}")
        logger.error("Pipeline failed", exc_info=True)
        await teardown_infra()
        return

    ai_elapsed = time.time() - ai_start
    total_elapsed = time.time() - pipeline_start

    # =====================================================================
    # RESULTS
    # =====================================================================
    banner("PIPELINE RESULTS")

    # Analysis result
    analysis = pipeline_result.get("analysis_result")
    if analysis:
        result("Intent", analysis.get("intent_classification", "?"), indent=2)
        result("Confidence", str(analysis.get("confidence_score", "?")), indent=2)
        result("Urgency", analysis.get("urgency_level", "?"), indent=2)
        result("Sentiment", analysis.get("sentiment", "?"), indent=2)
        result("Multi-issue", str(analysis.get("multi_issue_detected", False)), indent=2)
        result("Category", analysis.get("suggested_category", "?"), indent=2)

        entities = analysis.get("extracted_entities", {})
        if entities:
            for key, vals in entities.items():
                if vals:
                    result(f"  {key}", str(vals), indent=2)

        result("Provider", analysis.get("provider", "?"), indent=2)
        result("Was fallback", str(analysis.get("was_fallback", False)), indent=2)
    else:
        result("Analysis", "[ERROR] No analysis result", indent=2)

    # Routing decision
    routing = pipeline_result.get("routing_decision")
    if routing:
        result("Team", routing.get("assigned_team", "?"), indent=2)
        result("SLA", f"{routing.get('sla_hours', '?')}h", indent=2)
        result("Automation blocked", str(routing.get("automation_blocked", False)), indent=2)
    else:
        result("Routing", "[SKIP] Not reached", indent=2)

    # KB search
    kb = pipeline_result.get("kb_search_response")
    if kb:
        kb_results = kb.get("results", [])
        result("KB results", str(len(kb_results)), indent=2)
        result("Top score", str(kb.get("top_score", 0.0)), indent=2)
        for i, r in enumerate(kb_results[:3]):
            result(f"  #{i+1}", f"{r.get('source_document', '?')} (sim={r.get('similarity', 0):.2f})", indent=2)
    else:
        result("KB search", "[SKIP] Not reached", indent=2)

    # Path decision
    selected_path = pipeline_result.get("selected_path", "?")
    path_labels = {
        "A": "Path A — AI-Resolved (KB has the answer)",
        "B": "Path B — Human-Team-Resolved (KB lacks specific facts)",
        "C": "Path C — Low-Confidence (human reviewer validates)",
    }
    result("Selected path", path_labels.get(selected_path, f"Path {selected_path}"), indent=2)

    # Error
    error = pipeline_result.get("error")
    if error:
        result("Error", error, indent=2)

    # Timing
    print(f"\n{SUBDIV}")
    result("Email intake", f"{email_intake_elapsed:.1f}s", indent=2)
    result("AI pipeline", f"{ai_elapsed:.1f}s", indent=2)
    result("Total", f"{total_elapsed:.1f}s", indent=2)
    print()

    # --- Cleanup ---
    await teardown_infra()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    """Parse CLI args and run the full email-to-analysis pipeline."""
    parser = argparse.ArgumentParser(
        description="VQMS: Fetch email → run full AI pipeline (Steps E1-E2, 7-9)",
    )
    parser.add_argument(
        "--resource",
        type=str,
        default=None,
        help="Fetch a specific email by Graph API resource path. "
             "If omitted, fetches the latest email from the mailbox.",
    )
    args = parser.parse_args()

    asyncio.run(run_full_email_pipeline(resource=args.resource))


if __name__ == "__main__":
    main()
