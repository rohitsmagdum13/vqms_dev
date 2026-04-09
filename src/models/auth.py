"""Pydantic models for user authentication in VQMS.

These models map to the existing public.tbl_users and
public.tbl_user_roles tables in RDS (created by the local_vqm
teammate's backend). They are used by the auth service for
login, logout, JWT creation, and token validation.

The password hash is intentionally excluded from UserRecord —
it is only accessed inside the auth service, never returned
in API responses or passed between modules.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class UserRecord(BaseModel):
    """A user record from public.tbl_users.

    Maps to the existing tbl_users table. Includes all columns
    except the password hash (security — never expose outside
    the auth service).
    """

    id: int = Field(description="Auto-increment primary key")
    user_name: str = Field(description="Unique username for login")
    email_id: str = Field(description="Unique email address")
    tenant: str = Field(description="Tenant/organization the user belongs to")
    status: str = Field(
        default="ACTIVE",
        description="Account status: ACTIVE or INACTIVE",
    )

    # Security Q&A — used for password recovery flows
    security_q1: str | None = Field(
        default=None,
        description="First security question",
    )
    security_a1: str | None = Field(
        default=None,
        description="Answer to first security question",
    )
    security_q2: str | None = Field(
        default=None,
        description="Second security question",
    )
    security_a2: str | None = Field(
        default=None,
        description="Answer to second security question",
    )
    security_q3: str | None = Field(
        default=None,
        description="Third security question",
    )
    security_a3: str | None = Field(
        default=None,
        description="Answer to third security question",
    )


class UserRoleRecord(BaseModel):
    """A user role record from public.tbl_user_roles.

    Maps to the existing tbl_user_roles table. Links a user
    to their role within a tenant, with audit metadata for
    who created/modified/deleted the role assignment.
    """

    slno: int = Field(description="Auto-increment serial number")
    first_name: str = Field(description="User's first name")
    last_name: str = Field(description="User's last name")
    email_id: str = Field(description="User's email address")
    user_name: str = Field(description="Username matching tbl_users.user_name")
    tenant: str = Field(description="Tenant/organization")
    role: str = Field(description="Role name (e.g., ADMIN, VENDOR, REVIEWER)")

    # Audit fields
    created_by: str | None = Field(default=None, description="Who created this role")
    created_date: datetime | None = Field(default=None, description="When created")
    modified_by: str | None = Field(default=None, description="Who last modified")
    modified_date: datetime | None = Field(default=None, description="When last modified")
    deleted_by: str | None = Field(default=None, description="Who deleted (soft delete)")
    deleted_date: datetime | None = Field(default=None, description="When deleted")


class LoginRequest(BaseModel):
    """Request body for POST /auth/login.

    Accepts either a username or email address for login,
    along with the password. The auth service tries both
    lookup methods (username match, then email match).
    """

    username_or_email: str = Field(
        description="Username or email address to log in with",
    )
    password: str = Field(
        description="User password (verified against werkzeug hash in DB)",
    )


class LoginResponse(BaseModel):
    """Response body for POST /auth/login.

    Returns a JWT token and the authenticated user's profile.
    The Angular frontend uses this to store auth state and
    display user info in the portal header.
    """

    token: str = Field(description="JWT access token")
    user_name: str = Field(description="Authenticated username")
    email: str = Field(description="User's email address")
    role: str = Field(description="User role (ADMIN, VENDOR, REVIEWER)")
    tenant: str = Field(description="User's tenant/organization")
    vendor_id: str | None = Field(
        default=None,
        description="Vendor ID if user has VENDOR role (from Salesforce)",
    )


class TokenPayload(BaseModel):
    """Decoded JWT claims structure.

    The auth service creates tokens with these claims. The
    middleware decodes the token and uses these fields to set
    request.state for downstream route handlers.

    The 'jti' (JWT ID) is a UUID that uniquely identifies each
    token — used for the Redis-based blacklist on logout.
    """

    sub: str = Field(description="Subject — the username")
    role: str = Field(description="User role from tbl_user_roles")
    tenant: str = Field(description="User's tenant/organization")
    exp: float = Field(description="Expiration time (Unix timestamp)")
    iat: float = Field(description="Issued-at time (Unix timestamp)")
    jti: str = Field(description="JWT ID — UUID for blacklist tracking")
