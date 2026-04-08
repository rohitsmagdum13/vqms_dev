"""Fake authentication endpoint for development.

POST /auth/login — Accepts any email/password and returns a fake token
with a vendor_id. This allows the Angular frontend to simulate the
login flow (Step P1) without real Cognito JWT infrastructure.

# TODO Phase 7: Replace with real Cognito JWT auth via AWS Cognito
# user pool (vqms-agent-portal-users). The vendor_id will come from
# JWT claims, not from this fake endpoint.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    """Fake login request body."""

    email: str = Field(description="Vendor email address")
    password: str = Field(description="Vendor password (ignored in dev)")


class LoginResponse(BaseModel):
    """Fake login response with token and vendor identity."""

    token: str = Field(description="Fake JWT token for dev mode")
    vendor_id: str = Field(description="Fake vendor ID derived from email")
    email: str = Field(description="The email that was submitted")
    vendor_name: str = Field(description="Vendor display name")
    role: str = Field(description="User role (always VENDOR in dev)")


@router.post("/auth/login")
async def fake_login(request: LoginRequest) -> LoginResponse:
    """Fake login that accepts any email/password.

    In development mode, this endpoint simulates Cognito authentication.
    It generates a deterministic vendor_id from the email so the same
    email always maps to the same vendor for testing consistency.

    # TODO Phase 7: Replace with real Cognito JWT auth
    """
    # Generate a deterministic vendor_id from the email domain
    # so "john@acme.com" always gets the same vendor_id
    domain = request.email.split("@")[1] if "@" in request.email else "unknown"
    vendor_id = f"VN-{abs(hash(domain)) % 100000:05d}"
    vendor_name = domain.split(".")[0].title() if domain != "unknown" else "Dev Vendor"

    logger.info(
        "Fake login successful",
        extra={
            "email": request.email,
            "vendor_id": vendor_id,
        },
    )

    return LoginResponse(
        token=f"fake-jwt-dev-{vendor_id}",
        vendor_id=vendor_id,
        email=request.email,
        vendor_name=vendor_name,
        role="VENDOR",
    )
