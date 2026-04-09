"""Context Loading Node for VQMS LangGraph Pipeline (Step 7).

Sub-Steps 7.1 through 7.4 from the Solution Flow Document:
  7.1 — Update case_execution status to ANALYZING
  7.2 — Cache workflow state in Redis (24h TTL)
  7.3 — Load vendor profile (Redis cache → Salesforce CRM)
  7.4 — Load vendor history (PostgreSQL episodic_memory)

Output: Populated context with vendor_profile and vendor_history
added to the graph state.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import text

from config.settings import get_settings
from src.cache.redis_client import set_with_ttl, workflow_key
from src.db.connection import get_engine
from src.models.budget import Budget
from src.services.memory_context import load_vendor_history, load_vendor_profile
from src.utils.log_context import LogContext

logger = logging.getLogger(__name__)


async def context_loading(state: dict) -> dict:
    """Load all context needed for query analysis.

    This is the first node in the LangGraph pipeline. It receives
    the raw payload from the SQS consumer and loads vendor profile,
    vendor history, and initializes the execution budget.

    Args:
        state: PipelineState dict with 'payload', 'correlation_id',
            'execution_id', 'query_id'.

    Returns:
        Partial state dict with 'vendor_profile', 'vendor_history',
        and 'budget' fields populated.
    """
    payload = state["payload"]
    correlation_id = state["correlation_id"]
    execution_id = state["execution_id"]
    query_id = state["query_id"]
    vendor_id = payload.get("vendor_id")
    sender_email = payload.get("sender_email")

    ctx = LogContext.from_state(state).with_update(
        agent_role="orchestrator",
        step="STEP_7",
        status="ANALYZING",
    )

    logger.info(
        "Step 7: Context loading started",
        extra={**ctx.to_dict(), "vendor_id": vendor_id},
    )

    # --- Sub-Step 7.1: Update status to ANALYZING ---
    await _update_case_status(execution_id, "analyzing", correlation_id=correlation_id)

    # --- Sub-Step 7.2: Cache workflow state in Redis ---
    await _cache_workflow_state(
        execution_id=execution_id,
        query_id=query_id,
        vendor_id=vendor_id,
        step="CONTEXT_LOADING",
        correlation_id=correlation_id,
    )

    # --- Sub-Step 7.3: Load vendor profile ---
    vendor_profile = await load_vendor_profile(
        vendor_id,
        sender_email,
        correlation_id=correlation_id,
    )

    # --- Sub-Step 7.4: Load vendor history ---
    vendor_history = await load_vendor_history(
        vendor_id,
        correlation_id=correlation_id,
    )

    # --- Initialize execution budget ---
    settings = get_settings()
    budget = Budget(
        max_tokens_in=settings.agent_budget_max_tokens_in,
        max_tokens_out=settings.agent_budget_max_tokens_out,
        currency_limit_usd=settings.agent_budget_currency_limit_usd,
    )

    # --- Write audit log ---
    await _write_audit_log(
        correlation_id=correlation_id,
        execution_id=execution_id,
        action="CONTEXT_LOADED",
        details={
            "vendor_id": vendor_id,
            "vendor_found": vendor_profile is not None,
            "history_count": len(vendor_history),
        },
    )

    logger.info(
        "Step 7: Context loading completed",
        extra={
            **ctx.to_dict(),
            "vendor_found": vendor_profile is not None,
            "history_count": len(vendor_history),
        },
    )

    return {
        "vendor_profile": vendor_profile.model_dump() if vendor_profile else None,
        "vendor_history": vendor_history,
        "budget": budget.model_dump(),
    }


async def _update_case_status(
    execution_id: str,
    status: str,
    *,
    correlation_id: str | None = None,
) -> None:
    """Update the case_execution status in PostgreSQL."""
    engine = get_engine()
    if engine is None:
        return

    sql = text(
        "UPDATE workflow.case_execution "
        "SET status = :status, updated_at = NOW() "
        "WHERE execution_id = :execution_id"
    )
    try:
        async with engine.begin() as conn:
            await conn.execute(sql, {"status": status, "execution_id": execution_id})
    except Exception:
        logger.error(
            "Failed to update case_execution status",
            extra={
                "execution_id": execution_id,
                "status": status,
                "correlation_id": correlation_id,
            },
            exc_info=True,
        )


async def _cache_workflow_state(
    *,
    execution_id: str,
    query_id: str,
    vendor_id: str | None,
    step: str,
    correlation_id: str | None = None,
) -> None:
    """Cache workflow state in Redis for fast status lookups."""
    key, ttl = workflow_key(execution_id)
    state_data = json.dumps({
        "status": "analyzing",
        "query_id": query_id,
        "vendor_id": vendor_id,
        "step": step,
    })
    try:
        await set_with_ttl(key, state_data, ttl)
    except Exception:
        logger.warning(
            "Failed to cache workflow state in Redis",
            extra={"execution_id": execution_id, "correlation_id": correlation_id},
            exc_info=True,
        )


async def _write_audit_log(
    *,
    correlation_id: str | None,
    execution_id: str,
    action: str,
    details: dict,
) -> None:
    """Write an entry to the audit.action_log table."""
    engine = get_engine()
    if engine is None:
        return

    sql = text(
        "INSERT INTO audit.action_log "
        "(correlation_id, execution_id, actor, action, details) "
        "VALUES (:correlation_id, :execution_id, :actor, :action, :details)"
    )
    try:
        async with engine.begin() as conn:
            await conn.execute(
                sql,
                {
                    "correlation_id": correlation_id or "",
                    "execution_id": execution_id,
                    "actor": "orchestrator",
                    "action": action,
                    "details": json.dumps(details, default=str),
                },
            )
    except Exception:
        logger.warning(
            "Failed to write audit log",
            extra={"execution_id": execution_id, "action": action},
            exc_info=True,
        )
