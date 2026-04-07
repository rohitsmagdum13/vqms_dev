"""Salesforce CRM adapter stub for vendor resolution.

In Phase 2, this is a STUB returning mock vendor data.
Real Salesforce integration comes in Phase 8.

The vendor resolution logic uses a 3-step fallback:
  1. Exact email match against known contacts
  2. Vendor ID regex extracted from email body
  3. Fuzzy name similarity match

Mock vendor data covers the reference scenarios from the
VQMS architecture document.
"""

from __future__ import annotations

import logging
import re

from src.models.vendor import VendorMatch, VendorTier

logger = logging.getLogger(__name__)

# --- Mock Vendor Data ---
# These represent pre-loaded Salesforce Account + Contact records.
# In Phase 8, this data comes from real Salesforce API calls.

_MOCK_VENDORS = [
    {
        "vendor_id": "SF-001",
        "vendor_name": "TechNova Solutions",
        "vendor_tier": VendorTier.GOLD,
        "contacts": ["rajesh.mehta@technova.com", "support@technova.com"],
        "risk_flags": [],
    },
    {
        "vendor_id": "SF-002",
        "vendor_name": "Acme Corporation",
        "vendor_tier": VendorTier.STANDARD,
        "contacts": ["john@acme-corp.com", "billing@acme-corp.com"],
        "risk_flags": [],
    },
    {
        "vendor_id": "SF-003",
        "vendor_name": "Platinum Partner Inc",
        "vendor_tier": VendorTier.PLATINUM,
        "contacts": ["admin@platinumpartner.com"],
        "risk_flags": [],
    },
]

# Regex pattern to find vendor IDs like "SF-001" or "VN-30892" in email body
_VENDOR_ID_PATTERN = re.compile(r"\b(SF-\d{3}|VN-\d{4,6})\b", re.IGNORECASE)


async def resolve_vendor(
    sender_email: str,
    sender_name: str,
    body_text: str,
    *,
    correlation_id: str | None = None,
) -> VendorMatch | None:
    """Resolve a vendor from Salesforce CRM using a 3-step fallback.

    Step 1: Exact email match against Salesforce Contact.Email
    Step 2: Extract vendor ID from email body text via regex
    Step 3: Fuzzy name similarity match against Salesforce Account.Name

    Args:
        sender_email: Email address of the person who sent the query.
        sender_name: Display name of the sender.
        body_text: Plain text body of the email (used for vendor ID extraction).
        correlation_id: Tracing ID for this request.

    Returns:
        VendorMatch if a vendor was found, None if no match at all.
    """
    logger.info(
        "Starting vendor resolution",
        extra={
            "sender_email": sender_email,
            "sender_name": sender_name,
            "correlation_id": correlation_id,
        },
    )

    # Step 1: Exact email match
    match = _match_by_email(sender_email)
    if match is not None:
        logger.info(
            "Vendor matched by email",
            extra={
                "vendor_id": match.vendor_id,
                "match_method": match.match_method,
                "correlation_id": correlation_id,
            },
        )
        return match

    # Step 2: Vendor ID extracted from email body
    match = _match_by_vendor_id_in_body(body_text)
    if match is not None:
        logger.info(
            "Vendor matched by ID in body",
            extra={
                "vendor_id": match.vendor_id,
                "match_method": match.match_method,
                "correlation_id": correlation_id,
            },
        )
        return match

    # Step 3: Fuzzy name similarity
    match = _match_by_name_similarity(sender_name)
    if match is not None:
        logger.info(
            "Vendor matched by name similarity",
            extra={
                "vendor_id": match.vendor_id,
                "match_method": match.match_method,
                "correlation_id": correlation_id,
            },
        )
        return match

    # No match found — this is a normal business case for email path.
    # The orchestrator will mark the vendor as UNRESOLVED.
    logger.info(
        "No vendor match found",
        extra={
            "sender_email": sender_email,
            "correlation_id": correlation_id,
        },
    )
    return None


def _match_by_email(sender_email: str) -> VendorMatch | None:
    """Step 1: Check if sender_email exactly matches a known contact."""
    normalized_email = sender_email.lower().strip()
    for vendor in _MOCK_VENDORS:
        if normalized_email in vendor["contacts"]:
            return VendorMatch(
                vendor_id=vendor["vendor_id"],
                vendor_name=vendor["vendor_name"],
                vendor_tier=vendor["vendor_tier"],
                match_method="EMAIL_EXACT",
                match_confidence=0.95,
                risk_flags=vendor["risk_flags"],
            )
    return None


def _match_by_vendor_id_in_body(body_text: str) -> VendorMatch | None:
    """Step 2: Look for a vendor ID pattern in the email body text."""
    id_match = _VENDOR_ID_PATTERN.search(body_text)
    if id_match is None:
        return None

    found_id = id_match.group(1).upper()
    for vendor in _MOCK_VENDORS:
        if vendor["vendor_id"].upper() == found_id:
            return VendorMatch(
                vendor_id=vendor["vendor_id"],
                vendor_name=vendor["vendor_name"],
                vendor_tier=vendor["vendor_tier"],
                match_method="VENDOR_ID_BODY",
                match_confidence=0.90,
                risk_flags=vendor["risk_flags"],
            )
    return None


def _match_by_name_similarity(sender_name: str) -> VendorMatch | None:
    """Step 3: Simple case-insensitive substring match on vendor name.

    In Phase 8, this will use proper fuzzy matching (e.g., fuzzywuzzy
    or rapidfuzz). For now, a simple substring check is sufficient
    to demonstrate the fallback chain.
    """
    if not sender_name:
        return None

    normalized_name = sender_name.lower().strip()
    for vendor in _MOCK_VENDORS:
        vendor_name_lower = vendor["vendor_name"].lower()
        # Check if the sender name contains the vendor name or vice versa
        if normalized_name in vendor_name_lower or vendor_name_lower in normalized_name:
            return VendorMatch(
                vendor_id=vendor["vendor_id"],
                vendor_name=vendor["vendor_name"],
                vendor_tier=vendor["vendor_tier"],
                match_method="NAME_SIMILARITY",
                match_confidence=0.60,
                risk_flags=vendor["risk_flags"],
            )
    return None
