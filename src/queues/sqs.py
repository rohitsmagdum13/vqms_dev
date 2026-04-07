"""SQS queue adapter for VQMS.

All queue operations go through real SQS using boto3. No
in-memory fallback. Pre-provisioned queues are read from
environment variables via settings.

Queue names referenced in the VQMS architecture:
  - vqms-query-intake-queue (portal submissions)
  - vqms-email-intake-queue (email ingestions)
  - Plus 9 more queues added in later phases

For testing, use moto to mock SQS calls.
"""

from __future__ import annotations

import json
import logging

import boto3
from botocore.exceptions import ClientError

from config.settings import get_settings

logger = logging.getLogger(__name__)

# Lazy-initialized SQS client and queue URL cache
_sqs_client = None
_queue_url_cache: dict[str, str] = {}


def _get_sqs_client():
    """Get or create the boto3 SQS client."""
    global _sqs_client  # noqa: PLW0603
    if _sqs_client is None:
        settings = get_settings()
        _sqs_client = boto3.client("sqs", region_name=settings.aws_region)
    return _sqs_client


def _get_queue_url(queue_name: str) -> str:
    """Resolve queue name to queue URL via SQS API.

    Caches the URL so we only call get_queue_url once per queue name.
    The queue must already exist (pre-provisioned by infra team).
    """
    if queue_name in _queue_url_cache:
        return _queue_url_cache[queue_name]

    client = _get_sqs_client()
    try:
        response = client.get_queue_url(QueueName=queue_name)
        url = response["QueueUrl"]
        _queue_url_cache[queue_name] = url
        return url
    except ClientError as err:
        error_code = err.response["Error"]["Code"]
        if error_code == "AWS.SimpleQueueService.NonExistentQueue":
            logger.error(
                "SQS queue does not exist — ask infra team to create it",
                extra={"queue_name": queue_name},
            )
        raise


async def publish(
    queue_name: str,
    message: dict,
    *,
    correlation_id: str | None = None,
) -> str:
    """Publish a message to an SQS queue.

    Args:
        queue_name: Name of the pre-provisioned SQS queue.
        message: Dict to be JSON-serialized as the message body.
        correlation_id: Tracing ID, sent as a message attribute.

    Returns:
        SQS MessageId of the published message.

    Raises:
        ClientError: If SQS rejects the request.
    """
    client = _get_sqs_client()
    queue_url = _get_queue_url(queue_name)

    body = json.dumps(message, default=str)

    # Send correlation_id as a message attribute for tracing
    attributes = {}
    if correlation_id:
        attributes["correlation_id"] = {
            "DataType": "String",
            "StringValue": correlation_id,
        }

    try:
        response = client.send_message(
            QueueUrl=queue_url,
            MessageBody=body,
            MessageAttributes=attributes,
        )
        message_id = response["MessageId"]
        logger.info(
            "Published to SQS",
            extra={
                "queue_name": queue_name,
                "message_id": message_id,
                "correlation_id": correlation_id,
            },
        )
        return message_id
    except ClientError as err:
        error_code = err.response["Error"]["Code"]
        if error_code in ("AccessDenied", "AccessDeniedException"):
            logger.error(
                "SQS permission denied — check IAM policy",
                extra={
                    "queue_name": queue_name,
                    "error_code": error_code,
                    "correlation_id": correlation_id,
                },
            )
        raise


async def consume(
    queue_name: str,
    *,
    max_messages: int = 1,
    wait_time_seconds: int = 0,
) -> dict | None:
    """Consume a single message from an SQS queue.

    Uses short polling by default (wait_time_seconds=0). For long
    polling in production consumers, set wait_time_seconds=20.

    Args:
        queue_name: Name of the pre-provisioned SQS queue.
        max_messages: Max messages to receive (default 1).
        wait_time_seconds: Long polling wait time (0 = short poll).

    Returns:
        Parsed message dict, or None if no messages available.
    """
    client = _get_sqs_client()
    queue_url = _get_queue_url(queue_name)

    try:
        response = client.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=max_messages,
            WaitTimeSeconds=wait_time_seconds,
            MessageAttributeNames=["All"],
        )

        messages = response.get("Messages", [])
        if not messages:
            return None

        msg = messages[0]
        body = json.loads(msg["Body"])

        # Delete the message after successful receive
        client.delete_message(
            QueueUrl=queue_url,
            ReceiptHandle=msg["ReceiptHandle"],
        )

        return body
    except ClientError as err:
        logger.error(
            "SQS consume failed",
            extra={"queue_name": queue_name, "error": str(err)},
        )
        raise


def get_queue_size(queue_name: str) -> int:
    """Get approximate number of messages in the queue."""
    client = _get_sqs_client()
    queue_url = _get_queue_url(queue_name)

    response = client.get_queue_attributes(
        QueueUrl=queue_url,
        AttributeNames=["ApproximateNumberOfMessages"],
    )
    return int(response["Attributes"]["ApproximateNumberOfMessages"])


def reset_client() -> None:
    """Reset the SQS client and URL cache. Used in tests with moto."""
    global _sqs_client, _queue_url_cache  # noqa: PLW0603
    _sqs_client = None
    _queue_url_cache = {}
