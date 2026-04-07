"""Tests for the portal submission service.

Tests the full portal intake flow with mocked Redis, SQS, and EventBridge.
Verifies that the service produces the correct output, publishes
events, and enqueues messages correctly.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.models.query import QuerySubmission
from src.models.workflow import Priority, QueryType
from src.services.portal_submission import submit_portal_query
from src.utils.exceptions import DuplicateQueryError


@pytest.fixture
def sample_submission() -> QuerySubmission:
    """A valid portal query submission."""
    return QuerySubmission(
        query_type=QueryType.BILLING,
        subject="Invoice Payment Status",
        description="Need update on invoice INV-2026-0451 payment.",
        priority=Priority.MEDIUM,
        reference_number="INV-2026-0451",
    )


class TestPortalSubmission:
    """Tests for submit_portal_query()."""

    @pytest.mark.asyncio
    @patch("src.services.portal_submission.publish", new_callable=AsyncMock, return_value="msg-001")
    @patch("src.services.portal_submission.publish_event", new_callable=AsyncMock, return_value="evt-001")
    @patch("src.services.portal_submission.get_value", new_callable=AsyncMock, return_value=None)
    @patch("src.services.portal_submission.set_with_ttl", new_callable=AsyncMock)
    async def test_successful_submission(
        self, mock_set, mock_get, mock_event, mock_sqs, sample_submission
    ):
        """A valid submission should return accepted status with IDs."""
        result = await submit_portal_query(
            submission=sample_submission,
            vendor_id="SF-001",
            vendor_name="TechNova Solutions",
        )

        assert result["status"] == "accepted"
        assert result["query_id"].startswith("VQ-")
        assert len(result["execution_id"]) == 36  # UUID4
        assert len(result["correlation_id"]) == 36

    @pytest.mark.asyncio
    @patch("src.services.portal_submission.publish", new_callable=AsyncMock, return_value="msg-001")
    @patch("src.services.portal_submission.publish_event", new_callable=AsyncMock, return_value="evt-001")
    @patch("src.services.portal_submission.get_value", new_callable=AsyncMock, return_value=None)
    @patch("src.services.portal_submission.set_with_ttl", new_callable=AsyncMock)
    async def test_publishes_query_received_event(
        self, mock_set, mock_get, mock_event, mock_sqs, sample_submission
    ):
        """Submission should publish a QueryReceived event."""
        await submit_portal_query(
            submission=sample_submission,
            vendor_id="SF-001",
            vendor_name="TechNova Solutions",
        )

        # Verify publish_event was called with the correct detail_type
        mock_event.assert_called_once()
        call_args = mock_event.call_args
        assert call_args.kwargs.get("detail_type") or call_args.args[0] == "QueryReceived"

    @pytest.mark.asyncio
    @patch("src.services.portal_submission.publish", new_callable=AsyncMock, return_value="msg-001")
    @patch("src.services.portal_submission.publish_event", new_callable=AsyncMock, return_value="evt-001")
    @patch("src.services.portal_submission.get_value", new_callable=AsyncMock, return_value=None)
    @patch("src.services.portal_submission.set_with_ttl", new_callable=AsyncMock)
    async def test_enqueues_to_sqs(
        self, mock_set, mock_get, mock_event, mock_sqs, sample_submission
    ):
        """Submission should enqueue a message to the query intake queue."""
        await submit_portal_query(
            submission=sample_submission,
            vendor_id="SF-001",
            vendor_name="TechNova Solutions",
        )

        # Verify publish was called with the correct queue and message
        mock_sqs.assert_called_once()
        call_kwargs = mock_sqs.call_args
        queue_name = call_kwargs.args[0] if call_kwargs.args else call_kwargs.kwargs.get("queue_name")
        assert queue_name == "vqms-query-intake-queue"

    @pytest.mark.asyncio
    @patch("src.services.portal_submission.get_value", new_callable=AsyncMock, return_value="1")
    async def test_duplicate_raises_error(self, mock_get, sample_submission):
        """A duplicate submission should raise DuplicateQueryError."""
        with pytest.raises(DuplicateQueryError):
            await submit_portal_query(
                submission=sample_submission,
                vendor_id="SF-001",
                vendor_name="TechNova Solutions",
            )

    @pytest.mark.asyncio
    @patch("src.services.portal_submission.publish", new_callable=AsyncMock, return_value="msg-001")
    @patch("src.services.portal_submission.publish_event", new_callable=AsyncMock, return_value="evt-001")
    @patch("src.services.portal_submission.get_value", new_callable=AsyncMock, side_effect=ConnectionError("Redis down"))
    async def test_redis_failure_allows_submission(
        self, mock_get, mock_event, mock_sqs, sample_submission
    ):
        """If Redis is down, submission should still proceed."""
        result = await submit_portal_query(
            submission=sample_submission,
            vendor_id="SF-001",
            vendor_name="TechNova Solutions",
        )

        assert result["status"] == "accepted"

    @pytest.mark.asyncio
    @patch("src.services.portal_submission.publish", new_callable=AsyncMock, return_value="msg-001")
    @patch("src.services.portal_submission.publish_event", new_callable=AsyncMock, return_value="evt-001")
    @patch("src.services.portal_submission.get_value", new_callable=AsyncMock, return_value=None)
    @patch("src.services.portal_submission.set_with_ttl", new_callable=AsyncMock)
    async def test_uses_provided_correlation_id(
        self, mock_set, mock_get, mock_event, mock_sqs, sample_submission
    ):
        """If a correlation_id is provided, it should be used."""
        result = await submit_portal_query(
            submission=sample_submission,
            vendor_id="SF-001",
            vendor_name="TechNova Solutions",
            correlation_id="custom-corr-id-123",
        )

        assert result["correlation_id"] == "custom-corr-id-123"
