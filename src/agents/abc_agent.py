"""Base agent class for VQMS AI agents.

All AI agents (Query Analysis, Resolution, Communication Drafting)
inherit from BaseAgent. It provides common functionality:
  - Jinja2 prompt template loading and rendering
  - Bedrock LLM calling with budget tracking
  - JSON response parsing with markdown fence stripping

Agents are stateless — each call to execute() is independent.
State flows through function arguments, not instance variables.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from src.llm.factory import llm_complete
from src.models.budget import Budget

logger = logging.getLogger(__name__)

# Prompts directory at project root
PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"


class BaseAgent:
    """Base class for all VQMS AI agents.

    Subclasses implement execute() with their specific logic.
    The base class handles template loading, LLM calling, and
    JSON parsing so agents can focus on their domain logic.
    """

    def __init__(self, agent_name: str, prompt_dir: str) -> None:
        """Initialize the agent.

        Args:
            agent_name: Human-readable name for logging (e.g., "QueryAnalysisAgent").
            prompt_dir: Subdirectory under prompts/ (e.g., "query_analysis").
        """
        self.agent_name = agent_name
        self.prompt_dir = prompt_dir
        self._jinja_env = Environment(
            loader=FileSystemLoader(str(PROMPTS_DIR)),
            autoescape=False,
            keep_trailing_newline=True,
        )

    def load_and_render(self, template_name: str, **context: object) -> str:
        """Load a Jinja2 template and render it with the given context.

        Args:
            template_name: Template filename relative to prompt_dir
                (e.g., "v1.jinja" loads prompts/<prompt_dir>/v1.jinja).
            **context: Template variables.

        Returns:
            Rendered prompt string.
        """
        template_path = f"{self.prompt_dir}/{template_name}"
        template = self._jinja_env.get_template(template_path)
        rendered = template.render(**context)
        logger.debug(
            "Prompt template rendered",
            extra={
                "agent": self.agent_name,
                "template": template_path,
                "rendered_length": len(rendered),
            },
        )
        return rendered

    async def call_llm(
        self,
        prompt: str,
        *,
        system_prompt: str = "",
        budget: Budget | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        correlation_id: str | None = None,
    ) -> dict:
        """Call LLM via the factory with automatic provider fallback.

        Checks if the budget allows another LLM call before
        proceeding. After the call, updates the budget counters
        with actual token usage.

        Args:
            prompt: User message for the LLM.
            system_prompt: System instruction.
            budget: Token/cost budget tracker. If provided, will be
                checked before the call and updated after.
            temperature: Sampling temperature override.
            max_tokens: Max output tokens override.
            correlation_id: Tracing ID.

        Returns:
            Dict with: text, tokens_in, tokens_out, cost_usd,
            latency_ms, model, provider, was_fallback.

        Raises:
            BudgetExceededError: If budget limits are exceeded.
        """
        # Check budget before making the call
        if budget is not None and not budget.is_within_budget():
            logger.warning(
                "Budget exceeded — skipping LLM call",
                extra={
                    "agent_role": self.agent_name,
                    "tokens_used_in": budget.tokens_used_in,
                    "tokens_used_out": budget.tokens_used_out,
                    "cost_used_usd": budget.cost_used_usd,
                    "correlation_id": correlation_id,
                },
            )
            raise BudgetExceededError(self.agent_name)

        result = await llm_complete(
            prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            correlation_id=correlation_id,
        )

        # Update budget counters after the call
        if budget is not None:
            budget.tokens_used_in += result["tokens_in"]
            budget.tokens_used_out += result["tokens_out"]
            budget.cost_used_usd += result["cost_usd"]

        logger.info(
            "Agent LLM call completed",
            extra={
                "agent_role": self.agent_name,
                "model": result.get("model", "unknown"),
                "provider": result.get("provider", "unknown"),
                "was_fallback": result.get("was_fallback", False),
                "tokens_in": result["tokens_in"],
                "tokens_out": result["tokens_out"],
                "cost_usd": round(result["cost_usd"], 6),
                "latency_ms": round(result["latency_ms"], 1),
                "correlation_id": correlation_id,
            },
        )

        return result

    @staticmethod
    def parse_json_response(raw_text: str) -> dict:
        """Parse a JSON response from the LLM, stripping markdown fences.

        Claude sometimes wraps JSON in ```json ... ``` even when
        instructed not to. This method handles that case.

        Args:
            raw_text: Raw LLM output text.

        Returns:
            Parsed dict from the JSON.

        Raises:
            json.JSONDecodeError: If the text is not valid JSON
                even after stripping markdown fences.
        """
        cleaned = raw_text.strip()

        # Strip markdown code fences: ```json ... ``` or ``` ... ```
        fence_pattern = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?\s*```$", re.DOTALL)
        match = fence_pattern.match(cleaned)
        if match:
            cleaned = match.group(1).strip()

        return json.loads(cleaned)


class BudgetExceededError(Exception):
    """Raised when an agent's LLM call would exceed the token/cost budget.

    The orchestrator catches this and routes to human review
    instead of making more LLM calls.
    """

    def __init__(self, agent_name: str) -> None:
        self.agent_name = agent_name
        super().__init__(f"Budget exceeded for agent: {agent_name}")
