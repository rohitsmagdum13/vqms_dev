"""Query Analysis Agent for VQMS (Step 8).

Analyzes incoming vendor queries from EITHER entry point (email
or portal). Extracts intent, entities, urgency, sentiment, and
a confidence score. The confidence score determines the processing
path:
  - >= 0.85: continue to routing + KB search (Path A or B)
  - < 0.85: route to human review (Path C)

Uses Claude Sonnet 3.5 via the Bedrock adapter with temperature=0.1
for classification precision. Prompt template loaded from
prompts/query_analysis/v1.jinja.

Corresponds to Step 8 in the VQMS Solution Flow Document.
"""

from __future__ import annotations

import json
import logging

from src.agents.abc_agent import BaseAgent
from src.models.budget import Budget
from src.models.vendor import VendorProfile
from src.models.workflow import AnalysisResult, Sentiment, UrgencyLevel
from src.utils.log_context import LogContext

logger = logging.getLogger(__name__)

# System prompt instructs Claude to return pure JSON
SYSTEM_PROMPT = (
    "You are a vendor query analysis agent. "
    "Return ONLY a valid JSON object. "
    "No markdown formatting, no code fences, no explanation, no preamble."
)

# Retry prompt appended when the first response is not valid JSON
JSON_FIX_PROMPT = (
    "\n\nYour previous response was not valid JSON. "
    "Please return ONLY a valid JSON object with the exact fields specified. "
    "No markdown, no explanation — just the JSON."
)


class QueryAnalysisAgent(BaseAgent):
    """Analyzes vendor queries and produces structured AnalysisResult.

    Usage:
        agent = QueryAnalysisAgent()
        result = await agent.analyze_query(
            query_payload=payload,
            vendor_profile=vendor,
            vendor_history=history,
            budget=budget,
            correlation_id="abc-123",
        )
    """

    def __init__(self) -> None:
        super().__init__(
            agent_name="QueryAnalysisAgent",
            prompt_dir="query_analysis",
        )

    async def analyze_query(
        self,
        query_payload: dict,
        *,
        vendor_profile: VendorProfile | None = None,
        vendor_history: list[dict] | None = None,
        budget: Budget | None = None,
        correlation_id: str | None = None,
    ) -> AnalysisResult:
        """Analyze a vendor query and return structured analysis.

        Renders the prompt template with query + vendor context,
        calls Claude Sonnet 3.5, and parses the JSON response
        into an AnalysisResult model.

        If JSON parsing fails on the first attempt, retries once
        with a "fix your JSON" instruction. If the second attempt
        also fails, returns a low-confidence result that will
        route to Path C (human review).

        Args:
            query_payload: Dict with keys: subject, description,
                query_type, reference_number.
            vendor_profile: Vendor profile from Salesforce (optional).
            vendor_history: List of past query summaries (optional).
            budget: Token/cost budget tracker.
            correlation_id: Tracing ID.

        Returns:
            AnalysisResult with all classification fields populated.
        """
        ctx = LogContext(
            correlation_id=correlation_id,
            agent_role="query_analysis",
            step="STEP_8",
        )

        logger.info(
            "Starting query analysis",
            extra={
                **ctx.to_dict(),
                "query_subject": query_payload.get("subject", ""),
                "vendor_id": vendor_profile.vendor_id if vendor_profile else None,
            },
        )

        # Build context for template rendering
        query_context = {
            "subject": query_payload.get("subject", ""),
            "description": query_payload.get("description", ""),
            "query_type": query_payload.get("query_type"),
            "reference_number": query_payload.get("reference_number"),
        }

        # Render the prompt template
        prompt = self.load_and_render(
            "v1.jinja",
            query=query_context,
            vendor_profile=vendor_profile,
            vendor_history=vendor_history or [],
        )

        # First LLM call attempt
        llm_result = await self.call_llm(
            prompt,
            system_prompt=SYSTEM_PROMPT,
            budget=budget,
            temperature=0.1,
            max_tokens=500,
            correlation_id=correlation_id,
        )

        raw_text = llm_result["text"]

        # Try to parse JSON response
        try:
            parsed = self.parse_json_response(raw_text)
            return self._build_analysis_result(parsed, llm_result)
        except json.JSONDecodeError:
            logger.warning(
                "First JSON parse failed — retrying with fix prompt",
                extra={
                    **ctx.to_dict(),
                    "raw_text_preview": raw_text[:200],
                },
            )

        # Second attempt: append fix instruction to the original prompt
        retry_prompt = prompt + JSON_FIX_PROMPT
        llm_result = await self.call_llm(
            retry_prompt,
            system_prompt=SYSTEM_PROMPT,
            budget=budget,
            temperature=0.0,
            max_tokens=500,
            correlation_id=correlation_id,
        )

        raw_text = llm_result["text"]

        try:
            parsed = self.parse_json_response(raw_text)
            return self._build_analysis_result(parsed, llm_result)
        except json.JSONDecodeError:
            # Both attempts failed — return low-confidence result
            # This will trigger Path C (human review)
            logger.error(
                "Both JSON parse attempts failed — returning low confidence",
                extra={
                    **ctx.to_dict(),
                    "raw_text_preview": raw_text[:200],
                },
            )
            return AnalysisResult(
                intent_classification="UNKNOWN",
                extracted_entities={},
                urgency_level=UrgencyLevel.MEDIUM,
                sentiment=Sentiment.NEUTRAL,
                confidence_score=0.0,
                multi_issue_detected=False,
                suggested_category="general",
                raw_llm_output=raw_text,
                tokens_in=llm_result["tokens_in"],
                tokens_out=llm_result["tokens_out"],
                cost_usd=llm_result["cost_usd"],
                latency_ms=llm_result["latency_ms"],
                provider=llm_result.get("provider"),
                was_fallback=llm_result.get("was_fallback", False),
            )

    @staticmethod
    def _build_analysis_result(parsed: dict, llm_result: dict) -> AnalysisResult:
        """Build an AnalysisResult from parsed JSON and LLM metadata.

        Maps LLM output field names to the AnalysisResult model,
        handling case-insensitive enum values and missing fields.
        """
        # Map urgency string to enum (case-insensitive)
        urgency_str = parsed.get("urgency_level", "medium").lower()
        try:
            urgency = UrgencyLevel(urgency_str)
        except ValueError:
            urgency = UrgencyLevel.MEDIUM

        # Map sentiment string — the LLM uses different names than our enum
        sentiment_map = {
            "neutral": Sentiment.NEUTRAL,
            "polite_concerned": Sentiment.NEUTRAL,
            "frustrated": Sentiment.FRUSTRATED,
            "escalation_tone": Sentiment.ANGRY,
            "positive": Sentiment.POSITIVE,
            "negative": Sentiment.NEGATIVE,
            "angry": Sentiment.ANGRY,
        }
        sentiment_str = parsed.get("sentiment", "neutral").lower()
        sentiment = sentiment_map.get(sentiment_str, Sentiment.NEUTRAL)

        return AnalysisResult(
            intent_classification=parsed.get("intent_classification", "GENERAL_INQUIRY"),
            extracted_entities=parsed.get("extracted_entities", {}),
            urgency_level=urgency,
            sentiment=sentiment,
            confidence_score=float(parsed.get("confidence_score", 0.0)),
            multi_issue_detected=bool(parsed.get("multi_issue_detected", False)),
            suggested_category=parsed.get("suggested_category", "general"),
            raw_llm_output=llm_result["text"],
            tokens_in=llm_result["tokens_in"],
            tokens_out=llm_result["tokens_out"],
            cost_usd=llm_result["cost_usd"],
            latency_ms=llm_result["latency_ms"],
            provider=llm_result.get("provider"),
            was_fallback=llm_result.get("was_fallback", False),
        )
