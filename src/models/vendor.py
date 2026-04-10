"""Pydantic models for vendor data in VQMS.

These models define the shape of vendor information as it flows
through the pipeline — from Salesforce lookup to agent decisions.

Also includes models for vendor CRUD operations against the
Salesforce standard Account object (used by the portal's vendor
management UI, merged from local_vqm).

Corresponds to:
  - memory.vendor_profile_cache table in PostgreSQL
  - cache.kv_store with key vqms:vendor:<vendor_id> (1-hour TTL)
  - Steps E2.5 (email vendor identification) and 7.3 (context loading)
  - GET /vendors and PUT /vendors/{vendor_id} API endpoints
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, model_validator


class VendorTier(str, Enum):
    """Vendor importance level — determines SLA targets and escalation speed.

    Tier is pulled from Salesforce during vendor resolution.
    Higher tiers get faster SLA targets and earlier escalations.
    """

    PLATINUM = "platinum"
    GOLD = "gold"
    SILVER = "silver"
    STANDARD = "standard"


class VendorMatch(BaseModel):
    """Result of looking up a vendor in Salesforce.

    The Vendor Resolution Service produces this after trying
    to match an email sender against Salesforce CRM records.
    For portal queries, vendor_id is already known from the JWT.
    """

    vendor_id: str = Field(description="Salesforce Account ID")
    vendor_name: str = Field(description="Company name from Salesforce")
    vendor_tier: VendorTier = Field(
        default=VendorTier.STANDARD,
        description="SLA tier — drives response time targets",
    )

    # How we found this vendor
    match_method: str = Field(
        description=(
            "How the vendor was matched: "
            "EMAIL_EXACT, VENDOR_ID_BODY, NAME_SIMILARITY, or UNRESOLVED"
        ),
    )
    match_confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="How confident we are in this match (0.0 to 1.0)",
    )

    # Flags for routing decisions
    risk_flags: list[str] = Field(
        default_factory=list,
        description="Any risk flags from Salesforce (e.g., 'payment_overdue')",
    )


class VendorProfile(BaseModel):
    """Full vendor profile loaded from Salesforce for context enrichment.

    Used by agents to understand who they're dealing with —
    tier affects SLA, risk flags affect routing, account manager
    info is included in ticket creation.
    """

    vendor_id: str = Field(description="Salesforce Account ID")
    vendor_name: str = Field(description="Company name from Salesforce")
    vendor_tier: VendorTier = Field(
        default=VendorTier.STANDARD,
        description="SLA tier from Salesforce",
    )
    contact_email: str = Field(description="Primary contact email address")
    account_manager: str | None = Field(
        default=None,
        description="Assigned account manager name",
    )
    payment_terms: str | None = Field(
        default=None,
        description="Payment terms (e.g., 'Net 30')",
    )
    risk_flags: list[str] = Field(
        default_factory=list,
        description="Active risk flags from Salesforce",
    )
    is_active: bool = Field(
        default=True,
        description="False if vendor account is deactivated in Salesforce",
    )


# --- Vendor CRUD Models (merged from local_vqm) ---
# These models are used by the vendor management portal endpoints
# (GET /vendors, PUT /vendors/{vendor_id}). They map to the
# Salesforce STANDARD Account object — NOT the custom
# Vendor_Account__c object used by the AI pipeline above.


class VendorAccountData(BaseModel):
    """Full vendor record from the Salesforce standard Account object.

    Returned by GET /vendors. Contains all fields that the portal
    displays in the vendor management table. Fields are optional
    because not all Salesforce records have every field populated.
    """

    id: str = Field(description="Salesforce Account record ID")
    name: str = Field(description="Account name (company name)")
    vendor_id: str | None = Field(
        default=None,
        description="Custom Vendor_ID__c field on Account",
    )
    website: str | None = Field(default=None, description="Company website URL")
    vendor_tier: str | None = Field(
        default=None,
        description="Vendor tier (Vendor_Tier__c): platinum, gold, silver, standard",
    )
    category: str | None = Field(
        default=None,
        description="Vendor category (Category__c)",
    )
    payment_terms: str | None = Field(
        default=None,
        description="Payment terms (Payment_Terms__c), e.g. 'Net 30'",
    )
    annual_revenue: float | None = Field(
        default=None,
        description="Annual revenue from Salesforce AnnualRevenue field",
    )
    sla_response_hours: float | None = Field(
        default=None,
        description="SLA response time in hours (SLA_Response_Hours__c)",
    )
    sla_resolution_days: float | None = Field(
        default=None,
        description="SLA resolution time in days (SLA_Resolution_Days__c)",
    )
    vendor_status: str | None = Field(
        default=None,
        description="Vendor status (Vendor_Status__c): Active, Inactive",
    )
    onboarded_date: str | None = Field(
        default=None,
        description="Date vendor was onboarded (Onboarded_Date__c)",
    )
    billing_city: str | None = Field(default=None, description="BillingCity")
    billing_state: str | None = Field(default=None, description="BillingState")
    billing_country: str | None = Field(default=None, description="BillingCountry")


# Fields that are allowed to be updated via PUT /vendors/{vendor_id}
VENDOR_UPDATABLE_FIELDS: set[str] = {
    "Website",
    "Vendor_Tier__c",
    "Category__c",
    "Payment_Terms__c",
    "AnnualRevenue",
    "SLA_Response_Hours__c",
    "SLA_Resolution_Days__c",
    "Vendor_Status__c",
    "Onboarded_Date__c",
    "BillingCity",
    "BillingState",
    "BillingCountry",
}


class VendorUpdateRequest(BaseModel):
    """Request body for PUT /vendors/{vendor_id}.

    At least one field must be provided. Field names use
    snake_case (Python convention) and are mapped to Salesforce
    API names in the adapter.
    """

    website: str | None = Field(default=None, description="Company website URL")
    vendor_tier: str | None = Field(default=None, description="Vendor tier")
    category: str | None = Field(default=None, description="Vendor category")
    payment_terms: str | None = Field(default=None, description="Payment terms")
    annual_revenue: float | None = Field(default=None, description="Annual revenue")
    sla_response_hours: float | None = Field(default=None, description="SLA response hours")
    sla_resolution_days: float | None = Field(default=None, description="SLA resolution days")
    vendor_status: str | None = Field(default=None, description="Vendor status")
    onboarded_date: str | None = Field(default=None, description="Onboarded date")
    billing_city: str | None = Field(default=None, description="Billing city")
    billing_state: str | None = Field(default=None, description="Billing state")
    billing_country: str | None = Field(default=None, description="Billing country")

    @model_validator(mode="after")
    def at_least_one_field(self) -> VendorUpdateRequest:
        """Ensure at least one field is provided for update."""
        values = self.model_dump(exclude_none=True)
        if not values:
            msg = "At least one field must be provided for update"
            raise ValueError(msg)
        return self

    def to_salesforce_fields(self) -> dict:
        """Convert snake_case Python fields to Salesforce API field names.

        Only includes fields that have non-None values.
        """
        field_mapping = {
            "website": "Website",
            "vendor_tier": "Vendor_Tier__c",
            "category": "Category__c",
            "payment_terms": "Payment_Terms__c",
            "annual_revenue": "AnnualRevenue",
            "sla_response_hours": "SLA_Response_Hours__c",
            "sla_resolution_days": "SLA_Resolution_Days__c",
            "vendor_status": "Vendor_Status__c",
            "onboarded_date": "Onboarded_Date__c",
            "billing_city": "BillingCity",
            "billing_state": "BillingState",
            "billing_country": "BillingCountry",
        }
        result = {}
        for python_name, sf_name in field_mapping.items():
            value = getattr(self, python_name)
            if value is not None:
                result[sf_name] = value
        return result


class VendorUpdateResult(BaseModel):
    """Response body for PUT /vendors/{vendor_id}."""

    success: bool = Field(description="Whether the update succeeded")
    vendor_id: str = Field(description="The Vendor_ID__c that was updated")
    updated_fields: list[str] = Field(
        description="List of Salesforce field names that were updated",
    )
    message: str = Field(description="Human-readable result message")
