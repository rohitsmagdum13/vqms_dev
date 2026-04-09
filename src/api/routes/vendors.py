"""Vendor management endpoints for VQMS.

GET  /vendors              — List all active vendors from Salesforce
PUT  /vendors/{vendor_id}  — Update a vendor's fields in Salesforce

These endpoints provide the portal's vendor management UI with
CRUD operations against the Salesforce standard Account object.
Merged from the local_vqm backend.

All endpoints require JWT authentication (enforced by AuthMiddleware).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.adapters.salesforce import SalesforceAdapterError, get_salesforce_adapter
from src.models.vendor import VendorAccountData, VendorUpdateRequest, VendorUpdateResult
from src.utils.correlation import generate_correlation_id
from src.utils.logger import log_api_call

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vendors", tags=["vendors"])


@router.get("")
@log_api_call
async def get_all_vendors(request: Request) -> list[VendorAccountData]:
    """Get all active vendors from Salesforce.

    Returns a list of vendor records from the standard Account
    object where Vendor_Status__c is 'Active'. Used by the
    vendor management table in the portal UI.

    Requires authentication (JWT via AuthMiddleware).
    """
    if not getattr(request.state, "is_authenticated", False):
        return JSONResponse(
            status_code=401,
            content={"detail": "Not authenticated"},
        )

    correlation_id = generate_correlation_id()

    try:
        adapter = get_salesforce_adapter()
        raw_vendors = adapter.get_all_active_vendors(
            correlation_id=correlation_id,
        )
    except SalesforceAdapterError as exc:
        logger.error(
            "Failed to fetch vendors from Salesforce",
            extra={
                "error": str(exc),
                "correlation_id": correlation_id,
            },
        )
        return JSONResponse(
            status_code=502,
            content={"detail": "Salesforce query failed"},
        )

    # Convert raw dicts to validated Pydantic models
    return [VendorAccountData(**vendor) for vendor in raw_vendors]


@router.put("/{vendor_id}")
@log_api_call
async def update_vendor(
    vendor_id: str,
    update_request: VendorUpdateRequest,
    request: Request,
) -> VendorUpdateResult:
    """Update a vendor's fields in Salesforce.

    Accepts a partial update — only the fields provided in the
    request body are updated. The vendor is looked up by
    Vendor_ID__c in the standard Account object.

    Requires authentication (JWT via AuthMiddleware).
    """
    if not getattr(request.state, "is_authenticated", False):
        return JSONResponse(
            status_code=401,
            content={"detail": "Not authenticated"},
        )

    correlation_id = generate_correlation_id()

    # Convert Python snake_case fields to Salesforce API names
    sf_fields = update_request.to_salesforce_fields()

    try:
        adapter = get_salesforce_adapter()
        result = adapter.update_vendor_account(
            vendor_id_field=vendor_id,
            update_data=sf_fields,
            correlation_id=correlation_id,
        )
    except SalesforceAdapterError as exc:
        logger.error(
            "Failed to update vendor in Salesforce",
            extra={
                "vendor_id": vendor_id,
                "error": str(exc),
                "correlation_id": correlation_id,
            },
        )
        return JSONResponse(
            status_code=502,
            content={"detail": f"Salesforce update failed: {exc}"},
        )

    return VendorUpdateResult(
        success=result["success"],
        vendor_id=result["vendor_id"],
        updated_fields=result["updated_fields"],
        message=f"Updated {len(result['updated_fields'])} field(s) for vendor {vendor_id}",
    )
