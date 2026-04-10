"""Authentication Service for VQMS.

Handles user login, logout, JWT token management, and session
control. Replaces the local_vqm auth logic with VQMS-standard
patterns: async DB via get_engine(), PostgreSQL-based token
blacklist, structured logging, and correlation IDs.

Database: Queries public.tbl_users and public.tbl_user_roles
via raw SQL (same pattern as portal_submission.py).

Password hashing: Uses werkzeug.security.check_password_hash
to verify passwords — compatible with existing hashed passwords
in tbl_users created by the local_vqm backend.

Token blacklist: Uses PostgreSQL cache table (cache.kv_store).
Key pattern: vqms:auth:blacklist:<jti> with TTL matching JWT lifetime.
"""

from __future__ import annotations

import asyncio
import time
import uuid

from jose import JWTError, jwt
from sqlalchemy import text
from werkzeug.security import check_password_hash

from config.settings import get_settings
from src.cache.pg_cache import (
    auth_blacklist_key,
    exists_key,
    set_with_ttl,
)
from src.db.connection import get_engine
from src.models.auth import LoginResponse, TokenPayload
from src.utils.logger import get_logger, log_service_call

logger = get_logger(__name__)


class AuthenticationError(Exception):
    """Raised when authentication fails.

    Covers: invalid credentials, inactive account, missing role,
    JWT decode failure, blacklisted token. The message is safe
    to return to the client (no internal details leaked).
    """


@log_service_call
async def authenticate_user(
    username_or_email: str,
    password: str,
    *,
    correlation_id: str | None = None,
) -> LoginResponse:
    """Authenticate a user by username/email and password.

    Queries public.tbl_users to find the user, verifies the
    password hash with werkzeug, then queries public.tbl_user_roles
    for the user's role. Creates a JWT.

    Args:
        username_or_email: The username or email to log in with.
        password: Plain-text password to verify against the hash.
        correlation_id: Tracing ID for log correlation.

    Returns:
        LoginResponse with JWT token and user profile.

    Raises:
        AuthenticationError: If credentials are invalid, account
            is inactive, or no role is assigned.
    """
    engine = get_engine()
    if engine is None:
        raise AuthenticationError("Database not available")

    # Step 1: Find user by username or email
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT id, user_name, email_id, tenant, password, status, "
                "security_q1, security_a1, security_q2, security_a2, "
                "security_q3, security_a3 "
                "FROM public.tbl_users "
                "WHERE user_name = :login OR email_id = :login "
                "LIMIT 1"
            ),
            {"login": username_or_email},
        )
        user_row = result.mappings().first()

    if user_row is None:
        logger.warning(
            "Login failed — user not found",
            extra={
                "username_or_email": username_or_email,
                "correlation_id": correlation_id,
            },
        )
        raise AuthenticationError("Invalid credentials")

    # Step 2: Check account is active
    if user_row["status"] != "ACTIVE":
        logger.warning(
            "Login failed — account inactive",
            extra={
                "user_name": user_row["user_name"],
                "status": user_row["status"],
                "correlation_id": correlation_id,
            },
        )
        raise AuthenticationError("Account is inactive")

    # Step 3: Verify password
    # check_password_hash is CPU-bound, run in thread to avoid
    # blocking the async event loop
    password_valid = await asyncio.to_thread(
        check_password_hash, user_row["password"], password
    )
    if not password_valid:
        logger.warning(
            "Login failed — invalid password",
            extra={
                "user_name": user_row["user_name"],
                "correlation_id": correlation_id,
            },
        )
        raise AuthenticationError("Invalid credentials")

    # Step 4: Get user's role from tbl_user_roles
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT slno, first_name, last_name, email_id, "
                "user_name, tenant, role "
                "FROM public.tbl_user_roles "
                "WHERE user_name = :user_name "
                "LIMIT 1"
            ),
            {"user_name": user_row["user_name"]},
        )
        role_row = result.mappings().first()

    if role_row is None:
        logger.warning(
            "Login failed — no role assigned",
            extra={
                "user_name": user_row["user_name"],
                "correlation_id": correlation_id,
            },
        )
        raise AuthenticationError("No role assigned to this user")

    # Step 5: Create JWT token
    role = role_row["role"]
    tenant = role_row["tenant"] or user_row["tenant"]
    token = create_access_token(
        user_name=user_row["user_name"],
        role=role,
        tenant=tenant,
    )

    logger.info(
        "Login successful",
        extra={
            "user_name": user_row["user_name"],
            "role": role,
            "tenant": tenant,
            "correlation_id": correlation_id,
        },
    )

    return LoginResponse(
        token=token,
        user_name=user_row["user_name"],
        email=user_row["email_id"],
        role=role,
        tenant=tenant,
        vendor_id=None,  # TODO: resolve vendor_id for VENDOR role users
    )


def create_access_token(
    user_name: str,
    role: str,
    tenant: str,
) -> str:
    """Create a signed JWT with user claims.

    The token includes a JTI (JWT ID) — a UUID that uniquely
    identifies this token instance. Used by the blacklist to
    invalidate specific tokens on logout.

    Args:
        user_name: The authenticated username (becomes 'sub' claim).
        role: User role from tbl_user_roles.
        tenant: User's tenant/organization.

    Returns:
        Encoded JWT string.
    """
    settings = get_settings()
    now = time.time()

    claims = {
        "sub": user_name,
        "role": role,
        "tenant": tenant,
        "exp": now + settings.session_timeout_seconds,
        "iat": now,
        "jti": str(uuid.uuid4()),
    }

    return jwt.encode(
        claims,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


async def validate_token(token: str) -> TokenPayload | None:
    """Decode and validate a JWT token.

    Checks:
      1. Token is valid and not expired (jose handles this)
      2. Token's JTI is not in the cache blacklist (logout check)

    Args:
        token: The raw JWT string from the Authorization header.

    Returns:
        TokenPayload with decoded claims, or None if the token
        is invalid, expired, or blacklisted.
    """
    settings = get_settings()

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError:
        return None

    # Check required claims exist
    required_claims = {"sub", "role", "tenant", "exp", "iat", "jti"}
    if not required_claims.issubset(payload.keys()):
        return None

    # Check if token has been blacklisted (user logged out)
    try:
        blacklist_key, _ttl = auth_blacklist_key(payload["jti"])
        is_blacklisted = await exists_key(blacklist_key)
        if is_blacklisted:
            return None
    except Exception:
        # If the database is down, we allow the token through rather
        # than blocking all authenticated requests
        logger.warning(
            "Cache unavailable for blacklist check — allowing token",
            extra={"jti": payload["jti"]},
        )

    return TokenPayload(
        sub=payload["sub"],
        role=payload["role"],
        tenant=payload["tenant"],
        exp=payload["exp"],
        iat=payload["iat"],
        jti=payload["jti"],
    )


@log_service_call
async def blacklist_token(
    token: str,
    *,
    correlation_id: str | None = None,
) -> None:
    """Add a token to the cache blacklist (logout).

    Decodes the token to extract the JTI, then stores it in
    the PostgreSQL cache with a TTL matching the JWT lifetime.
    After the token would have expired naturally, the blacklist
    entry is cleaned up by the periodic cache cleanup task.

    Args:
        token: The raw JWT string to blacklist.
        correlation_id: Tracing ID for log correlation.

    Raises:
        AuthenticationError: If the token cannot be decoded.
    """
    settings = get_settings()

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"verify_exp": False},  # Allow blacklisting expired tokens
        )
    except JWTError as exc:
        raise AuthenticationError(f"Cannot decode token for blacklisting: {exc}") from exc

    jti = payload.get("jti")
    if not jti:
        raise AuthenticationError("Token has no JTI claim")

    # Store in cache blacklist
    try:
        key, ttl = auth_blacklist_key(jti)
        await set_with_ttl(key, "blacklisted", ttl)
        logger.info(
            "Token blacklisted",
            extra={
                "jti": jti,
                "user_name": payload.get("sub"),
                "correlation_id": correlation_id,
            },
        )
    except Exception:
        # Cache unavailable — log warning but don't fail logout
        logger.warning(
            "Cache unavailable — token blacklist skipped",
            extra={
                "jti": jti,
                "correlation_id": correlation_id,
            },
        )


async def refresh_token_if_expiring(
    payload: TokenPayload,
) -> str | None:
    """Create a new token if the current one is about to expire.

    If the token has less than token_refresh_threshold_seconds
    remaining, a new token is generated with the same claims
    and the old token's JTI is blacklisted.

    Args:
        payload: Decoded claims from the current token.

    Returns:
        New JWT string if refresh was needed, or None if the
        token still has plenty of time left.
    """
    settings = get_settings()
    remaining = payload.exp - time.time()

    if remaining > settings.token_refresh_threshold_seconds:
        return None

    # Create a new token with the same claims
    new_token = create_access_token(
        user_name=payload.sub,
        role=payload.role,
        tenant=payload.tenant,
    )

    # Blacklist the old token's JTI so it cannot be reused
    try:
        key, ttl = auth_blacklist_key(payload.jti)
        await set_with_ttl(key, "refreshed", ttl)
    except Exception:
        logger.warning(
            "Cache unavailable — old token JTI not blacklisted after refresh",
            extra={"jti": payload.jti},
        )

    logger.info(
        "Token refreshed",
        extra={
            "user_name": payload.sub,
            "old_jti": payload.jti,
            "remaining_seconds": remaining,
        },
    )

    return new_token
