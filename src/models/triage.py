"""Pydantic model for Path C human review triage package.

When the Query Analysis Agent's confidence is below 0.85,
the workflow pauses and creates a TriagePackage for a human
reviewer. The package contains everything the reviewer needs
to correct the classification and resume the workflow.

Corresponds to:
  - Steps 8C.1-8C.3 in the Solution Flow Document
  - vqms-human-review-queue (SQS)
  - GET /triage/queue and POST /triage/{id}/review API endpoints
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from src.models.communication import DraftResponse
from src.models.query import UnifiedQueryPayload
from src.models.ticket import RoutingDecision
from src.models.vendor import VendorMatch
from src.models.workflow import AnalysisResult
from src.utils.helpers import ist_now


class ReviewStatus(str):
    """Constants for triage review status values."""

    PENDING = "pending"
    APPROVED = "approved"
    CORRECTED = "corrected"
    REJECTED = "rejected"


class TriagePackage(BaseModel):
    """Complete context package for human reviewer (Path C).

    When confidence < 0.85, the workflow creates this package
    with everything a reviewer needs:
      - The original query
      - AI's analysis (with confidence breakdown showing why it's low)
      - Vendor match result
      - What the system would do if it proceeded automatically
      - An optional draft (if AI generated one before confidence check)

    The reviewer corrects any misclassifications and submits,
    which resumes the workflow via Step Functions SendTaskSuccess.
    """

    # Identifiers
    triage_id: str = Field(description="UUID4 unique ID for this triage package")
    execution_id: str = Field(description="VQMS execution ID")
    correlation_id: str = Field(description="UUID4 tracing ID")

    # Context for the reviewer
    original_query: UnifiedQueryPayload = Field(
        description="The full query payload as submitted",
    )
    analysis_result: AnalysisResult = Field(
        description="AI's analysis — reviewer can correct these fields",
    )
    vendor_match: VendorMatch | None = Field(
        default=None,
        description="Vendor lookup result (reviewer can correct vendor assignment)",
    )
    suggested_routing: RoutingDecision | None = Field(
        default=None,
        description="What routing the system would apply (reviewer can override)",
    )
    confidence_breakdown: dict[str, float] = Field(
        default_factory=dict,
        description="Why confidence is low: analysis_confidence, vendor_confidence, etc.",
    )
    suggested_draft: DraftResponse | None = Field(
        default=None,
        description="Draft email if AI generated one before the confidence check",
    )

    # Workflow control
    step_functions_token: str | None = Field(
        default=None,
        description="AWS Step Functions callback token for resuming the workflow",
    )

    # Review state
    review_status: str = Field(
        default=ReviewStatus.PENDING,
        description="Current review state: pending, approved, corrected, or rejected",
    )
    reviewer_id: str | None = Field(
        default=None,
        description="Cognito user ID of the reviewer (set when review is submitted)",
    )
    reviewer_notes: str | None = Field(
        default=None,
        description="Optional notes from the reviewer explaining corrections",
    )

    # Timestamps
    created_at: datetime = Field(default_factory=ist_now)
    reviewed_at: datetime | None = Field(
        default=None,
        description="When the review was submitted",
    )
