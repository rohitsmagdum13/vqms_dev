"""Email Dashboard API routes.

GET /emails           — List email chains (paginated, filterable, sortable)
GET /emails/stats     — Dashboard summary statistics
GET /emails/{query_id} — Get a single email chain by query_id
GET /emails/{query_id}/attachments/{attachment_id}/download — Presigned download URL

These endpoints serve email data from PostgreSQL for the frontend
email dashboard. Response shapes match the TypeScript MailChain,
MailItem, User, and Attachment types exactly.

All endpoints are read-only. No auth required in dev mode
(TODO: Cognito JWT in Phase 7).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Header, HTTPException, Query

from src.models.email_dashboard import (
    AttachmentDownloadResponse,
    EmailStatsResponse,
    MailChainListResponse,
    MailChainResponse,
)
from src.services.email_dashboard_service import (
    fetch_email_stats,
    fetch_mail_chains,
    fetch_single_mail_chain,
    generate_attachment_download_url,
)
from src.utils.correlation import generate_correlation_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/emails", tags=["email-dashboard"])


@router.get("", response_model=MailChainListResponse)
async def list_email_chains(
    page: int = Query(default=1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    status: str | None = Query(
        default=None,
        description="Filter by status: 'New', 'Reopened', 'Resolved'",
    ),
    priority: str | None = Query(
        default=None,
        description="Filter by priority: 'High', 'Medium', 'Low'",
    ),
    search: str | None = Query(
        default=None,
        description="Search in subject and body text",
    ),
    sort_by: str = Query(
        default="timestamp",
        description="Sort field: 'timestamp', 'status', 'priority'",
    ),
    sort_order: str = Query(
        default="desc",
        description="Sort direction: 'asc' or 'desc'",
    ),
    x_correlation_id: str | None = Header(default=None),
) -> MailChainListResponse:
    """List email chains for the dashboard.

    Returns paginated, filterable, sortable email chains. Each
    chain groups related emails by query_id and includes status
    and priority from the workflow.

    Response matches the TypeScript MailChain[] type.
    """
    correlation_id = x_correlation_id or generate_correlation_id()

    # Validate filter values
    valid_statuses = {"New", "Reopened", "Resolved"}
    if status and status not in valid_statuses:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status filter. Must be one of: {', '.join(valid_statuses)}",
        )

    valid_priorities = {"High", "Medium", "Low"}
    if priority and priority not in valid_priorities:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid priority filter. Must be one of: {', '.join(valid_priorities)}",
        )

    valid_sort_fields = {"timestamp", "status", "priority"}
    if sort_by not in valid_sort_fields:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid sort_by. Must be one of: {', '.join(valid_sort_fields)}",
        )

    valid_sort_orders = {"asc", "desc"}
    if sort_order.lower() not in valid_sort_orders:
        raise HTTPException(
            status_code=422,
            detail="Invalid sort_order. Must be 'asc' or 'desc'.",
        )

    logger.info(
        "Listing email chains",
        extra={
            "page": page,
            "page_size": page_size,
            "status": status,
            "priority": priority,
            "search": search,
            "correlation_id": correlation_id,
        },
    )

    result = await fetch_mail_chains(
        page=page,
        page_size=page_size,
        status=status,
        priority=priority,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
        correlation_id=correlation_id,
    )

    return result


@router.get("/stats", response_model=EmailStatsResponse)
async def get_email_stats(
    x_correlation_id: str | None = Header(default=None),
) -> EmailStatsResponse:
    """Get aggregate statistics for the email dashboard.

    Returns total email count, counts by status, priority
    breakdown, and recent counts (today, this week).
    """
    correlation_id = x_correlation_id or generate_correlation_id()

    logger.info(
        "Fetching email stats",
        extra={"correlation_id": correlation_id},
    )

    return await fetch_email_stats(correlation_id=correlation_id)


@router.get("/{query_id}", response_model=MailChainResponse)
async def get_email_chain(
    query_id: str,
    x_correlation_id: str | None = Header(default=None),
) -> MailChainResponse:
    """Get a single email chain by query_id.

    Returns all emails in the thread, sorted newest first.
    Includes attachments for each email.

    Response matches the TypeScript MailChain type.
    """
    correlation_id = x_correlation_id or generate_correlation_id()

    logger.info(
        "Fetching email chain",
        extra={"query_id": query_id, "correlation_id": correlation_id},
    )

    chain = await fetch_single_mail_chain(
        query_id, correlation_id=correlation_id,
    )

    if chain is None:
        raise HTTPException(
            status_code=404,
            detail=f"Email chain not found for query_id: {query_id}",
        )

    return chain


@router.get(
    "/{query_id}/attachments/{attachment_id}/download",
    response_model=AttachmentDownloadResponse,
)
async def download_attachment(
    query_id: str,
    attachment_id: int,
    x_correlation_id: str | None = Header(default=None),
) -> AttachmentDownloadResponse:
    """Generate a presigned S3 URL for downloading an attachment.

    The URL expires after 1 hour. The attachment must belong to
    an email in the specified query chain.
    """
    correlation_id = x_correlation_id or generate_correlation_id()

    logger.info(
        "Generating attachment download URL",
        extra={
            "query_id": query_id,
            "attachment_id": attachment_id,
            "correlation_id": correlation_id,
        },
    )

    result = await generate_attachment_download_url(
        query_id=query_id,
        attachment_id=attachment_id,
        correlation_id=correlation_id,
    )

    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Attachment {attachment_id} not found for query {query_id}",
        )

    return result
