"""Tests for LogContext dataclass.

Verifies construction, to_dict() filtering, with_update()
immutability, from_state() extraction, and convenience methods.
"""

from __future__ import annotations

import pytest

from src.utils.log_context import LogContext


class TestLogContextConstruction:
    """Test basic LogContext creation and defaults."""

    def test_all_fields_default_to_none(self):
        """A bare LogContext should have all fields as None."""
        ctx = LogContext()
        assert ctx.correlation_id is None
        assert ctx.agent_role is None
        assert ctx.tokens_in is None
        assert ctx.safety_flags is None

    def test_fields_set_via_constructor(self):
        """Fields passed to the constructor should be stored correctly."""
        ctx = LogContext(
            correlation_id="abc-123",
            query_id="VQ-2026-0001",
            agent_role="query_analysis",
            step="STEP_8",
        )
        assert ctx.correlation_id == "abc-123"
        assert ctx.query_id == "VQ-2026-0001"
        assert ctx.agent_role == "query_analysis"
        assert ctx.step == "STEP_8"

    def test_frozen_immutability(self):
        """LogContext should not allow mutation of existing fields."""
        ctx = LogContext(correlation_id="abc-123")
        with pytest.raises(AttributeError):
            ctx.correlation_id = "new-value"  # type: ignore[misc]


class TestToDict:
    """Test LogContext.to_dict() output filtering."""

    def test_empty_context_returns_empty_dict(self):
        """A bare LogContext.to_dict() should return an empty dict."""
        ctx = LogContext()
        assert ctx.to_dict() == {}

    def test_none_values_are_excluded(self):
        """Fields with None values should not appear in the dict."""
        ctx = LogContext(correlation_id="abc-123")
        d = ctx.to_dict()
        assert "correlation_id" in d
        assert "agent_role" not in d
        assert "tokens_in" not in d

    def test_empty_string_excluded(self):
        """Empty string values should be filtered out."""
        ctx = LogContext(correlation_id="abc-123", agent_role="")
        d = ctx.to_dict()
        assert "agent_role" not in d
        assert d["correlation_id"] == "abc-123"

    def test_empty_tuple_excluded(self):
        """Empty safety_flags tuple should be filtered out."""
        ctx = LogContext(safety_flags=())
        assert "safety_flags" not in ctx.to_dict()

    def test_was_fallback_false_excluded(self):
        """was_fallback=False should be omitted (only log when True)."""
        ctx = LogContext(was_fallback=False)
        assert "was_fallback" not in ctx.to_dict()

    def test_was_fallback_true_included(self):
        """was_fallback=True should be included in the output."""
        ctx = LogContext(was_fallback=True)
        assert ctx.to_dict()["was_fallback"] is True

    def test_safety_flags_tuple_converted_to_list(self):
        """safety_flags should be converted from tuple to list for JSON."""
        ctx = LogContext(safety_flags=("LOW_CONFIDENCE", "PII_DETECTED"))
        d = ctx.to_dict()
        assert d["safety_flags"] == ["LOW_CONFIDENCE", "PII_DETECTED"]
        assert isinstance(d["safety_flags"], list)

    def test_numeric_zero_included(self):
        """Numeric zero values should be included (not filtered)."""
        ctx = LogContext(tokens_in=0, cost_usd=0.0)
        d = ctx.to_dict()
        assert d["tokens_in"] == 0
        assert d["cost_usd"] == 0.0

    def test_full_context_output(self):
        """A fully populated LogContext should output all non-None fields."""
        ctx = LogContext(
            correlation_id="abc-123",
            query_id="VQ-2026-0001",
            execution_id="exec-456",
            agent_role="query_analysis",
            step="STEP_8",
            status="ANALYZING",
            tokens_in=1500,
            tokens_out=500,
            cost_usd=0.012,
            model="claude-sonnet",
            provider="bedrock",
        )
        d = ctx.to_dict()
        assert len(d) == 11
        assert d["correlation_id"] == "abc-123"
        assert d["tokens_in"] == 1500


class TestWithUpdate:
    """Test LogContext.with_update() immutable copy pattern."""

    def test_returns_new_instance(self):
        """with_update() should return a new LogContext, not mutate."""
        ctx1 = LogContext(correlation_id="abc-123")
        ctx2 = ctx1.with_update(step="STEP_8")

        assert ctx1 is not ctx2
        assert ctx1.step is None
        assert ctx2.step == "STEP_8"
        assert ctx2.correlation_id == "abc-123"

    def test_multiple_field_update(self):
        """with_update() should accept multiple field changes."""
        ctx = LogContext(correlation_id="abc")
        ctx2 = ctx.with_update(step="STEP_9", status="ROUTING", agent_role="routing")

        assert ctx2.step == "STEP_9"
        assert ctx2.status == "ROUTING"
        assert ctx2.agent_role == "routing"
        assert ctx2.correlation_id == "abc"

    def test_safety_flags_list_converted_to_tuple(self):
        """with_update() should convert list safety_flags to tuple."""
        ctx = LogContext()
        ctx2 = ctx.with_update(safety_flags=["FLAG_A", "FLAG_B"])

        assert ctx2.safety_flags == ("FLAG_A", "FLAG_B")
        assert isinstance(ctx2.safety_flags, tuple)


class TestWithLlmResult:
    """Test LogContext.with_llm_result() convenience method."""

    def test_enriches_with_llm_fields(self):
        """with_llm_result() should set all LLM-specific fields."""
        ctx = LogContext(correlation_id="abc")
        ctx2 = ctx.with_llm_result(
            provider="bedrock",
            model="claude-sonnet",
            tokens_in=1500,
            tokens_out=500,
            cost_usd=0.012,
            latency_ms=3456.7,
            was_fallback=True,
        )

        assert ctx2.provider == "bedrock"
        assert ctx2.model == "claude-sonnet"
        assert ctx2.tokens_in == 1500
        assert ctx2.tokens_out == 500
        assert ctx2.cost_usd == 0.012
        assert ctx2.latency_ms == 3456.7
        assert ctx2.was_fallback is True
        # Original unchanged
        assert ctx.provider is None


class TestWithPolicyDecision:
    """Test LogContext.with_policy_decision() convenience method."""

    def test_sets_decision_and_flags(self):
        """with_policy_decision() should set both fields."""
        ctx = LogContext(correlation_id="abc")
        ctx2 = ctx.with_policy_decision(
            "PASS: confidence=0.92 >= threshold=0.85",
            safety_flags=["LOW_CONFIDENCE"],
        )

        assert ctx2.policy_decision == "PASS: confidence=0.92 >= threshold=0.85"
        assert ctx2.safety_flags == ("LOW_CONFIDENCE",)

    def test_no_flags_sets_none(self):
        """with_policy_decision() without flags should leave safety_flags as None."""
        ctx = LogContext()
        ctx2 = ctx.with_policy_decision("PATH_A: kb_match=0.92")

        assert ctx2.policy_decision == "PATH_A: kb_match=0.92"
        assert ctx2.safety_flags is None


class TestFromState:
    """Test LogContext.from_state() factory method."""

    def test_extracts_tracing_ids_from_state(self):
        """from_state() should pull correlation_id, execution_id, query_id."""
        state = {
            "correlation_id": "corr-123",
            "execution_id": "exec-456",
            "query_id": "VQ-2026-0001",
            "payload": {"some": "data"},
        }
        ctx = LogContext.from_state(state)

        assert ctx.correlation_id == "corr-123"
        assert ctx.execution_id == "exec-456"
        assert ctx.query_id == "VQ-2026-0001"
        # Other fields should be None
        assert ctx.agent_role is None

    def test_handles_missing_keys(self):
        """from_state() should handle state dicts missing some keys."""
        state = {"correlation_id": "corr-123"}
        ctx = LogContext.from_state(state)

        assert ctx.correlation_id == "corr-123"
        assert ctx.execution_id is None
        assert ctx.query_id is None

    def test_empty_state_returns_empty_context(self):
        """from_state() with empty dict should return a bare LogContext."""
        ctx = LogContext.from_state({})
        assert ctx.to_dict() == {}
