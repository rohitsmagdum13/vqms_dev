"""Manual integration tests for LLM providers.

Runs real LLM calls against Bedrock and OpenAI to verify both
providers work and return compatible results. Requires real
credentials in .env.

Usage:
    uv run python tests/manual/test_llm_providers.py

NOT run by pytest — excluded via tests/manual/conftest.py.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path so imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from config.settings import get_settings  # noqa: E402
from src.llm.factory import (  # noqa: E402
    llm_complete,
    llm_embed,
    reset_providers,
)
from src.utils.logger import setup_logging  # noqa: E402

logger = logging.getLogger(__name__)


async def test_bedrock_llm() -> None:
    """Test 1: Bedrock-only LLM call."""
    reset_providers()
    settings = get_settings()

    # Temporarily override to bedrock_only
    original = settings.llm_provider
    settings.llm_provider = "bedrock_only"
    reset_providers()

    try:
        result = await llm_complete(
            "What is 2 + 2? Reply with just the number.",
            correlation_id="manual-test-bedrock-llm",
        )
        print(f"✓ Bedrock LLM: provider={result['provider']}, "
              f"model={result['model']}, "
              f"tokens_in={result['tokens_in']}, "
              f"tokens_out={result['tokens_out']}, "
              f"latency={result['latency_ms']:.0f}ms")
        print(f"  Response: {result['text'][:100]}")
    except Exception as err:
        print(f"✗ Bedrock LLM failed: {err}")
    finally:
        settings.llm_provider = original
        reset_providers()


async def test_openai_llm() -> None:
    """Test 2: OpenAI-only LLM call."""
    reset_providers()
    settings = get_settings()

    original = settings.llm_provider
    settings.llm_provider = "openai_only"
    reset_providers()

    try:
        result = await llm_complete(
            "What is 2 + 2? Reply with just the number.",
            correlation_id="manual-test-openai-llm",
        )
        print(f"✓ OpenAI LLM: provider={result['provider']}, "
              f"model={result['model']}, "
              f"tokens_in={result['tokens_in']}, "
              f"tokens_out={result['tokens_out']}, "
              f"latency={result['latency_ms']:.0f}ms")
        print(f"  Response: {result['text'][:100]}")
    except Exception as err:
        print(f"✗ OpenAI LLM failed: {err}")
    finally:
        settings.llm_provider = original
        reset_providers()


async def test_fallback_llm() -> None:
    """Test 3: Fallback chain LLM call (default mode)."""
    reset_providers()

    try:
        result = await llm_complete(
            "What is 2 + 2? Reply with just the number.",
            correlation_id="manual-test-fallback-llm",
        )
        print(f"✓ Fallback LLM: provider={result['provider']}, "
              f"was_fallback={result['was_fallback']}, "
              f"model={result['model']}, "
              f"latency={result['latency_ms']:.0f}ms")
        print(f"  Response: {result['text'][:100]}")
    except Exception as err:
        print(f"✗ Fallback LLM failed: {err}")
    finally:
        reset_providers()


async def test_bedrock_embed() -> None:
    """Test 4: Bedrock-only embedding (verify 1536 dimensions)."""
    reset_providers()
    settings = get_settings()

    original = settings.embedding_provider
    settings.embedding_provider = "bedrock_only"
    reset_providers()

    try:
        result = await llm_embed(
            "Invoice payment status inquiry",
            correlation_id="manual-test-bedrock-embed",
        )
        print(f"✓ Bedrock Embed: provider={result['provider']}, "
              f"dimensions={result['dimensions']}, "
              f"model={result['model']}, "
              f"latency={result['latency_ms']:.0f}ms")
        assert result["dimensions"] == 1536, f"Expected 1536, got {result['dimensions']}"
    except Exception as err:
        print(f"✗ Bedrock Embed failed: {err}")
    finally:
        settings.embedding_provider = original
        reset_providers()


async def test_openai_embed() -> None:
    """Test 5: OpenAI-only embedding (verify 1536 dimensions)."""
    reset_providers()
    settings = get_settings()

    original = settings.embedding_provider
    settings.embedding_provider = "openai_only"
    reset_providers()

    try:
        result = await llm_embed(
            "Invoice payment status inquiry",
            correlation_id="manual-test-openai-embed",
        )
        print(f"✓ OpenAI Embed: provider={result['provider']}, "
              f"dimensions={result['dimensions']}, "
              f"model={result['model']}, "
              f"latency={result['latency_ms']:.0f}ms")
        assert result["dimensions"] == 1536, f"Expected 1536, got {result['dimensions']}"
    except Exception as err:
        print(f"✗ OpenAI Embed failed: {err}")
    finally:
        settings.embedding_provider = original
        reset_providers()


async def test_embedding_dimension_compatibility() -> None:
    """Test 6: Both providers return same-dimension embeddings."""
    reset_providers()
    settings = get_settings()
    text = "Invoice payment status for PO-2026-001"

    dims = {}

    # Bedrock embedding
    original = settings.embedding_provider
    settings.embedding_provider = "bedrock_only"
    reset_providers()
    try:
        result = await llm_embed(text, correlation_id="manual-compat-bedrock")
        dims["bedrock"] = result["dimensions"]
    except Exception as err:
        print(f"  Bedrock embed skipped: {err}")
    finally:
        settings.embedding_provider = original
        reset_providers()

    # OpenAI embedding
    settings.embedding_provider = "openai_only"
    reset_providers()
    try:
        result = await llm_embed(text, correlation_id="manual-compat-openai")
        dims["openai"] = result["dimensions"]
    except Exception as err:
        print(f"  OpenAI embed skipped: {err}")
    finally:
        settings.embedding_provider = original
        reset_providers()

    if len(dims) == 2:
        if dims["bedrock"] == dims["openai"] == 1536:
            print(f"✓ Dimension compatibility: both return {dims['bedrock']} dims")
        else:
            print(f"✗ Dimension mismatch: bedrock={dims['bedrock']}, openai={dims['openai']}")
    else:
        print(f"⚠ Could only test {list(dims.keys())} — need both for comparison")


async def main() -> None:
    """Run all manual provider tests."""
    settings = get_settings()
    setup_logging(settings.log_level)

    print("=" * 60)
    print("VQMS LLM Provider Manual Tests")
    print(f"Default LLM mode: {settings.llm_provider}")
    print(f"Default embed mode: {settings.embedding_provider}")
    print("=" * 60)
    print()

    await test_bedrock_llm()
    print()
    await test_openai_llm()
    print()
    await test_fallback_llm()
    print()
    await test_bedrock_embed()
    print()
    await test_openai_embed()
    print()
    await test_embedding_dimension_compatibility()

    print()
    print("=" * 60)
    print("Manual tests complete")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
