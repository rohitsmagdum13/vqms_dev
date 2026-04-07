"""Pydantic models for vendor data in VQMS.

These models define the shape of vendor information as it flows
through the pipeline — from Salesforce lookup to agent decisions.

Corresponds to:
  - memory.vendor_profile_cache table in PostgreSQL
  - vqms:vendor:<vendor_id> Redis key family (1-hour TTL)
  - Steps E2.5 (email vendor identification) and 7.3 (context loading)
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


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
