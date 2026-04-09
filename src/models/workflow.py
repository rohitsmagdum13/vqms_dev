"""Pydantic models for workflow state and shared enums.

This module contains the enums and models that track a query's
journey through the VQMS pipeline. The enums defined here
(Status, UrgencyLevel, Sentiment, QuerySource) are used across
many other model files.

Corresponds to the workflow.case_execution table in PostgreSQL
and the vqms:workflow:<execution_id> Redis key family.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from src.utils.helpers import utc_now

# --- Shared Enums ---
# These are used by models across multiple files, so they live
# here in workflow.py to avoid circular imports.


class Status(str, Enum):
    """Workflow status for a query as it moves through the pipeline.

    Each status corresponds to a step in the VQMS Solution Flow Document.
    The status is stored in workflow.case_execution and cached in Redis.
    """

    NEW = "new"
    ANALYZING = "analyzing"
    ROUTING = "routing"
    DRAFTING = "drafting"
    VALIDATING = "validating"
    SENDING = "sending"
    AWAITING_HUMAN_REVIEW = "awaiting_human_review"
    AWAITING_TEAM_RESOLUTION = "awaiting_team_resolution"
    RESOLVED = "resolved"
    CLOSED = "closed"
    REOPENED = "reopened"
    FAILED = "failed"
    DRAFT_REJECTED = "draft_rejected"


class UrgencyLevel(str, Enum):
    """Urgency classification from the Query Analysis Agent.

    Urgency affects SLA targets and escalation speed.
    CRITICAL triggers immediate escalation regardless of confidence.
    """

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Sentiment(str, Enum):
    """Vendor sentiment detected by the Query Analysis Agent.

    Used for tone-matching in email drafts and for flagging
    frustrated vendors for priority handling.
    """

    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"
    FRUSTRATED = "frustrated"
    ANGRY = "angry"


class QuerySource(str, Enum):
    """How a query entered the VQMS system.

    EMAIL: Vendor sent to vendor-support@company.com (Graph API)
    PORTAL: Vendor submitted via the VQMS web portal (Cognito + API)
    """

    EMAIL = "email"
    PORTAL = "portal"


class QueryType(str, Enum):
    """Classification of the vendor's query type.

    Used by the portal submission form and by the Query Analysis
    Agent when classifying email queries.
    """

    BILLING = "billing"
    TECHNICAL = "technical"
    FEATURE_REQUEST = "feature_request"
    ACCOUNT = "account"
    COMPLIANCE = "compliance"
    OTHER = "other"


class Priority(str, Enum):
    """Priority level set by the vendor (portal) or inferred by AI (email)."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# --- Models ---


class AnalysisResult(BaseModel):
    """Output of the Query Analysis Agent (LLM Call #1, Step 8).

    Contains the AI's understanding of what the vendor is asking,
    how urgent it is, and how confident the AI is in its analysis.
    Confidence >= 0.85 continues to routing; < 0.85 routes to Path C.
    """

    intent_classification: str = Field(
        description="What the vendor is asking about (e.g., 'invoice_status')",
    )
    extracted_entities: dict[str, Any] = Field(
        default_factory=dict,
        description="Named entities found: invoice numbers, dates, amounts, PO numbers",
    )
    urgency_level: UrgencyLevel = Field(
        default=UrgencyLevel.MEDIUM,
        description="How urgent the query is — affects SLA and escalation",
    )
    sentiment: Sentiment = Field(
        default=Sentiment.NEUTRAL,
        description="Vendor's emotional tone — affects email draft tone",
    )
    confidence_score: float = Field(
        ge=0.0,
        le=1.0,
        description="AI confidence in this analysis (0.0-1.0). Below 0.85 triggers Path C",
    )
    multi_issue_detected: bool = Field(
        default=False,
        description="True if the query contains multiple distinct issues",
    )
    suggested_category: str | None = Field(
        default=None,
        description="KB category for filtering search results",
    )
    raw_llm_output: str | None = Field(
        default=None,
        description="Raw LLM response text — stored for audit trail",
    )
    tokens_in: int | None = Field(
        default=None,
        description="Input tokens consumed by the LLM call",
    )
    tokens_out: int | None = Field(
        default=None,
        description="Output tokens produced by the LLM call",
    )
    cost_usd: float | None = Field(
        default=None,
        description="Estimated cost in USD for this LLM call",
    )
    latency_ms: float | None = Field(
        default=None,
        description="Wall-clock time in milliseconds for the LLM call",
    )
    provider: str | None = Field(
        default=None,
        description="LLM provider used: 'bedrock' or 'openai'",
    )
    was_fallback: bool | None = Field(
        default=None,
        description="True if the primary provider failed and fallback was used",
    )


class WorkflowState(BaseModel):
    """Current workflow state cached in Redis for fast access.

    This is a lightweight view of the case_execution record,
    stored at vqms:workflow:<execution_id> with 24-hour TTL.
    """

    execution_id: str = Field(description="UUID4 for this workflow execution")
    query_id: str = Field(description="Human-readable query ID (VQ-2026-XXXX)")
    status: Status = Field(description="Current step in the pipeline")
    source: QuerySource = Field(description="How the query entered the system")
    current_phase: str = Field(
        default="intake",
        description="Human-readable phase name for logging",
    )
    selected_path: str | None = Field(
        default=None,
        description="A, B, or C — set after routing decision",
    )
    analysis_result: AnalysisResult | None = Field(
        default=None,
        description="Result from Query Analysis Agent (set at Step 8)",
    )
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class CaseExecution(BaseModel):
    """Central state record for a query — maps to workflow.case_execution table.

    Every query that enters VQMS (email or portal) creates one
    CaseExecution record. This is the single source of truth for
    "what happened to this query" and is used for dashboard views,
    audit trails, and SLA tracking.
    """

    execution_id: str = Field(description="UUID4 primary key")
    query_id: str = Field(description="Human-readable ID (VQ-2026-XXXX)")
    correlation_id: str = Field(description="UUID4 tracing ID across all services")
    status: Status = Field(
        default=Status.NEW,
        description="Current workflow status",
    )
    source: QuerySource = Field(description="EMAIL or PORTAL")
    vendor_id: str | None = Field(
        default=None,
        description="Salesforce Account ID (may be null if UNRESOLVED)",
    )
    analysis_result: dict[str, Any] | None = Field(
        default=None,
        description="Serialized AnalysisResult JSON",
    )
    routing_decision: dict[str, Any] | None = Field(
        default=None,
        description="Serialized RoutingDecision JSON",
    )
    selected_path: str | None = Field(
        default=None,
        description="A (AI-resolved), B (human-team), or C (low-confidence review)",
    )
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = Field(
        default=None,
        description="When the case was closed or resolved",
    )
