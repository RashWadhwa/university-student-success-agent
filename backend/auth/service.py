"""Supabase JWT verification without insecure manual decoding."""

from __future__ import annotations

import asyncio
from time import monotonic
from typing import Any
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx
import jwt
from jwt import PyJWKSet

from backend.auth.errors import AuthenticationError
from backend.auth.models import Principal, Role
from backend.core.config import AuthMode, Settings

_ALGORITHMS = frozenset({"RS256", "ES256"})


class AuthenticationService:
    """Validate Supabase access tokens and construct trusted principals."""

    def __init__(self, settings: Settings, *, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._client = client or httpx.AsyncClient(timeout=5.0)
        self._owns_client = client is None
        self._jwks: dict[str, Any] | None = None
        self._jwks_loaded_at = 0.0
        self._lock = asyncio.Lock()

    async def authenticate(self, token: str | None) -> Principal:
        if self.settings.auth_mode is AuthMode.LOCAL:
            if self.settings.is_production:
                raise AuthenticationError()
            return Principal(
                user_id=uuid5(NAMESPACE_URL, "student-success-agent:local-user"),
                tenant_id=self.settings.default_tenant_id,
                role=Role(self.settings.local_auth_role),
            )
        if not token or len(token) > 8192:
            raise AuthenticationError()
        claims = await self._decode(token)
        try:
            user_id = UUID(str(claims["sub"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise AuthenticationError("The access token is invalid.") from exc
        app_metadata = claims.get("app_metadata")
        trusted = app_metadata if isinstance(app_metadata, dict) else {}
        try:
            role = Role(str(trusted.get("app_role", Role.STUDENT.value)))
        except ValueError as exc:
            raise AuthenticationError("The access token is invalid.") from exc
        tenant = str(trusted.get("tenant_id", self.settings.default_tenant_id)).strip()
        if not tenant or len(tenant) > 100:
            raise AuthenticationError("The access token is invalid.")
        return Principal(user_id=user_id, tenant_id=tenant, role=role, token_id=claims.get("jti"))

    async def _decode(self, token: str) -> dict[str, Any]:
        auth_url = self.settings.supabase_auth_url
        if auth_url is None:
            raise AuthenticationError()
        try:
            header = jwt.get_unverified_header(token)
            algorithm = header.get("alg")
            key_id = header.get("kid")
            if algorithm not in _ALGORITHMS or not isinstance(key_id, str):
                raise AuthenticationError("The access token is invalid.")
            jwks = await self._get_jwks(auth_url)
            signing_key = next(
                (item.key for item in PyJWKSet.from_dict(jwks).keys if item.key_id == key_id),
                None,
            )
            if signing_key is None:
                self._jwks = None
                jwks = await self._get_jwks(auth_url)
                signing_key = next(
                    (item.key for item in PyJWKSet.from_dict(jwks).keys if item.key_id == key_id),
                    None,
                )
            if signing_key is None:
                raise AuthenticationError("The access token is invalid.")
            issuer = auth_url.rstrip("/")
            claims = jwt.decode(
                token,
                signing_key,
                algorithms=[algorithm],
                audience=self.settings.supabase_jwt_audience,
                issuer=issuer,
                options={"require": ["exp", "iat", "sub", "iss", "aud"]},
            )
            return dict(claims)
        except AuthenticationError:
            raise
        except (jwt.PyJWTError, httpx.HTTPError, ValueError, StopIteration) as exc:
            raise AuthenticationError("The access token is invalid or expired.") from exc

    async def _get_jwks(self, auth_url: str) -> dict[str, Any]:
        if (
            self._jwks
            and monotonic() - self._jwks_loaded_at < self.settings.auth_jwks_cache_seconds
        ):
            return self._jwks
        async with self._lock:
            if (
                self._jwks
                and monotonic() - self._jwks_loaded_at < self.settings.auth_jwks_cache_seconds
            ):
                return self._jwks
            parsed = urlparse(auth_url)
            local_http = (
                parsed.scheme == "http"
                and parsed.hostname in {"localhost", "127.0.0.1"}
                and not self.settings.is_production
            )
            if (parsed.scheme != "https" and not local_http) or not parsed.netloc:
                raise AuthenticationError("Authentication is unavailable.")
            response = await self._client.get(f"{auth_url.rstrip('/')}/.well-known/jwks.json")
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(payload.get("keys"), list):
                raise AuthenticationError("Authentication is unavailable.")
            self._jwks = payload
            self._jwks_loaded_at = monotonic()
            return payload

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @property
    def configured(self) -> bool:
        return (
            self.settings.auth_mode is AuthMode.LOCAL or self.settings.supabase_auth_url is not None
        )
