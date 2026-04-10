"""EventBridge adapter for VQMS.

All event publishing goes through real EventBridge using boto3.
No local fallback. The event bus name is read from environment
variables via settings.

The VQMS architecture defines 20 event types. Phase 2 publishes:
  - QueryReceived (portal intake)
  - EmailIngested (email intake)

For testing, use moto to mock EventBridge calls.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from src.utils.helpers import IST

import boto3
from botocore.exceptions import ClientError

from config.settings import get_settings

logger = logging.getLogger(__name__)

# Lazy-initialized EventBridge client
_events_client = None


def _get_events_client():
    """Get or create the boto3 EventBridge client."""
    global _events_client  # noqa: PLW0603
    if _events_client is None:
        settings = get_settings()
        _events_client = boto3.client("events", region_name=settings.aws_region)
    return _events_client


async def publish_event(
    detail_type: str,
    detail: dict,
    *,
    correlation_id: str | None = None,
) -> str:
    """Publish an event to EventBridge.

    Args:
        detail_type: Event type name (e.g., "QueryReceived", "EmailIngested").
        detail: Event payload dict.
        correlation_id: Tracing ID, included in the event detail.

    Returns:
        EventBridge event ID.

    Raises:
        ClientError: If EventBridge rejects the request.
    """
    settings = get_settings()
    client = _get_events_client()

    # Include correlation_id and timestamp in the event detail
    enriched_detail = {
        **detail,
        "correlation_id": correlation_id,
        "time": datetime.now(IST).isoformat(),
    }

    try:
        response = client.put_events(
            Entries=[
                {
                    "Source": settings.eventbridge_source,
                    "DetailType": detail_type,
                    "Detail": json.dumps(enriched_detail, default=str),
                    "EventBusName": settings.eventbridge_bus_name,
                }
            ]
        )

        # Check for partial failures
        if response.get("FailedEntryCount", 0) > 0:
            failed = response["Entries"][0]
            logger.error(
                "EventBridge event failed",
                extra={
                    "tool": "eventbridge",
                    "detail_type": detail_type,
                    "error_code": failed.get("ErrorCode"),
                    "error_message": failed.get("ErrorMessage"),
                    "correlation_id": correlation_id,
                },
            )
            return ""

        event_id = response["Entries"][0]["EventId"]
        logger.info(
            "Published event to EventBridge",
            extra={
                "tool": "eventbridge",
                "detail_type": detail_type,
                "event_id": event_id,
                "correlation_id": correlation_id,
            },
        )
        return event_id

    except ClientError as err:
        error_code = err.response["Error"]["Code"]
        if error_code in ("AccessDenied", "AccessDeniedException"):
            logger.error(
                "EventBridge permission denied — check IAM policy",
                extra={
                    "tool": "eventbridge",
                    "detail_type": detail_type,
                    "error_code": error_code,
                    "correlation_id": correlation_id,
                },
            )
        raise


def reset_client() -> None:
    """Reset the EventBridge client. Used in tests with moto."""
    global _events_client  # noqa: PLW0603
    _events_client = None
