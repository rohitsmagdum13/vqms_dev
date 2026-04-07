"""Tests for Phase 2 adapters: S3 (moto), SQS (moto), EventBridge (moto), Salesforce stub.

Uses moto to mock AWS services. No real AWS credentials needed.
"""

from __future__ import annotations

import os

import boto3
import pytest
from moto import mock_aws

from src.adapters.salesforce import resolve_vendor

# ============================================================
# S3 Tests (moto)
# ============================================================


@pytest.fixture
def aws_credentials():
    """Set dummy AWS credentials for moto."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    yield
    # Cleanup is handled by moto


@pytest.fixture
def s3_setup(aws_credentials):
    """Create a mocked S3 bucket using moto."""
    with mock_aws():
        # Import here so the client is created inside the mock context
        from src.storage import s3_client

        s3_client.reset_client()

        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="test-bucket")
        yield s3_client

        s3_client.reset_client()


class TestS3Storage:
    """Tests for S3 storage adapter with moto."""

    @pytest.mark.asyncio
    async def test_upload_and_download(self, s3_setup):
        """Upload a file to S3 and download it back."""
        s3_client = s3_setup

        content = b"Hello, VQMS!"
        uri = await s3_client.upload_file(
            bucket="test-bucket",
            key="test/file.txt",
            content=content,
            correlation_id="test-corr-001",
        )
        assert uri == "s3://test-bucket/test/file.txt"

        downloaded = await s3_client.download_file(
            bucket="test-bucket",
            key="test/file.txt",
            correlation_id="test-corr-001",
        )
        assert downloaded == content

    @pytest.mark.asyncio
    async def test_download_missing_file_raises(self, s3_setup):
        """Downloading a non-existent key should raise FileNotFoundError."""
        s3_client = s3_setup

        with pytest.raises(FileNotFoundError):
            await s3_client.download_file(
                bucket="test-bucket",
                key="does-not-exist.txt",
            )

    @pytest.mark.asyncio
    async def test_upload_returns_s3_uri(self, s3_setup):
        """Upload should return an s3:// URI."""
        s3_client = s3_setup

        uri = await s3_client.upload_file(
            bucket="test-bucket",
            key="a/b/c/deep.bin",
            content=b"\x00\x01\x02",
        )
        assert uri.startswith("s3://")
        assert "test-bucket" in uri


# ============================================================
# SQS Tests (moto)
# ============================================================


@pytest.fixture
def sqs_setup(aws_credentials):
    """Create a mocked SQS queue using moto."""
    with mock_aws():
        from src.queues import sqs

        sqs.reset_client()

        client = boto3.client("sqs", region_name="us-east-1")
        client.create_queue(QueueName="test-queue")
        client.create_queue(QueueName="vqms-query-intake-queue")
        client.create_queue(QueueName="vqms-email-intake-queue")
        yield sqs

        sqs.reset_client()


class TestSQSQueue:
    """Tests for SQS queue adapter with moto."""

    @pytest.mark.asyncio
    async def test_publish_and_consume(self, sqs_setup):
        """Publish a message and consume it back."""
        sqs = sqs_setup

        msg = {"query_id": "VQ-2026-0001", "subject": "Test"}
        message_id = await sqs.publish("test-queue", msg, correlation_id="corr-001")
        assert message_id  # SQS returns a MessageId

        result = await sqs.consume("test-queue")
        assert result is not None
        assert result["query_id"] == "VQ-2026-0001"

    @pytest.mark.asyncio
    async def test_consume_empty_queue_returns_none(self, sqs_setup):
        """Consuming from an empty queue should return None."""
        sqs = sqs_setup
        result = await sqs.consume("test-queue")
        assert result is None

    @pytest.mark.asyncio
    async def test_queue_size(self, sqs_setup):
        """Queue size should reflect published messages."""
        sqs = sqs_setup
        await sqs.publish("test-queue", {"a": 1})
        await sqs.publish("test-queue", {"b": 2})

        size = sqs.get_queue_size("test-queue")
        assert size == 2


# ============================================================
# EventBridge Tests (moto)
# ============================================================


@pytest.fixture
def eb_setup(aws_credentials):
    """Create a mocked EventBridge bus using moto."""
    with mock_aws():
        from src.events import eventbridge

        eventbridge.reset_client()

        client = boto3.client("events", region_name="us-east-1")
        client.create_event_bus(Name="vqms-event-bus")
        yield eventbridge

        eventbridge.reset_client()


class TestEventBridge:
    """Tests for EventBridge adapter with moto."""

    @pytest.mark.asyncio
    async def test_publish_event_returns_event_id(self, eb_setup):
        """Published event should return an event ID."""
        eventbridge = eb_setup

        event_id = await eventbridge.publish_event(
            detail_type="QueryReceived",
            detail={"query_id": "VQ-2026-0001"},
            correlation_id="corr-001",
        )
        # moto returns an event ID
        assert event_id

    @pytest.mark.asyncio
    async def test_publish_multiple_events(self, eb_setup):
        """Multiple events should succeed without error."""
        eventbridge = eb_setup

        id1 = await eventbridge.publish_event("QueryReceived", {"id": "1"})
        id2 = await eventbridge.publish_event("EmailIngested", {"id": "2"})

        assert id1
        assert id2
        assert id1 != id2


# ============================================================
# Salesforce Stub Tests
# ============================================================


class TestSalesforceStub:
    """Tests for the Salesforce vendor resolution stub."""

    @pytest.mark.asyncio
    async def test_exact_email_match_technova(self):
        """TechNova should match by exact email."""
        match = await resolve_vendor(
            sender_email="rajesh.mehta@technova.com",
            sender_name="Rajesh Mehta",
            body_text="Some query about an invoice",
        )
        assert match is not None
        assert match.vendor_id == "SF-001"
        assert match.vendor_name == "TechNova Solutions"
        assert match.match_method == "EMAIL_EXACT"
        assert match.match_confidence == 0.95

    @pytest.mark.asyncio
    async def test_exact_email_match_acme(self):
        """Acme should match by exact email."""
        match = await resolve_vendor(
            sender_email="john@acme-corp.com",
            sender_name="John Doe",
            body_text="",
        )
        assert match is not None
        assert match.vendor_id == "SF-002"

    @pytest.mark.asyncio
    async def test_vendor_id_in_body(self):
        """Vendor ID in email body should match (step 2 fallback)."""
        match = await resolve_vendor(
            sender_email="unknown@example.com",
            sender_name="Unknown Person",
            body_text="Please check our account SF-003 for payment status",
        )
        assert match is not None
        assert match.vendor_id == "SF-003"
        assert match.match_method == "VENDOR_ID_BODY"
        assert match.match_confidence == 0.90

    @pytest.mark.asyncio
    async def test_name_similarity_match(self):
        """Vendor name similarity should match (step 3 fallback)."""
        match = await resolve_vendor(
            sender_email="unknown@example.com",
            sender_name="TechNova Solutions",
            body_text="No vendor ID here",
        )
        assert match is not None
        assert match.vendor_id == "SF-001"
        assert match.match_method == "NAME_SIMILARITY"
        assert match.match_confidence == 0.60

    @pytest.mark.asyncio
    async def test_no_match_returns_none(self):
        """Unknown sender with no vendor ID should return None."""
        match = await resolve_vendor(
            sender_email="nobody@nowhere.com",
            sender_name="Nobody",
            body_text="Generic question with no identifiers",
        )
        assert match is None

    @pytest.mark.asyncio
    async def test_email_match_is_case_insensitive(self):
        """Email matching should be case-insensitive."""
        match = await resolve_vendor(
            sender_email="RAJESH.MEHTA@TECHNOVA.COM",
            sender_name="",
            body_text="",
        )
        assert match is not None
        assert match.vendor_id == "SF-001"
