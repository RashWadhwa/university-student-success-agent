"""IdentityService/SupabaseAuthProvider tests — no live Supabase calls (MockTransport only)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
import pytest

from backend.auth.errors import AuthenticationError
from backend.auth.identity_service import IdentityService
from backend.auth.models import Role
from backend.auth.supabase_provider import SupabaseAuthProvider
from backend.core.exceptions import ApplicationError

_AUTH_URL = "https://project.supabase.co/auth/v1"


class _RecordingTransport(httpx.MockTransport):
    """Wraps MockTransport to also capture every outgoing request for assertions."""

    def __init__(self, handler: Any) -> None:
        self.calls: list[httpx.Request] = []

        def _wrapped(request: httpx.Request) -> httpx.Response:
            self.calls.append(request)
            return handler(request)

        super().__init__(_wrapped)


def _service(
    handler: Any, *, service_role_key: str | None = "service-role-key"
) -> tuple[IdentityService, _RecordingTransport]:
    transport = _RecordingTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    provider = SupabaseAuthProvider(
        auth_url=_AUTH_URL,
        anon_key="anon-key",
        service_role_key=service_role_key,
        client=client,
    )
    return IdentityService(provider, default_tenant_id="default"), transport


def _session_payload(*, role: str = "student", user_id: str | None = None) -> dict[str, Any]:
    return {
        "access_token": "access-token",
        "refresh_token": "refresh-token",
        "expires_in": 3600,
        "user": {
            "id": user_id or str(uuid4()),
            "email": "student@example.edu",
            "app_metadata": {"app_role": role, "tenant_id": "default"},
            "user_metadata": {"display_name": "Alex Morgan"},
        },
    }


@pytest.mark.asyncio
async def test_register_with_immediate_session_always_assigns_student_role() -> None:
    new_user_id = str(uuid4())

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/signup"):
            return httpx.Response(200, json=_session_payload(role="", user_id=new_user_id))
        if request.url.path.endswith(f"/admin/users/{new_user_id}"):
            return httpx.Response(200, json={"id": new_user_id})
        raise AssertionError(f"unexpected call: {request.url}")

    service, transport = _service(handler)
    outcome = await service.register(
        email="student@example.edu", password="correct-horse-1", display_name="Alex Morgan"
    )
    await service.close()

    assert outcome.pending_verification is False
    assert outcome.identity is not None

    admin_calls = [c for c in transport.calls if "/admin/users/" in str(c.url)]
    assert len(admin_calls) == 1
    import json as _json

    body = _json.loads(admin_calls[0].content)
    assert body["app_metadata"]["app_role"] == "student"
    assert admin_calls[0].headers["apikey"] == "service-role-key"


@pytest.mark.asyncio
async def test_register_without_immediate_session_reports_pending_verification() -> None:
    new_user_id = str(uuid4())

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/signup"):
            return httpx.Response(
                200,
                json={"id": new_user_id, "email": "student@example.edu", "app_metadata": {}},
            )
        if request.url.path.endswith(f"/admin/users/{new_user_id}"):
            return httpx.Response(200, json={"id": new_user_id})
        raise AssertionError(f"unexpected call: {request.url}")

    service, _ = _service(handler)
    outcome = await service.register(
        email="student@example.edu", password="correct-horse-1", display_name="Alex Morgan"
    )
    await service.close()

    assert outcome.pending_verification is True
    assert outcome.identity is None
    assert outcome.session is None


@pytest.mark.asyncio
async def test_register_admin_metadata_failure_does_not_break_registration() -> None:
    """Defense-in-depth: token verification already defaults an unset app_role to student."""

    new_user_id = str(uuid4())

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/signup"):
            return httpx.Response(200, json=_session_payload(role="", user_id=new_user_id))
        if "/admin/users/" in request.url.path:
            return httpx.Response(500, json={"msg": "internal error"})
        raise AssertionError(f"unexpected call: {request.url}")

    service, _ = _service(handler)
    outcome = await service.register(
        email="student@example.edu", password="correct-horse-1", display_name="Alex Morgan"
    )
    await service.close()

    assert outcome.pending_verification is False
    assert outcome.identity is not None


@pytest.mark.asyncio
async def test_login_success_maps_trusted_app_metadata_to_role() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/token")
        assert request.url.params["grant_type"] == "password"
        return httpx.Response(200, json=_session_payload(role="staff"))

    service, _ = _service(handler)
    issued = await service.login(email="staff@example.edu", password="correct-horse-1")
    await service.close()

    assert issued.identity.role is Role.STAFF
    assert issued.access_token == "access-token"
    assert issued.expires_at > datetime.now(UTC)


@pytest.mark.asyncio
async def test_login_invalid_credentials_raises_generic_authentication_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"error_code": "invalid_credentials", "msg": "Invalid login credentials"}
        )

    service, _ = _service(handler)
    with pytest.raises(AuthenticationError) as excinfo:
        await service.login(email="student@example.edu", password="wrong-password")
    await service.close()

    assert excinfo.value.message == "Invalid email or password."


@pytest.mark.asyncio
async def test_login_unverified_email_surfaces_distinct_safe_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"error_code": "email_not_confirmed", "msg": "Email not confirmed"}
        )

    service, _ = _service(handler)
    with pytest.raises(ApplicationError) as excinfo:
        await service.login(email="student@example.edu", password="correct-horse-1")
    await service.close()

    assert excinfo.value.code == "EMAIL_NOT_VERIFIED"
    assert excinfo.value.status_code == 403


@pytest.mark.asyncio
async def test_refresh_success_and_failure() -> None:
    def ok_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_session_payload())

    service, _ = _service(ok_handler)
    issued = await service.refresh(refresh_token="a-refresh-token")
    await service.close()
    assert issued.access_token == "access-token"

    def fail_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error_code": "invalid_grant", "msg": "bad token"})

    failing_service, _ = _service(fail_handler)
    with pytest.raises(AuthenticationError) as excinfo:
        await failing_service.refresh(refresh_token="expired")
    await failing_service.close()
    assert "session has expired" in excinfo.value.message.lower()


@pytest.mark.asyncio
async def test_logout_is_best_effort_even_when_provider_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"msg": "provider unavailable"})

    service, _ = _service(handler)
    await service.logout(access_token="some-token", principal=None)
    await service.close()


@pytest.mark.asyncio
async def test_request_password_reset_never_raises_even_on_provider_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"msg": "provider unavailable"})

    service, _ = _service(handler)
    await service.request_password_reset(email="nobody@example.edu")
    await service.close()


@pytest.mark.asyncio
async def test_reset_password_invalid_token_hash_is_rejected_safely() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error_code": "otp_expired", "msg": "Token has expired"})

    service, _ = _service(handler)
    with pytest.raises(ApplicationError) as excinfo:
        await service.reset_password(token_hash="stale-hash", new_password="new-password-1")
    await service.close()

    assert excinfo.value.code == "RESET_LINK_INVALID"


@pytest.mark.asyncio
async def test_reset_password_success_verifies_then_updates() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/verify"):
            return httpx.Response(200, json=_session_payload())
        if request.url.path.endswith("/user"):
            return httpx.Response(200, json={"id": "u", "email": "student@example.edu"})
        raise AssertionError(f"unexpected call: {request.url}")

    service, _ = _service(handler)
    await service.reset_password(token_hash="valid-hash", new_password="new-password-1")
    await service.close()

    assert any(path.endswith("/verify") for path in calls)
    assert any(path.endswith("/user") for path in calls)


@pytest.mark.asyncio
async def test_expires_at_uses_provider_expiry_window() -> None:
    from backend.auth.supabase_provider import SupabaseSession

    session = SupabaseSession(
        access_token="a",
        refresh_token="r",
        expires_in=120,
        user_id=str(uuid4()),
        email="student@example.edu",
        app_metadata={"app_role": "student", "tenant_id": "default"},
        user_metadata={},
    )
    service = IdentityService(
        SupabaseAuthProvider(auth_url=_AUTH_URL, anon_key="k", service_role_key=None),
        default_tenant_id="default",
    )
    issued = service._issued_session(session)
    await service.close()
    delta = issued.expires_at - datetime.now(UTC)
    assert timedelta(seconds=90) < delta <= timedelta(seconds=120)
