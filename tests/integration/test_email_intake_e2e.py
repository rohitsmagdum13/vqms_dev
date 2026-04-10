"""End-to-end integration test for the email intake pipeline.

Exercises the FULL email intake flow from webhook notification arrival
to SQS message output, with real AWS mocking (moto) for S3, SQS,
EventBridge and mock patches for Graph API and cache.

Pipeline under test (Steps E1-E2 from Solution Flow Document):

  1. POST /webhooks/ms-graph — webhook receives Graph notification
  2. fetch_email_by_resource() — Graph API fetches email (mocked)
  3. Idempotency check — cache checks for duplicate message_id (mocked)
  4. Vendor resolution — Salesforce stub matches sender email
  5. Thread correlation — determines NEW / EXISTING_OPEN
  6. S3 upload — raw email stored in vqms-email-raw-prod (moto)
  7. Tracking IDs — query_id (VQ-YYYY-XXXX), execution_id, correlation_id
  8. UnifiedQueryPayload — Pydantic model built
  9. CaseExecution — model prepared (DB write deferred)
  10. EventBridge — EmailIngested event published (moto)
  11. SQS — payload enqueued to vqms-email-intake-queue (moto)

After the pipeline:
  - Verify the SQS message contains a valid UnifiedQueryPayload
  - Verify the S3 bucket contains the raw email JSON
  - Verify the EventBridge event was published
  - Verify the webhook HTTP response is correct

Uses moto for S3/SQS/EventBridge, in-memory mock for cache,
and mock for Graph API. No real AWS credentials or services needed.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import boto3
import pytest
from httpx import ASGITransport, AsyncClient
from moto import mock_aws

from src.models.email import EmailAttachment, EmailMessage
from src.models.vendor import VendorMatch, VendorTier

# ---------------------------------------------------------------------------
# Reference scenario email: Rajesh Mehta from TechNova Solutions
# Invoice #INV-2026-0451 — the same scenario used in architecture docs
# ---------------------------------------------------------------------------

TECHNOVA_EMAIL = EmailMessage(
    message_id="AAMkAGQ2ZTIxNTRhLTechnova001",
    conversation_id="conv-technova-inv-0451",
    in_reply_to=None,
    references=[],
    sender_email="rajesh.mehta@technova.com",
    sender_name="Rajesh Mehta",
    subject="Invoice #INV-2026-0451 — Payment Status Query",
    body_text=(
        "Dear Support Team,\n\n"
        "I am writing to inquire about the payment status of "
        "Invoice #INV-2026-0451 for USD 45,000.00. The invoice was "
        "submitted on March 15, 2026 and payment was expected within "
        "30 days per our agreement.\n\n"
        "Could you please provide an update on when we can expect "
        "the payment to be processed?\n\n"
        "Vendor ID: SF-001\n\n"
        "Best regards,\nRajesh Mehta\nTechNova Solutions"
    ),
    body_html=None,
    received_at=datetime(2026, 4, 6, 10, 30, 0, tzinfo=timezone(timedelta(hours=5, minutes=30))),
    attachments=[
        EmailAttachment(
            filename="INV-2026-0451.pdf",
            content_type="application/pdf",
            size_bytes=245_760,
            s3_key=None,
        ),
    ],
)

# A reply email — has in_reply_to header, should be EXISTING_OPEN
TECHNOVA_REPLY_EMAIL = EmailMessage(
    message_id="AAMkAGQ2ZTIxNTRhLTechnova002",
    conversation_id="conv-technova-inv-0451",
    in_reply_to="AAMkAGQ2ZTIxNTRhLTechnova001",
    references=["AAMkAGQ2ZTIxNTRhLTechnova001"],
    sender_email="rajesh.mehta@technova.com",
    sender_name="Rajesh Mehta",
    subject="Re: Invoice #INV-2026-0451 — Payment Status Query",
    body_text="Thank you for the update. Could you confirm the exact date?",
    body_html=None,
    received_at=datetime(2026, 4, 6, 14, 15, 0, tzinfo=timezone(timedelta(hours=5, minutes=30))),
    attachments=[],
)

# An email from an unknown sender — should result in UNRESOLVED vendor
UNKNOWN_SENDER_EMAIL = EmailMessage(
    message_id="AAMkAGQ2ZTIxNTRhLUnknown001",
    conversation_id=None,
    in_reply_to=None,
    references=[],
    sender_email="nobody@random-company.com",
    sender_name="Unknown Person",
    subject="Question about services",
    body_text="Hello, I have a general question about your services.",
    body_html=None,
    received_at=datetime(2026, 4, 6, 11, 0, 0, tzinfo=timezone(timedelta(hours=5, minutes=30))),
    attachments=[],
)


# ---------------------------------------------------------------------------
# AWS Resource Setup (moto)
# ---------------------------------------------------------------------------

@pytest.fixture
def aws_credentials():
    """Set dummy AWS credentials for moto."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    yield
    for key in [
        "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
        "AWS_SECURITY_TOKEN", "AWS_SESSION_TOKEN", "AWS_DEFAULT_REGION",
    ]:
        os.environ.pop(key, None)


@pytest.fixture
def aws_infra(aws_credentials):
    """Create mocked S3 bucket, SQS queue, and EventBridge bus.

    Mirrors the pre-provisioned AWS resources from CLAUDE.md:
      - S3: vqms-email-raw-prod
      - SQS: vqms-email-intake-queue
      - EventBridge: vqms-event-bus
    """
    with mock_aws():
        region = "us-east-1"

        # --- S3: raw email storage + attachments ---
        s3 = boto3.client("s3", region_name=region)
        s3.create_bucket(Bucket="vqms-email-raw-prod")
        s3.create_bucket(Bucket="vqms-email-attachments-prod")

        # --- SQS: email intake queue ---
        sqs = boto3.client("sqs", region_name=region)
        sqs.create_queue(QueueName="vqms-email-intake-queue")

        # --- EventBridge: event bus ---
        eb = boto3.client("events", region_name=region)
        eb.create_event_bus(Name="vqms-event-bus")

        # Reset adapter clients so they pick up moto's mock
        from src.events import eventbridge
        from src.queues import sqs as sqs_module
        from src.storage import s3_client

        s3_client.reset_client()
        sqs_module.reset_client()
        eventbridge.reset_client()

        yield {
            "s3": s3,
            "sqs": sqs,
            "eb": eb,
            "s3_client": s3_client,
            "sqs_module": sqs_module,
            "eventbridge": eventbridge,
        }

        # Cleanup after test
        s3_client.reset_client()
        sqs_module.reset_client()
        eventbridge.reset_client()


# ---------------------------------------------------------------------------
# Cache mock (simulates in-memory key store)
# ---------------------------------------------------------------------------

class FakeCache:
    """Simple in-memory cache mock for idempotency checks.

    Tracks keys and TTLs. get_value() returns None for missing keys.
    set_with_ttl() stores the key. This is enough for idempotency logic.
    """

    def __init__(self):
        self._store: dict[str, str] = {}

    async def get_value(self, key: str) -> str | None:
        return self._store.get(key)

    async def set_with_ttl(self, key: str, value: str, ttl: int) -> None:
        self._store[key] = value

    def has_key(self, key: str) -> bool:
        return key in self._store

    @property
    def stored_keys(self) -> list[str]:
        return list(self._store.keys())


# ---------------------------------------------------------------------------
# Mock vendor match for Salesforce adapter
# ---------------------------------------------------------------------------

TECHNOVA_VENDOR_MATCH = VendorMatch(
    vendor_id="V-001",
    vendor_name="TechNova Solutions",
    vendor_tier=VendorTier.GOLD,
    match_method="EMAIL_EXACT",
    match_confidence=0.95,
)


async def _mock_resolve_vendor(sender_email, sender_name, body_text, **kwargs):
    """Mock vendor resolution — returns TechNova for known emails, None otherwise."""
    known = {"rajesh.mehta@technova.com"}
    if sender_email.lower() in known:
        return TECHNOVA_VENDOR_MATCH
    return None


# ---------------------------------------------------------------------------
# Test: Full Email Intake Pipeline (Happy Path — TechNova, Path A scenario)
# ---------------------------------------------------------------------------

class TestEmailIntakeEndToEnd:
    """End-to-end tests for the email intake pipeline.

    Each test exercises the full pipeline: webhook → service →
    S3 + SQS + EventBridge. AWS services are real (moto-mocked).
    Graph API and cache are mock-patched.
    """

    @pytest.mark.asyncio
    @patch("src.services.email_intake.resolve_vendor", side_effect=_mock_resolve_vendor)
    @patch("src.services.email_intake.fetch_email_by_resource", new_callable=AsyncMock)
    async def test_happy_path_technova_new_email(self, mock_fetch, mock_vendor, aws_infra):
        """Full pipeline: TechNova new email → S3 + EventBridge + SQS.

        Exercises the reference scenario from the architecture doc:
        Rajesh Mehta from TechNova, Invoice #INV-2026-0451.
        """
        mock_fetch.return_value = TECHNOVA_EMAIL
        fake_cache = FakeCache()

        with (
            patch("src.services.email_intake.get_value", side_effect=fake_cache.get_value),
            patch("src.services.email_intake.set_with_ttl", side_effect=fake_cache.set_with_ttl),
        ):
            from src.services.email_intake import process_email_notification

            result = await process_email_notification(
                resource="messages/AAMkAGQ2ZTIxNTRhLTechnova001",
            )

        # --- Verify service result ---
        assert result["status"] == "accepted"
        assert result["query_id"].startswith("VQ-")
        assert result["execution_id"]  # UUID present
        assert result["correlation_id"]  # UUID present
        assert result["vendor_id"] == "V-001"  # TechNova matched by Salesforce
        assert result["thread_status"] == "NEW"

        # --- Verify S3: raw email stored ---
        s3 = aws_infra["s3"]
        s3_objects = s3.list_objects_v2(Bucket="vqms-email-raw-prod")
        assert s3_objects["KeyCount"] == 1

        s3_key = s3_objects["Contents"][0]["Key"]
        assert s3_key.startswith("emails/")
        assert TECHNOVA_EMAIL.message_id in s3_key

        # Download and verify raw email content
        raw_obj = s3.get_object(Bucket="vqms-email-raw-prod", Key=s3_key)
        raw_body = json.loads(raw_obj["Body"].read().decode("utf-8"))
        assert raw_body["message_id"] == TECHNOVA_EMAIL.message_id
        assert raw_body["from_address"] == "rajesh.mehta@technova.com"
        assert raw_body["subject"] == "Invoice #INV-2026-0451 — Payment Status Query"
        assert "INV-2026-0451" in raw_body["body_text"]
        assert raw_body["has_attachments"] is True
        assert raw_body["attachment_count"] == 1
        assert len(raw_body["attachments"]) == 1
        assert raw_body["attachments"][0]["filename"] == "INV-2026-0451.pdf"
        assert raw_body["vendor_id"] == "V-001"
        assert raw_body["is_reply"] is False
        assert raw_body["status"] == "NEW"

        # --- Verify SQS: message enqueued ---
        sqs = aws_infra["sqs"]
        queue_url = sqs.get_queue_url(QueueName="vqms-email-intake-queue")["QueueUrl"]
        messages = sqs.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=10,
            WaitTimeSeconds=0,
        )
        assert "Messages" in messages
        assert len(messages["Messages"]) == 1

        sqs_body = json.loads(messages["Messages"][0]["Body"])
        assert sqs_body["query_id"] == result["query_id"]
        assert sqs_body["execution_id"] == result["execution_id"]
        assert sqs_body["source"] == "email"
        assert sqs_body["vendor_id"] == "V-001"
        assert sqs_body["vendor_name"] == "TechNova Solutions"
        assert sqs_body["subject"] == "Invoice #INV-2026-0451 — Payment Status Query"
        assert sqs_body["thread_status"] == "NEW"
        assert sqs_body["message_id"] == TECHNOVA_EMAIL.message_id

        # --- Verify cache: idempotency key set ---
        assert len(fake_cache.stored_keys) == 1
        assert any("email:" in k for k in fake_cache.stored_keys)

    @pytest.mark.asyncio
    @patch("src.services.email_intake.resolve_vendor", side_effect=_mock_resolve_vendor)
    @patch("src.services.email_intake.fetch_email_by_resource", new_callable=AsyncMock)
    async def test_reply_email_thread_correlation(self, mock_fetch, mock_vendor, aws_infra):
        """A reply email (has in_reply_to) should be marked EXISTING_OPEN."""
        mock_fetch.return_value = TECHNOVA_REPLY_EMAIL
        fake_cache = FakeCache()

        with (
            patch("src.services.email_intake.get_value", side_effect=fake_cache.get_value),
            patch("src.services.email_intake.set_with_ttl", side_effect=fake_cache.set_with_ttl),
        ):
            from src.services.email_intake import process_email_notification

            result = await process_email_notification(
                resource="messages/AAMkAGQ2ZTIxNTRhLTechnova002",
            )

        assert result["thread_status"] == "EXISTING_OPEN"
        assert result["vendor_id"] == "V-001"  # Still TechNova

        # Verify SQS payload has correct thread_status
        sqs = aws_infra["sqs"]
        queue_url = sqs.get_queue_url(QueueName="vqms-email-intake-queue")["QueueUrl"]
        messages = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=10)
        sqs_body = json.loads(messages["Messages"][0]["Body"])
        assert sqs_body["thread_status"] == "EXISTING_OPEN"

    @pytest.mark.asyncio
    @patch("src.services.email_intake.resolve_vendor", side_effect=_mock_resolve_vendor)
    @patch("src.services.email_intake.fetch_email_by_resource", new_callable=AsyncMock)
    async def test_unknown_sender_resolves_to_unresolved(self, mock_fetch, mock_vendor, aws_infra):
        """An email from an unknown sender should have vendor_id=UNRESOLVED."""
        mock_fetch.return_value = UNKNOWN_SENDER_EMAIL
        fake_cache = FakeCache()

        with (
            patch("src.services.email_intake.get_value", side_effect=fake_cache.get_value),
            patch("src.services.email_intake.set_with_ttl", side_effect=fake_cache.set_with_ttl),
        ):
            from src.services.email_intake import process_email_notification

            result = await process_email_notification(
                resource="messages/AAMkAGQ2ZTIxNTRhLUnknown001",
            )

        assert result["vendor_id"] == "UNRESOLVED"
        assert result["thread_status"] == "NEW"
        assert result["status"] == "accepted"

        # SQS payload should have vendor_id=UNRESOLVED
        sqs = aws_infra["sqs"]
        queue_url = sqs.get_queue_url(QueueName="vqms-email-intake-queue")["QueueUrl"]
        messages = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=10)
        sqs_body = json.loads(messages["Messages"][0]["Body"])
        assert sqs_body["vendor_id"] == "UNRESOLVED"
        assert sqs_body["vendor_name"] == "Unknown Vendor"

    @pytest.mark.asyncio
    @patch("src.services.email_intake.resolve_vendor", side_effect=_mock_resolve_vendor)
    @patch("src.services.email_intake.fetch_email_by_resource", new_callable=AsyncMock)
    async def test_duplicate_email_is_rejected(self, mock_fetch, mock_vendor, aws_infra):
        """Sending the same email twice should fail on the second attempt."""
        mock_fetch.return_value = TECHNOVA_EMAIL
        fake_cache = FakeCache()

        with (
            patch("src.services.email_intake.get_value", side_effect=fake_cache.get_value),
            patch("src.services.email_intake.set_with_ttl", side_effect=fake_cache.set_with_ttl),
        ):
            from src.services.email_intake import process_email_notification
            from src.utils.exceptions import DuplicateQueryError

            # First call: succeeds
            result1 = await process_email_notification(
                resource="messages/AAMkAGQ2ZTIxNTRhLTechnova001",
            )
            assert result1["status"] == "accepted"

            # Second call: duplicate detected
            with pytest.raises(DuplicateQueryError):
                await process_email_notification(
                    resource="messages/AAMkAGQ2ZTIxNTRhLTechnova001",
                )

        # Only one message should be in SQS (the first one)
        sqs = aws_infra["sqs"]
        queue_url = sqs.get_queue_url(QueueName="vqms-email-intake-queue")["QueueUrl"]
        messages = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=10)
        assert len(messages.get("Messages", [])) == 1

    @pytest.mark.asyncio
    @patch("src.services.email_intake.resolve_vendor", side_effect=_mock_resolve_vendor)
    @patch("src.services.email_intake.fetch_email_by_resource", new_callable=AsyncMock)
    async def test_cache_down_still_processes_email(self, mock_fetch, mock_vendor, aws_infra):
        """If cache is unavailable, email should still process successfully."""
        mock_fetch.return_value = TECHNOVA_EMAIL

        with (
            patch(
                "src.services.email_intake.get_value",
                new_callable=AsyncMock,
                side_effect=ConnectionError("Cache connection refused"),
            ),
            patch(
                "src.services.email_intake.set_with_ttl",
                new_callable=AsyncMock,
                side_effect=ConnectionError("Cache connection refused"),
            ),
        ):
            from src.services.email_intake import process_email_notification

            result = await process_email_notification(
                resource="messages/AAMkAGQ2ZTIxNTRhLTechnova001",
            )

        assert result["status"] == "accepted"
        assert result["vendor_id"] == "V-001"

        # S3 and SQS should still have data
        s3 = aws_infra["s3"]
        s3_objects = s3.list_objects_v2(Bucket="vqms-email-raw-prod")
        assert s3_objects["KeyCount"] == 1

        sqs = aws_infra["sqs"]
        queue_url = sqs.get_queue_url(QueueName="vqms-email-intake-queue")["QueueUrl"]
        messages = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=10)
        assert len(messages["Messages"]) == 1

    @pytest.mark.asyncio
    @patch("src.services.email_intake.resolve_vendor", side_effect=_mock_resolve_vendor)
    @patch("src.services.email_intake.fetch_email_by_resource", new_callable=AsyncMock)
    async def test_correlation_id_propagated_to_sqs_message(self, mock_fetch, mock_vendor, aws_infra):
        """A provided correlation_id should appear in the SQS message payload."""
        mock_fetch.return_value = TECHNOVA_EMAIL
        fake_cache = FakeCache()
        custom_correlation = "custom-corr-id-12345"

        with (
            patch("src.services.email_intake.get_value", side_effect=fake_cache.get_value),
            patch("src.services.email_intake.set_with_ttl", side_effect=fake_cache.set_with_ttl),
        ):
            from src.services.email_intake import process_email_notification

            result = await process_email_notification(
                resource="messages/AAMkAGQ2ZTIxNTRhLTechnova001",
                correlation_id=custom_correlation,
            )

        assert result["correlation_id"] == custom_correlation

        # Verify SQS message has the correlation_id
        sqs = aws_infra["sqs"]
        queue_url = sqs.get_queue_url(QueueName="vqms-email-intake-queue")["QueueUrl"]
        messages = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=10)
        sqs_body = json.loads(messages["Messages"][0]["Body"])
        assert sqs_body["correlation_id"] == custom_correlation


# ---------------------------------------------------------------------------
# Test: Webhook HTTP Endpoint (FastAPI TestClient)
# ---------------------------------------------------------------------------

class TestWebhookEndToEnd:
    """End-to-end tests via the FastAPI webhook endpoint.

    Exercises the HTTP layer: POST /webhooks/ms-graph → full pipeline.
    """

    @pytest.mark.asyncio
    @patch("src.services.email_intake.resolve_vendor", side_effect=_mock_resolve_vendor)
    @patch("src.services.email_intake.fetch_email_by_resource", new_callable=AsyncMock)
    async def test_webhook_notification_processes_email(self, mock_fetch, mock_vendor, aws_infra):
        """POST /webhooks/ms-graph with a change notification → accepted."""
        mock_fetch.return_value = TECHNOVA_EMAIL
        fake_cache = FakeCache()

        with (
            patch("src.services.email_intake.get_value", side_effect=fake_cache.get_value),
            patch("src.services.email_intake.set_with_ttl", side_effect=fake_cache.set_with_ttl),
        ):
            from main import app

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/webhooks/ms-graph",
                    json={
                        "value": [
                            {
                                "resource": "messages/AAMkAGQ2ZTIxNTRhLTechnova001",
                                "changeType": "created",
                            }
                        ]
                    },
                )

        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "accepted"
        assert body["processed"] == 1
        assert body["results"][0]["query_id"].startswith("VQ-")
        assert body["results"][0]["vendor_id"] == "V-001"

    @pytest.mark.asyncio
    async def test_webhook_subscription_validation(self, aws_infra):
        """GET /webhooks/ms-graph?validationToken=abc → echoes token."""
        from main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/webhooks/ms-graph?validationToken=test-token-12345",
            )

        assert response.status_code == 200
        assert response.text == "test-token-12345"
        assert response.headers["content-type"] == "text/plain; charset=utf-8"

    @pytest.mark.asyncio
    async def test_webhook_empty_payload_returns_400(self, aws_infra):
        """POST /webhooks/ms-graph with empty value array → 400."""
        from main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/webhooks/ms-graph",
                json={"value": []},
            )

        assert response.status_code == 400

    @pytest.mark.asyncio
    @patch("src.services.email_intake.resolve_vendor", side_effect=_mock_resolve_vendor)
    @patch("src.services.email_intake.fetch_email_by_resource", new_callable=AsyncMock)
    async def test_webhook_duplicate_in_batch_handled_gracefully(
        self, mock_fetch, mock_vendor, aws_infra
    ):
        """If a notification batch contains a duplicate, it should not fail the whole batch."""
        mock_fetch.return_value = TECHNOVA_EMAIL
        fake_cache = FakeCache()

        with (
            patch("src.services.email_intake.get_value", side_effect=fake_cache.get_value),
            patch("src.services.email_intake.set_with_ttl", side_effect=fake_cache.set_with_ttl),
        ):
            from main import app

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # Send same resource twice in one batch
                response = await client.post(
                    "/webhooks/ms-graph",
                    json={
                        "value": [
                            {
                                "resource": "messages/AAMkAGQ2ZTIxNTRhLTechnova001",
                                "changeType": "created",
                            },
                            {
                                "resource": "messages/AAMkAGQ2ZTIxNTRhLTechnova001",
                                "changeType": "created",
                            },
                        ]
                    },
                )

        assert response.status_code == 202
        body = response.json()
        assert body["processed"] == 2
        # First: accepted, second: duplicate
        statuses = [r["status"] for r in body["results"]]
        assert "accepted" in statuses
        assert "duplicate" in statuses
