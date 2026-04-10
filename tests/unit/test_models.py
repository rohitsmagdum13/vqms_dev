"""Tests for all VQMS Pydantic models.

Validates model creation, default values, field constraints,
and validation errors. Follows the test pattern from CLAUDE.md:
test valid creation, test defaults, test validation errors.
"""

from __future__ import annotations

from datetime import datetime

from src.utils.helpers import IST

import pytest

from src.models.budget import Budget
from src.models.communication import DraftResponse, ValidationReport
from src.models.email import EmailAttachment, EmailMessage, ParsedEmailPayload
from src.models.memory import EmbeddingRecord, EpisodicMemory, VendorProfileCache
from src.models.messages import AgentMessage, ToolCall
from src.models.query import QuerySubmission, UnifiedQueryPayload
from src.models.ticket import RoutingDecision, TicketRecord
from src.models.triage import TriagePackage
from src.models.vendor import VendorMatch, VendorProfile, VendorTier
from src.models.workflow import (
    AnalysisResult,
    CaseExecution,
    Priority,
    QuerySource,
    QueryType,
    Sentiment,
    Status,
    UrgencyLevel,
    WorkflowState,
)

# ===== Enums =====


class TestEnums:
    """Verify all enums have the expected values."""

    def test_status_values(self):
        assert Status.NEW == "new"
        assert Status.CLOSED == "closed"
        assert Status.DRAFT_REJECTED == "draft_rejected"

    def test_urgency_level_values(self):
        assert UrgencyLevel.CRITICAL == "critical"
        assert UrgencyLevel.LOW == "low"

    def test_sentiment_values(self):
        assert Sentiment.ANGRY == "angry"
        assert Sentiment.NEUTRAL == "neutral"

    def test_query_source_values(self):
        assert QuerySource.EMAIL == "email"
        assert QuerySource.PORTAL == "portal"

    def test_vendor_tier_values(self):
        assert VendorTier.PLATINUM == "platinum"
        assert VendorTier.STANDARD == "standard"

    def test_query_type_values(self):
        assert QueryType.BILLING == "billing"
        assert QueryType.TECHNICAL == "technical"

    def test_priority_values(self):
        assert Priority.CRITICAL == "critical"
        assert Priority.LOW == "low"


# ===== Vendor Models =====


class TestVendorMatch:
    """Test the VendorMatch model."""

    def test_valid_creation(self, sample_vendor_match):
        assert sample_vendor_match.vendor_id == "SF-ACC-30892"
        assert sample_vendor_match.vendor_name == "TechNova Solutions"
        assert sample_vendor_match.vendor_tier == VendorTier.GOLD
        assert sample_vendor_match.match_confidence == 0.95

    def test_default_tier_is_standard(self):
        match = VendorMatch(
            vendor_id="SF-001",
            vendor_name="Unknown Corp",
            match_method="NAME_SIMILARITY",
            match_confidence=0.60,
        )
        assert match.vendor_tier == VendorTier.STANDARD

    def test_confidence_must_be_between_zero_and_one(self):
        with pytest.raises(ValueError):
            VendorMatch(
                vendor_id="SF-001",
                vendor_name="Bad Corp",
                match_method="EMAIL_EXACT",
                match_confidence=1.5,
            )

    def test_confidence_cannot_be_negative(self):
        with pytest.raises(ValueError):
            VendorMatch(
                vendor_id="SF-001",
                vendor_name="Bad Corp",
                match_method="EMAIL_EXACT",
                match_confidence=-0.1,
            )

    def test_risk_flags_default_to_empty_list(self):
        match = VendorMatch(
            vendor_id="SF-001",
            vendor_name="Safe Corp",
            match_method="EMAIL_EXACT",
            match_confidence=0.90,
        )
        assert match.risk_flags == []
        assert isinstance(match.risk_flags, list)


class TestVendorProfile:
    """Test the VendorProfile model."""

    def test_valid_creation(self):
        profile = VendorProfile(
            vendor_id="SF-001",
            vendor_name="Acme Corp",
            contact_email="vendor@acme.com",
        )
        assert profile.vendor_id == "SF-001"
        assert profile.is_active is True
        assert profile.vendor_tier == VendorTier.STANDARD


# ===== Workflow Models =====


class TestAnalysisResult:
    """Test the AnalysisResult model."""

    def test_valid_creation(self, sample_analysis_result):
        assert sample_analysis_result.intent_classification == "invoice_status"
        assert sample_analysis_result.confidence_score == 0.92
        assert sample_analysis_result.multi_issue_detected is False

    def test_confidence_bounds(self):
        with pytest.raises(ValueError):
            AnalysisResult(
                intent_classification="test",
                confidence_score=1.1,
            )

    def test_default_values(self):
        result = AnalysisResult(
            intent_classification="general_inquiry",
            confidence_score=0.75,
        )
        assert result.urgency_level == UrgencyLevel.MEDIUM
        assert result.sentiment == Sentiment.NEUTRAL
        assert result.multi_issue_detected is False
        assert result.extracted_entities == {}

    def test_entities_stored_correctly(self):
        result = AnalysisResult(
            intent_classification="invoice_query",
            confidence_score=0.9,
            extracted_entities={"invoice": "INV-001", "amount": "5000"},
        )
        assert result.extracted_entities["invoice"] == "INV-001"


class TestCaseExecution:
    """Test the CaseExecution model."""

    def test_valid_creation(self, sample_case_execution):
        assert sample_case_execution.query_id == "VQ-2026-0451"
        assert sample_case_execution.status == Status.NEW
        assert sample_case_execution.source == QuerySource.EMAIL

    def test_default_status_is_new(self):
        case = CaseExecution(
            execution_id="test-exec-id",
            query_id="VQ-2026-0001",
            correlation_id="test-corr-id",
            source=QuerySource.PORTAL,
        )
        assert case.status == Status.NEW
        assert case.selected_path is None
        assert case.completed_at is None

    def test_timestamps_are_set(self):
        case = CaseExecution(
            execution_id="test-exec-id",
            query_id="VQ-2026-0001",
            correlation_id="test-corr-id",
            source=QuerySource.EMAIL,
        )
        assert isinstance(case.created_at, datetime)
        assert case.created_at.tzinfo is not None


class TestWorkflowState:
    """Test the WorkflowState model."""

    def test_valid_creation(self):
        state = WorkflowState(
            execution_id="exec-001",
            query_id="VQ-2026-0001",
            status=Status.ANALYZING,
            source=QuerySource.EMAIL,
        )
        assert state.current_phase == "intake"
        assert state.selected_path is None


# ===== Email Models =====


class TestEmailAttachment:
    """Test the EmailAttachment model."""

    def test_valid_creation(self):
        att = EmailAttachment(
            filename="invoice.pdf",
            content_type="application/pdf",
            size_bytes=1024,
        )
        assert att.filename == "invoice.pdf"
        assert att.s3_key is None

    def test_size_cannot_be_negative(self):
        with pytest.raises(ValueError):
            EmailAttachment(
                filename="bad.pdf",
                size_bytes=-1,
            )


class TestEmailMessage:
    """Test the EmailMessage model."""

    def test_valid_creation(self):
        msg = EmailMessage(
            message_id="<abc123@mail.com>",
            sender_email="vendor@acme.com",
            subject="Invoice Query",
            body_text="Please check invoice INV-001",
            received_at=datetime.now(IST),
        )
        assert msg.message_id == "<abc123@mail.com>"
        assert msg.attachments == []
        assert msg.references == []


class TestParsedEmailPayload:
    """Test the ParsedEmailPayload model."""

    def test_valid_creation(self):
        email_msg = EmailMessage(
            message_id="<abc@test.com>",
            sender_email="vendor@test.com",
            subject="Test",
            body_text="Test body",
            received_at=datetime.now(IST),
        )
        payload = ParsedEmailPayload(
            email=email_msg,
            correlation_id="corr-001",
            query_id="VQ-2026-0001",
            execution_id="exec-001",
        )
        assert payload.thread_status == "NEW"
        assert payload.is_duplicate is False


# ===== Query Models =====


class TestQuerySubmission:
    """Test the QuerySubmission model."""

    def test_valid_creation(self):
        sub = QuerySubmission(
            query_type=QueryType.BILLING,
            subject="Invoice not received",
            description="I haven't received invoice INV-2026-0451",
        )
        assert sub.priority == Priority.MEDIUM
        assert sub.attachments == []

    def test_subject_cannot_be_empty(self):
        with pytest.raises(ValueError):
            QuerySubmission(
                query_type=QueryType.BILLING,
                subject="",
                description="Some description",
            )

    def test_description_cannot_be_empty(self):
        with pytest.raises(ValueError):
            QuerySubmission(
                query_type=QueryType.BILLING,
                subject="Test",
                description="",
            )


class TestUnifiedQueryPayload:
    """Test the UnifiedQueryPayload model."""

    def test_valid_email_payload(self):
        payload = UnifiedQueryPayload(
            query_id="VQ-2026-0001",
            execution_id="exec-001",
            correlation_id="corr-001",
            source=QuerySource.EMAIL,
            subject="Invoice Query",
            description="Please check INV-001",
            thread_status="NEW",
            message_id="<abc@test.com>",
        )
        assert payload.source == QuerySource.EMAIL
        assert payload.thread_status == "NEW"

    def test_valid_portal_payload(self):
        payload = UnifiedQueryPayload(
            query_id="VQ-2026-0002",
            execution_id="exec-002",
            correlation_id="corr-002",
            source=QuerySource.PORTAL,
            vendor_id="SF-001",
            subject="Feature Request",
            description="Please add dark mode",
            query_type=QueryType.FEATURE_REQUEST,
        )
        assert payload.source == QuerySource.PORTAL
        assert payload.thread_status is None


# ===== Ticket Models =====


class TestTicketRecord:
    """Test the TicketRecord model."""

    def test_valid_creation(self):
        ticket = TicketRecord(
            ticket_id="sys-001",
            ticket_number="INC0012345",
            execution_id="exec-001",
            vendor_id="SF-001",
            subject="Invoice query",
            description="Vendor needs invoice status",
            assignment_group="billing-support",
            sla_target_hours=4.0,
        )
        assert ticket.status == "new"
        assert ticket.priority == "medium"


class TestRoutingDecision:
    """Test the RoutingDecision model."""

    def test_valid_creation(self, sample_routing_decision):
        assert sample_routing_decision.path == "A"
        assert sample_routing_decision.sla_hours == 4.0
        assert sample_routing_decision.automation_blocked is False

    def test_confidence_bounds(self):
        with pytest.raises(ValueError):
            RoutingDecision(
                execution_id="exec-001",
                assigned_team="support",
                routing_reason="test",
                sla_hours=4.0,
                vendor_tier=VendorTier.STANDARD,
                urgency_level=UrgencyLevel.LOW,
                confidence_score=2.0,
                path="A",
            )


# ===== Communication Models =====


class TestDraftResponse:
    """Test the DraftResponse model."""

    def test_valid_creation(self):
        draft = DraftResponse(
            subject="Re: Invoice Query",
            body="Your invoice INV-001 was processed on March 15.",
            confidence=0.88,
            sources=["KB-BILLING-001"],
            draft_type="RESOLUTION",
        )
        assert draft.confidence == 0.88
        assert len(draft.sources) == 1

    def test_confidence_bounds(self):
        with pytest.raises(ValueError):
            DraftResponse(
                subject="Test",
                body="Test body",
                confidence=-0.1,
                draft_type="RESOLUTION",
            )


class TestValidationReport:
    """Test the ValidationReport model."""

    def test_passed_report(self):
        report = ValidationReport(
            execution_id="exec-001",
            passed=True,
            checks_run=["ticket_format", "sla_wording", "length"],
        )
        assert report.passed is True
        assert report.failures == []
        assert report.pii_detected is False

    def test_failed_report(self):
        report = ValidationReport(
            execution_id="exec-001",
            passed=False,
            checks_run=["pii_scan"],
            failures=["PII detected: email address in body"],
            pii_detected=True,
        )
        assert report.passed is False
        assert report.pii_detected is True


# ===== Memory Models =====


class TestEpisodicMemory:
    """Test the EpisodicMemory model."""

    def test_valid_creation(self):
        mem = EpisodicMemory(
            memory_id="mem-001",
            vendor_id="SF-001",
            query_id="VQ-2026-0001",
            summary="Vendor asked about invoice INV-001, resolved via KB",
        )
        assert mem.resolution_path is None
        assert mem.metadata == {}


class TestVendorProfileCache:
    """Test the VendorProfileCache model."""

    def test_valid_creation(self):
        cache = VendorProfileCache(
            vendor_id="SF-001",
            vendor_name="Acme Corp",
        )
        assert cache.vendor_tier == VendorTier.STANDARD
        assert cache.ttl_seconds == 3600


class TestEmbeddingRecord:
    """Test the EmbeddingRecord model."""

    def test_valid_creation(self):
        rec = EmbeddingRecord(
            record_id="emb-001",
            source_document="KB-BILLING-001",
            chunk_text="Payment terms are Net 30 for all vendors.",
            embedding=[0.1] * 10,
        )
        assert len(rec.embedding) == 10
        assert rec.metadata == {}


# ===== Budget Model =====


class TestBudget:
    """Test the Budget model."""

    def test_default_budget_is_within_limits(self):
        budget = Budget()
        assert budget.is_within_budget() is True
        assert budget.remaining_tokens_in == 8000
        assert budget.remaining_tokens_out == 4096

    def test_exceeded_budget(self):
        budget = Budget(
            max_tokens_in=100,
            tokens_used_in=150,
        )
        assert budget.is_within_budget() is False
        assert budget.remaining_tokens_in == 0

    def test_cost_exceeded(self):
        budget = Budget(
            currency_limit_usd=0.10,
            cost_used_usd=0.15,
        )
        assert budget.is_within_budget() is False

    def test_remaining_cost(self):
        budget = Budget(
            currency_limit_usd=0.50,
            cost_used_usd=0.30,
        )
        assert budget.remaining_cost_usd == pytest.approx(0.20)


# ===== Messages Models =====


class TestToolCall:
    """Test the ToolCall model."""

    def test_valid_creation(self):
        call = ToolCall(
            tool_name="vendor_lookup",
            tool_input={"email": "vendor@acme.com"},
        )
        assert call.success is True
        assert call.tool_output is None


class TestAgentMessage:
    """Test the AgentMessage model."""

    def test_valid_creation(self):
        msg = AgentMessage(
            agent_name="QueryAnalysisAgent",
            role="worker",
            content="Classified as billing query with high confidence",
            correlation_id="corr-001",
        )
        assert msg.tool_calls == []
        assert msg.metadata == {}

    def test_with_tool_calls(self):
        tool = ToolCall(
            tool_name="kb_search",
            tool_input={"query": "invoice status"},
            tool_output={"articles": ["KB-001"]},
            execution_time_ms=150.5,
        )
        msg = AgentMessage(
            agent_name="ResolutionAgent",
            role="worker",
            content="Found relevant KB article",
            tool_calls=[tool],
            correlation_id="corr-001",
        )
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0].tool_name == "kb_search"


# ===== Triage Model =====


class TestTriagePackage:
    """Test the TriagePackage model."""

    def test_valid_creation(self, sample_analysis_result, sample_vendor_match):
        query = UnifiedQueryPayload(
            query_id="VQ-2026-0001",
            execution_id="exec-001",
            correlation_id="corr-001",
            source=QuerySource.EMAIL,
            subject="Complex query",
            description="Multiple issues mentioned",
        )
        triage = TriagePackage(
            triage_id="triage-001",
            execution_id="exec-001",
            correlation_id="corr-001",
            original_query=query,
            analysis_result=sample_analysis_result,
            vendor_match=sample_vendor_match,
            confidence_breakdown={
                "analysis_confidence": 0.72,
                "vendor_confidence": 0.95,
            },
        )
        assert triage.review_status == "pending"
        assert triage.reviewer_id is None
        assert triage.vendor_match is not None
