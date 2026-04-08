"""Pydantic response models for the Email Dashboard API.

These models define the exact JSON shape returned by the email
dashboard endpoints. The frontend TypeScript types are the source
of truth — these models must produce JSON that matches them exactly.

TypeScript contract:
  - UserResponse      -> User { name, email }
  - AttachmentResponse -> Attachment { name, size, file_format, url }
  - MailItemResponse   -> MailItem { from, to, cc, subject, body, timestamp, attachments }
  - MailChainResponse  -> MailChain { mail_items, status, priority }

IMPORTANT: MailItemResponse uses Field(alias="from") so the JSON
output says "from" (matching TypeScript) instead of "from_user"
(which would conflict with Python's reserved keyword).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class UserResponse(BaseModel):
    """A person's name and email address.

    Maps to the TypeScript `User` type.
    """

    name: str = Field(description="Display name of the person")
    email: str = Field(description="Email address")


class AttachmentResponse(BaseModel):
    """Metadata for a single email attachment.

    Maps to the TypeScript `Attachment` type.
    """

    name: str = Field(description="Original filename (e.g., 'invoice_copy.pdf')")
    size: int = Field(description="File size in bytes")
    file_format: str = Field(description="Uppercase file extension: PDF, TXT, DOCX, etc.")
    url: str = Field(description="S3 URI for the attachment file")


class MailItemResponse(BaseModel):
    """A single email message with sender, recipients, and content.

    Maps to the TypeScript `MailItem` type.

    The 'from' field uses a Pydantic alias because 'from' is a
    Python reserved keyword. In JSON output, it serializes as "from"
    (not "from_user") thanks to by_alias=True in model_config.
    """

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    from_user: UserResponse = Field(
        alias="from",
        description="Email sender",
    )
    to: list[UserResponse] = Field(description="Direct recipients (To line)")
    cc: list[UserResponse] = Field(description="CC recipients")
    subject: str = Field(description="Email subject line")
    body: str = Field(description="Plain text email body")
    timestamp: str = Field(
        description="When the email was received, ISO 8601 with timezone",
    )
    attachments: list[AttachmentResponse] = Field(
        default_factory=list,
        description="Attachment metadata list",
    )


class MailChainResponse(BaseModel):
    """A thread of related emails with workflow status.

    Maps to the TypeScript `MailChain` type.
    mail_items are sorted newest first.

    NOTE (Phase 3 gap): Until the AI pipeline and routing
    engine are built (Phase 3), status will always be "New"
    and priority will always be "Medium". These values become
    meaningful after Phase 3 populates case_execution.status
    and routing_decision.urgency_level.
    """

    mail_items: list[MailItemResponse] = Field(
        description="Emails in this thread, sorted newest first",
    )
    status: str = Field(
        description="Dashboard status: 'New', 'Reopened', or 'Resolved'. "
        "NOTE: Always 'New' until Phase 3 (AI pipeline) is built.",
    )
    priority: str = Field(
        description="Priority level: 'High', 'Medium', or 'Low'. "
        "NOTE: Defaults to 'Medium' until Phase 3 (routing engine) is built.",
    )


class MailChainListResponse(BaseModel):
    """Paginated list of mail chains for the dashboard.

    Wraps MailChainResponse with pagination metadata.
    """

    total: int = Field(description="Total number of mail chains matching the filters")
    page: int = Field(description="Current page number (1-based)")
    page_size: int = Field(description="Number of items per page")
    mail_chains: list[MailChainResponse] = Field(
        description="Mail chains for this page",
    )


class EmailStatsResponse(BaseModel):
    """Aggregate statistics for the email dashboard summary cards."""

    total_emails: int = Field(description="Total number of email chains")
    new_count: int = Field(description="Count of chains with status 'New'")
    reopened_count: int = Field(description="Count of chains with status 'Reopened'")
    resolved_count: int = Field(description="Count of chains with status 'Resolved'")
    priority_breakdown: dict[str, int] = Field(
        description="Count per priority level: {'High': N, 'Medium': N, 'Low': N}",
    )
    today_count: int = Field(description="Chains received today")
    this_week_count: int = Field(description="Chains received in the last 7 days")


class AttachmentDownloadResponse(BaseModel):
    """Presigned S3 URL for downloading an attachment."""

    download_url: str = Field(description="Presigned S3 URL (expires in 1 hour)")
