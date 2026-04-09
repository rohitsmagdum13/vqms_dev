"""SQS Consumer for VQMS AI Pipeline.

Polls the vqms-query-intake-queue for new query messages from
both the email and portal intake paths. Each message is
deserialized into a UnifiedQueryPayload and passed through
the LangGraph pipeline.

Message handling:
  - On success: delete the message from SQS
  - On failure: leave the message in the queue for retry
    (after 3 retries, SQS routes it to vqms-dlq)

The consumer runs as a background async task, started from
main.py lifespan or scripts/run_pipeline.py.
"""

from __future__ import annotations

import asyncio
import json
import logging

from botocore.exceptions import ClientError

from config.settings import get_settings
from src.orchestration.graph import PipelineState, build_pipeline_graph
from src.queues.sqs import _get_queue_url, _get_sqs_client
from src.utils.log_context import LogContext

logger = logging.getLogger(__name__)


async def start_consumer(
    *,
    shutdown_event: asyncio.Event | None = None,
) -> None:
    """Start the SQS consumer loop for the AI pipeline.

    Polls the query intake queue using long polling (20 seconds).
    Each message is processed through the full LangGraph pipeline.
    The consumer runs until the shutdown_event is set or the
    process is interrupted.

    Args:
        shutdown_event: Optional asyncio.Event to signal graceful
            shutdown. If None, runs until cancelled.
    """
    settings = get_settings()
    queue_name = settings.sqs_query_intake_queue

    logger.info(
        "SQS consumer starting",
        extra={"queue_name": queue_name},
    )

    # Build the pipeline graph once — reuse for all messages
    graph = build_pipeline_graph()

    # Resolve queue URL
    try:
        queue_url = _get_queue_url(queue_name)
    except ClientError:
        logger.error(
            "Failed to resolve queue URL — consumer cannot start",
            extra={"queue_name": queue_name},
            exc_info=True,
        )
        return

    logger.info(
        "SQS consumer ready — polling for messages",
        extra={"queue_name": queue_name, "queue_url": queue_url},
    )

    client = _get_sqs_client()

    while True:
        # Check for shutdown signal
        if shutdown_event and shutdown_event.is_set():
            logger.info("SQS consumer shutdown signal received")
            break

        try:
            # Long-poll for messages (20 second wait)
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: client.receive_message(
                    QueueUrl=queue_url,
                    MaxNumberOfMessages=1,
                    WaitTimeSeconds=20,
                    VisibilityTimeout=300,
                    MessageAttributeNames=["All"],
                ),
            )
        except ClientError:
            logger.error(
                "SQS receive_message failed — retrying in 5 seconds",
                extra={"queue_name": queue_name},
                exc_info=True,
            )
            await asyncio.sleep(5)
            continue

        messages = response.get("Messages", [])
        if not messages:
            continue

        for msg in messages:
            receipt_handle = msg["ReceiptHandle"]
            sqs_message_id = msg.get("MessageId", "unknown")

            # Extract correlation_id from message attributes if present
            attrs = msg.get("MessageAttributes", {})
            correlation_id = (
                attrs.get("correlation_id", {}).get("StringValue")
            )

            try:
                body = json.loads(msg["Body"])
            except json.JSONDecodeError:
                logger.error(
                    "Failed to parse SQS message body — deleting invalid message",
                    extra={"sqs_message_id": sqs_message_id},
                )
                await _delete_message(client, queue_url, receipt_handle)
                continue

            # Build initial pipeline state from the SQS message
            execution_id = body.get("execution_id", "")
            query_id = body.get("query_id", "")
            correlation_id = correlation_id or body.get("correlation_id", "")

            ctx = LogContext(
                correlation_id=correlation_id,
                execution_id=execution_id,
                query_id=query_id,
                agent_role="sqs_consumer",
            )

            logger.info(
                "Processing message from SQS",
                extra={**ctx.to_dict(), "sqs_message_id": sqs_message_id},
            )

            initial_state: PipelineState = {
                "payload": body,
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

            try:
                # Run the full pipeline
                result = await graph.ainvoke(initial_state)

                logger.info(
                    "Pipeline completed successfully",
                    extra={
                        **ctx.with_update(
                            status="COMPLETED",
                        ).to_dict(),
                        "selected_path": result.get("selected_path"),
                    },
                )

                # Delete the message on success
                await _delete_message(client, queue_url, receipt_handle)

            except Exception:
                # Do NOT delete — message will return after visibility
                # timeout and go to DLQ after 3 failures
                logger.error(
                    "Pipeline failed — leaving message for retry/DLQ",
                    extra={
                        **ctx.to_dict(),
                        "sqs_message_id": sqs_message_id,
                    },
                    exc_info=True,
                )


async def _delete_message(
    client: object,
    queue_url: str,
    receipt_handle: str,
) -> None:
    """Delete a successfully processed message from SQS."""
    try:
        await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: client.delete_message(
                QueueUrl=queue_url,
                ReceiptHandle=receipt_handle,
            ),
        )
    except ClientError:
        logger.error(
            "Failed to delete SQS message after successful processing",
            exc_info=True,
        )
