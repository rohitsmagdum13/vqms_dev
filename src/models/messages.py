"""Pydantic models for inter-agent communication in VQMS.

Agents communicate through structured messages that include
the sender, content, tool calls, and correlation metadata.
These models follow the AgentMessage schema from the coding
standards (Section 2: Multi-Layer Architecture).

Used by the LangGraph orchestrator to pass data between
agents and to maintain audit trails of agent decisions.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from src.utils.helpers import ist_now


class ToolCall(BaseModel):
    """Record of a tool invocation by an agent.

    Agents call tools (vendor lookup, KB search, ticket creation)
    during their execution. Each call is recorded for audit trail
    and cost tracking purposes.
    """

    tool_name: str = Field(description="Name of the tool invoked")
    tool_input: dict[str, Any] = Field(
        default_factory=dict,
        description="Input parameters passed to the tool",
    )
    tool_output: dict[str, Any] | None = Field(
        default=None,
        description="Output returned by the tool (None if not yet executed)",
    )
    execution_time_ms: float | None = Field(
        default=None,
        description="How long the tool call took in milliseconds",
    )
    success: bool = Field(
        default=True,
        description="Whether the tool call succeeded",
    )


class AgentMessage(BaseModel):
    """Structured message passed between agents in the pipeline.

    Every agent interaction produces an AgentMessage that records
    what the agent did, which tools it called, and the correlation
    ID for tracing. These messages are stored in the audit trail.
    """

    agent_name: str = Field(
        description="Name of the agent that produced this message",
    )
    role: str = Field(
        description="Agent role: planner, worker, reviewer, or system",
    )
    content: str = Field(
        description="The agent's output text or decision",
    )
    tool_calls: list[ToolCall] = Field(
        default_factory=list,
        description="Tools the agent invoked during this step",
    )
    correlation_id: str = Field(
        description="UUID4 tracing ID linking to the query",
    )
    timestamp: datetime = Field(default_factory=ist_now)
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional context: tokens_used, cost, model_id, prompt_id",
    )
