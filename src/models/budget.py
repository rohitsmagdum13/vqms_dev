"""Budget tracking model for LLM token and cost management.

Every query execution has a budget that limits how many tokens
and how much money can be spent on LLM calls. The orchestrator
checks the budget before each LLM call and stops if limits
are exceeded.

Budget limits come from environment variables:
  - AGENT_BUDGET_MAX_TOKENS_IN (default 8000)
  - AGENT_BUDGET_MAX_TOKENS_OUT (default 4096)
  - AGENT_BUDGET_CURRENCY_LIMIT_USD (default 0.50)
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Budget(BaseModel):
    """Token and cost budget for a single query execution.

    Tracks limits and current usage. The orchestrator checks
    is_within_budget() before making each LLM call. If the
    budget is exceeded, the query routes to human review
    instead of making more LLM calls.
    """

    # Limits — set from config at execution start
    max_tokens_in: int = Field(
        default=8000,
        description="Maximum input tokens allowed across all LLM calls",
    )
    max_tokens_out: int = Field(
        default=4096,
        description="Maximum output tokens allowed across all LLM calls",
    )
    currency_limit_usd: float = Field(
        default=0.50,
        description="Maximum cost in USD for this execution",
    )

    # Current usage — updated after each LLM call
    tokens_used_in: int = Field(
        default=0,
        description="Total input tokens used so far",
    )
    tokens_used_out: int = Field(
        default=0,
        description="Total output tokens used so far",
    )
    cost_used_usd: float = Field(
        default=0.0,
        description="Total cost in USD so far",
    )

    def is_within_budget(self) -> bool:
        """Check if the execution is still within all budget limits.

        Returns:
            True if all three limits (tokens in, tokens out, cost)
            have not been exceeded.
        """
        return (
            self.tokens_used_in <= self.max_tokens_in
            and self.tokens_used_out <= self.max_tokens_out
            and self.cost_used_usd <= self.currency_limit_usd
        )

    @property
    def remaining_tokens_in(self) -> int:
        """How many input tokens are left before hitting the limit."""
        return max(0, self.max_tokens_in - self.tokens_used_in)

    @property
    def remaining_tokens_out(self) -> int:
        """How many output tokens are left before hitting the limit."""
        return max(0, self.max_tokens_out - self.tokens_used_out)

    @property
    def remaining_cost_usd(self) -> float:
        """How much budget (in USD) is left before hitting the limit."""
        return max(0.0, self.currency_limit_usd - self.cost_used_usd)
