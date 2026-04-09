"""Tests for auth Pydantic models.

Validates model creation, default values, field constraints,
and serialization for all auth-related models.
"""

from __future__ import annotations

import time

from src.models.auth import (
    LoginRequest,
    LoginResponse,
    TokenPayload,
    UserRecord,
    UserRoleRecord,
)


class TestUserRecord:
    """Tests for the UserRecord model."""

    def test_valid_user_record(self):
        """A UserRecord with all required fields creates successfully."""
        user = UserRecord(
            id=1,
            user_name="john_doe",
            email_id="john@acme.com",
            tenant="acme",
            status="ACTIVE",
        )
        assert user.user_name == "john_doe"
        assert user.email_id == "john@acme.com"
        assert user.tenant == "acme"
        assert user.status == "ACTIVE"

    def test_default_status_is_active(self):
        """When no status is provided, defaults to ACTIVE."""
        user = UserRecord(
            id=2,
            user_name="jane",
            email_id="jane@acme.com",
            tenant="acme",
        )
        assert user.status == "ACTIVE"

    def test_security_qa_fields_default_to_none(self):
        """Security Q&A fields should default to None."""
        user = UserRecord(
            id=3,
            user_name="test_user",
            email_id="test@test.com",
            tenant="test",
        )
        assert user.security_q1 is None
        assert user.security_a1 is None
        assert user.security_q2 is None
        assert user.security_a2 is None
        assert user.security_q3 is None
        assert user.security_a3 is None

    def test_security_qa_fields_can_be_set(self):
        """Security Q&A fields can be provided."""
        user = UserRecord(
            id=4,
            user_name="secure_user",
            email_id="secure@acme.com",
            tenant="acme",
            security_q1="What is your pet?",
            security_a1="Dog",
        )
        assert user.security_q1 == "What is your pet?"
        assert user.security_a1 == "Dog"


class TestUserRoleRecord:
    """Tests for the UserRoleRecord model."""

    def test_valid_role_record(self):
        """A UserRoleRecord with all required fields creates successfully."""
        role = UserRoleRecord(
            slno=1,
            first_name="John",
            last_name="Doe",
            email_id="john@acme.com",
            user_name="john_doe",
            tenant="acme",
            role="VENDOR",
        )
        assert role.role == "VENDOR"
        assert role.first_name == "John"

    def test_audit_fields_default_to_none(self):
        """Audit fields should default to None."""
        role = UserRoleRecord(
            slno=2,
            first_name="Jane",
            last_name="Doe",
            email_id="jane@acme.com",
            user_name="jane_doe",
            tenant="acme",
            role="ADMIN",
        )
        assert role.created_by is None
        assert role.created_date is None
        assert role.modified_by is None
        assert role.deleted_by is None


class TestLoginRequest:
    """Tests for the LoginRequest model."""

    def test_valid_login_request(self):
        """A LoginRequest with username and password creates successfully."""
        req = LoginRequest(
            username_or_email="john_doe",
            password="secret123",
        )
        assert req.username_or_email == "john_doe"
        assert req.password == "secret123"

    def test_login_with_email(self):
        """LoginRequest accepts email as username_or_email."""
        req = LoginRequest(
            username_or_email="john@acme.com",
            password="secret123",
        )
        assert req.username_or_email == "john@acme.com"


class TestLoginResponse:
    """Tests for the LoginResponse model."""

    def test_valid_login_response(self):
        """A LoginResponse with all fields creates successfully."""
        resp = LoginResponse(
            token="eyJhbGciOiJIUzI1NiJ9.test",
            user_name="john_doe",
            email="john@acme.com",
            role="VENDOR",
            tenant="acme",
            vendor_id="VN-12345",
        )
        assert resp.token.startswith("eyJ")
        assert resp.vendor_id == "VN-12345"

    def test_vendor_id_defaults_to_none(self):
        """vendor_id should default to None for non-vendor users."""
        resp = LoginResponse(
            token="test-token",
            user_name="admin",
            email="admin@acme.com",
            role="ADMIN",
            tenant="acme",
        )
        assert resp.vendor_id is None


class TestTokenPayload:
    """Tests for the TokenPayload model."""

    def test_valid_token_payload(self):
        """A TokenPayload with all claims creates successfully."""
        now = time.time()
        payload = TokenPayload(
            sub="john_doe",
            role="VENDOR",
            tenant="acme",
            exp=now + 1800,
            iat=now,
            jti="550e8400-e29b-41d4-a716-446655440000",
        )
        assert payload.sub == "john_doe"
        assert payload.role == "VENDOR"
        assert payload.jti == "550e8400-e29b-41d4-a716-446655440000"
        assert payload.exp > payload.iat
