"""Authentication and authorization boundary tests without live Supabase calls."""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from backend.auth.errors import AuthenticationError
from backend.auth.models import Capability, Principal, Role
from backend.auth.service import AuthenticationService
from backend.core.config import AuthMode, Environment, Settings


def auth_fixture() -> tuple[Settings, object, dict[str, object]]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk.update({"kid": "test-key", "alg": "RS256", "use": "sig"})
    settings = Settings(
        _env_file=None,
        environment=Environment.STAGING,
        auth_mode=AuthMode.SUPABASE,
        supabase_auth_url="https://project.supabase.co/auth/v1",
        supabase_jwt_audience="authenticated",
        rate_limit_secret="test-auth-rate-limit-key",
        llm_provider="mock",
        eval_provider="mock",
        embedding_dimensions=8,
    )
    return settings, private_key, jwk


def token_for(
    private_key: object,
    *,
    issuer: str = "https://project.supabase.co/auth/v1",
    audience: str = "authenticated",
    expires_delta: timedelta = timedelta(minutes=5),
    app_metadata: dict[str, str] | None = None,
) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(uuid4()),
            "iss": issuer,
            "aud": audience,
            "iat": now,
            "exp": now + expires_delta,
            "app_metadata": app_metadata or {"app_role": "student", "tenant_id": "tenant-a"},
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )


@pytest.mark.asyncio
async def test_valid_supabase_token_uses_trusted_app_metadata() -> None:
    settings, private_key, jwk = auth_fixture()
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"keys": [jwk]}))
    )
    service = AuthenticationService(settings, client=client)

    principal = await service.authenticate(
        token_for(private_key, app_metadata={"app_role": "staff", "tenant_id": "tenant-a"})
    )

    assert principal.role is Role.STAFF
    assert principal.tenant_id == "tenant-a"
    assert principal.can(Capability.DOCUMENT_MANAGE)
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"expires_delta": timedelta(seconds=-1)},
        {"issuer": "https://wrong.example/auth/v1"},
        {"audience": "wrong"},
    ],
)
async def test_invalid_expired_issuer_and_audience_fail_closed(
    changes: dict[str, object],
) -> None:
    settings, private_key, jwk = auth_fixture()
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"keys": [jwk]}))
    )
    service = AuthenticationService(settings, client=client)

    with pytest.raises(AuthenticationError):
        await service.authenticate(token_for(private_key, **changes))  # type: ignore[arg-type]
    await client.aclose()


@pytest.mark.asyncio
async def test_missing_token_fails_in_supabase_mode() -> None:
    settings, _, _ = auth_fixture()
    service = AuthenticationService(settings)
    with pytest.raises(AuthenticationError):
        await service.authenticate(None)
    await service.close()


@pytest.mark.asyncio
async def test_invalid_signature_fails_closed() -> None:
    settings, _, jwk = auth_fixture()
    attacker_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"keys": [jwk]}))
    )
    service = AuthenticationService(settings, client=client)

    with pytest.raises(AuthenticationError):
        await service.authenticate(token_for(attacker_key))
    await client.aclose()


def test_request_body_cannot_construct_or_spoof_principal() -> None:
    assert (
        "user_id"
        not in __import__(
            "backend.schemas.memory", fromlist=["MemoryCreateRequest"]
        ).MemoryCreateRequest.model_fields
    )
    principal = Principal(user_id=uuid4(), tenant_id="tenant-a", role=Role.STUDENT)
    assert not principal.can(Capability.DOCUMENT_MANAGE)
    assert not principal.can(Capability.EVALUATION_RUN)


@pytest.mark.parametrize(
    ("role", "capability", "allowed"),
    [
        (Role.STUDENT, Capability.DOCUMENT_MANAGE, False),
        (Role.STAFF, Capability.DOCUMENT_MANAGE, True),
        (Role.STAFF, Capability.EVALUATION_RUN, False),
        (Role.ADMIN, Capability.EVALUATION_RUN, True),
        (Role.ADMIN, Capability.AUDIT_READ, True),
    ],
)
def test_role_capabilities_are_explicit(role: Role, capability: Capability, allowed: bool) -> None:
    principal = Principal(user_id=uuid4(), tenant_id="tenant-a", role=role)
    assert principal.can(capability) is allowed
