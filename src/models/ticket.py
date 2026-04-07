"""Pydantic models for ticket operations in VQMS.

These models define ServiceNow ticket records, the link between
VQMS queries and ServiceNow incidents, and routing decisions
that determine team assignment and SLA targets.

Corresponds to:
  - workflow.ticket_link and workflow.routing_decision tables
  - ServiceNow incident table (external)
  - Steps 9A (routing) and 12 (ticket creation)
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from src.models.vendor import VendorTier
from src.models.workflow import UrgencyLevel
from src.utils.helpers import utc_now


class TicketRecord(BaseModel):
    """Representation of a ServiceNow incident ticket.

    Created by the Ticket Operations Service (Step 12) after
    the Quality Gate passes. For Path A, the team monitors.
    For Path B, the team investigates.
    """

    ticket_id: str = Field(description="ServiceNow sys_id")
    ticket_number: str = Field(description="ServiceNow incident number (e.g., INC0012345)")
    execution_id: str = Field(description="VQMS execution ID linking to case_execution")
    vendor_id: str = Field(description="Salesforce Account ID of the vendor")
    subject: str = Field(description="Ticket short description")
    description: str = Field(description="Ticket detailed description")
    status: str = Field(
        default="new",
        description="ServiceNow incident state",
    )
    assignment_group: str = Field(description="Team assigned to handle the ticket")
    priority: str = Field(
        default="medium",
        description="ServiceNow priority level",
    )
    sla_target_hours: float = Field(
        description="SLA target in hours based on vendor tier + urgency",
    )
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class TicketLink(BaseModel):
    """Link between a VQMS query execution and a ServiceNow ticket.

    A single execution can link to multiple tickets (e.g., when
    a ticket is reopened or a new linked ticket is created).
    Stored in workflow.ticket_link table.
    """

    execution_id: str = Field(description="VQMS execution ID")
    ticket_id: str = Field(description="ServiceNow ticket sys_id")
    link_type: str = Field(
        description="Relationship type: CREATED, UPDATED, or REOPENED",
    )
    created_at: datetime = Field(default_factory=utc_now)


class RoutingDecision(BaseModel):
    """Output of the deterministic Routing Service (Step 9A).

    Evaluates confidence score, urgency, vendor tier, and flags
    to determine: which team handles this, what the SLA target is,
    and whether to block automation (route to human review).
    """

    execution_id: str = Field(description="VQMS execution ID")
    assigned_team: str = Field(description="Team name for ServiceNow assignment")
    routing_reason: str = Field(
        description="Human-readable explanation of why this team was chosen",
    )
    sla_hours: float = Field(
        description="SLA target in hours (e.g., 4.0 for Gold + High)",
    )
    vendor_tier: VendorTier = Field(description="Vendor's SLA tier")
    urgency_level: UrgencyLevel = Field(description="Query urgency from analysis")
    confidence_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Analysis confidence that determined routing",
    )
    path: str = Field(
        description="Processing path: A (AI-resolved), B (human-team), or C (low-confidence)",
    )
    automation_blocked: bool = Field(
        default=False,
        description="True if automation is blocked (CRITICAL urgency, BLOCK_AUTOMATION flag)",
    )
    created_at: datetime = Field(default_factory=utc_now)
