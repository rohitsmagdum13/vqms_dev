"""Pydantic models for query submissions in VQMS.

Two entry points, one unified payload:
  - QuerySubmission: what the portal sends (POST /queries)
  - UnifiedQueryPayload: the normalized payload that both email
    and portal paths produce before entering the AI pipeline

Corresponds to Steps P1-P6 (portal) and the SQS queue messages
(vqms-email-intake-queue and vqms-query-intake-queue).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from src.models.workflow import Priority, QuerySource, QueryType
from src.utils.helpers import ist_now


class QuerySubmission(BaseModel):
    """Portal query submission payload (POST /queries).

    This is what the React frontend sends when a vendor submits
    a query through the VQMS portal wizard form.

    IMPORTANT: vendor_id is NOT in this model — it is extracted
    from the JWT token on the server side (Step P6). Never trust
    vendor identity from the request body.
    """

    query_type: QueryType = Field(
        description="Type of query selected in the wizard form",
    )
    subject: str = Field(
        min_length=1,
        max_length=500,
        description="Query subject line entered by the vendor",
    )
    description: str = Field(
        min_length=1,
        max_length=10000,
        description="Detailed description of the query",
    )
    priority: Priority = Field(
        default=Priority.MEDIUM,
        description="Priority level selected by the vendor",
    )
    reference_number: str | None = Field(
        default=None,
        max_length=100,
        description="Optional reference: invoice number, PO number, ticket ID",
    )
    attachments: list[str] = Field(
        default_factory=list,
        description="List of uploaded attachment S3 keys",
    )


class UnifiedQueryPayload(BaseModel):
    """Normalized query payload for the AI pipeline.

    Both entry points (email and portal) produce this same structure
    before enqueueing to SQS. The LangGraph orchestrator consumes
    this from either vqms-email-intake-queue or vqms-query-intake-queue
    and processes it identically regardless of source.
    """

    # VQMS identifiers — generated at intake
    query_id: str = Field(description="Human-readable ID (VQ-2026-XXXX)")
    execution_id: str = Field(description="UUID4 workflow execution ID")
    correlation_id: str = Field(description="UUID4 tracing ID across all services")

    # Origin
    source: QuerySource = Field(description="EMAIL or PORTAL")
    vendor_id: str | None = Field(
        default=None,
        description="Salesforce Account ID (from JWT for portal, from lookup for email)",
    )
    vendor_name: str | None = Field(
        default=None,
        description="Vendor company name (if resolved)",
    )

    # Query content
    subject: str = Field(description="Query subject line")
    description: str = Field(description="Full query text / email body")
    query_type: QueryType | None = Field(
        default=None,
        description="Query type (set by portal, inferred by AI for email)",
    )
    priority: Priority | None = Field(
        default=None,
        description="Priority (set by portal, inferred by AI for email)",
    )
    reference_number: str | None = Field(
        default=None,
        description="Invoice number, PO number, or other reference",
    )

    # Email-specific fields (null for portal queries)
    thread_status: str | None = Field(
        default=None,
        description="NEW, EXISTING_OPEN, or REPLY_TO_CLOSED (email path only)",
    )
    message_id: str | None = Field(
        default=None,
        description="RFC 2822 Message-ID (email path only)",
    )

    # Metadata
    received_at: datetime = Field(default_factory=ist_now)
