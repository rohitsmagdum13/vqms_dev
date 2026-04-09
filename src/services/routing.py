"""Routing Service for VQMS (Step 9A).

Deterministic rules engine — NO LLM calls. Pure business logic.
Evaluates the analysis result and vendor profile to determine:
  - Which team handles the query
  - What the SLA target is (in hours)
  - Whether automation should be blocked

The SLA matrix is based on vendor tier (PLATINUM/GOLD/SILVER/STANDARD)
crossed with urgency level (CRITICAL/HIGH/MEDIUM/LOW).

Corresponds to Step 9A in the VQMS Solution Flow Document.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import text

from src.db.connection import get_engine
from src.models.ticket import RoutingDecision
from src.models.vendor import VendorProfile, VendorTier
from src.models.workflow import AnalysisResult, UrgencyLevel
from src.utils.helpers import utc_now
from src.utils.log_context import LogContext

logger = logging.getLogger(__name__)


# --- SLA Matrix ---
# Maps (vendor_tier, urgency_level) → SLA target in hours.
# Higher tiers and higher urgencies get shorter SLAs.
SLA_MATRIX: dict[VendorTier, dict[UrgencyLevel, int]] = {
    VendorTier.PLATINUM: {
        UrgencyLevel.CRITICAL: 1,
        UrgencyLevel.HIGH: 2,
        UrgencyLevel.MEDIUM: 4,
        UrgencyLevel.LOW: 8,
    },
    VendorTier.GOLD: {
        UrgencyLevel.CRITICAL: 2,
        UrgencyLevel.HIGH: 4,
        UrgencyLevel.MEDIUM: 8,
        UrgencyLevel.LOW: 16,
    },
    VendorTier.SILVER: {
        UrgencyLevel.CRITICAL: 4,
        UrgencyLevel.HIGH: 4,
        UrgencyLevel.MEDIUM: 8,
        UrgencyLevel.LOW: 24,
    },
    VendorTier.STANDARD: {
        UrgencyLevel.CRITICAL: 4,
        UrgencyLevel.HIGH: 8,
        UrgencyLevel.MEDIUM: 24,
        UrgencyLevel.LOW: 48,
    },
}

# Default SLA when tier or urgency is unknown
DEFAULT_SLA_HOURS = 24


# --- Team Assignment ---
# Maps suggested_category from the analysis to a team name.
TEAM_ASSIGNMENT: dict[str, str] = {
    "invoice_payment": "Finance Team",
    "purchase_order": "Procurement Team",
    "contract": "Contract Team",
    "general": "General Support",
}

DEFAULT_TEAM = "General Support"


class RoutingError(Exception):
    """Raised when the routing rules engine encounters an unexpected error."""


def calculate_sla_hours(
    vendor_tier: VendorTier,
    urgency: UrgencyLevel,
) -> int:
    """Look up the SLA target hours from the tier × urgency matrix.

    Args:
        vendor_tier: Vendor's SLA tier from Salesforce.
        urgency: Urgency level from the Query Analysis Agent.

    Returns:
        SLA target in hours.
    """
    tier_sla = SLA_MATRIX.get(vendor_tier, SLA_MATRIX[VendorTier.STANDARD])
    return tier_sla.get(urgency, DEFAULT_SLA_HOURS)


def assign_team(suggested_category: str | None) -> str:
    """Determine which team handles this query based on category.

    Args:
        suggested_category: Category from the Query Analysis Agent.

    Returns:
        Team name string.
    """
    if not suggested_category:
        return DEFAULT_TEAM
    return TEAM_ASSIGNMENT.get(suggested_category.lower(), DEFAULT_TEAM)


def check_automation_blocked(
    analysis: AnalysisResult,
    vendor_profile: VendorProfile | None,
) -> bool:
    """Check if automation should be blocked for this query.

    Automation is blocked when:
      - The vendor has a BLOCK_AUTOMATION risk flag in Salesforce
      - (Other conditions can be added here in the future)

    Note: CRITICAL urgency does NOT block automation — it just
    triggers immediate escalation. The query can still be
    auto-resolved if KB has the answer.

    Args:
        analysis: Output from the Query Analysis Agent.
        vendor_profile: Vendor profile from Salesforce.

    Returns:
        True if automation should be blocked.
    """
    if vendor_profile and "BLOCK_AUTOMATION" in vendor_profile.risk_flags:
        return True
    return False


async def route_query(
    analysis: AnalysisResult,
    vendor_profile: VendorProfile | None,
    *,
    execution_id: str,
    correlation_id: str | None = None,
) -> RoutingDecision:
    """Execute the routing rules engine for a query.

    Evaluates the analysis result and vendor profile to determine
    team assignment, SLA target, and automation level. Writes the
    routing decision to the workflow.routing_decision table.

    Args:
        analysis: Output from the Query Analysis Agent.
        vendor_profile: Vendor profile (None if unresolved).
        execution_id: VQMS execution ID for this query.
        correlation_id: Tracing ID.

    Returns:
        RoutingDecision with team, SLA, and automation level.
    """
    # Determine vendor tier (default to STANDARD if no profile)
    vendor_tier = vendor_profile.vendor_tier if vendor_profile else VendorTier.STANDARD

    # Calculate SLA
    sla_hours = calculate_sla_hours(vendor_tier, analysis.urgency_level)
    sla_deadline = utc_now() + timedelta(hours=sla_hours)

    # Assign team
    team = assign_team(analysis.suggested_category)

    # Check automation blocking
    automation_blocked = check_automation_blocked(analysis, vendor_profile)

    # Build reasoning string
    risk_flags = vendor_profile.risk_flags if vendor_profile else []
    reasoning_parts = [
        f"Category: {analysis.suggested_category or 'unknown'} → Team: {team}",
        f"Tier: {vendor_tier.value} + Urgency: {analysis.urgency_level.value} → SLA: {sla_hours}h",
    ]
    if automation_blocked:
        reasoning_parts.append("Automation BLOCKED: BLOCK_AUTOMATION flag on vendor")
    if risk_flags:
        reasoning_parts.append(f"Risk flags: {', '.join(risk_flags)}")

    reasoning = ". ".join(reasoning_parts)

    decision = RoutingDecision(
        execution_id=execution_id,
        assigned_team=team,
        routing_reason=reasoning,
        sla_hours=sla_hours,
        sla_deadline=sla_deadline,
        vendor_tier=vendor_tier,
        urgency_level=analysis.urgency_level,
        confidence_score=analysis.confidence_score,
        path="",  # Set later by path_decision node
        automation_blocked=automation_blocked,
        risk_flags=risk_flags,
    )

    ctx = LogContext(
        correlation_id=correlation_id,
        execution_id=execution_id,
        agent_role="routing",
        step="STEP_9A",
    )

    policy = f"team={team}, sla={sla_hours}h, blocked={automation_blocked}"
    ctx = ctx.with_policy_decision(
        decision=policy,
        safety_flags=risk_flags if risk_flags else None,
    )

    logger.info(
        "Routing decision made",
        extra={
            **ctx.to_dict(),
            "team": team,
            "sla_hours": sla_hours,
            "automation_blocked": automation_blocked,
            "vendor_tier": vendor_tier.value,
            "urgency": analysis.urgency_level.value,
        },
    )

    # Write to database
    await _save_routing_decision(decision, correlation_id=correlation_id)

    return decision


async def _save_routing_decision(
    decision: RoutingDecision,
    *,
    correlation_id: str | None = None,
) -> None:
    """Persist the routing decision to workflow.routing_decision table."""
    engine = get_engine()
    if engine is None:
        logger.warning(
            "Database not available — skipping routing decision save",
            extra={"execution_id": decision.execution_id, "correlation_id": correlation_id},
        )
        return

    sql = text(
        "INSERT INTO workflow.routing_decision "
        "(execution_id, assigned_team, routing_reason, sla_hours, "
        " vendor_tier, urgency_level, confidence_score, path, automation_blocked) "
        "VALUES (:execution_id, :assigned_team, :routing_reason, :sla_hours, "
        " :vendor_tier, :urgency_level, :confidence_score, :path, :automation_blocked)"
    )

    try:
        async with engine.begin() as conn:
            await conn.execute(
                sql,
                {
                    "execution_id": decision.execution_id,
                    "assigned_team": decision.assigned_team,
                    "routing_reason": decision.routing_reason,
                    "sla_hours": decision.sla_hours,
                    "vendor_tier": decision.vendor_tier.value,
                    "urgency_level": decision.urgency_level.value,
                    "confidence_score": decision.confidence_score,
                    "path": decision.path,
                    "automation_blocked": decision.automation_blocked,
                },
            )
        logger.info(
            "Routing decision saved to database",
            extra={
                "execution_id": decision.execution_id,
                "correlation_id": correlation_id,
            },
        )
    except Exception:
        logger.error(
            "Failed to save routing decision to database",
            extra={
                "execution_id": decision.execution_id,
                "correlation_id": correlation_id,
            },
            exc_info=True,
        )
