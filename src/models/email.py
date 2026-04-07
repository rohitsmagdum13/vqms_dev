"""Pydantic models for email data in VQMS.

These models define the shape of email messages as they flow
through the email ingestion pipeline — from raw MIME parsing
to the unified query payload that enters the AI pipeline.

Corresponds to:
  - intake.email_messages and intake.email_attachments tables
  - S3 buckets: vqms-email-raw-prod, vqms-email-attachments-prod
  - Steps E1-E2 in the VQMS Solution Flow Document
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from src.models.vendor import VendorMatch
from src.utils.helpers import utc_now


class EmailAttachment(BaseModel):
    """Metadata and content for an email attachment stored in S3.

    The actual file content is stored in the vqms-email-attachments-prod
    S3 bucket. This model tracks metadata and holds content bytes
    temporarily until they are uploaded to S3.
    """

    filename: str = Field(description="Original filename from the email")
    content_type: str = Field(
        default="application/octet-stream",
        description="MIME content type (e.g., 'application/pdf')",
    )
    size_bytes: int = Field(
        ge=0,
        description="File size in bytes",
    )
    s3_key: str | None = Field(
        default=None,
        description="S3 key where the attachment is stored",
    )
    checksum: str | None = Field(
        default=None,
        description="SHA-256 checksum for integrity verification",
    )
    content_bytes: bytes | None = Field(
        default=None,
        description="Raw file content — held temporarily until uploaded to S3",
        exclude=True,  # Never serialize content_bytes to JSON
    )


class EmailMessage(BaseModel):
    """Parsed email message from Exchange Online via Graph API.

    Contains all fields extracted from the raw MIME email.
    Thread correlation uses in_reply_to, references, and
    conversation_id to link related emails together.
    """

    # Identity and threading
    message_id: str = Field(
        description="RFC 2822 Message-ID — unique per email, used for idempotency",
    )
    conversation_id: str | None = Field(
        default=None,
        description="MS Graph conversation ID for thread correlation",
    )
    in_reply_to: str | None = Field(
        default=None,
        description="RFC 2822 In-Reply-To header for thread correlation",
    )
    references: list[str] = Field(
        default_factory=list,
        description="RFC 2822 References header — chain of parent message IDs",
    )

    # Sender and recipients
    sender_email: EmailStr = Field(
        description="Email address of the sender (used for vendor matching)",
    )
    sender_name: str | None = Field(
        default=None,
        description="Display name of the sender",
    )
    recipients: list[str] = Field(
        default_factory=list,
        description="To and CC email addresses (combined, kept for backward compat)",
    )
    to_addresses: list[str] = Field(
        default_factory=list,
        description="Direct To recipients (email addresses only)",
    )
    cc_addresses: list[str] = Field(
        default_factory=list,
        description="CC recipients (email addresses only)",
    )

    # Content
    subject: str = Field(description="Email subject line")
    body_text: str = Field(description="Plain text body extracted from MIME")
    body_html: str | None = Field(
        default=None,
        description="HTML body (kept for reference, not used for analysis)",
    )
    body_preview: str | None = Field(
        default=None,
        description="Short preview of the email body (first ~200 chars)",
    )

    # Metadata
    received_at: datetime = Field(description="When Exchange Online received the email")
    attachments: list[EmailAttachment] = Field(
        default_factory=list,
        description="List of attachment metadata",
    )
    raw_s3_key: str | None = Field(
        default=None,
        description="S3 key for the raw .eml file (compliance storage)",
    )
    is_auto_reply: bool = Field(
        default=False,
        description="True if Exchange flagged this as an auto-reply (OOF, read receipt, etc.)",
    )
    language: str | None = Field(
        default=None,
        description="Detected language code (e.g., 'en', 'fr'). "
        "From Graph API inferenceClassification or Comprehend in Phase 3.",
    )


class ParsedEmailPayload(BaseModel):
    """Complete parsed email ready for the AI pipeline.

    This is the output of the Email Ingestion Service (Steps E1-E2).
    It wraps the parsed email with VQMS-specific IDs and vendor
    match results, ready to be enqueued for orchestration.
    """

    email: EmailMessage = Field(description="The parsed email content")
    correlation_id: str = Field(description="UUID4 tracing ID for this email")
    query_id: str = Field(description="Human-readable ID (VQ-2026-XXXX)")
    execution_id: str = Field(description="UUID4 workflow execution ID")
    vendor_match: VendorMatch | None = Field(
        default=None,
        description="Vendor lookup result (None if unresolved)",
    )
    thread_status: str = Field(
        default="NEW",
        description="Thread correlation result: NEW, EXISTING_OPEN, or REPLY_TO_CLOSED",
    )
    is_duplicate: bool = Field(
        default=False,
        description="True if this message_id was already processed (idempotency check)",
    )
    created_at: datetime = Field(default_factory=utc_now)
