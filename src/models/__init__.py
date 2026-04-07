"""VQMS Pydantic data models.

Re-exports all public models and enums for convenient imports:
    from src.models import VendorMatch, AnalysisResult, CaseExecution
"""

from __future__ import annotations

from src.models.budget import Budget
from src.models.communication import (
    DraftEmailPackage,
    DraftResponse,
    ValidationReport,
)
from src.models.email import EmailAttachment, EmailMessage, ParsedEmailPayload
from src.models.memory import EmbeddingRecord, EpisodicMemory, VendorProfileCache
from src.models.messages import AgentMessage, ToolCall
from src.models.query import QuerySubmission, UnifiedQueryPayload
from src.models.ticket import RoutingDecision, TicketLink, TicketRecord
from src.models.triage import TriagePackage
from src.models.vendor import VendorMatch, VendorProfile, VendorTier
from src.models.workflow import (
    AnalysisResult,
    CaseExecution,
    Priority,
    QuerySource,
    QueryType,
    Sentiment,
    Status,
    UrgencyLevel,
    WorkflowState,
)

__all__ = [
    # Enums
    "Priority",
    "QuerySource",
    "QueryType",
    "Sentiment",
    "Status",
    "UrgencyLevel",
    "VendorTier",
    # Workflow
    "AnalysisResult",
    "CaseExecution",
    "WorkflowState",
    # Vendor
    "VendorMatch",
    "VendorProfile",
    # Email
    "EmailAttachment",
    "EmailMessage",
    "ParsedEmailPayload",
    # Query
    "QuerySubmission",
    "UnifiedQueryPayload",
    # Ticket
    "RoutingDecision",
    "TicketLink",
    "TicketRecord",
    # Communication
    "DraftEmailPackage",
    "DraftResponse",
    "ValidationReport",
    # Memory
    "EmbeddingRecord",
    "EpisodicMemory",
    "VendorProfileCache",
    # Budget
    "Budget",
    # Messages
    "AgentMessage",
    "ToolCall",
    # Triage
    "TriagePackage",
]
