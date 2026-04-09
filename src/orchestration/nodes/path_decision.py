"""Path Decision — Conditional routing function for LangGraph.

Decision Point 2 (from Solution Flow Document):
  - KB match >= 80% AND has_specific_facts AND automation NOT blocked
    → "path_a" (AI drafts resolution email with full answer)
  - Otherwise
    → "path_b" (AI drafts acknowledgment only, human team investigates)

This function runs AFTER routing_and_kb_search and determines
whether the KB has enough specific facts to resolve the query
automatically (Path A) or if a human team needs to investigate
(Path B).
"""

from __future__ import annotations

import logging

from config.settings import get_settings
from src.utils.log_context import LogContext

logger = logging.getLogger(__name__)


def path_decision(state: dict) -> str:
    """Decide between Path A (AI-resolved) and Path B (human-team).

    Args:
        state: PipelineState dict with 'routing_decision' and
            'kb_search_response'.

    Returns:
        "path_a" if KB has specific facts with high similarity
        and automation is not blocked.
        "path_b" otherwise.
    """
    settings = get_settings()

    ctx = LogContext.from_state(state).with_update(
        agent_role="path_decision",
        step="STEP_9.5",
    )

    routing = state.get("routing_decision", {})
    kb_response = state.get("kb_search_response", {})

    # Check if automation is blocked by vendor flags
    automation_blocked = routing.get("automation_blocked", False)
    if automation_blocked:
        decision = "PATH_B: automation blocked by vendor flag"
        logger.info(
            "Path decision: PATH B — automation blocked by vendor flag",
            extra=ctx.with_policy_decision(
                decision,
                safety_flags=["VENDOR_BLOCK_AUTOMATION"],
            ).to_dict(),
        )
        return "path_b"

    # Check KB results quality
    kb_results = kb_response.get("results", [])
    top_score = kb_response.get("top_score", 0.0)
    threshold = settings.kb_match_threshold

    # Path A requires: at least one result above threshold with specific facts
    has_good_match = top_score >= threshold
    has_facts = any(r.get("has_specific_facts", False) for r in kb_results)

    if has_good_match and has_facts:
        results_with_facts = sum(1 for r in kb_results if r.get("has_specific_facts"))
        decision = f"PATH_A: kb_match={top_score}, has_facts=True, results_with_facts={results_with_facts}"
        logger.info(
            "Path decision: PATH A — KB has specific facts",
            extra={
                **ctx.with_policy_decision(decision).to_dict(),
                "top_score": top_score,
                "threshold": threshold,
                "results_with_facts": results_with_facts,
            },
        )
        return "path_a"
    else:
        decision = f"PATH_B: kb_match={top_score}, has_good_match={has_good_match}, has_facts={has_facts}"
        logger.info(
            "Path decision: PATH B — KB lacks specific facts",
            extra={
                **ctx.with_policy_decision(decision).to_dict(),
                "top_score": top_score,
                "threshold": threshold,
                "has_good_match": has_good_match,
                "has_facts": has_facts,
            },
        )
        return "path_b"
