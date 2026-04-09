"""Portal query submission API route.

POST /queries — Vendor submits a new query via the VQMS portal.

The vendor_id is extracted from the X-Vendor-ID header in dev mode.
In Phase 8, this will be extracted from the Cognito JWT token.
The vendor_id is NEVER taken from the request body.

Corresponds to Step P6 in the VQMS Solution Flow Document.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Header, HTTPException, Request

from src.models.query import QuerySubmission
from src.services.portal_submission import submit_portal_query
from src.utils.exceptions import DuplicateQueryError
from src.utils.logger import log_api_call

logger = logging.getLogger(__name__)

router = APIRouter(tags=["queries"])


@router.post("/queries", status_code=201)
@log_api_call
async def create_query(
    request: Request,
    submission: QuerySubmission,
    x_vendor_id: str | None = Header(default=None),
    x_vendor_name: str | None = Header(default=None),
    x_correlation_id: str | None = Header(default=None),
) -> dict:
    """Submit a new vendor query via the portal.

    In development mode, vendor identity comes from headers:
      - X-Vendor-ID: Salesforce Account ID (required)
      - X-Vendor-Name: Vendor display name (optional, defaults to "Portal Vendor")

    In production (Phase 8), vendor identity comes from Cognito JWT claims.

    Returns:
        201: Query accepted with query_id, execution_id, correlation_id.
        401: Missing vendor identity (no X-Vendor-ID header).
        409: Duplicate query detected (idempotency check).
        422: Validation error in request body.
    """
    # --- Auth: Extract vendor_id ---
    # NEVER from request body — always from header/JWT
    if not x_vendor_id:
        raise HTTPException(
            status_code=401,
            detail="Missing X-Vendor-ID header. Vendor identity is required.",
        )

    vendor_name = x_vendor_name or "Portal Vendor"

    try:
        result = await submit_portal_query(
            submission=submission,
            vendor_id=x_vendor_id,
            vendor_name=vendor_name,
            correlation_id=x_correlation_id,
        )
        return result

    except DuplicateQueryError as err:
        raise HTTPException(
            status_code=409,
            detail=f"Duplicate query: {err.identifier}",
        ) from err
