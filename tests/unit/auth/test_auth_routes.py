"""Auth lifecycle route tests: request validation, role-escalation resistance,
safe fallbacks, and rate limiting.

Uses a stub IdentityService (no live Supabase calls) and, for the
unconfigured case, the real 503 fallback.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.auth.identity_service import AuthenticatedIdentity, IssuedSession, RegistrationOutcome
from backend.auth.models import Role
from backend.core.exceptions import ApplicationError
from backend.security.dependencies import rate_limit_by_ip


class _StubIdentityService:
    def __init__(self) -> None:
        self.register_calls: list[dict[str, str]] = []
        self.reset_calls: list[dict[str, str]] = []

    async def register(
        self, *, email: str, password: str, display_name: str
    ) -> RegistrationOutcome:
        self.register_calls.append(
            {"email": email, "password": password, "display_name": display_name}
        )
        identity = AuthenticatedIdentity(
            user_id=uuid4(),
            email=email,
            display_name=display_name,
            role=Role.STUDENT,
            tenant_id="default",
        )
        session = IssuedSession(
            identity=identity,
            access_token="access-token",
            refresh_token="refresh-token",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        return RegistrationOutcome(pending_verification=False, identity=identity, session=session)

    async def login(self, *, email: str, password: str) -> IssuedSession:
        identity = AuthenticatedIdentity(
            user_id=uuid4(),
            email=email,
            display_name="Alex Morgan",
            role=Role.STUDENT,
            tenant_id="default",
        )
        return IssuedSession(
            identity=identity,
            access_token="access-token",
            refresh_token="refresh-token",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )

    async def refresh(self, *, refresh_token: str) -> IssuedSession:
        identity = AuthenticatedIdentity(
            user_id=uuid4(),
            email="student@example.edu",
            display_name=None,
            role=Role.STUDENT,
            tenant_id="default",
        )
        return IssuedSession(
            identity=identity,
            access_token="new-access-token",
            refresh_token="new-refresh-token",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )

    async def logout(self, *, access_token: str, principal: object) -> None:
        return None

    async def request_password_reset(self, *, email: str) -> None:
        return None

    async def reset_password(self, *, token_hash: str, new_password: str) -> None:
        self.reset_calls.append({"token_hash": token_hash, "new_password": new_password})


def test_register_rejects_mismatched_passwords(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "display_name": "Alex Morgan",
            "email": "alex@example.edu",
            "password": "correct-horse-1",
            "confirm_password": "different-horse-1",
        },
    )
    assert response.status_code == 422


def test_register_body_cannot_carry_a_role_field(client: TestClient) -> None:
    """StrictModel(extra='forbid') makes role-in-body a structural impossibility."""

    response = client.post(
        "/api/v1/auth/register",
        json={
            "display_name": "Alex Morgan",
            "email": "alex@example.edu",
            "password": "correct-horse-1",
            "confirm_password": "correct-horse-1",
            "role": "admin",
        },
    )
    assert response.status_code == 422


def test_register_weak_password_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "display_name": "Alex Morgan",
            "email": "alex@example.edu",
            "password": "alllettersnodigits",
            "confirm_password": "alllettersnodigits",
        },
    )
    assert response.status_code == 422


def test_register_without_configured_provider_returns_503(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "display_name": "Alex Morgan",
            "email": "alex@example.edu",
            "password": "correct-horse-1",
            "confirm_password": "correct-horse-1",
        },
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "AUTH_PROVIDER_UNAVAILABLE"


def test_register_success_always_returns_student_role(app: FastAPI, client: TestClient) -> None:
    stub = _StubIdentityService()
    app.state.identity_service = stub
    try:
        response = client.post(
            "/api/v1/auth/register",
            json={
                "display_name": "Alex Morgan",
                "email": "alex@example.edu",
                "password": "correct-horse-1",
                "confirm_password": "correct-horse-1",
            },
        )
    finally:
        app.state.identity_service = None

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "registered"
    assert body["user"]["role"] == "student"
    assert "confirm_password" not in body


def test_login_returns_application_owned_shape(app: FastAPI, client: TestClient) -> None:
    app.state.identity_service = _StubIdentityService()
    try:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "alex@example.edu", "password": "correct-horse-1"},
        )
    finally:
        app.state.identity_service = None

    assert response.status_code == 200
    body = response.json()
    assert body["authenticated"] is True
    assert body["user"]["role"] == "student"
    assert "access_token" in body["session"]
    assert "refresh_token" in body["session"]


def test_logout_without_bearer_token_is_rejected(client: TestClient) -> None:
    response = client.post("/api/v1/auth/logout")
    assert response.status_code == 401


def test_logout_with_token_succeeds_even_without_valid_principal(
    app: FastAPI, client: TestClient
) -> None:
    app.state.identity_service = _StubIdentityService()
    try:
        response = client.post(
            "/api/v1/auth/logout", headers={"Authorization": "Bearer not-a-real-token"}
        )
    finally:
        app.state.identity_service = None

    assert response.status_code == 200
    assert "signed out" in response.json()["message"].lower()


def test_forgot_password_response_is_identical_regardless_of_account_existence(
    app: FastAPI, client: TestClient
) -> None:
    app.state.identity_service = _StubIdentityService()
    try:
        known = client.post(
            "/api/v1/auth/forgot-password", json={"email": "exists@example.edu"}
        ).json()
        unknown = client.post(
            "/api/v1/auth/forgot-password", json={"email": "does-not-exist@example.edu"}
        ).json()
    finally:
        app.state.identity_service = None

    assert known == unknown
    assert "account existence" not in known["message"].lower()


def test_reset_password_rejects_mismatched_passwords(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/reset-password",
        json={
            "token_hash": "some-hash",
            "new_password": "new-password-1",
            "confirm_password": "different-1",
        },
    )
    assert response.status_code == 422


def test_reset_password_success(app: FastAPI, client: TestClient) -> None:
    stub = _StubIdentityService()
    app.state.identity_service = stub
    try:
        response = client.post(
            "/api/v1/auth/reset-password",
            json={
                "token_hash": "email-link-hash",
                "new_password": "new-password-1",
                "confirm_password": "new-password-1",
            },
        )
    finally:
        app.state.identity_service = None

    assert response.status_code == 200
    assert stub.reset_calls == [{"token_hash": "email-link-hash", "new_password": "new-password-1"}]


def test_demo_login_disabled_by_default(app: FastAPI, client: TestClient) -> None:
    app.state.identity_service = _StubIdentityService()
    try:
        response = client.post("/api/v1/auth/demo-login", json={"demo_role": "student"})
    finally:
        app.state.identity_service = None

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DEMO_AUTH_DISABLED"


def test_demo_login_enabled_but_unconfigured_role(app: FastAPI, client: TestClient) -> None:
    app.state.settings.enable_demo_auth = True
    app.state.identity_service = _StubIdentityService()
    try:
        response = client.post("/api/v1/auth/demo-login", json={"demo_role": "admin"})
    finally:
        app.state.settings.enable_demo_auth = False
        app.state.identity_service = None

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DEMO_ACCOUNT_NOT_CONFIGURED"


def test_demo_login_success_never_carries_a_password_field(
    app: FastAPI, client: TestClient
) -> None:
    from pydantic import SecretStr

    stub = _StubIdentityService()
    app.state.identity_service = stub
    app.state.settings.enable_demo_auth = True
    app.state.settings.demo_student_email = "student-demo@example.edu"
    app.state.settings.demo_student_password = SecretStr("demo-password-not-sent-by-client")
    try:
        response = client.post("/api/v1/auth/demo-login", json={"demo_role": "student"})
    finally:
        app.state.settings.enable_demo_auth = False
        app.state.settings.demo_student_email = None
        app.state.settings.demo_student_password = None
        app.state.identity_service = None

    assert response.status_code == 200
    assert "password" not in response.text
    assert response.json()["user"]["role"] == "student"


@pytest.mark.asyncio
async def test_rate_limit_by_ip_denies_over_limit_requests() -> None:
    class _DenyingRateLimitService:
        async def allow(self, *, identity: str, bucket: str, limit: int) -> bool:
            return False

    class _FakeApp:
        class state:
            rate_limit_service = _DenyingRateLimitService()

            class settings:
                rate_limit_auth_login = 10

    class _FakeClient:
        host = "203.0.113.5"

    class _FakeRequest:
        app = _FakeApp()
        client = _FakeClient()

    dependency = rate_limit_by_ip("auth_login", "rate_limit_auth_login")
    with pytest.raises(ApplicationError) as excinfo:
        await dependency(_FakeRequest())
    assert excinfo.value.status_code == 429
