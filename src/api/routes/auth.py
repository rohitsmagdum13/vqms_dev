"""Authentication endpoints for VQMS.

POST /auth/login  — Authenticate with username/email + password, get JWT
POST /auth/logout — Blacklist the current token (invalidate session)

Replaces the fake dev-mode login with real authentication against
public.tbl_users in RDS. Passwords are verified with werkzeug
against hashes stored in the database.

In production, this will be replaced by AWS Cognito JWT auth.
For now, this provides working authentication for the Angular
frontend and API consumers during development.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.models.auth import LoginRequest, LoginResponse
from src.services.auth import AuthenticationError, authenticate_user, blacklist_token
from src.utils.correlation import generate_correlation_id
from src.utils.logger import log_api_call

logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])


@router.post("/auth/login")
@log_api_call
async def login(request_body: LoginRequest) -> LoginResponse:
    """Authenticate a user and return a JWT token.

    Accepts username or email address with password. Validates
    against tbl_users in PostgreSQL, retrieves role from
    tbl_user_roles, and returns a signed JWT.

    The Angular frontend stores this token and sends it as
    Authorization: Bearer <token> on subsequent requests.
    """
    correlation_id = generate_correlation_id()

    try:
        response = await authenticate_user(
            username_or_email=request_body.username_or_email,
            password=request_body.password,
            correlation_id=correlation_id,
        )
    except AuthenticationError as exc:
        logger.warning(
            "Login rejected",
            extra={
                "username_or_email": request_body.username_or_email,
                "reason": str(exc),
                "correlation_id": correlation_id,
            },
        )
        return JSONResponse(
            status_code=401,
            content={"detail": str(exc)},
        )

    return response


@router.post("/auth/logout")
@log_api_call
async def logout(request: Request) -> dict:
    """Log out by blacklisting the current JWT token.

    Adds the token's JTI to the cache blacklist so any
    subsequent request with this token is rejected by the
    auth middleware. The blacklist entry auto-expires when
    the JWT would have expired naturally.
    """
    correlation_id = generate_correlation_id()

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse(
            status_code=401,
            content={"detail": "No token provided"},
        )

    token = auth_header[7:]

    try:
        await blacklist_token(token, correlation_id=correlation_id)
    except AuthenticationError as exc:
        logger.warning(
            "Logout failed",
            extra={
                "reason": str(exc),
                "correlation_id": correlation_id,
            },
        )
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )

    return {"message": "Logged out successfully"}
