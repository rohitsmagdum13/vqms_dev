"""Query Analysis Node for VQMS LangGraph Pipeline (Step 8).

Wraps the QueryAnalysisAgent to run LLM Call #1 (Claude Sonnet 3.5)
for intent classification, entity extraction, urgency scoring,
sentiment analysis, and confidence scoring.

After analysis:
  - Updates case_execution.analysis_result in PostgreSQL
  - Updates Redis workflow state to ANALYSIS_COMPLETE
  - Uploads prompt snapshot to S3 for audit trail
  - Publishes AnalysisCompleted event to EventBridge
  - Writes audit log entry
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import text

from src.agents.query_analysis import QueryAnalysisAgent
from src.cache.redis_client import set_with_ttl, workflow_key
from src.db.connection import get_engine
from src.events.eventbridge import publish_event
from src.models.budget import Budget
from src.models.vendor import VendorProfile
from src.utils.log_context import LogContext

logger = logging.getLogger(__name__)

# Singleton agent instance — stateless, so safe to reuse
_agent = QueryAnalysisAgent()


async def query_analysis(state: dict) -> dict:
    """Run the Query Analysis Agent on the loaded context.

    Args:
        state: PipelineState dict with 'payload', 'vendor_profile',
            'vendor_history', 'budget', 'execution_id', 'correlation_id'.

    Returns:
        Partial state dict with 'analysis_result' populated.
    """
    payload = state["payload"]
    correlation_id = state["correlation_id"]
    execution_id = state["execution_id"]

    # Reconstruct vendor profile from state dict
    vendor_profile = None
    if state.get("vendor_profile"):
        vendor_profile = VendorProfile(**state["vendor_profile"])

    # Reconstruct budget from state dict
    budget = Budget(**state["budget"]) if state.get("budget") else None

    ctx = LogContext.from_state(state).with_update(
        agent_role="query_analysis",
        step="STEP_8",
        status="ANALYZING",
    )

    logger.info(
        "Step 8: Query analysis started",
        extra={**ctx.to_dict(), "query_subject": payload.get("subject", "")},
    )

    # Run the Query Analysis Agent (LLM Call #1)
    analysis_result = await _agent.analyze_query(
        query_payload=payload,
        vendor_profile=vendor_profile,
        vendor_history=state.get("vendor_history", []),
        budget=budget,
        correlation_id=correlation_id,
    )

    analysis_dict = analysis_result.model_dump()

    # --- Persist analysis result to PostgreSQL ---
    await _save_analysis_result(execution_id, analysis_dict, correlation_id=correlation_id)

    # --- Update Redis workflow state ---
    key, ttl = workflow_key(execution_id)
    try:
        await set_with_ttl(
            key,
            json.dumps({
                "status": "analysis_complete",
                "query_id": state["query_id"],
                "vendor_id": payload.get("vendor_id"),
                "step": "ANALYSIS_COMPLETE",
                "confidence": analysis_result.confidence_score,
                "intent": analysis_result.intent_classification,
            }),
            ttl,
        )
    except Exception:
        logger.warning(
            "Failed to update Redis workflow state after analysis",
            extra={"execution_id": execution_id, "correlation_id": correlation_id},
            exc_info=True,
        )

    # --- Upload prompt snapshot to S3 for audit trail ---
    try:
        from config.settings import get_settings
        from src.storage.s3_client import upload_file

        settings = get_settings()
        snapshot = {
            "execution_id": execution_id,
            "agent": "QueryAnalysisAgent",
            "analysis_result": analysis_dict,
        }
        await upload_file(
            bucket=settings.s3_bucket_knowledge,
            key=f"audit/prompts/{execution_id}/query_analysis.json",
            content=json.dumps(snapshot, default=str).encode(),
            correlation_id=correlation_id,
        )
    except Exception:
        logger.warning(
            "Failed to upload prompt snapshot to S3",
            extra={"execution_id": execution_id, "correlation_id": correlation_id},
            exc_info=True,
        )

    # --- Publish AnalysisCompleted event ---
    try:
        await publish_event(
            detail_type="AnalysisCompleted",
            detail={
                "execution_id": execution_id,
                "query_id": state["query_id"],
                "intent": analysis_result.intent_classification,
                "confidence": analysis_result.confidence_score,
                "urgency": analysis_result.urgency_level.value,
            },
            correlation_id=correlation_id,
        )
    except Exception:
        logger.warning(
            "Failed to publish AnalysisCompleted event",
            extra={"execution_id": execution_id, "correlation_id": correlation_id},
            exc_info=True,
        )

    # --- Write audit log ---
    await _write_audit_log(
        correlation_id=correlation_id,
        execution_id=execution_id,
        action="ANALYSIS_COMPLETED",
        details={
            "intent": analysis_result.intent_classification,
            "confidence": analysis_result.confidence_score,
            "urgency": analysis_result.urgency_level.value,
            "sentiment": analysis_result.sentiment.value,
            "tokens_in": analysis_result.tokens_in,
            "tokens_out": analysis_result.tokens_out,
            "cost_usd": analysis_result.cost_usd,
        },
    )

    logger.info(
        "Step 8: Query analysis completed",
        extra={
            **ctx.with_update(status="ANALYSIS_COMPLETE").to_dict(),
            "intent": analysis_result.intent_classification,
            "confidence": analysis_result.confidence_score,
            "urgency": analysis_result.urgency_level.value,
            "tokens_in": analysis_result.tokens_in,
            "tokens_out": analysis_result.tokens_out,
            "cost_usd": analysis_result.cost_usd,
        },
    )

    # Return updated budget back to state
    budget_dict = budget.model_dump() if budget else state.get("budget")

    return {
        "analysis_result": analysis_dict,
        "budget": budget_dict,
    }


async def _save_analysis_result(
    execution_id: str,
    analysis_dict: dict,
    *,
    correlation_id: str | None = None,
) -> None:
    """Update case_execution with the analysis result."""
    engine = get_engine()
    if engine is None:
        return

    sql = text(
        "UPDATE workflow.case_execution "
        "SET analysis_result = :analysis_result, "
        "    status = 'analysis_complete', "
        "    updated_at = NOW() "
        "WHERE execution_id = :execution_id"
    )
    try:
        async with engine.begin() as conn:
            await conn.execute(
                sql,
                {
                    "analysis_result": json.dumps(analysis_dict, default=str),
                    "execution_id": execution_id,
                },
            )
    except Exception:
        logger.error(
            "Failed to save analysis result to database",
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
                    "actor": "QueryAnalysisAgent",
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
