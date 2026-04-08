"""Tests for Phase 2 adapters: S3 (moto), SQS (moto), EventBridge (moto), Salesforce.

Uses moto to mock AWS services. No real AWS credentials needed.
Salesforce adapter is mocked via unittest.mock — no real Salesforce needed.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import boto3
import pytest
from moto import mock_aws

from src.services.vendor_resolution import resolve_vendor

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
# Salesforce Vendor Resolution Tests (mocked adapter)
# ============================================================


def _make_mock_adapter():
    """Create a mock SalesforceAdapter with realistic return data.

    Mimics the CUSTOM Salesforce objects:
      - Vendor_Contact__c  (Email__c, Vendor_Account__c lookup)
      - Vendor_Account__c  (Vendor_ID__c, Vendor_Tier__c, etc.)
    The adapter normalizes field names, so contacts return
    {Id, AccountId, Email, Name} and accounts return
    {Id, Name, Vendor_ID__c, Vendor_Tier__c, ...}.
    """
    adapter = MagicMock()

    def _find_contact_by_email(email, **kwargs):
        # Returns normalized dict from SalesforceAdapter.find_contact_by_email
        contacts = {
            "rajesh.mehta@technova.com": {
                "Id": "a01xx0001",
                "AccountId": "a00xx0001",
                "Email": "rajesh.mehta@technova.com",
                "Name": "Rajesh Mehta",
            },
            "john@acme-corp.com": {
                "Id": "a01xx0002",
                "AccountId": "a00xx0002",
                "Email": "john@acme-corp.com",
                "Name": "John Doe",
            },
        }
        return contacts.get(email.lower())

    def _find_account_by_id(account_id, **kwargs):
        # Returns Vendor_Account__c fields
        accounts = {
            "a00xx0001": {
                "Id": "a00xx0001",
                "Name": "TechNova Solutions",
                "Vendor_ID__c": "V-001",
                "Vendor_Tier__c": "Gold",
                "Vendor_Status__c": "Active",
                "Category__c": "Technology",
            },
            "a00xx0002": {
                "Id": "a00xx0002",
                "Name": "Acme Corporation",
                "Vendor_ID__c": "V-002",
                "Vendor_Tier__c": "Silver",
                "Vendor_Status__c": "Active",
                "Category__c": "Manufacturing",
            },
        }
        return accounts.get(account_id)

    def _find_account_by_vendor_id(vendor_id, **kwargs):
        # Lookup by Vendor_ID__c (e.g. "V-001")
        by_vid = {
            "V-001": {
                "Id": "a00xx0001",
                "Name": "TechNova Solutions",
                "Vendor_ID__c": "V-001",
                "Vendor_Tier__c": "Gold",
                "Vendor_Status__c": "Active",
                "Category__c": "Technology",
            },
            "V-002": {
                "Id": "a00xx0002",
                "Name": "Acme Corporation",
                "Vendor_ID__c": "V-002",
                "Vendor_Tier__c": "Silver",
                "Vendor_Status__c": "Active",
                "Category__c": "Manufacturing",
            },
        }
        return by_vid.get(vendor_id.upper() if vendor_id else None)

    def _find_account_by_name(name, **kwargs):
        # Simple substring match against known vendor accounts
        known = [
            {"Id": "a00xx0001", "Name": "TechNova Solutions",
             "Vendor_ID__c": "V-001", "Vendor_Tier__c": "Gold"},
            {"Id": "a00xx0002", "Name": "Acme Corporation",
             "Vendor_ID__c": "V-002", "Vendor_Tier__c": "Silver"},
        ]
        return [a for a in known if name.lower() in a["Name"].lower()]

    adapter.find_contact_by_email = MagicMock(side_effect=_find_contact_by_email)
    adapter.find_account_by_id = MagicMock(side_effect=_find_account_by_id)
    adapter.find_account_by_vendor_id = MagicMock(side_effect=_find_account_by_vendor_id)
    adapter.find_account_by_name = MagicMock(side_effect=_find_account_by_name)
    return adapter


class TestVendorResolution:
    """Tests for vendor resolution with mocked Salesforce adapter.

    The SalesforceAdapter is mocked — no real Salesforce connection needed.
    Tests verify the three-step fallback logic in vendor_resolution.py.
    """

    @pytest.mark.asyncio
    @patch("src.services.vendor_resolution.get_salesforce_adapter")
    async def test_exact_email_match_technova(self, mock_get_adapter):
        """TechNova should match by exact email (Step 1)."""
        mock_get_adapter.return_value = _make_mock_adapter()
        match = await resolve_vendor(
            sender_email="rajesh.mehta@technova.com",
            sender_name="Rajesh Mehta",
            body_text="Some query about an invoice",
        )
        assert match is not None
        assert match.vendor_id == "V-001"
        assert match.vendor_name == "TechNova Solutions"
        assert match.match_method == "EMAIL_EXACT"
        assert match.match_confidence == 0.95
        # Vendor tier should be mapped from Salesforce Vendor_Tier__c
        assert match.vendor_tier.value == "gold"

    @pytest.mark.asyncio
    @patch("src.services.vendor_resolution.get_salesforce_adapter")
    async def test_exact_email_match_acme(self, mock_get_adapter):
        """Acme should match by exact email (Step 1)."""
        mock_get_adapter.return_value = _make_mock_adapter()
        match = await resolve_vendor(
            sender_email="john@acme-corp.com",
            sender_name="John Doe",
            body_text="",
        )
        assert match is not None
        assert match.vendor_id == "V-002"
        assert match.vendor_tier.value == "silver"

    @pytest.mark.asyncio
    @patch("src.services.vendor_resolution.get_salesforce_adapter")
    async def test_vendor_id_in_body_match(self, mock_get_adapter):
        """Vendor ID pattern V-001 in body should match (Step 2)."""
        mock_get_adapter.return_value = _make_mock_adapter()
        match = await resolve_vendor(
            sender_email="unknown@example.com",
            sender_name="Unknown Person",
            body_text="Please check our account V-001 for details",
        )
        assert match is not None
        assert match.vendor_id == "V-001"
        assert match.vendor_name == "TechNova Solutions"
        assert match.match_method == "VENDOR_ID_BODY"
        assert match.match_confidence == 0.90

    @pytest.mark.asyncio
    @patch("src.services.vendor_resolution.get_salesforce_adapter")
    async def test_name_similarity_match(self, mock_get_adapter):
        """Vendor name similarity should match (Step 3 fallback)."""
        mock_get_adapter.return_value = _make_mock_adapter()
        match = await resolve_vendor(
            sender_email="unknown@example.com",
            sender_name="TechNova Solutions",
            body_text="No vendor ID here",
        )
        assert match is not None
        assert match.vendor_id == "V-001"
        assert match.match_method == "NAME_SIMILARITY"
        assert match.match_confidence == 0.60
        assert match.vendor_tier.value == "gold"

    @pytest.mark.asyncio
    @patch("src.services.vendor_resolution.get_salesforce_adapter")
    async def test_no_match_returns_none(self, mock_get_adapter):
        """Unknown sender with no vendor ID should return None."""
        mock_get_adapter.return_value = _make_mock_adapter()
        match = await resolve_vendor(
            sender_email="nobody@nowhere.com",
            sender_name="Nobody",
            body_text="Generic question with no identifiers",
        )
        assert match is None

    @pytest.mark.asyncio
    @patch("src.services.vendor_resolution.get_salesforce_adapter")
    async def test_email_match_is_case_insensitive(self, mock_get_adapter):
        """Email matching should be case-insensitive (Salesforce handles it)."""
        adapter = _make_mock_adapter()
        # Override to handle uppercase — Salesforce SOQL is case-insensitive
        # but our mock needs to handle it explicitly
        original_fn = adapter.find_contact_by_email.side_effect

        def case_insensitive_find(email, **kwargs):
            return original_fn(email.lower(), **kwargs)

        adapter.find_contact_by_email = MagicMock(side_effect=case_insensitive_find)
        mock_get_adapter.return_value = adapter
        match = await resolve_vendor(
            sender_email="RAJESH.MEHTA@TECHNOVA.COM",
            sender_name="",
            body_text="",
        )
        assert match is not None
        assert match.vendor_id == "V-001"

    @pytest.mark.asyncio
    @patch("src.services.vendor_resolution.get_salesforce_adapter")
    async def test_salesforce_down_returns_none(self, mock_get_adapter):
        """If Salesforce adapter raises, resolve_vendor returns None gracefully."""
        from src.adapters.salesforce import SalesforceAdapterError

        adapter = _make_mock_adapter()
        adapter.find_contact_by_email.side_effect = SalesforceAdapterError("down")
        adapter.find_account_by_name.side_effect = SalesforceAdapterError("down")
        mock_get_adapter.return_value = adapter
        match = await resolve_vendor(
            sender_email="rajesh.mehta@technova.com",
            sender_name="Rajesh Mehta",
            body_text="",
        )
        # Should return None, not raise — graceful degradation
        assert match is None
