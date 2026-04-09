"""Confidence Check — Conditional routing function for LangGraph.

This is NOT a regular node — it is a conditional edge function
that determines the next node based on the confidence score
from the Query Analysis Agent.

Decision Point 1 (from Solution Flow Document):
  - confidence >= 0.85 → "pass" → continue to routing_and_kb_search
  - confidence < 0.85  → "fail" → route to path_c_stub (human review)

The threshold is configurable via AGENT_CONFIDENCE_THRESHOLD env var.
"""

from __future__ import annotations

import logging

from config.settings import get_settings
from src.utils.log_context import LogContext

logger = logging.getLogger(__name__)


def confidence_check(state: dict) -> str:
    """Evaluate the analysis confidence and decide the next step.

    Args:
        state: PipelineState dict with 'analysis_result' containing
            the confidence_score field.

    Returns:
        "pass" if confidence >= threshold (continue to routing).
        "fail" if confidence < threshold (route to human review).
    """
    settings = get_settings()
    threshold = settings.agent_confidence_threshold

    analysis = state.get("analysis_result", {})
    confidence = analysis.get("confidence_score", 0.0)

    ctx = LogContext.from_state(state).with_update(
        agent_role="confidence_check",
        step="STEP_8.5",
    )

    if confidence >= threshold:
        decision = f"PASS: confidence={confidence} >= threshold={threshold}"
        logger.info(
            "Confidence check PASSED — continuing to routing + KB search",
            extra={
                **ctx.with_policy_decision(decision).to_dict(),
                "confidence": confidence,
                "threshold": threshold,
            },
        )
        return "pass"
    else:
        decision = f"FAIL: confidence={confidence} < threshold={threshold}"
        logger.info(
            "Confidence check FAILED — routing to Path C (human review)",
            extra={
                **ctx.with_policy_decision(
                    decision,
                    safety_flags=["LOW_CONFIDENCE"],
                ).to_dict(),
                "confidence": confidence,
                "threshold": threshold,
            },
        )
        return "fail"
