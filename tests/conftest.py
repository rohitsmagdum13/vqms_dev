"""Shared test fixtures for VQMS.

Provides reusable sample data for unit tests. These fixtures
return valid model instances that can be used as-is or modified
for specific test scenarios.
"""

from __future__ import annotations

import pytest

from src.models.ticket import RoutingDecision
from src.models.vendor import VendorMatch, VendorTier
from src.models.workflow import (
    AnalysisResult,
    CaseExecution,
    QuerySource,
    Sentiment,
    Status,
    UrgencyLevel,
)
from src.utils.helpers import ist_now


@pytest.fixture
def sample_vendor_match() -> VendorMatch:
    """A valid VendorMatch for TechNova Solutions (reference scenario)."""
    return VendorMatch(
        vendor_id="SF-ACC-30892",
        vendor_name="TechNova Solutions",
        vendor_tier=VendorTier.GOLD,
        match_method="EMAIL_EXACT",
        match_confidence=0.95,
        risk_flags=[],
    )


@pytest.fixture
def sample_analysis_result() -> AnalysisResult:
    """A valid AnalysisResult with high confidence (Path A scenario)."""
    return AnalysisResult(
        intent_classification="invoice_status",
        extracted_entities={
            "invoice_number": "INV-2026-0451",
            "amount": "45000.00",
            "currency": "USD",
        },
        urgency_level=UrgencyLevel.MEDIUM,
        sentiment=Sentiment.NEUTRAL,
        confidence_score=0.92,
        multi_issue_detected=False,
        suggested_category="billing",
    )


@pytest.fixture
def sample_case_execution() -> CaseExecution:
    """A valid CaseExecution for a new email query."""
    return CaseExecution(
        execution_id="550e8400-e29b-41d4-a716-446655440000",
        query_id="VQ-2026-0451",
        correlation_id="660e8400-e29b-41d4-a716-446655440001",
        status=Status.NEW,
        source=QuerySource.EMAIL,
        vendor_id="SF-ACC-30892",
    )


@pytest.fixture
def sample_routing_decision() -> RoutingDecision:
    """A valid RoutingDecision for Path A (AI-resolved)."""
    return RoutingDecision(
        execution_id="550e8400-e29b-41d4-a716-446655440000",
        assigned_team="billing-support",
        routing_reason="High confidence, KB match found, Gold tier vendor",
        sla_hours=4.0,
        vendor_tier=VendorTier.GOLD,
        urgency_level=UrgencyLevel.MEDIUM,
        confidence_score=0.92,
        path="A",
    )


@pytest.fixture
def now():
    """Current IST time for timestamp comparisons."""
    return ist_now()
