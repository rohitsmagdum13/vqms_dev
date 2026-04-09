"""Tests for vendor CRUD models and field mapping.

Tests the VendorAccountData, VendorUpdateRequest, and
VendorUpdateResult Pydantic models, plus the snake_case
to Salesforce field name conversion.
"""

from __future__ import annotations

import pytest

from src.models.vendor import (
    VendorAccountData,
    VendorUpdateRequest,
    VendorUpdateResult,
)


class TestVendorAccountData:
    """Tests for the VendorAccountData model."""

    def test_valid_vendor_with_all_fields(self):
        """A vendor record with all fields creates successfully."""
        vendor = VendorAccountData(
            id="001ABC",
            name="Acme Corp",
            vendor_id="V-001",
            website="https://acme.com",
            vendor_tier="gold",
            category="technology",
            payment_terms="Net 30",
            annual_revenue=5000000.0,
            sla_response_hours=4.0,
            sla_resolution_days=2.0,
            vendor_status="Active",
            onboarded_date="2025-01-15",
            billing_city="Mumbai",
            billing_state="Maharashtra",
            billing_country="India",
        )
        assert vendor.name == "Acme Corp"
        assert vendor.annual_revenue == 5000000.0

    def test_minimal_vendor_with_required_fields_only(self):
        """Only id and name are required — everything else defaults to None."""
        vendor = VendorAccountData(id="001ABC", name="Acme Corp")
        assert vendor.vendor_id is None
        assert vendor.website is None
        assert vendor.annual_revenue is None
        assert vendor.billing_city is None


class TestVendorUpdateRequest:
    """Tests for the VendorUpdateRequest model."""

    def test_valid_partial_update(self):
        """An update with some fields creates successfully."""
        req = VendorUpdateRequest(
            website="https://new-acme.com",
            billing_city="Delhi",
        )
        assert req.website == "https://new-acme.com"
        assert req.billing_city == "Delhi"
        assert req.vendor_tier is None  # not being updated

    def test_at_least_one_field_required(self):
        """An empty update (all None) should raise ValueError."""
        with pytest.raises(ValueError, match="At least one field"):
            VendorUpdateRequest()

    def test_to_salesforce_fields_mapping(self):
        """Snake_case fields should map to correct Salesforce API names."""
        req = VendorUpdateRequest(
            website="https://acme.com",
            vendor_tier="gold",
            annual_revenue=1000000.0,
            billing_city="Mumbai",
        )
        sf_fields = req.to_salesforce_fields()

        assert sf_fields == {
            "Website": "https://acme.com",
            "Vendor_Tier__c": "gold",
            "AnnualRevenue": 1000000.0,
            "BillingCity": "Mumbai",
        }

    def test_to_salesforce_fields_excludes_none(self):
        """Only non-None fields should appear in Salesforce mapping."""
        req = VendorUpdateRequest(website="https://acme.com")
        sf_fields = req.to_salesforce_fields()

        assert sf_fields == {"Website": "https://acme.com"}
        assert "BillingCity" not in sf_fields
        assert "Vendor_Tier__c" not in sf_fields


class TestVendorUpdateResult:
    """Tests for the VendorUpdateResult model."""

    def test_successful_result(self):
        """A successful update result creates correctly."""
        result = VendorUpdateResult(
            success=True,
            vendor_id="V-001",
            updated_fields=["Website", "BillingCity"],
            message="Updated 2 field(s)",
        )
        assert result.success is True
        assert len(result.updated_fields) == 2

    def test_failed_result(self):
        """A failed update result creates correctly."""
        result = VendorUpdateResult(
            success=False,
            vendor_id="V-999",
            updated_fields=[],
            message="Vendor not found",
        )
        assert result.success is False
        assert result.updated_fields == []
