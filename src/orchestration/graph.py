"""LangGraph State Machine for VQMS AI Pipeline.

This is the central orchestration graph that processes vendor
queries through the AI pipeline. It wires together all the
nodes from Steps 7, 8, and 9:

  context_loading → query_analysis → [confidence_check]
    → (pass) routing_and_kb_search → [path_decision]
        → (path_a) path_a_stub → END
        → (path_b) path_b_stub → END
    → (fail) path_c_stub → END

The graph uses LangGraph's StateGraph with async nodes.
State flows as a PipelineState TypedDict through each node.

Usage:
    graph = build_pipeline_graph()
    result = await graph.ainvoke(initial_state)
"""

from __future__ import annotations

import logging
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from src.orchestration.nodes.confidence_check import confidence_check
from src.orchestration.nodes.context_loading import context_loading
from src.orchestration.nodes.path_decision import path_decision
from src.orchestration.nodes.path_stubs import path_a_stub, path_b_stub, path_c_stub
from src.orchestration.nodes.query_analysis_node import query_analysis
from src.orchestration.nodes.routing_and_kb_search import routing_and_kb_search

logger = logging.getLogger(__name__)


class PipelineState(TypedDict, total=False):
    """State that flows through the LangGraph pipeline.

    Each node reads from and writes to this shared state.
    Fields use basic types (dict, list, str) instead of Pydantic
    models so LangGraph can serialize/checkpoint the state.
    """

    # --- Set by SQS consumer at invocation ---
    payload: dict[str, Any]       # UnifiedQueryPayload as dict
    correlation_id: str
    execution_id: str
    query_id: str

    # --- Set by context_loading node (Step 7) ---
    vendor_profile: dict[str, Any] | None
    vendor_history: list[dict[str, Any]]
    budget: dict[str, Any]

    # --- Set by query_analysis node (Step 8) ---
    analysis_result: dict[str, Any] | None

    # --- Set by routing_and_kb_search node (Step 9) ---
    routing_decision: dict[str, Any] | None
    kb_search_response: dict[str, Any] | None

    # --- Set by path stubs ---
    selected_path: str | None

    # --- Error tracking ---
    error: str | None


def build_pipeline_graph() -> Any:
    """Build and compile the VQMS AI pipeline graph.

    Returns:
        A compiled LangGraph that can be invoked with:
        result = await graph.ainvoke(initial_state)
    """
    graph = StateGraph(PipelineState)

    # --- Add nodes ---
    graph.add_node("context_loading", context_loading)
    graph.add_node("query_analysis", query_analysis)
    graph.add_node("routing_and_kb_search", routing_and_kb_search)
    graph.add_node("path_a_stub", path_a_stub)
    graph.add_node("path_b_stub", path_b_stub)
    graph.add_node("path_c_stub", path_c_stub)

    # --- Set entry point ---
    graph.set_entry_point("context_loading")

    # --- Wire edges ---

    # Step 7 → Step 8: context loading feeds into query analysis
    graph.add_edge("context_loading", "query_analysis")

    # Step 8 → Decision Point 1: confidence check
    # Routes to routing_and_kb_search (pass) or path_c_stub (fail)
    graph.add_conditional_edges(
        "query_analysis",
        confidence_check,
        {
            "pass": "routing_and_kb_search",
            "fail": "path_c_stub",
        },
    )

    # Step 9 → Decision Point 2: path decision
    # Routes to path_a_stub or path_b_stub
    graph.add_conditional_edges(
        "routing_and_kb_search",
        path_decision,
        {
            "path_a": "path_a_stub",
            "path_b": "path_b_stub",
        },
    )

    # All path stubs terminate the graph
    graph.add_edge("path_a_stub", END)
    graph.add_edge("path_b_stub", END)
    graph.add_edge("path_c_stub", END)

    # --- Compile and return ---
    compiled = graph.compile()

    logger.info("VQMS pipeline graph compiled successfully")

    return compiled
