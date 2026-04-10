"""Tests for the email intake service.

Tests the full email ingestion flow with mocked Graph API,
Salesforce, cache, S3, SQS, and EventBridge. Verifies vendor
resolution, thread correlation, event publishing, and SQS enqueuing.
"""

from __future__ import annotations

from datetime import datetime

from src.utils.helpers import IST
from unittest.mock import AsyncMock, patch

import pytest

from src.models.email import EmailAttachment, EmailMessage
from src.models.vendor import VendorMatch, VendorTier
from src.services.email_intake import (
    _determine_thread_status,
    process_email_notification,
)
from src.utils.exceptions import DuplicateQueryError


def _make_mock_vendor_match() -> VendorMatch:
    """Create a mock VendorMatch for the TechNova reference scenario."""
    return VendorMatch(
        vendor_id="V-001",
        vendor_name="TechNova Solutions",
        vendor_tier=VendorTier.GOLD,
        match_method="EMAIL_EXACT",
        match_confidence=0.95,
    )


def _make_mock_email() -> EmailMessage:
    """Create a mock email matching the TechNova reference scenario."""
    return EmailMessage(
        message_id="stub-messages/test-123",
        conversation_id="conv-technova-inv-001",
        in_reply_to=None,
        references=[],
        sender_email="rajesh.mehta@technova.com",
        sender_name="Rajesh Mehta",
        subject="Invoice #INV-2026-0451 — Payment Status Query",
        body_text=(
            "Dear Support Team,\n\n"
            "I am writing to inquire about Invoice #INV-2026-0451.\n\n"
            "Vendor ID: SF-001"
        ),
        body_html=None,
        received_at=datetime.now(IST),
        attachments=[
            EmailAttachment(
                filename="INV-2026-0451.pdf",
                content_type="application/pdf",
                size_bytes=245_760,
                s3_key=None,
            ),
        ],
    )


# Common decorator stack for email intake tests:
# Mock Graph API (returns TechNova email), cache, S3, SQS, EventBridge
_COMMON_PATCHES = [
    patch("src.services.email_intake.set_with_ttl", new_callable=AsyncMock),
    patch("src.services.email_intake.get_value", new_callable=AsyncMock, return_value=None),
    patch("src.services.email_intake.upload_file", new_callable=AsyncMock, return_value="s3://bucket/key"),
    patch("src.services.email_intake.publish_event", new_callable=AsyncMock, return_value="evt-001"),
    patch("src.services.email_intake.publish", new_callable=AsyncMock, return_value="msg-001"),
    patch("src.services.email_intake.fetch_email_by_resource", new_callable=AsyncMock),
]


class TestEmailIntake:
    """Tests for process_email_notification()."""

    @pytest.mark.asyncio
    @patch("src.services.email_intake.resolve_vendor", new_callable=AsyncMock)
    @patch("src.services.email_intake.publish", new_callable=AsyncMock, return_value="msg-001")
    @patch("src.services.email_intake.publish_event", new_callable=AsyncMock, return_value="evt-001")
    @patch("src.services.email_intake.upload_file", new_callable=AsyncMock, return_value="s3://bucket/key")
    @patch("src.services.email_intake.get_value", new_callable=AsyncMock, return_value=None)
    @patch("src.services.email_intake.set_with_ttl", new_callable=AsyncMock)
    @patch("src.services.email_intake.fetch_email_by_resource", new_callable=AsyncMock)
    async def test_successful_email_processing(
        self, mock_fetch, mock_set, mock_get, mock_s3, mock_event, mock_sqs, mock_vendor
    ):
        """A valid email notification should be processed end-to-end."""
        mock_fetch.return_value = _make_mock_email()
        mock_vendor.return_value = _make_mock_vendor_match()

        result = await process_email_notification(resource="messages/test-123")

        assert result["status"] == "accepted"
        assert result["query_id"].startswith("VQ-")
        assert result["vendor_id"] == "V-001"  # TechNova from mocked Salesforce
        assert result["thread_status"] == "NEW"

    @pytest.mark.asyncio
    @patch("src.services.email_intake.resolve_vendor", new_callable=AsyncMock)
    @patch("src.services.email_intake.publish", new_callable=AsyncMock, return_value="msg-001")
    @patch("src.services.email_intake.publish_event", new_callable=AsyncMock, return_value="evt-001")
    @patch("src.services.email_intake.upload_file", new_callable=AsyncMock, return_value="s3://bucket/key")
    @patch("src.services.email_intake.get_value", new_callable=AsyncMock, return_value=None)
    @patch("src.services.email_intake.set_with_ttl", new_callable=AsyncMock)
    @patch("src.services.email_intake.fetch_email_by_resource", new_callable=AsyncMock)
    async def test_publishes_email_ingested_event(
        self, mock_fetch, mock_set, mock_get, mock_s3, mock_event, mock_sqs, mock_vendor
    ):
        """Email processing should publish an EmailIngested event."""
        mock_fetch.return_value = _make_mock_email()
        mock_vendor.return_value = _make_mock_vendor_match()

        await process_email_notification(resource="messages/test-456")

        mock_event.assert_called_once()
        call_args = mock_event.call_args
        detail_type = call_args.kwargs.get("detail_type") or call_args.args[0]
        assert detail_type == "EmailIngested"

    @pytest.mark.asyncio
    @patch("src.services.email_intake.resolve_vendor", new_callable=AsyncMock)
    @patch("src.services.email_intake.publish", new_callable=AsyncMock, return_value="msg-001")
    @patch("src.services.email_intake.publish_event", new_callable=AsyncMock, return_value="evt-001")
    @patch("src.services.email_intake.upload_file", new_callable=AsyncMock, return_value="s3://bucket/key")
    @patch("src.services.email_intake.get_value", new_callable=AsyncMock, return_value=None)
    @patch("src.services.email_intake.set_with_ttl", new_callable=AsyncMock)
    @patch("src.services.email_intake.fetch_email_by_resource", new_callable=AsyncMock)
    async def test_enqueues_to_email_intake_queue(
        self, mock_fetch, mock_set, mock_get, mock_s3, mock_event, mock_sqs, mock_vendor
    ):
        """Email processing should enqueue to the email intake queue."""
        mock_fetch.return_value = _make_mock_email()
        mock_vendor.return_value = _make_mock_vendor_match()

        await process_email_notification(resource="messages/test-789")

        mock_sqs.assert_called_once()
        call_args = mock_sqs.call_args
        queue_name = call_args.args[0] if call_args.args else call_args.kwargs.get("queue_name")
        assert queue_name == "vqms-email-intake-queue"

    @pytest.mark.asyncio
    @patch("src.services.email_intake.resolve_vendor", new_callable=AsyncMock)
    @patch("src.services.email_intake.publish", new_callable=AsyncMock, return_value="msg-001")
    @patch("src.services.email_intake.publish_event", new_callable=AsyncMock, return_value="evt-001")
    @patch("src.services.email_intake.upload_file", new_callable=AsyncMock, return_value="s3://bucket/key")
    @patch("src.services.email_intake.get_value", new_callable=AsyncMock, return_value=None)
    @patch("src.services.email_intake.set_with_ttl", new_callable=AsyncMock)
    @patch("src.services.email_intake.fetch_email_by_resource", new_callable=AsyncMock)
    async def test_stores_raw_email_in_s3(
        self, mock_fetch, mock_set, mock_get, mock_s3, mock_event, mock_sqs, mock_vendor
    ):
        """Raw email should be uploaded to S3."""
        mock_fetch.return_value = _make_mock_email()
        mock_vendor.return_value = _make_mock_vendor_match()

        await process_email_notification(resource="messages/s3-test")

        mock_s3.assert_called_once()
        call_kwargs = mock_s3.call_args
        bucket = call_kwargs.kwargs.get("bucket") or call_kwargs.args[0]
        assert bucket == "vqms-email-raw-prod"

    @pytest.mark.asyncio
    @patch("src.services.email_intake.fetch_email_by_resource", new_callable=AsyncMock)
    @patch("src.services.email_intake.get_value", new_callable=AsyncMock, return_value="1")
    async def test_duplicate_email_raises_error(self, mock_get, mock_fetch):
        """A duplicate email (message_id already in cache) should raise."""
        mock_fetch.return_value = _make_mock_email()

        with pytest.raises(DuplicateQueryError):
            await process_email_notification(resource="messages/dup-test")

    @pytest.mark.asyncio
    @patch("src.services.email_intake.resolve_vendor", new_callable=AsyncMock)
    @patch("src.services.email_intake.publish", new_callable=AsyncMock, return_value="msg-001")
    @patch("src.services.email_intake.publish_event", new_callable=AsyncMock, return_value="evt-001")
    @patch("src.services.email_intake.upload_file", new_callable=AsyncMock, return_value="s3://bucket/key")
    @patch("src.services.email_intake.fetch_email_by_resource", new_callable=AsyncMock)
    @patch("src.services.email_intake.get_value", new_callable=AsyncMock, side_effect=ConnectionError("DB down"))
    async def test_cache_failure_allows_processing(
        self, mock_get, mock_fetch, mock_s3, mock_event, mock_sqs, mock_vendor
    ):
        """If cache is down, email should still be processed."""
        mock_fetch.return_value = _make_mock_email()
        mock_vendor.return_value = _make_mock_vendor_match()

        result = await process_email_notification(resource="messages/cache-down")
        assert result["status"] == "accepted"


class TestThreadCorrelation:
    """Tests for _determine_thread_status()."""

    def test_new_email_without_reply_headers(self):
        """Email without in_reply_to or references should be NEW."""

        class MockEmail:
            in_reply_to = None
            references = []
            conversation_id = None

        assert _determine_thread_status(MockEmail()) == "NEW"

    def test_reply_with_in_reply_to(self):
        """Email with in_reply_to should be EXISTING_OPEN."""

        class MockEmail:
            in_reply_to = "<original-msg-id@example.com>"
            references = []
            conversation_id = None

        assert _determine_thread_status(MockEmail()) == "EXISTING_OPEN"

    def test_reply_with_references(self):
        """Email with references should be EXISTING_OPEN."""

        class MockEmail:
            in_reply_to = None
            references = ["<ref1@example.com>", "<ref2@example.com>"]
            conversation_id = None

        assert _determine_thread_status(MockEmail()) == "EXISTING_OPEN"

    def test_conversation_id_only_is_new(self):
        """Email with only conversation_id (no reply headers) is NEW in Phase 2."""

        class MockEmail:
            in_reply_to = None
            references = []
            conversation_id = "conv-12345"

        assert _determine_thread_status(MockEmail()) == "NEW"
