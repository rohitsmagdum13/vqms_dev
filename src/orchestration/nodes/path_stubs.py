"""Path stub nodes for VQMS LangGraph Pipeline.

These are STUB implementations for Phase 3. They set the
selected path, update the case_execution status, and return.
Full implementations come in Phase 4 (Path A and B) and
Phase 5 (Path C).

Path A: AI-Resolved — Resolution Agent drafts full answer
Path B: Human-Team-Resolved — Acknowledgment email, team investigates
Path C: Low-Confidence — Workflow pauses for human reviewer
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import text

from src.cache.redis_client import set_with_ttl, workflow_key
from src.db.connection import get_engine
from src.events.eventbridge import publish_event
from src.utils.log_context import LogContext

logger = logging.getLogger(__name__)


async def path_a_stub(state: dict) -> dict:
    """STUB — Phase 4 will implement Resolution Agent (Path A).

    Sets status to RESOLVING_AI and selected_path to "A".
    In Phase 4, this will call the Resolution Agent to draft
    a full resolution email using KB article facts.
    """
    execution_id = state["execution_id"]
    correlation_id = state["correlation_id"]

    ctx = LogContext.from_state(state).with_update(
        agent_role="orchestrator",
        step="PATH_A",
        status="RESOLVING_AI",
    )

    logger.info(
        "PATH A selected — AI-Resolved (STUB: Phase 4 will implement)",
        extra=ctx.to_dict(),
    )

    await _update_path(
        execution_id=execution_id,
        path="A",
        status="resolving_ai",
        event_type="PathASelected",
        correlation_id=correlation_id,
    )

    return {"selected_path": "A"}


async def path_b_stub(state: dict) -> dict:
    """STUB — Phase 4 will implement Communication Agent (Path B).

    Sets status to AWAITING_TEAM_RESOLUTION and selected_path to "B".
    In Phase 4, this will call the Communication Drafting Agent
    to draft an acknowledgment email (no answer, just confirmation).
    """
    execution_id = state["execution_id"]
    correlation_id = state["correlation_id"]

    ctx = LogContext.from_state(state).with_update(
        agent_role="orchestrator",
        step="PATH_B",
        status="AWAITING_TEAM_RESOLUTION",
    )

    logger.info(
        "PATH B selected — Human-Team-Resolved (STUB: Phase 4 will implement)",
        extra=ctx.to_dict(),
    )

    await _update_path(
        execution_id=execution_id,
        path="B",
        status="awaiting_team_resolution",
        event_type="PathBSelected",
        correlation_id=correlation_id,
    )

    return {"selected_path": "B"}


async def path_c_stub(state: dict) -> dict:
    """STUB — Phase 5 will implement Human Review (Path C).

    Sets status to AWAITING_HUMAN_REVIEW and selected_path to "C".
    In Phase 5, this will create a TriagePackage, push to
    vqms-human-review-queue, and pause via Step Functions
    callback token pattern.
    """
    execution_id = state["execution_id"]
    correlation_id = state["correlation_id"]

    ctx = LogContext.from_state(state).with_update(
        agent_role="orchestrator",
        step="PATH_C",
        status="AWAITING_HUMAN_REVIEW",
    )

    logger.info(
        "PATH C selected — Low-Confidence Human Review (STUB: Phase 5 will implement)",
        extra=ctx.to_dict(),
    )

    await _update_path(
        execution_id=execution_id,
        path="C",
        status="awaiting_human_review",
        event_type="HumanReviewRequired",
        correlation_id=correlation_id,
    )

    return {"selected_path": "C"}


async def _update_path(
    *,
    execution_id: str,
    path: str,
    status: str,
    event_type: str,
    correlation_id: str | None,
) -> None:
    """Update case_execution with the selected path and publish event.

    Shared by all three path stubs to avoid code duplication.
    """
    # Update PostgreSQL
    engine = get_engine()
    if engine is not None:
        sql = text(
            "UPDATE workflow.case_execution "
            "SET selected_path = :path, status = :status, updated_at = NOW() "
            "WHERE execution_id = :execution_id"
        )
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    sql,
                    {"path": path, "status": status, "execution_id": execution_id},
                )
        except Exception:
            logger.error(
                "Failed to update case_execution path",
                extra={"execution_id": execution_id, "path": path},
                exc_info=True,
            )

    # Update Redis workflow state
    key, ttl = workflow_key(execution_id)
    try:
        await set_with_ttl(
            key,
            json.dumps({"status": status, "step": f"PATH_{path}", "selected_path": path}),
            ttl,
        )
    except Exception:
        logger.warning(
            "Failed to update Redis workflow state for path",
            extra={"execution_id": execution_id, "path": path},
            exc_info=True,
        )

    # Publish EventBridge event
    try:
        await publish_event(
            detail_type=event_type,
            detail={"execution_id": execution_id, "selected_path": path},
            correlation_id=correlation_id,
        )
    except Exception:
        logger.warning(
            "Failed to publish path event",
            extra={"execution_id": execution_id, "event_type": event_type},
            exc_info=True,
        )

    # Write audit log
    if engine is not None:
        audit_sql = text(
            "INSERT INTO audit.action_log "
            "(correlation_id, execution_id, actor, action, details) "
            "VALUES (:correlation_id, :execution_id, :actor, :action, :details)"
        )
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    audit_sql,
                    {
                        "correlation_id": correlation_id or "",
                        "execution_id": execution_id,
                        "actor": "orchestrator",
                        "action": f"PATH_{path}_SELECTED",
                        "details": json.dumps({"path": path, "status": status}),
                    },
                )
        except Exception:
            logger.warning(
                "Failed to write path selection audit log",
                extra={"execution_id": execution_id, "path": path},
                exc_info=True,
            )
