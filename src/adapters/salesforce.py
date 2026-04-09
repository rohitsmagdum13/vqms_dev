"""Salesforce CRM adapter for VQMS vendor resolution.

Connects to Salesforce using the simple-salesforce library with
username + password + security_token authentication. Provides
methods to query custom Vendor objects via SOQL.

This org uses CUSTOM Salesforce objects (not standard Contact/Account):
  - Vendor_Account__c  — vendor companies (has Vendor_ID__c, Vendor_Tier__c)
  - Vendor_Contact__c  — vendor contacts (has Email__c, Vendor_Account__c lookup)

The vendor resolution service (src/services/vendor_resolution.py)
calls these methods as part of the three-step fallback:
  1. find_contact_by_email() — exact email match on Vendor_Contact__c.Email__c
  2. find_account_by_id() — lookup Vendor_Account__c by Salesforce ID
  3. find_account_by_vendor_id() — lookup Vendor_Account__c by Vendor_ID__c (e.g. "V-001")
  4. find_account_by_name() — fuzzy LIKE search on Vendor_Account__c.Name

Credentials come from .env via config/settings.py:
  SALESFORCE_USERNAME, SALESFORCE_PASSWORD,
  SALESFORCE_SECURITY_TOKEN, SALESFORCE_LOGIN_URL
"""

from __future__ import annotations

import logging
from functools import lru_cache

from simple_salesforce import Salesforce, SalesforceAuthenticationFailed
from simple_salesforce.exceptions import SalesforceError

from config.settings import get_settings

logger = logging.getLogger(__name__)


class SalesforceAdapterError(Exception):
    """Raised when a Salesforce API call fails unexpectedly.

    This wraps simple_salesforce exceptions so callers don't need
    to import simple_salesforce directly.
    """


class SalesforceAdapter:
    """Adapter for Salesforce CRM queries via simple-salesforce.

    Uses lazy connection — the Salesforce session is created on
    the first API call, not at instantiation time. This avoids
    blocking app startup if Salesforce is temporarily unreachable.

    Usage:
        adapter = get_salesforce_adapter()
        contact = adapter.find_contact_by_email("john@acme.com")
    """

    def __init__(self) -> None:
        self._sf: Salesforce | None = None

    def connect(self) -> Salesforce:
        """Authenticate with Salesforce and return the session.

        Uses username + password + security_token flow.
        The login URL (login.salesforce.com vs test.salesforce.com)
        is read from SALESFORCE_LOGIN_URL in .env.

        Returns:
            Authenticated Salesforce instance.

        Raises:
            SalesforceAdapterError: If authentication fails
                (wrong password, expired token, locked account).
        """
        if self._sf is not None:
            return self._sf

        settings = get_settings()

        if not settings.salesforce_username or not settings.salesforce_password:
            raise SalesforceAdapterError(
                "Salesforce credentials not configured. "
                "Set SALESFORCE_USERNAME, SALESFORCE_PASSWORD, and "
                "SALESFORCE_SECURITY_TOKEN in .env"
            )

        # Extract domain from login URL for simple-salesforce
        # "https://login.salesforce.com" -> "login"
        # "https://test.salesforce.com" -> "test"
        login_url = settings.salesforce_login_url
        domain = "login"
        if "test.salesforce.com" in login_url:
            domain = "test"

        try:
            self._sf = Salesforce(
                username=settings.salesforce_username,
                password=settings.salesforce_password,
                security_token=settings.salesforce_security_token,
                domain=domain,
            )
            logger.info(
                "Salesforce connection established",
                extra={"tool": "salesforce", "instance_url": self._sf.sf_instance},
            )
            return self._sf
        except SalesforceAuthenticationFailed as exc:
            logger.error(
                "Salesforce authentication failed — check credentials",
                extra={"tool": "salesforce", "error": str(exc)},
            )
            raise SalesforceAdapterError(
                f"Salesforce authentication failed: {exc}"
            ) from exc
        except Exception as exc:
            logger.error(
                "Salesforce connection error",
                extra={"tool": "salesforce", "error": str(exc)},
            )
            raise SalesforceAdapterError(
                f"Salesforce connection error: {exc}"
            ) from exc

    def find_contact_by_email(
        self,
        email: str,
        *,
        correlation_id: str | None = None,
    ) -> dict | None:
        """Find a Vendor Contact by exact email match.

        Uses custom object Vendor_Contact__c (NOT standard Contact).
        The Email__c field stores vendor contact emails.
        The Vendor_Account__c field is a lookup to the parent account.

        SOQL: SELECT Id, Vendor_Account__c, Email__c, Name
              FROM Vendor_Contact__c
              WHERE Email__c = '<email>'
              LIMIT 1

        Args:
            email: Email address to search for.
            correlation_id: Tracing ID for log correlation.

        Returns:
            Dict with fields (Id, AccountId, Email, Name) where
            AccountId is the Vendor_Account__c lookup value.
            Returns None if no contact found.

        Raises:
            SalesforceAdapterError: If the SOQL query fails.
        """
        sf = self.connect()

        # Escape single quotes in email to prevent SOQL injection
        safe_email = email.replace("'", "\\'")
        soql = (
            "SELECT Id, Vendor_Account__c, Email__c, Name "
            "FROM Vendor_Contact__c "
            f"WHERE Email__c = '{safe_email}' "
            "LIMIT 1"
        )

        logger.info(
            "Salesforce SOQL: find_contact_by_email (Vendor_Contact__c)",
            extra={
                "tool": "salesforce",
                "email": email,
                "correlation_id": correlation_id,
            },
        )

        try:
            result = sf.query(soql)
        except SalesforceError as exc:
            logger.error(
                "Salesforce query failed: find_contact_by_email",
                extra={
                    "email": email,
                    "error": str(exc),
                    "correlation_id": correlation_id,
                },
            )
            raise SalesforceAdapterError(
                f"SOQL query failed for vendor contact email lookup: {exc}"
            ) from exc

        records = result.get("records", [])
        if not records:
            logger.info(
                "No Vendor_Contact__c found for email",
                extra={
                    "email": email,
                    "correlation_id": correlation_id,
                },
            )
            return None

        contact = records[0]
        logger.info(
            "Vendor_Contact__c found",
            extra={
                "contact_id": contact.get("Id"),
                "account_id": contact.get("Vendor_Account__c"),
                "contact_name": contact.get("Name"),
                "correlation_id": correlation_id,
            },
        )
        # Return normalized keys so vendor_resolution.py doesn't
        # need to know about custom field names
        return {
            "Id": contact.get("Id"),
            "AccountId": contact.get("Vendor_Account__c"),
            "Email": contact.get("Email__c"),
            "Name": contact.get("Name"),
        }

    def find_account_by_id(
        self,
        account_id: str,
        *,
        correlation_id: str | None = None,
    ) -> dict | None:
        """Find a Vendor Account by its Salesforce record ID.

        Uses custom object Vendor_Account__c (NOT standard Account).

        SOQL: SELECT Id, Name, Vendor_ID__c, Vendor_Tier__c,
                     Vendor_Status__c, Category__c
              FROM Vendor_Account__c
              WHERE Id = '<account_id>'

        Args:
            account_id: Salesforce record ID (18-char or 15-char).
            correlation_id: Tracing ID for log correlation.

        Returns:
            Dict with Vendor Account fields (Id, Name, Vendor_ID__c,
            Vendor_Tier__c, Vendor_Status__c, Category__c)
            or None if not found.

        Raises:
            SalesforceAdapterError: If the SOQL query fails.
        """
        sf = self.connect()

        safe_id = account_id.replace("'", "\\'")
        soql = (
            "SELECT Id, Name, Vendor_ID__c, Vendor_Tier__c, "
            "Vendor_Status__c, Category__c "
            "FROM Vendor_Account__c "
            f"WHERE Id = '{safe_id}'"
        )

        logger.info(
            "Salesforce SOQL: find_account_by_id (Vendor_Account__c)",
            extra={
                "tool": "salesforce",
                "account_id": account_id,
                "correlation_id": correlation_id,
            },
        )

        try:
            result = sf.query(soql)
        except SalesforceError as exc:
            logger.error(
                "Salesforce query failed: find_account_by_id",
                extra={
                    "account_id": account_id,
                    "error": str(exc),
                    "correlation_id": correlation_id,
                },
            )
            raise SalesforceAdapterError(
                f"SOQL query failed for vendor account ID lookup: {exc}"
            ) from exc

        records = result.get("records", [])
        if not records:
            logger.info(
                "No Vendor_Account__c found for ID",
                extra={
                    "account_id": account_id,
                    "correlation_id": correlation_id,
                },
            )
            return None

        account = records[0]
        logger.info(
            "Vendor_Account__c found",
            extra={
                "account_id": account.get("Id"),
                "account_name": account.get("Name"),
                "vendor_id": account.get("Vendor_ID__c"),
                "correlation_id": correlation_id,
            },
        )
        return {
            "Id": account.get("Id"),
            "Name": account.get("Name"),
            "Vendor_ID__c": account.get("Vendor_ID__c"),
            "Vendor_Tier__c": account.get("Vendor_Tier__c"),
            "Vendor_Status__c": account.get("Vendor_Status__c"),
            "Category__c": account.get("Category__c"),
        }

    def find_account_by_vendor_id(
        self,
        vendor_id: str,
        *,
        correlation_id: str | None = None,
    ) -> dict | None:
        """Find a Vendor Account by its Vendor_ID__c field (e.g. "V-001").

        This is used in Step 2 of vendor resolution when we extract
        a vendor ID like "V-001" from the email body text.

        SOQL: SELECT Id, Name, Vendor_ID__c, Vendor_Tier__c,
                     Vendor_Status__c, Category__c
              FROM Vendor_Account__c
              WHERE Vendor_ID__c = '<vendor_id>'
              LIMIT 1

        Args:
            vendor_id: Vendor ID string (e.g. "V-001", "V-012").
            correlation_id: Tracing ID for log correlation.

        Returns:
            Dict with Vendor Account fields or None if not found.

        Raises:
            SalesforceAdapterError: If the SOQL query fails.
        """
        sf = self.connect()

        safe_id = vendor_id.replace("'", "\\'")
        soql = (
            "SELECT Id, Name, Vendor_ID__c, Vendor_Tier__c, "
            "Vendor_Status__c, Category__c "
            "FROM Vendor_Account__c "
            f"WHERE Vendor_ID__c = '{safe_id}' "
            "LIMIT 1"
        )

        logger.info(
            "Salesforce SOQL: find_account_by_vendor_id (Vendor_Account__c)",
            extra={
                "tool": "salesforce",
                "vendor_id": vendor_id,
                "correlation_id": correlation_id,
            },
        )

        try:
            result = sf.query(soql)
        except SalesforceError as exc:
            logger.error(
                "Salesforce query failed: find_account_by_vendor_id",
                extra={
                    "vendor_id": vendor_id,
                    "error": str(exc),
                    "correlation_id": correlation_id,
                },
            )
            raise SalesforceAdapterError(
                f"SOQL query failed for vendor ID lookup: {exc}"
            ) from exc

        records = result.get("records", [])
        if not records:
            logger.info(
                "No Vendor_Account__c found for Vendor_ID__c",
                extra={
                    "vendor_id": vendor_id,
                    "correlation_id": correlation_id,
                },
            )
            return None

        account = records[0]
        logger.info(
            "Vendor_Account__c found by Vendor_ID__c",
            extra={
                "sf_id": account.get("Id"),
                "account_name": account.get("Name"),
                "vendor_id": account.get("Vendor_ID__c"),
                "correlation_id": correlation_id,
            },
        )
        return {
            "Id": account.get("Id"),
            "Name": account.get("Name"),
            "Vendor_ID__c": account.get("Vendor_ID__c"),
            "Vendor_Tier__c": account.get("Vendor_Tier__c"),
            "Vendor_Status__c": account.get("Vendor_Status__c"),
            "Category__c": account.get("Category__c"),
        }

    def find_account_by_name(
        self,
        name: str,
        *,
        correlation_id: str | None = None,
    ) -> list[dict]:
        """Search for Vendor Accounts by fuzzy name match.

        Uses custom object Vendor_Account__c (NOT standard Account).

        SOQL: SELECT Id, Name, Vendor_ID__c, Vendor_Tier__c
              FROM Vendor_Account__c
              WHERE Name LIKE '%<name>%'
              LIMIT 5

        Args:
            name: Name string to search for (substring match).
            correlation_id: Tracing ID for log correlation.

        Returns:
            List of dicts with Vendor Account fields
            (Id, Name, Vendor_ID__c, Vendor_Tier__c).
            Empty list if no matches.

        Raises:
            SalesforceAdapterError: If the SOQL query fails.
        """
        sf = self.connect()

        # Escape single quotes and % in name for SOQL safety
        safe_name = name.replace("'", "\\'").replace("%", "\\%")
        soql = (
            "SELECT Id, Name, Vendor_ID__c, Vendor_Tier__c "
            "FROM Vendor_Account__c "
            f"WHERE Name LIKE '%{safe_name}%' "
            "LIMIT 5"
        )

        logger.info(
            "Salesforce SOQL: find_account_by_name (Vendor_Account__c)",
            extra={
                "tool": "salesforce",
                "search_name": name,
                "correlation_id": correlation_id,
            },
        )

        try:
            result = sf.query(soql)
        except SalesforceError as exc:
            logger.error(
                "Salesforce query failed: find_account_by_name",
                extra={
                    "search_name": name,
                    "error": str(exc),
                    "correlation_id": correlation_id,
                },
            )
            raise SalesforceAdapterError(
                f"SOQL query failed for vendor account name search: {exc}"
            ) from exc

        records = result.get("records", [])
        logger.info(
            "Vendor_Account__c name search results",
            extra={
                "search_name": name,
                "result_count": len(records),
                "correlation_id": correlation_id,
            },
        )
        return [
            {
                "Id": r.get("Id"),
                "Name": r.get("Name"),
                "Vendor_ID__c": r.get("Vendor_ID__c"),
                "Vendor_Tier__c": r.get("Vendor_Tier__c"),
            }
            for r in records
        ]


@lru_cache(maxsize=1)
def get_salesforce_adapter() -> SalesforceAdapter:
    """Return a cached SalesforceAdapter singleton.

    The adapter uses lazy connection — Salesforce auth happens
    on the first query, not when this function is called.
    """
    return SalesforceAdapter()
