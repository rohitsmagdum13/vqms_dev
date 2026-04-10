"""Manual test: Full Phase 3 pipeline end-to-end.

Creates a test UnifiedQueryPayload, runs it through the full
LangGraph pipeline (context loading → analysis → routing + KB
search → path decision), and prints results at each step.

Usage:
    uv run python tests/manual/test_phase3_pipeline.py
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import datetime

from src.utils.helpers import IST
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from config.settings import get_settings
from src.db.connection import init_db, start_ssh_tunnel
from src.orchestration.graph import PipelineState, build_pipeline_graph
from src.utils.logger import setup_logging


def _build_test_payload() -> dict:
    """Create a realistic test query payload."""
    return {
        "query_id": f"VQ-2026-{uuid.uuid4().hex[:4].upper()}",
        "execution_id": str(uuid.uuid4()),
        "correlation_id": str(uuid.uuid4()),
        "source": "portal",
        "vendor_id": "V-001",
        "vendor_name": "TechNova Solutions",
        "subject": "Payment status inquiry for Invoice INV-2026-0451",
        "description": (
            "Dear Team,\n\n"
            "I am writing to inquire about the payment status of our "
            "Invoice INV-2026-0451 dated 15th February 2026 for Rs. 475,000 "
            "against Purchase Order PO-HEX-78412. The payment was due on "
            "17th March 2026 (Net 30 terms) and we have not yet received it.\n\n"
            "Could you please check and provide an update on when we can "
            "expect the payment?\n\n"
            "Best regards,\nRajesh Mehta\nTechNova Solutions"
        ),
        "query_type": "billing",
        "priority": "high",
        "reference_number": "INV-2026-0451",
        "received_at": datetime.now(IST).isoformat(),
    }


async def main() -> None:
    settings = get_settings()
    setup_logging("INFO")

    print("=" * 70)
    print("VQMS — Phase 3 Pipeline End-to-End Test")
    print("=" * 70)

    # --- Bootstrap infrastructure ---
    print("\n[1/5] Connecting to infrastructure...")

    # Database
    db_url = settings.database_url
    try:
        if settings.ssh_host:
            local_host, local_port = start_ssh_tunnel(
                ssh_host=settings.ssh_host,
                ssh_port=settings.ssh_port,
                ssh_username=settings.ssh_username,
                ssh_private_key_path=settings.ssh_private_key_path,
                rds_host=settings.rds_host,
                rds_port=settings.rds_port,
            )
            db_url = (
                f"postgresql+asyncpg://{settings.postgres_user}:{settings.postgres_password}"
                f"@{local_host}:{local_port}/{settings.postgres_db}"
            )
        await init_db(db_url, pool_min=2, pool_max=5)
        print("  PostgreSQL: connected")
    except Exception as e:
        print(f"  PostgreSQL: FAILED — {e}")

    # --- Build test payload ---
    print("\n[2/5] Building test payload...")
    payload = _build_test_payload()
    print(f"  Query ID:     {payload['query_id']}")
    print(f"  Execution ID: {payload['execution_id']}")
    print(f"  Subject:      {payload['subject']}")

    # --- Build and run pipeline ---
    print("\n[3/5] Building LangGraph pipeline...")
    graph = build_pipeline_graph()
    print("  Pipeline compiled successfully")

    initial_state: PipelineState = {
        "payload": payload,
        "correlation_id": payload["correlation_id"],
        "execution_id": payload["execution_id"],
        "query_id": payload["query_id"],
        "vendor_profile": None,
        "vendor_history": [],
        "budget": {},
        "analysis_result": None,
        "routing_decision": None,
        "kb_search_response": None,
        "selected_path": None,
        "error": None,
    }

    print("\n[4/5] Running pipeline...")
    print("-" * 70)

    try:
        result = await graph.ainvoke(initial_state)
    except Exception as e:
        print(f"\n  PIPELINE FAILED: {e}")
        import traceback
        traceback.print_exc()
        return

    # --- Print results ---
    print("-" * 70)
    print("\n[5/5] Pipeline Results:")
    print("=" * 70)

    # Analysis Result
    analysis = result.get("analysis_result", {})
    print("\n  ANALYSIS RESULT (Step 8):")
    print(f"    Intent:       {analysis.get('intent_classification')}")
    print(f"    Confidence:   {analysis.get('confidence_score')}")
    print(f"    Urgency:      {analysis.get('urgency_level')}")
    print(f"    Sentiment:    {analysis.get('sentiment')}")
    print(f"    Category:     {analysis.get('suggested_category')}")
    print(f"    Multi-issue:  {analysis.get('multi_issue_detected')}")
    print(f"    Tokens:       {analysis.get('tokens_in')} in / {analysis.get('tokens_out')} out")
    print(f"    Cost:         ${analysis.get('cost_usd', 0):.6f}")

    entities = analysis.get("extracted_entities", {})
    if entities:
        print("    Entities:")
        for key, val in entities.items():
            if val:
                print(f"      {key}: {val}")

    # Routing Decision
    routing = result.get("routing_decision", {})
    print("\n  ROUTING DECISION (Step 9A):")
    print(f"    Team:         {routing.get('assigned_team')}")
    print(f"    SLA:          {routing.get('sla_hours')} hours")
    print(f"    Automation:   {'BLOCKED' if routing.get('automation_blocked') else 'ALLOWED'}")
    print(f"    Reasoning:    {routing.get('routing_reason')}")

    # KB Search Results
    kb = result.get("kb_search_response", {})
    kb_results = kb.get("results", [])
    print("\n  KB SEARCH RESULTS (Step 9B):")
    print(f"    Top score:    {kb.get('top_score', 0):.4f}")
    print(f"    Results:      {len(kb_results)} articles found")
    for i, r in enumerate(kb_results[:3], 1):
        print(f"    [{i}] {r.get('source_document')} — {r.get('similarity_score', 0):.4f} (facts: {r.get('has_specific_facts')})")

    # Path Decision
    print(f"\n  SELECTED PATH:  {result.get('selected_path')}")

    path = result.get("selected_path")
    if path == "A":
        print("  → AI-Resolved: Resolution Agent will draft full answer (Phase 4)")
    elif path == "B":
        print("  → Human-Team: Acknowledgment email sent, team investigates (Phase 4)")
    elif path == "C":
        print("  → Low-Confidence: Workflow pauses for human review (Phase 5)")

    print("\n" + "=" * 70)
    print("Phase 3 pipeline test completed successfully!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
