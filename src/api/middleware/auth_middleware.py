"""JWT authentication middleware for VQMS.

Intercepts all incoming requests, decodes the JWT from the
Authorization header, and sets user context on request.state.
Also handles automatic token refresh when the JWT is about
to expire (adds X-New-Token response header).

Combines two local_vqm concerns (UserContextMiddleware +
token refresh middleware) into a single middleware to avoid
decoding the JWT twice per request.

Skip paths: /health, /auth/login, /docs, /openapi.json, /webhooks/
These endpoints either don't need auth or have their own auth
mechanism (e.g., Graph API webhook uses HMAC verification).
"""

from __future__ import annotations

import logging

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from src.services.auth import refresh_token_if_expiring, validate_token

logger = logging.getLogger(__name__)

# Paths that bypass JWT authentication entirely
SKIP_PATHS: tuple[str, ...] = (
    "/health",
    "/auth/login",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/webhooks/",
)


class AuthMiddleware(BaseHTTPMiddleware):
    """JWT authentication and user context middleware.

    For every request (except skip paths):
      1. Extracts Bearer token from Authorization header
      2. Validates the JWT and checks token blacklist
      3. Sets request.state: username, role, tenant, is_authenticated
      4. After the route handler runs, checks if the token needs
         refresh and adds X-New-Token header if so

    If the token is missing or invalid, returns 401 JSON response.
    The route handler never executes for unauthenticated requests.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """Process each request through JWT authentication."""
        # Skip auth for certain paths
        path = request.url.path
        if _should_skip_auth(path):
            # Set unauthenticated state so routes can check if needed
            request.state.username = None
            request.state.role = None
            request.state.tenant = None
            request.state.is_authenticated = False
            return await call_next(request)

        # Extract token from Authorization: Bearer <token>
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "Not authenticated"},
            )

        token = auth_header[7:]  # Strip "Bearer " prefix

        # Validate token (decode + blacklist check)
        payload = await validate_token(token)
        if payload is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or expired token"},
            )

        # Set user context on request.state for downstream handlers
        request.state.username = payload.sub
        request.state.role = payload.role
        request.state.tenant = payload.tenant
        request.state.is_authenticated = True

        # Execute the route handler
        response = await call_next(request)

        # Check if token needs refresh (nearing expiry)
        new_token = await refresh_token_if_expiring(payload)
        if new_token is not None:
            response.headers["X-New-Token"] = new_token

        return response


def _should_skip_auth(path: str) -> bool:
    """Check if a request path should bypass JWT authentication.

    Args:
        path: The URL path of the incoming request.

    Returns:
        True if the path matches any skip pattern.
    """
    for skip_path in SKIP_PATHS:
        if path == skip_path or path.startswith(skip_path):
            return True
    return False
