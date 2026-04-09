"""Seed script — inserts realistic test emails into PostgreSQL.

Creates sample email chains so you can test the email dashboard
API endpoints without needing real emails from Graph API.

Usage:
    uv run python scripts/seed_email_dashboard.py

    # To clear seeded data first:
    uv run python scripts/seed_email_dashboard.py --clear

Prerequisites:
    - Server does NOT need to be running
    - PostgreSQL must be reachable (via SSH tunnel if configured)
    - Migrations 001 + 002 + 006 must have been run

After seeding, start the server and test:
    uv run uvicorn main:app --reload --port 8000

    curl http://localhost:8000/emails
    curl http://localhost:8000/emails/stats
    curl http://localhost:8000/emails/VQ-2026-9001
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

# Load .env BEFORE any project imports so boto3/settings pick up credentials
load_dotenv(override=True)

from config.settings import get_settings  # noqa: E402
from src.db.connection import (  # noqa: E402
    close_db,
    get_engine,
    init_db,
    start_ssh_tunnel,
    stop_ssh_tunnel,
)

# --- Test Data ---

# Two conversations: one with 3 emails (a thread), one with 1 email
SEED_EMAILS = [
    # --- Conversation 1: Invoice thread (3 emails) ---
    {
        "message_id": "<seed-msg-001@test.vqms>",
        "conversation_id": "CONV-SEED-001",
        "in_reply_to": None,
        "sender_email": "rajesh.mehta@technova.com",
        "sender_name": "Rajesh Mehta",
        "recipients": json.dumps(["vendor-support@company.com"]),
        "to_address": json.dumps([
            {"name": "Vendor Support", "email": "vendor-support@company.com"},
        ]),
        "cc_addresses": json.dumps([
            {"name": "Priya Sharma", "email": "priya@technova.com"},
        ]),
        "subject": "Payment Status Inquiry - Invoice #INV-2026-0451",
        "body_text": (
            "Dear Support Team,\n\n"
            "We are writing regarding the payment status of invoice #INV-2026-0451 "
            "dated March 15, 2026 for $45,000. The payment was due on March 30 "
            "and we have not received it yet.\n\n"
            "Could you please provide an update on when we can expect payment?\n\n"
            "Best regards,\nRajesh Mehta\nTechNova Solutions"
        ),
        "body_html": None,
        "body_preview": "Dear Support Team, We are writing regarding the payment status...",
        "raw_s3_key": "emails/seed-msg-001.json",
        "received_at": datetime(2026, 4, 7, 10, 30, 0, tzinfo=timezone.utc),
        "has_attachments": True,
        "attachment_count": 1,
        "thread_id": "CONV-SEED-001",
        "is_reply": False,
        "is_auto_reply": False,
        "language": "en",
        "status": "NEW",
        "vendor_id": "SF-TECHNOVA-001",
        "query_type": None,
        "invoice_ref": "INV-2026-0451",
        "po_ref": None,
        "contract_ref": None,
        "amount": 45000.00,
        "correlation_id": "corr-seed-001",
        "query_id": "VQ-2026-9001",
        "execution_id": "exec-seed-001",
    },
    {
        "message_id": "<seed-msg-002@test.vqms>",
        "conversation_id": "CONV-SEED-001",
        "in_reply_to": "<seed-msg-001@test.vqms>",
        "sender_email": "vendor-support@company.com",
        "sender_name": "Vendor Support",
        "recipients": json.dumps(["rajesh.mehta@technova.com"]),
        "to_address": json.dumps([
            {"name": "Rajesh Mehta", "email": "rajesh.mehta@technova.com"},
        ]),
        "cc_addresses": json.dumps([
            {"name": "Priya Sharma", "email": "priya@technova.com"},
        ]),
        "subject": "Re: Payment Status Inquiry - Invoice #INV-2026-0451",
        "body_text": (
            "Hi Rajesh,\n\n"
            "Thank you for reaching out. We have checked our records and "
            "invoice #INV-2026-0451 is currently in the approval queue. "
            "Payment is expected to be processed by April 10, 2026.\n\n"
            "Your ticket number is INC0054321.\n\n"
            "Best regards,\nVendor Support Team"
        ),
        "body_html": None,
        "body_preview": "Hi Rajesh, Thank you for reaching out. We have checked...",
        "raw_s3_key": "emails/seed-msg-002.json",
        "received_at": datetime(2026, 4, 7, 14, 15, 0, tzinfo=timezone.utc),
        "has_attachments": False,
        "attachment_count": 0,
        "thread_id": "CONV-SEED-001",
        "is_reply": True,
        "is_auto_reply": False,
        "language": "en",
        "status": "NEW",
        "vendor_id": "SF-TECHNOVA-001",
        "query_type": None,
        "invoice_ref": "INV-2026-0451",
        "po_ref": None,
        "contract_ref": None,
        "amount": None,
        "correlation_id": "corr-seed-002",
        "query_id": "VQ-2026-9002",
        "execution_id": "exec-seed-002",
    },
    {
        "message_id": "<seed-msg-003@test.vqms>",
        "conversation_id": "CONV-SEED-001",
        "in_reply_to": "<seed-msg-002@test.vqms>",
        "sender_email": "rajesh.mehta@technova.com",
        "sender_name": "Rajesh Mehta",
        "recipients": json.dumps(["vendor-support@company.com"]),
        "to_address": json.dumps([
            {"name": "Vendor Support", "email": "vendor-support@company.com"},
        ]),
        "cc_addresses": json.dumps([]),
        "subject": "Re: Payment Status Inquiry - Invoice #INV-2026-0451",
        "body_text": (
            "Thank you for the update. We will wait until April 10.\n\n"
            "Regards,\nRajesh"
        ),
        "body_html": None,
        "body_preview": "Thank you for the update. We will wait until April 10.",
        "raw_s3_key": "emails/seed-msg-003.json",
        "received_at": datetime(2026, 4, 7, 15, 0, 0, tzinfo=timezone.utc),
        "has_attachments": False,
        "attachment_count": 0,
        "thread_id": "CONV-SEED-001",
        "is_reply": True,
        "is_auto_reply": False,
        "language": "en",
        "status": "NEW",
        "vendor_id": "SF-TECHNOVA-001",
        "query_type": None,
        "invoice_ref": None,
        "po_ref": None,
        "contract_ref": None,
        "amount": None,
        "correlation_id": "corr-seed-003",
        "query_id": "VQ-2026-9003",
        "execution_id": "exec-seed-003",
    },

    # --- Conversation 2: Shipping question (1 email, with attachment) ---
    {
        "message_id": "<seed-msg-004@test.vqms>",
        "conversation_id": "CONV-SEED-002",
        "in_reply_to": None,
        "sender_email": "lisa.chen@globalparts.com",
        "sender_name": "Lisa Chen",
        "recipients": json.dumps(["vendor-support@company.com"]),
        "to_address": json.dumps([
            {"name": "Vendor Support", "email": "vendor-support@company.com"},
        ]),
        "cc_addresses": json.dumps([
            {"name": "Mike Ross", "email": "mike.ross@globalparts.com"},
            {"name": "Finance Team", "email": "finance@globalparts.com"},
        ]),
        "subject": "PO-2026-78432 Shipment Delay - Urgent",
        "body_text": (
            "Hi,\n\n"
            "Our purchase order PO-2026-78432 was supposed to ship on April 1 "
            "but we have not received tracking information. This is holding up "
            "our production line.\n\n"
            "Attached is a copy of the PO for reference. Please advise ASAP.\n\n"
            "Lisa Chen\nGlobal Parts Inc."
        ),
        "body_html": None,
        "body_preview": "Hi, Our purchase order PO-2026-78432 was supposed to ship...",
        "raw_s3_key": "emails/seed-msg-004.json",
        "received_at": datetime(2026, 4, 8, 8, 45, 0, tzinfo=timezone.utc),
        "has_attachments": True,
        "attachment_count": 2,
        "thread_id": "CONV-SEED-002",
        "is_reply": False,
        "is_auto_reply": False,
        "language": "en",
        "status": "NEW",
        "vendor_id": "SF-GLOBALPARTS-002",
        "query_type": None,
        "invoice_ref": None,
        "po_ref": "PO-2026-78432",
        "contract_ref": None,
        "amount": None,
        "correlation_id": "corr-seed-004",
        "query_id": "VQ-2026-9004",
        "execution_id": "exec-seed-004",
    },

    # --- Conversation 3: Contract question (standalone, no attachments) ---
    {
        "message_id": "<seed-msg-005@test.vqms>",
        "conversation_id": None,
        "in_reply_to": None,
        "sender_email": "david.kumar@acmecorp.com",
        "sender_name": "David Kumar",
        "recipients": json.dumps(["vendor-support@company.com"]),
        "to_address": json.dumps([
            {"name": "Vendor Support", "email": "vendor-support@company.com"},
        ]),
        "cc_addresses": json.dumps([]),
        "subject": "Contract Renewal Terms - Agreement #CON-2025-112",
        "body_text": (
            "Hello,\n\n"
            "Our contract #CON-2025-112 expires on May 31, 2026. We would like "
            "to discuss renewal terms and any price adjustments.\n\n"
            "Can someone from your contracts team reach out?\n\n"
            "Thanks,\nDavid Kumar\nAcme Corporation"
        ),
        "body_html": None,
        "body_preview": "Hello, Our contract #CON-2025-112 expires on May 31, 2026...",
        "raw_s3_key": "emails/seed-msg-005.json",
        "received_at": datetime(2026, 4, 8, 11, 20, 0, tzinfo=timezone.utc),
        "has_attachments": False,
        "attachment_count": 0,
        "thread_id": None,
        "is_reply": False,
        "is_auto_reply": False,
        "language": "en",
        "status": "NEW",
        "vendor_id": "SF-ACME-003",
        "query_type": None,
        "invoice_ref": None,
        "po_ref": None,
        "contract_ref": "CON-2025-112",
        "amount": None,
        "correlation_id": "corr-seed-005",
        "query_id": "VQ-2026-9005",
        "execution_id": "exec-seed-005",
    },
]

# Attachments for emails that have them
SEED_ATTACHMENTS = [
    # Attachment for email 1 (invoice copy)
    {
        "message_id": "<seed-msg-001@test.vqms>",
        "filename": "INV-2026-0451.pdf",
        "content_type": "application/pdf",
        "size_bytes": 245760,
        "s3_key": "attachments/seed-msg-001/INV-2026-0451.pdf",
    },
    # Attachments for email 4 (PO copy + specs)
    {
        "message_id": "<seed-msg-004@test.vqms>",
        "filename": "PO-2026-78432.pdf",
        "content_type": "application/pdf",
        "size_bytes": 189440,
        "s3_key": "attachments/seed-msg-004/PO-2026-78432.pdf",
    },
    {
        "message_id": "<seed-msg-004@test.vqms>",
        "filename": "shipping_requirements.docx",
        "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "size_bytes": 52430,
        "s3_key": "attachments/seed-msg-004/shipping_requirements.docx",
    },
]

# Case execution records (one per query_id)
SEED_CASES = [
    {
        "execution_id": "exec-seed-001",
        "query_id": "VQ-2026-9001",
        "correlation_id": "corr-seed-001",
        "status": "new",
        "source": "email",
        "vendor_id": "SF-TECHNOVA-001",
    },
    {
        "execution_id": "exec-seed-002",
        "query_id": "VQ-2026-9002",
        "correlation_id": "corr-seed-002",
        "status": "new",
        "source": "email",
        "vendor_id": "SF-TECHNOVA-001",
    },
    {
        "execution_id": "exec-seed-003",
        "query_id": "VQ-2026-9003",
        "correlation_id": "corr-seed-003",
        "status": "new",
        "source": "email",
        "vendor_id": "SF-TECHNOVA-001",
    },
    {
        "execution_id": "exec-seed-004",
        "query_id": "VQ-2026-9004",
        "correlation_id": "corr-seed-004",
        "status": "new",
        "source": "email",
        "vendor_id": "SF-GLOBALPARTS-002",
    },
    {
        "execution_id": "exec-seed-005",
        "query_id": "VQ-2026-9005",
        "correlation_id": "corr-seed-005",
        "status": "new",
        "source": "email",
        "vendor_id": "SF-ACME-003",
    },
]


async def clear_seed_data(engine) -> None:
    """Delete all seeded test data."""
    from sqlalchemy import text

    async with engine.begin() as conn:
        # Delete attachments first (FK constraint)
        await conn.execute(text(
            "DELETE FROM intake.email_attachments WHERE email_id IN "
            "(SELECT id FROM intake.email_messages WHERE message_id LIKE '%seed%')"
        ))
        await conn.execute(text(
            "DELETE FROM intake.email_messages WHERE message_id LIKE '%seed%'"
        ))
        await conn.execute(text(
            "DELETE FROM workflow.case_execution WHERE execution_id LIKE 'exec-seed%'"
        ))
    print("[CLEARED] Removed all seed data")


async def insert_seed_data(engine) -> None:
    """Insert test emails, attachments, and case_execution records."""
    from sqlalchemy import text

    now = datetime.now(timezone.utc)

    async with engine.begin() as conn:
        # Insert case_execution records first (emails reference query_id)
        for case in SEED_CASES:
            await conn.execute(text("""
                INSERT INTO workflow.case_execution
                    (execution_id, query_id, correlation_id, status,
                     source, vendor_id, created_at, updated_at)
                VALUES
                    (:execution_id, :query_id, :correlation_id, :status,
                     :source, :vendor_id, :created_at, :updated_at)
                ON CONFLICT (execution_id) DO NOTHING
            """), {
                **case,
                "created_at": now,
                "updated_at": now,
            })
        print(f"[OK] Inserted {len(SEED_CASES)} case_execution records")

        # Insert email messages
        email_id_map: dict[str, int] = {}
        for email in SEED_EMAILS:
            result = await conn.execute(text("""
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
            """), email)

            row = result.fetchone()
            if row:
                email_id_map[email["message_id"]] = row[0]

        print(f"[OK] Inserted {len(email_id_map)} email records")

        # Insert attachments
        att_count = 0
        for att in SEED_ATTACHMENTS:
            email_db_id = email_id_map.get(att["message_id"])
            if email_db_id:
                await conn.execute(text("""
                    INSERT INTO intake.email_attachments
                        (email_id, filename, content_type, size_bytes, s3_key)
                    VALUES
                        (:email_id, :filename, :content_type, :size_bytes, :s3_key)
                """), {
                    "email_id": email_db_id,
                    "filename": att["filename"],
                    "content_type": att["content_type"],
                    "size_bytes": att["size_bytes"],
                    "s3_key": att["s3_key"],
                })
                att_count += 1

        print(f"[OK] Inserted {att_count} attachment records")


async def main() -> None:
    """Connect to DB, seed data, disconnect."""
    settings = get_settings()
    clear_first = "--clear" in sys.argv

    print("=" * 60)
    print("  VQMS Email Dashboard — Seed Script")
    print("=" * 60)

    # Establish SSH tunnel if configured
    db_url = settings.database_url
    try:
        if settings.ssh_host:
            print(f"\nConnecting via SSH tunnel to {settings.ssh_host}...")
            local_host, local_port = start_ssh_tunnel(
                ssh_host=settings.ssh_host,
                ssh_port=settings.ssh_port,
                ssh_username=settings.ssh_username,
                ssh_private_key_path=settings.ssh_private_key_path,
                rds_host=settings.rds_host,
                rds_port=settings.rds_port,
            )
            db_url = (
                f"postgresql+asyncpg://{settings.postgres_user}:{settings.postgres_password}"
                f"@{local_host}:{local_port}/{settings.postgres_db}"
            )
            print(f"[OK] SSH tunnel established (localhost:{local_port})")
        else:
            print("\nNo SSH_HOST configured — connecting directly")
    except Exception as e:
        print(f"[FAIL] SSH tunnel failed: {e}")
        sys.exit(1)

    # Connect to PostgreSQL
    try:
        await init_db(
            database_url=db_url,
            pool_min=1,
            pool_max=3,
        )
        print("[OK] Connected to PostgreSQL")
    except Exception as e:
        print(f"[FAIL] Cannot connect to PostgreSQL: {e}")
        sys.exit(1)

    engine = get_engine()
    if engine is None:
        print("[FAIL] Database engine not available")
        sys.exit(1)

    try:
        if clear_first:
            await clear_seed_data(engine)

        await insert_seed_data(engine)
    finally:
        await close_db()
        stop_ssh_tunnel()

    print("\n" + "=" * 60)
    print("  Seed complete! Now test the API:")
    print("=" * 60)
    print()
    print("  1. Start the server:")
    print("     uv run uvicorn main:app --reload --port 8000")
    print()
    print("  2. List all email chains (should show 3 chains):")
    print("     curl http://localhost:8000/emails")
    print()
    print("  3. Get stats:")
    print("     curl http://localhost:8000/emails/stats")
    print()
    print("  4. Get the invoice thread (3 emails in chain):")
    print("     curl http://localhost:8000/emails/VQ-2026-9001")
    print()
    print("  5. Get the shipping query (1 email, 2 attachments):")
    print("     curl http://localhost:8000/emails/VQ-2026-9004")
    print()
    print("  6. Get the contract query (no conversation_id):")
    print("     curl http://localhost:8000/emails/VQ-2026-9005")
    print()
    print("  7. Search for 'invoice':")
    print('     curl "http://localhost:8000/emails?search=invoice"')
    print()
    print("  8. Download attachment:")
    print("     curl http://localhost:8000/emails/VQ-2026-9001/attachments/1/download")
    print()
    print("  9. Run the full test script:")
    print("     uv run python tests/manual/test_email_dashboard_api.py")
    print()
    print("  To clear seed data later:")
    print("     uv run python scripts/seed_email_dashboard.py --clear")
    print()


if __name__ == "__main__":
    asyncio.run(main())
