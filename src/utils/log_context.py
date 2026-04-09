"""Log context that flows through the entire VQMS pipeline.

Every function in the pipeline receives or builds a LogContext.
The LogContext is passed to the logger as extra fields so that
every single log line contains full tracing information.

Usage:
    ctx = LogContext(
        correlation_id="f1a2b3c4-...",
        query_id="VQ-2026-0108",
        agent_role="query_analysis",
    )
    logger.info("Starting analysis", extra=ctx.to_dict())

    # Update context as pipeline progresses (returns NEW instance)
    ctx = ctx.with_update(step="STEP_8", status="ANALYZING")
    logger.info("Status updated", extra=ctx.to_dict())
"""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class LogContext:
    """Structured context that follows a query through the entire pipeline.

    Frozen (immutable) — use with_update() to create modified copies.
    This prevents accidental mutation when different pipeline branches
    need different contexts.
    """

    # Core tracing — present on EVERY log line
    correlation_id: str | None = None
    query_id: str | None = None
    execution_id: str | None = None

    # Who/what is logging
    agent_role: str | None = None
    username: str | None = None
    role: str | None = None
    tenant: str | None = None

    # Current pipeline position
    step: str | None = None
    status: str | None = None

    # External tool being called (when applicable)
    tool: str | None = None

    # Performance
    latency_ms: float | None = None

    # LLM-specific (when applicable)
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None
    model: str | None = None
    provider: str | None = None
    was_fallback: bool | None = None

    # Decision tracking
    policy_decision: str | None = None
    safety_flags: tuple[str, ...] | None = None

    def to_dict(self) -> dict:
        """Convert to dict for passing as logging extra fields.

        Removes None values, empty strings, empty tuples, and
        False was_fallback to keep logs clean. Only includes
        fields that have actual data.
        """
        result = {}
        for key in self.__dataclass_fields__:
            value = getattr(self, key)
            if value is None:
                continue
            if isinstance(value, str) and value == "":
                continue
            if isinstance(value, tuple) and len(value) == 0:
                continue
            # Omit was_fallback=False — only log when True
            if key == "was_fallback" and value is False:
                continue
            # Convert tuple to list for JSON serialization
            if isinstance(value, tuple):
                result[key] = list(value)
            else:
                result[key] = value
        return result

    def with_update(self, **kwargs: object) -> LogContext:
        """Return a NEW LogContext with updated fields.

        Does NOT mutate the original — creates a copy via
        dataclasses.replace(). This is important because different
        branches of the pipeline may need different contexts.

        Usage:
            ctx2 = ctx.with_update(step="STEP_9A", agent_role="routing")
        """
        # Convert list safety_flags to tuple for frozen dataclass
        if "safety_flags" in kwargs and isinstance(kwargs["safety_flags"], list):
            kwargs["safety_flags"] = tuple(kwargs["safety_flags"])
        return replace(self, **kwargs)

    def with_llm_result(
        self,
        *,
        provider: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
        cost_usd: float,
        latency_ms: float,
        was_fallback: bool = False,
    ) -> LogContext:
        """Return a NEW LogContext enriched with LLM call results."""
        return self.with_update(
            provider=provider,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            was_fallback=was_fallback,
        )

    def with_policy_decision(
        self,
        decision: str,
        safety_flags: list[str] | None = None,
    ) -> LogContext:
        """Return a NEW LogContext with routing/policy decision."""
        return self.with_update(
            policy_decision=decision,
            safety_flags=tuple(safety_flags) if safety_flags else None,
        )

    @classmethod
    def from_state(cls, state: dict) -> LogContext:
        """Build a LogContext from a LangGraph PipelineState dict.

        Extracts the three core tracing IDs that every orchestration
        node needs. Avoids repeating this extraction in every node.

        Args:
            state: PipelineState dict with correlation_id,
                execution_id, and query_id keys.
        """
        return cls(
            correlation_id=state.get("correlation_id"),
            execution_id=state.get("execution_id"),
            query_id=state.get("query_id"),
        )
