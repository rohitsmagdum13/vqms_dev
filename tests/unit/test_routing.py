"""Unit tests for the Routing Service (Step 9A).

Tests the deterministic routing rules engine with different
combinations of vendor tier, urgency level, and risk flags.
No external calls needed — this is pure business logic.
"""

from __future__ import annotations

from src.models.vendor import VendorProfile, VendorTier
from src.models.workflow import AnalysisResult, Sentiment, UrgencyLevel
from src.services.routing import (
    DEFAULT_TEAM,
    assign_team,
    calculate_sla_hours,
    check_automation_blocked,
)

# --- Helper to build a minimal AnalysisResult ---

def _make_analysis(
    *,
    urgency: UrgencyLevel = UrgencyLevel.MEDIUM,
    confidence: float = 0.95,
    category: str = "invoice_payment",
) -> AnalysisResult:
    return AnalysisResult(
        intent_classification="PAYMENT_QUERY",
        extracted_entities={},
        urgency_level=urgency,
        sentiment=Sentiment.NEUTRAL,
        confidence_score=confidence,
        multi_issue_detected=False,
        suggested_category=category,
    )


def _make_vendor(
    *,
    tier: VendorTier = VendorTier.STANDARD,
    risk_flags: list[str] | None = None,
) -> VendorProfile:
    return VendorProfile(
        vendor_id="V-001",
        vendor_name="Test Corp",
        vendor_tier=tier,
        contact_email="test@test.com",
        risk_flags=risk_flags or [],
    )


# ===========================================================
# SLA Matrix Tests — All 16 tier × urgency combinations
# ===========================================================

class TestSLAMatrix:
    """Test the SLA hours calculation for all tier/urgency combos."""

    # --- Platinum ---
    def test_platinum_critical_sla(self):
        assert calculate_sla_hours(VendorTier.PLATINUM, UrgencyLevel.CRITICAL) == 1

    def test_platinum_high_sla(self):
        assert calculate_sla_hours(VendorTier.PLATINUM, UrgencyLevel.HIGH) == 2

    def test_platinum_medium_sla(self):
        assert calculate_sla_hours(VendorTier.PLATINUM, UrgencyLevel.MEDIUM) == 4

    def test_platinum_low_sla(self):
        assert calculate_sla_hours(VendorTier.PLATINUM, UrgencyLevel.LOW) == 8

    # --- Gold ---
    def test_gold_critical_sla(self):
        assert calculate_sla_hours(VendorTier.GOLD, UrgencyLevel.CRITICAL) == 2

    def test_gold_high_sla(self):
        assert calculate_sla_hours(VendorTier.GOLD, UrgencyLevel.HIGH) == 4

    def test_gold_medium_sla(self):
        assert calculate_sla_hours(VendorTier.GOLD, UrgencyLevel.MEDIUM) == 8

    def test_gold_low_sla(self):
        assert calculate_sla_hours(VendorTier.GOLD, UrgencyLevel.LOW) == 16

    # --- Silver ---
    def test_silver_critical_sla(self):
        assert calculate_sla_hours(VendorTier.SILVER, UrgencyLevel.CRITICAL) == 4

    def test_silver_high_sla(self):
        assert calculate_sla_hours(VendorTier.SILVER, UrgencyLevel.HIGH) == 4

    def test_silver_medium_sla(self):
        assert calculate_sla_hours(VendorTier.SILVER, UrgencyLevel.MEDIUM) == 8

    def test_silver_low_sla(self):
        assert calculate_sla_hours(VendorTier.SILVER, UrgencyLevel.LOW) == 24

    # --- Standard ---
    def test_standard_critical_sla(self):
        assert calculate_sla_hours(VendorTier.STANDARD, UrgencyLevel.CRITICAL) == 4

    def test_standard_high_sla(self):
        assert calculate_sla_hours(VendorTier.STANDARD, UrgencyLevel.HIGH) == 8

    def test_standard_medium_sla(self):
        assert calculate_sla_hours(VendorTier.STANDARD, UrgencyLevel.MEDIUM) == 24

    def test_standard_low_sla(self):
        assert calculate_sla_hours(VendorTier.STANDARD, UrgencyLevel.LOW) == 48


# ===========================================================
# Team Assignment Tests
# ===========================================================

class TestTeamAssignment:
    """Test the team assignment by category."""

    def test_invoice_payment_category(self):
        assert assign_team("invoice_payment") == "Finance Team"

    def test_purchase_order_category(self):
        assert assign_team("purchase_order") == "Procurement Team"

    def test_contract_category(self):
        assert assign_team("contract") == "Contract Team"

    def test_general_category(self):
        assert assign_team("general") == "General Support"

    def test_unknown_category_defaults_to_general(self):
        assert assign_team("unknown_category") == DEFAULT_TEAM

    def test_none_category_defaults_to_general(self):
        assert assign_team(None) == DEFAULT_TEAM

    def test_empty_string_defaults_to_general(self):
        assert assign_team("") == DEFAULT_TEAM


# ===========================================================
# Automation Blocking Tests
# ===========================================================

class TestAutomationBlocking:
    """Test the automation blocking logic."""

    def test_block_automation_flag_blocks(self):
        """Vendor with BLOCK_AUTOMATION flag should block automation."""
        analysis = _make_analysis()
        vendor = _make_vendor(risk_flags=["BLOCK_AUTOMATION"])
        assert check_automation_blocked(analysis, vendor) is True

    def test_no_flags_does_not_block(self):
        """Vendor without BLOCK_AUTOMATION flag should not block."""
        analysis = _make_analysis()
        vendor = _make_vendor(risk_flags=[])
        assert check_automation_blocked(analysis, vendor) is False

    def test_other_flags_do_not_block(self):
        """Other risk flags should not block automation."""
        analysis = _make_analysis()
        vendor = _make_vendor(risk_flags=["OVERDUE_INVOICE_HISTORY", "HIGH_VALUE"])
        assert check_automation_blocked(analysis, vendor) is False

    def test_none_vendor_does_not_block(self):
        """No vendor profile should not block automation."""
        analysis = _make_analysis()
        assert check_automation_blocked(analysis, None) is False

    def test_critical_urgency_does_not_block(self):
        """CRITICAL urgency should NOT block automation by itself."""
        analysis = _make_analysis(urgency=UrgencyLevel.CRITICAL)
        vendor = _make_vendor()
        assert check_automation_blocked(analysis, vendor) is False
