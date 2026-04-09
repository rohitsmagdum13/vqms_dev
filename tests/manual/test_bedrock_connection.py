"""Manual test: Verify Amazon Bedrock connection.

Tests both the LLM (Claude Sonnet 3.5) and embedding (Titan Embed v2)
calls against real Bedrock. Requires AWS credentials in .env.

Usage:
    uv run python tests/manual/test_bedrock_connection.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.adapters.bedrock import embed_text, invoke_llm
from src.utils.logger import setup_logging


async def test_llm_call() -> None:
    """Test a simple LLM call to Claude Sonnet 3.5."""
    print("\n" + "=" * 60)
    print("TEST 1: LLM Call (Claude Sonnet 3.5)")
    print("=" * 60)

    result = await invoke_llm(
        "What is 2 + 2? Answer with just the number.",
        system_prompt="You are a helpful math assistant. Be concise.",
        temperature=0.0,
        max_tokens=50,
        correlation_id="test-llm-001",
    )

    print(f"  Response: {result['text']}")
    print(f"  Model:    {result['model_id']}")
    print(f"  Tokens:   {result['tokens_in']} in, {result['tokens_out']} out")
    print(f"  Cost:     ${result['cost_usd']:.6f}")
    print(f"  Latency:  {result['latency_ms']:.1f}ms")
    print("  STATUS:   PASS")


async def test_embedding_call() -> None:
    """Test an embedding call to Titan Embed v2."""
    print("\n" + "=" * 60)
    print("TEST 2: Embedding Call (Titan Embed v2)")
    print("=" * 60)

    text = "Invoice payment status inquiry for PO-12345"
    vector = await embed_text(text, correlation_id="test-embed-001")

    print(f"  Input:      '{text}'")
    print(f"  Dimensions: {len(vector)}")
    print(f"  First 5:    {vector[:5]}")
    print(f"  Last 5:     {vector[-5:]}")
    print("  STATUS:     PASS")


async def main() -> None:
    setup_logging("INFO")

    print("=" * 60)
    print("VQMS — Bedrock Connection Test")
    print("=" * 60)

    try:
        await test_llm_call()
    except Exception as e:
        print(f"  STATUS: FAIL — {e}")

    try:
        await test_embedding_call()
    except Exception as e:
        print(f"  STATUS: FAIL — {e}")

    print("\n" + "=" * 60)
    print("All Bedrock connection tests completed.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
