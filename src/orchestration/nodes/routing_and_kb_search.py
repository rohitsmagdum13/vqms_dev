"""Routing + KB Search Node (Step 9, Parallel Execution).

Executes the Routing Service (9A) and KB Search Service (9B)
in parallel using asyncio.gather(). Both receive the analysis
result and vendor profile, and both write their results back
to the graph state.

Corresponds to Step 9 in the VQMS Solution Flow Document.
"""

from __future__ import annotations

import asyncio
import logging
import time

from src.models.vendor import VendorProfile
from src.models.workflow import AnalysisResult
from src.services.kb_search import search_kb
from src.services.routing import route_query
from src.utils.log_context import LogContext

logger = logging.getLogger(__name__)


async def routing_and_kb_search(state: dict) -> dict:
    """Run routing and KB search in parallel.

    Args:
        state: PipelineState dict with 'analysis_result',
            'vendor_profile', 'payload', 'execution_id',
            'correlation_id'.

    Returns:
        Partial state dict with 'routing_decision' and
        'kb_search_response' populated.
    """
    correlation_id = state["correlation_id"]
    execution_id = state["execution_id"]
    payload = state["payload"]

    ctx = LogContext.from_state(state).with_update(
        agent_role="orchestrator",
        step="STEP_9",
    )

    # Reconstruct models from state dicts
    analysis = AnalysisResult(**state["analysis_result"])
    vendor_profile = None
    if state.get("vendor_profile"):
        vendor_profile = VendorProfile(**state["vendor_profile"])

    # Build search text from subject + description
    search_text = f"{payload.get('subject', '')} {payload.get('description', '')}"

    logger.info(
        "Step 9: Starting parallel routing + KB search",
        extra=ctx.to_dict(),
    )

    start_time = time.monotonic()

    # Run both in parallel
    routing_result, kb_result = await asyncio.gather(
        route_query(
            analysis,
            vendor_profile,
            execution_id=execution_id,
            correlation_id=correlation_id,
        ),
        search_kb(
            search_text,
            category=analysis.suggested_category,
            correlation_id=correlation_id,
        ),
    )

    total_ms = (time.monotonic() - start_time) * 1000

    logger.info(
        "Step 9: Parallel routing + KB search completed",
        extra={
            **ctx.with_update(latency_ms=round(total_ms, 1)).to_dict(),
            "team": routing_result.assigned_team,
            "sla_hours": routing_result.sla_hours,
            "kb_results_count": len(kb_result.results),
            "kb_top_score": kb_result.top_score,
        },
    )

    return {
        "routing_decision": routing_result.model_dump(mode="json"),
        "kb_search_response": kb_result.model_dump(),
    }
