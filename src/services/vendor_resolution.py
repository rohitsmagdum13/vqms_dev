"""Vendor Resolution Service for VQMS.

Matches an email sender to a vendor in Salesforce CRM using
a three-step fallback strategy:
  1. Exact email match — Vendor_Contact__c.Email__c lookup via SOQL
  2. Vendor ID extracted from email body (e.g. "V-001") — Vendor_Account__c lookup
  3. Fuzzy name similarity — Vendor_Account__c.Name LIKE search

NOTE: This org uses CUSTOM Salesforce objects:
  - Vendor_Account__c (not standard Account)
  - Vendor_Contact__c (not standard Contact)
  - Vendor IDs look like "V-001", "V-012" (field: Vendor_ID__c)
  - Contact emails in Email__c (not standard Email)

For portal queries, vendor_id is already known from the JWT token,
so this service is used primarily for email path vendor identification.

Corresponds to Step E2.5 (email path) and Step 7.3 (context loading)
in the VQMS Solution Flow Document.

Depends on:
  - src/adapters/salesforce.py (SalesforceAdapter for SOQL queries)
  - src/models/vendor.py (VendorMatch, VendorTier)
"""

from __future__ import annotations

import logging
import re

from src.adapters.salesforce import SalesforceAdapterError, get_salesforce_adapter
from src.models.vendor import VendorMatch, VendorTier

logger = logging.getLogger(__name__)

# Confidence thresholds for each matching method
EXACT_EMAIL_CONFIDENCE = 0.95
VENDOR_ID_CONFIDENCE = 0.90
NAME_SIMILARITY_CONFIDENCE = 0.60

# Regex pattern to find vendor IDs in email body text.
# This org uses Vendor_ID__c values like "V-001", "V-012".
# Also matches legacy patterns "VN-30892" and "SF-001" for safety.
_VENDOR_ID_PATTERN = re.compile(
    r"\b(V-\d{3,6}|VN-\d{4,6}|SF-\d{3,6})\b",
    re.IGNORECASE,
)


# Map Salesforce Vendor_Tier__c picklist values to our VendorTier enum.
# The picklist values in the org are: Platinum, Gold, Silver, Standard.
_TIER_MAP: dict[str, VendorTier] = {
    "platinum": VendorTier.PLATINUM,
    "gold": VendorTier.GOLD,
    "silver": VendorTier.SILVER,
    "standard": VendorTier.STANDARD,
}


def _map_vendor_tier(sf_tier: str | None) -> VendorTier:
    """Convert Salesforce Vendor_Tier__c value to our VendorTier enum.

    Falls back to STANDARD if the tier is missing or unrecognized.
    """
    if not sf_tier:
        return VendorTier.STANDARD
    return _TIER_MAP.get(sf_tier.lower().strip(), VendorTier.STANDARD)


class VendorResolutionError(Exception):
    """Raised when vendor lookup fails unexpectedly.

    This is NOT raised for "vendor not found" — that is a normal
    business case that returns None. This is for actual failures:
    Salesforce API down, auth error, etc.
    """


async def resolve_vendor(
    sender_email: str,
    sender_name: str,
    body_text: str,
    *,
    correlation_id: str | None = None,
) -> VendorMatch | None:
    """Resolve a vendor from Salesforce CRM using a 3-step fallback.

    Step 1: Exact email match against Salesforce Contact.Email
    Step 2: Extract vendor/account ID from email body text via regex,
            then look up the Account in Salesforce
    Step 3: Fuzzy name similarity search against Salesforce Account.Name

    If Salesforce is unreachable or credentials are misconfigured,
    logs the error and returns None (graceful degradation). The
    orchestrator will mark the vendor as UNRESOLVED and continue.

    Args:
        sender_email: Email address of the person who sent the query.
        sender_name: Display name of the sender.
        body_text: Plain text body of the email (used for ID extraction).
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

    try:
        adapter = get_salesforce_adapter()
    except Exception:
        logger.error(
            "Failed to get Salesforce adapter",
            extra={"correlation_id": correlation_id},
            exc_info=True,
        )
        return None

    # Step 1: Exact email match via Contact.Email
    match = _match_by_email(adapter, sender_email, correlation_id=correlation_id)
    if match is not None:
        logger.info(
            "Vendor matched by email (Step 1)",
            extra={
                "vendor_id": match.vendor_id,
                "vendor_name": match.vendor_name,
                "match_method": match.match_method,
                "correlation_id": correlation_id,
            },
        )
        return match

    # Step 2: Vendor/Account ID extracted from email body
    match = _match_by_id_in_body(adapter, body_text, correlation_id=correlation_id)
    if match is not None:
        logger.info(
            "Vendor matched by ID in body (Step 2)",
            extra={
                "vendor_id": match.vendor_id,
                "vendor_name": match.vendor_name,
                "match_method": match.match_method,
                "correlation_id": correlation_id,
            },
        )
        return match

    # Step 3: Fuzzy name similarity via Account.Name LIKE
    match = _match_by_name(adapter, sender_name, correlation_id=correlation_id)
    if match is not None:
        logger.info(
            "Vendor matched by name similarity (Step 3)",
            extra={
                "vendor_id": match.vendor_id,
                "vendor_name": match.vendor_name,
                "match_method": match.match_method,
                "correlation_id": correlation_id,
            },
        )
        return match

    # No match found — this is a normal business case for email path
    logger.info(
        "No vendor match found — will be marked UNRESOLVED",
        extra={
            "sender_email": sender_email,
            "sender_name": sender_name,
            "correlation_id": correlation_id,
        },
    )
    return None


def _match_by_email(
    adapter,
    sender_email: str,
    *,
    correlation_id: str | None = None,
) -> VendorMatch | None:
    """Step 1: Find vendor by exact email match in Salesforce.

    Queries Vendor_Contact__c.Email__c, then looks up the parent
    Vendor_Account__c to get the vendor name, ID, and tier.
    """
    try:
        contact = adapter.find_contact_by_email(
            sender_email, correlation_id=correlation_id
        )
    except SalesforceAdapterError:
        logger.warning(
            "Salesforce query failed in Step 1 (email match) — skipping",
            extra={"correlation_id": correlation_id},
            exc_info=True,
        )
        return None

    if contact is None:
        return None

    # AccountId is normalized from Vendor_Account__c lookup field
    account_id = contact.get("AccountId")
    if not account_id:
        # Contact exists but has no linked Vendor Account — rare
        logger.warning(
            "Vendor_Contact__c found but has no Vendor_Account__c link",
            extra={
                "contact_id": contact.get("Id"),
                "correlation_id": correlation_id,
            },
        )
        return None

    # Look up the parent Vendor_Account__c for vendor details
    try:
        account = adapter.find_account_by_id(
            account_id, correlation_id=correlation_id
        )
    except SalesforceAdapterError:
        logger.warning(
            "Vendor_Account__c lookup failed after contact match — skipping",
            extra={"correlation_id": correlation_id},
            exc_info=True,
        )
        return None

    if account is None:
        return None

    # Use Vendor_ID__c (e.g. "V-001") as the vendor_id if available,
    # otherwise fall back to the Salesforce record ID
    vendor_id = account.get("Vendor_ID__c") or account["Id"]

    return VendorMatch(
        vendor_id=vendor_id,
        vendor_name=account.get("Name", "Unknown"),
        vendor_tier=_map_vendor_tier(account.get("Vendor_Tier__c")),
        match_method="EMAIL_EXACT",
        match_confidence=EXACT_EMAIL_CONFIDENCE,
    )


def _match_by_id_in_body(
    adapter,
    body_text: str,
    *,
    correlation_id: str | None = None,
) -> VendorMatch | None:
    """Step 2: Extract a vendor ID from the email body and look it up.

    Scans the email body for patterns like "V-001" or "VN-30892"
    (the Vendor_ID__c field on Vendor_Account__c). Then queries
    Salesforce by that Vendor_ID__c value.
    """
    if not body_text:
        return None

    id_match = _VENDOR_ID_PATTERN.search(body_text)
    if id_match is None:
        return None

    found_id = id_match.group(1)
    logger.info(
        "Vendor ID pattern found in email body",
        extra={
            "found_id": found_id,
            "correlation_id": correlation_id,
        },
    )

    # Look up by Vendor_ID__c field (e.g. "V-001") on Vendor_Account__c
    try:
        account = adapter.find_account_by_vendor_id(
            found_id, correlation_id=correlation_id
        )
    except SalesforceAdapterError:
        logger.warning(
            "Vendor_Account__c lookup failed for body vendor ID — skipping",
            extra={
                "found_id": found_id,
                "correlation_id": correlation_id,
            },
            exc_info=True,
        )
        return None

    if account is None:
        return None

    vendor_id = account.get("Vendor_ID__c") or account["Id"]

    return VendorMatch(
        vendor_id=vendor_id,
        vendor_name=account.get("Name", "Unknown"),
        vendor_tier=_map_vendor_tier(account.get("Vendor_Tier__c")),
        match_method="VENDOR_ID_BODY",
        match_confidence=VENDOR_ID_CONFIDENCE,
    )


def _match_by_name(
    adapter,
    sender_name: str,
    *,
    correlation_id: str | None = None,
) -> VendorMatch | None:
    """Step 3: Fuzzy name match via Vendor_Account__c.Name LIKE search.

    Uses SOQL LIKE '%name%' to find vendor accounts whose name
    contains the sender's display name. Takes the first result
    if any are returned.
    """
    if not sender_name or not sender_name.strip():
        return None

    try:
        accounts = adapter.find_account_by_name(
            sender_name.strip(), correlation_id=correlation_id
        )
    except SalesforceAdapterError:
        logger.warning(
            "Vendor_Account__c name search failed in Step 3 — skipping",
            extra={"correlation_id": correlation_id},
            exc_info=True,
        )
        return None

    if not accounts:
        return None

    # Take the first match — SOQL returns them in default order
    best = accounts[0]
    vendor_id = best.get("Vendor_ID__c") or best["Id"]

    return VendorMatch(
        vendor_id=vendor_id,
        vendor_name=best.get("Name", "Unknown"),
        vendor_tier=_map_vendor_tier(best.get("Vendor_Tier__c")),
        match_method="NAME_SIMILARITY",
        match_confidence=NAME_SIMILARITY_CONFIDENCE,
    )
