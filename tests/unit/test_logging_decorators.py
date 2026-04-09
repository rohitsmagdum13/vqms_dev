"""Tests for logging decorators in src/utils/logger.py.

Verifies that each decorator (log_api_call, log_service_call,
log_llm_call, log_policy_decision) logs START/END/FAILED with
the correct fields and latency measurement.
"""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from src.utils.log_context import LogContext
from src.utils.logger import log_llm_call, log_policy_decision, log_service_call

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_extra(mock_call) -> dict:
    """Extract the extra dict from a mock logger call."""
    _, kwargs = mock_call
    return kwargs.get("extra", {})


# ---------------------------------------------------------------------------
# log_service_call
# ---------------------------------------------------------------------------


class TestLogServiceCall:
    """Test the @log_service_call decorator."""

    @pytest.mark.asyncio
    async def test_async_start_and_end_logged(self):
        """Async function should produce START and END log messages."""

        @log_service_call
        async def my_service(*, correlation_id: str | None = None) -> str:
            return "ok"

        with patch.object(logging.getLogger("tests.unit.test_logging_decorators"), "info") as mock_info:
            result = await my_service(correlation_id="test-cid")

        assert result == "ok"
        # Should have two info calls: START and END
        assert mock_info.call_count == 2

        start_msg = mock_info.call_args_list[0][0][0]
        end_msg = mock_info.call_args_list[1][0][0]
        assert "START" in start_msg
        assert "END" in end_msg
        assert "my_service" in start_msg

        # END log should have latency_ms
        end_extra = _extract_extra(mock_info.call_args_list[1])
        assert "latency_ms" in end_extra
        assert end_extra["correlation_id"] == "test-cid"

    @pytest.mark.asyncio
    async def test_async_failure_logged(self):
        """Async function failure should produce START and FAILED log."""

        @log_service_call
        async def failing_service(*, correlation_id: str | None = None) -> None:
            raise ValueError("test error")

        with (
            patch.object(logging.getLogger("tests.unit.test_logging_decorators"), "info") as mock_info,
            patch.object(logging.getLogger("tests.unit.test_logging_decorators"), "error") as mock_error,
        ):
            with pytest.raises(ValueError, match="test error"):
                await failing_service(correlation_id="fail-cid")

        assert mock_info.call_count == 1  # START only
        assert mock_error.call_count == 1  # FAILED

        error_msg = mock_error.call_args_list[0][0][0]
        assert "FAILED" in error_msg
        assert "ValueError" in error_msg

    def test_sync_start_and_end_logged(self):
        """Sync function should produce START and END log messages."""

        @log_service_call
        def sync_service(*, correlation_id: str | None = None) -> int:
            return 42

        with patch.object(logging.getLogger("tests.unit.test_logging_decorators"), "info") as mock_info:
            result = sync_service(correlation_id="sync-cid")

        assert result == 42
        assert mock_info.call_count == 2

    @pytest.mark.asyncio
    async def test_extracts_log_ctx_from_kwargs(self):
        """Should use explicit log_ctx kwarg when provided."""
        ctx = LogContext(correlation_id="ctx-123", agent_role="test_agent")

        @log_service_call
        async def with_ctx(*, log_ctx: LogContext | None = None) -> str:
            return "done"

        with patch.object(logging.getLogger("tests.unit.test_logging_decorators"), "info") as mock_info:
            await with_ctx(log_ctx=ctx)

        start_extra = _extract_extra(mock_info.call_args_list[0])
        assert start_extra["correlation_id"] == "ctx-123"
        assert start_extra["agent_role"] == "test_agent"

    @pytest.mark.asyncio
    async def test_extracts_from_state_dict(self):
        """Should extract LogContext from first arg if it is a state dict."""
        state = {
            "correlation_id": "state-cid",
            "execution_id": "state-eid",
            "query_id": "state-qid",
        }

        @log_service_call
        async def node_func(s: dict) -> dict:
            return s

        with patch.object(logging.getLogger("tests.unit.test_logging_decorators"), "info") as mock_info:
            await node_func(state)

        start_extra = _extract_extra(mock_info.call_args_list[0])
        assert start_extra["correlation_id"] == "state-cid"
        assert start_extra["execution_id"] == "state-eid"


# ---------------------------------------------------------------------------
# log_llm_call
# ---------------------------------------------------------------------------


class TestLogLlmCall:
    """Test the @log_llm_call decorator."""

    @pytest.mark.asyncio
    async def test_enriches_with_llm_result(self):
        """Should enrich END log with tokens, cost, model, provider."""

        @log_llm_call
        async def llm_complete(prompt: str, *, correlation_id: str | None = None) -> dict:
            return {
                "text": "Hello",
                "tokens_in": 100,
                "tokens_out": 50,
                "cost_usd": 0.005,
                "model": "claude-sonnet",
                "provider": "bedrock",
                "was_fallback": False,
            }

        with patch.object(logging.getLogger("tests.unit.test_logging_decorators"), "info") as mock_info:
            result = await llm_complete("test prompt", correlation_id="llm-cid")

        assert result["text"] == "Hello"
        assert mock_info.call_count == 2  # START + END

        end_extra = _extract_extra(mock_info.call_args_list[1])
        assert end_extra["tokens_in"] == 100
        assert end_extra["tokens_out"] == 50
        assert end_extra["cost_usd"] == 0.005
        assert end_extra["model"] == "claude-sonnet"
        assert end_extra["provider"] == "bedrock"
        assert end_extra["correlation_id"] == "llm-cid"
        assert "latency_ms" in end_extra

    @pytest.mark.asyncio
    async def test_failure_logged(self):
        """LLM call failure should produce FAILED log."""

        @log_llm_call
        async def failing_llm(prompt: str, *, correlation_id: str | None = None) -> dict:
            raise ConnectionError("Bedrock unreachable")

        with (
            patch.object(logging.getLogger("tests.unit.test_logging_decorators"), "info"),
            patch.object(logging.getLogger("tests.unit.test_logging_decorators"), "error") as mock_error,
        ):
            with pytest.raises(ConnectionError):
                await failing_llm("test", correlation_id="fail-llm")

        assert mock_error.call_count == 1
        error_msg = mock_error.call_args_list[0][0][0]
        assert "FAILED" in error_msg
        assert "ConnectionError" in error_msg


# ---------------------------------------------------------------------------
# log_policy_decision
# ---------------------------------------------------------------------------


class TestLogPolicyDecision:
    """Test the @log_policy_decision decorator."""

    def test_logs_string_return_as_decision(self):
        """String return value should be logged as policy_decision."""
        state = {"correlation_id": "policy-cid", "execution_id": "e1", "query_id": "q1"}

        @log_policy_decision
        def check_confidence(s: dict) -> str:
            return "pass"

        with patch.object(logging.getLogger("tests.unit.test_logging_decorators"), "info") as mock_info:
            result = check_confidence(state)

        assert result == "pass"
        assert mock_info.call_count == 1

        extra = _extract_extra(mock_info.call_args_list[0])
        assert extra["policy_decision"] == "pass"
        assert extra["correlation_id"] == "policy-cid"
        assert "latency_ms" in extra

    def test_failure_logged(self):
        """Policy decision failure should produce FAILED log."""

        @log_policy_decision
        def bad_decision(s: dict) -> str:
            raise RuntimeError("logic error")

        with patch.object(logging.getLogger("tests.unit.test_logging_decorators"), "error") as mock_error:
            with pytest.raises(RuntimeError):
                bad_decision({"correlation_id": "err-cid"})

        assert mock_error.call_count == 1
        error_msg = mock_error.call_args_list[0][0][0]
        assert "FAILED" in error_msg
