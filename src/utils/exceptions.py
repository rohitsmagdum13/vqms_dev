"""Domain-specific exception classes for VQMS.

Each service module raises these exceptions instead of bare
Exception or generic errors. This lets API routes catch specific
failures and return appropriate HTTP status codes.
"""

from __future__ import annotations


class DuplicateQueryError(Exception):
    """Raised when an idempotency check finds a duplicate query or email.

    The identifier is the query_id (portal) or message_id (email)
    that was already processed. API routes catch this and return HTTP 409.
    """

    def __init__(self, identifier: str) -> None:
        self.identifier = identifier
        super().__init__(f"Duplicate detected: {identifier}")


class VendorNotFoundError(Exception):
    """Raised when vendor resolution fails and a vendor is required.

    Not raised in Phase 2 (email path allows UNRESOLVED vendors),
    but defined here for use in later phases where vendor identity
    is mandatory (e.g., portal path without JWT).
    """

    def __init__(self, identifier: str) -> None:
        self.identifier = identifier
        super().__init__(f"Vendor not found: {identifier}")
