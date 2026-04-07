"""Pydantic models for email drafting and validation in VQMS.

These models define the shape of AI-generated email drafts,
complete email packages ready for delivery, and quality gate
validation reports.

Corresponds to:
  - Steps 10A (Resolution Agent), 10B (Communication Agent),
    and 11 (Quality & Governance Gate)
  - audit.validation_results table
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from src.utils.helpers import utc_now


class DraftResponse(BaseModel):
    """AI-generated email draft from Resolution or Communication Agent.

    Path A: Resolution Agent produces a RESOLUTION draft with
    specific facts from KB articles.
    Path B: Communication Agent produces an ACKNOWLEDGMENT draft
    (no answer, just confirmation and ticket number).
    Path B (later): Communication Agent produces a RESOLUTION_FROM_NOTES
    draft using the human team's investigation findings.
    """

    subject: str = Field(
        min_length=1,
        description="Email subject line for the vendor",
    )
    body: str = Field(
        min_length=1,
        description="Email body text (50-500 words expected by Quality Gate)",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="AI confidence in this draft quality",
    )
    sources: list[str] = Field(
        default_factory=list,
        description="KB article IDs or source references used in the draft",
    )
    draft_type: str = Field(
        description="RESOLUTION (Path A), ACKNOWLEDGMENT (Path B), or RESOLUTION_FROM_NOTES (Path B later)",
    )


class DraftEmailPackage(BaseModel):
    """Complete email package ready for Quality Gate and delivery.

    Wraps a DraftResponse with all the metadata needed to send
    the email via MS Graph API and create the audit trail.
    """

    execution_id: str = Field(description="VQMS execution ID")
    correlation_id: str = Field(description="UUID4 tracing ID")
    draft: DraftResponse = Field(description="The AI-generated draft")
    vendor_email: str = Field(description="Recipient email address")
    vendor_name: str = Field(description="Vendor company name for personalization")
    ticket_number: str = Field(
        description="ServiceNow ticket number to include in the email",
    )
    created_at: datetime = Field(default_factory=utc_now)


class ValidationReport(BaseModel):
    """Result of the Quality & Governance Gate (Step 11).

    The gate runs 7 checks on every outgoing email:
    1. Ticket number format correctness
    2. SLA wording matches vendor tier policy
    3. Required sections present
    4. Restricted terms scan
    5. Response length (50-500 words)
    6. Source citations check
    7. PII scan via Amazon Comprehend (for HIGH+ priority)

    Max 2 re-drafts before routing to human review.
    """

    execution_id: str = Field(description="VQMS execution ID")
    passed: bool = Field(description="True if all checks passed")
    checks_run: list[str] = Field(
        default_factory=list,
        description="Names of checks that were executed",
    )
    failures: list[str] = Field(
        default_factory=list,
        description="Specific check failures with details",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Non-blocking warnings for review",
    )
    pii_detected: bool = Field(
        default=False,
        description="True if PII was found in the draft (blocks sending)",
    )
    redraft_count: int = Field(
        default=0,
        description="How many re-drafts have been attempted (max 2)",
    )
    created_at: datetime = Field(default_factory=utc_now)
