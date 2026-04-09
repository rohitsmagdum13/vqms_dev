"""Memory and Context Service for VQMS (Step 7.3 and 7.4).

Loads the context that agents need before analyzing a query:
  - Vendor profile from Redis cache (1h TTL) or Salesforce CRM
  - Vendor query history from PostgreSQL episodic_memory table

This corresponds to Sub-Steps 7.3 and 7.4 in the VQMS Solution
Flow Document. The context package is passed to the Query Analysis
Agent so it can make better-informed classifications.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import text

from src.adapters.salesforce import SalesforceAdapterError, get_salesforce_adapter
from src.cache.redis_client import get_value, set_with_ttl, vendor_key
from src.db.connection import get_engine
from src.models.vendor import VendorProfile, VendorTier
from src.utils.log_context import LogContext

logger = logging.getLogger(__name__)


async def load_vendor_profile(
    vendor_id: str | None,
    sender_email: str | None = None,
    *,
    correlation_id: str | None = None,
) -> VendorProfile | None:
    """Load a vendor profile from Redis cache or Salesforce CRM.

    Sub-Step 7.3: Check Redis first. On cache miss, query Salesforce
    and cache the result for 1 hour.

    Args:
        vendor_id: Salesforce Account ID or Vendor_ID__c. May be
            None if vendor was UNRESOLVED during intake.
        sender_email: Email address to use for Salesforce contact
            lookup if vendor_id lookup fails.
        correlation_id: Tracing ID for log correlation.

    Returns:
        VendorProfile if found, None if vendor is unresolved or
        Salesforce is unreachable.
    """
    ctx = LogContext(
        correlation_id=correlation_id,
        agent_role="memory_context",
        step="STEP_7",
    )

    if not vendor_id:
        logger.info(
            "No vendor_id provided — skipping profile load",
            extra=ctx.to_dict(),
        )
        return None

    # Step 1: Check Redis cache
    key, ttl = vendor_key(vendor_id)
    try:
        cached_json = await get_value(key)
        if cached_json:
            logger.info(
                "Vendor profile cache HIT",
                extra={**ctx.with_update(tool="redis").to_dict(), "vendor_id": vendor_id},
            )
            cached_data = json.loads(cached_json)
            return VendorProfile(**cached_data)
    except Exception:
        # Redis failure is non-fatal — fall through to Salesforce
        logger.warning(
            "Redis cache read failed — falling through to Salesforce",
            extra={**ctx.with_update(tool="redis").to_dict(), "vendor_id": vendor_id},
            exc_info=True,
        )

    # Step 2: Query Salesforce
    logger.info(
        "Vendor profile cache MISS — querying Salesforce",
        extra={**ctx.with_update(tool="salesforce").to_dict(), "vendor_id": vendor_id},
    )

    try:
        adapter = get_salesforce_adapter()

        # Try by Vendor_ID__c first, then by Salesforce record ID
        account = adapter.find_account_by_vendor_id(
            vendor_id, correlation_id=correlation_id
        )
        if not account:
            account = adapter.find_account_by_id(
                vendor_id, correlation_id=correlation_id
            )

        # If still no match and we have an email, try contact lookup
        if not account and sender_email:
            contact = adapter.find_contact_by_email(
                sender_email, correlation_id=correlation_id
            )
            if contact and contact.get("AccountId"):
                account = adapter.find_account_by_id(
                    contact["AccountId"], correlation_id=correlation_id
                )

        if not account:
            logger.info(
                "Vendor not found in Salesforce",
                extra={**ctx.with_update(tool="salesforce").to_dict(), "vendor_id": vendor_id},
            )
            return None

        # Map Salesforce data to VendorProfile
        profile = _map_to_vendor_profile(account, vendor_id, sender_email)

        # Step 3: Cache in Redis
        try:
            profile_json = profile.model_dump_json()
            await set_with_ttl(key, profile_json, ttl)
            logger.info(
                "Vendor profile cached in Redis",
                extra={
                    **ctx.with_update(tool="redis").to_dict(),
                    "vendor_id": vendor_id,
                    "ttl_seconds": ttl,
                },
            )
        except Exception:
            logger.warning(
                "Failed to cache vendor profile in Redis",
                extra={**ctx.with_update(tool="redis").to_dict(), "vendor_id": vendor_id},
                exc_info=True,
            )

        return profile

    except SalesforceAdapterError:
        logger.error(
            "Salesforce query failed during vendor profile load",
            extra={**ctx.with_update(tool="salesforce").to_dict(), "vendor_id": vendor_id},
            exc_info=True,
        )
        return None


def _map_to_vendor_profile(
    account: dict,
    vendor_id: str,
    sender_email: str | None,
) -> VendorProfile:
    """Map a Salesforce account dict to a VendorProfile model.

    Handles missing fields and maps Vendor_Tier__c string
    to the VendorTier enum.
    """
    # Map tier string from Salesforce to VendorTier enum
    tier_str = (account.get("Vendor_Tier__c") or "standard").lower()
    try:
        tier = VendorTier(tier_str)
    except ValueError:
        tier = VendorTier.STANDARD

    return VendorProfile(
        vendor_id=account.get("Vendor_ID__c") or vendor_id,
        vendor_name=account.get("Name", "Unknown Vendor"),
        vendor_tier=tier,
        contact_email=sender_email or "",
        account_manager=None,
        payment_terms=None,
        risk_flags=[],
        is_active=account.get("Vendor_Status__c", "active").lower() == "active",
    )


async def load_vendor_history(
    vendor_id: str | None,
    *,
    correlation_id: str | None = None,
) -> list[dict]:
    """Load past query summaries for a vendor from episodic memory.

    Sub-Step 7.4: Query the memory.episodic_memory table for the
    most recent queries from this vendor. Returns an empty list
    if no history exists or if the database is unreachable.

    Args:
        vendor_id: Salesforce Account ID.
        correlation_id: Tracing ID for log correlation.

    Returns:
        List of dicts with keys: summary, resolution_path, metadata.
        Empty list if no history or on error.
    """
    ctx = LogContext(
        correlation_id=correlation_id,
        agent_role="memory_context",
        step="STEP_7",
    )

    if not vendor_id:
        return []

    engine = get_engine()
    if engine is None:
        logger.warning(
            "Database not available — skipping vendor history load",
            extra={**ctx.with_update(tool="postgresql").to_dict(), "vendor_id": vendor_id},
        )
        return []

    sql = text(
        "SELECT summary, resolution_path, metadata "
        "FROM memory.episodic_memory "
        "WHERE vendor_id = :vendor_id "
        "ORDER BY created_at DESC "
        "LIMIT 10"
    )

    try:
        async with engine.connect() as conn:
            result = await conn.execute(sql, {"vendor_id": vendor_id})
            rows = result.fetchall()

        history = [
            {
                "summary": row[0],
                "resolution_path": row[1],
                "metadata": row[2] if row[2] else {},
            }
            for row in rows
        ]

        logger.info(
            "Loaded vendor history",
            extra={
                **ctx.with_update(tool="postgresql").to_dict(),
                "vendor_id": vendor_id,
                "history_count": len(history),
            },
        )
        return history

    except Exception:
        logger.warning(
            "Failed to load vendor history — returning empty list",
            extra={**ctx.with_update(tool="postgresql").to_dict(), "vendor_id": vendor_id},
            exc_info=True,
        )
        return []
