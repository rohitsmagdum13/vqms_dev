"""Microsoft Graph API webhook route for email ingestion.

POST /webhooks/ms-graph — Receives email notifications from
Microsoft Graph subscription.

Two modes:
  1. Subscription validation: Graph sends validationToken,
     we echo it back as plain text.
  2. Change notification: Graph sends a list of changed resources,
     we process each one through the email intake service.

Corresponds to Step E2.1 in the VQMS Solution Flow Document.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel

from src.services.email_intake import process_email_notification
from src.utils.exceptions import DuplicateQueryError
from src.utils.logger import log_api_call

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhooks"])


# --- Request Models ---


class GraphNotificationValue(BaseModel):
    """A single change notification from Microsoft Graph."""

    resource: str
    changeType: str | None = None  # noqa: N815 — matches Graph API field name
    clientState: str | None = None  # noqa: N815
    subscriptionId: str | None = None  # noqa: N815
    tenantId: str | None = None  # noqa: N815


class GraphNotificationPayload(BaseModel):
    """Wrapper for Microsoft Graph change notifications.

    Graph sends an array of notifications in the 'value' field.
    In practice, we usually get one notification per request.
    """

    value: list[GraphNotificationValue]


@router.post("/webhooks/ms-graph", status_code=202, response_model=None)
@log_api_call
async def handle_graph_notification(
    payload: GraphNotificationPayload | None = None,
    validationToken: str | None = Query(default=None),  # noqa: N803
) -> Response | dict:
    """Handle Microsoft Graph webhook notifications.

    Two scenarios:
      1. Subscription validation: returns validationToken as plain text.
      2. Change notification: processes each resource through email intake.

    Returns:
        200 + plain text: For subscription validation.
        202: Notification accepted and processing started.
        400: Invalid payload (no notifications and no validationToken).
        409: Duplicate email detected (already processed).
    """
    # --- Subscription Validation ---
    # Graph sends validationToken as a query parameter when setting up
    # or renewing a webhook subscription. We must echo it back.
    if validationToken is not None:
        logger.info("Graph webhook subscription validation request")
        return Response(
            content=validationToken,
            media_type="text/plain",
            status_code=200,
        )

    # --- Change Notification ---
    if payload is None or not payload.value:
        raise HTTPException(
            status_code=400,
            detail="Invalid notification: no value array provided.",
        )

    results = []
    for notification in payload.value:
        try:
            result = await process_email_notification(
                resource=notification.resource,
            )
            results.append(result)
        except DuplicateQueryError as err:
            # Log but don't fail the whole batch — Graph may retry
            logger.info(
                "Duplicate email in notification batch",
                extra={"resource": notification.resource, "identifier": err.identifier},
            )
            results.append({"resource": notification.resource, "status": "duplicate"})

    return {"status": "accepted", "processed": len(results), "results": results}
