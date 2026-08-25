"""Minimal Supabase GoTrue (Auth) REST client.

Deliberately dependency-free (plain httpx, no ``supabase``/``gotrue`` SDK) so the
Supabase-specific surface stays small and swappable, matching how
``AuthenticationService`` already talks to the JWKS endpoint over raw HTTP.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

_TIMEOUT_SECONDS = 10.0


class SupabaseAuthError(Exception):
    """A Supabase Auth REST call failed. Carries only safe, structured metadata."""

    def __init__(self, reason: str, *, status_code: int, provider_code: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code
        self.provider_code = provider_code


@dataclass(frozen=True, slots=True)
class SupabaseUser:
    user_id: str
    email: str | None
    app_metadata: dict[str, Any] = field(default_factory=dict)
    user_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SupabaseSession:
    access_token: str
    refresh_token: str
    expires_in: int
    user_id: str
    email: str | None
    app_metadata: dict[str, Any] = field(default_factory=dict)
    user_metadata: dict[str, Any] = field(default_factory=dict)


class SupabaseAuthProvider:
    """Thin wrapper over the Supabase GoTrue REST API, scoped to this app's needs."""

    def __init__(
        self,
        *,
        auth_url: str,
        anon_key: str,
        service_role_key: str | None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base = auth_url.rstrip("/")
        self._anon_key = anon_key
        self._service_role_key = service_role_key
        self._client = client or httpx.AsyncClient(timeout=_TIMEOUT_SECONDS)
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def sign_up(
        self, *, email: str, password: str, display_name: str
    ) -> tuple[SupabaseUser, SupabaseSession | None]:
        payload = await self._post(
            "/signup",
            json={"email": email, "password": password, "data": {"display_name": display_name}},
            headers=self._headers(),
        )
        user_payload = payload.get("user") if isinstance(payload.get("user"), dict) else payload
        user = self._parse_user(user_payload)
        session = self._parse_session(payload) if payload.get("access_token") else None
        return user, session

    async def sign_in_with_password(self, *, email: str, password: str) -> SupabaseSession:
        payload = await self._post(
            "/token",
            params={"grant_type": "password"},
            json={"email": email, "password": password},
            headers=self._headers(),
        )
        return self._parse_session(payload)

    async def refresh_session(self, *, refresh_token: str) -> SupabaseSession:
        payload = await self._post(
            "/token",
            params={"grant_type": "refresh_token"},
            json={"refresh_token": refresh_token},
            headers=self._headers(),
        )
        return self._parse_session(payload)

    async def sign_out(self, *, access_token: str) -> None:
        await self._post(
            "/logout",
            json=None,
            headers=self._headers(bearer=access_token),
            expect_empty=True,
        )

    async def request_password_recovery(self, *, email: str) -> None:
        await self._post("/recover", json={"email": email}, headers=self._headers())

    async def verify_recovery_token(self, *, token_hash: str) -> SupabaseSession:
        payload = await self._post(
            "/verify",
            json={"type": "recovery", "token_hash": token_hash},
            headers=self._headers(),
        )
        return self._parse_session(payload)

    async def update_password(self, *, access_token: str, new_password: str) -> None:
        await self._put(
            "/user",
            json={"password": new_password},
            headers=self._headers(bearer=access_token),
        )

    async def admin_set_app_metadata(self, *, user_id: str, app_metadata: dict[str, Any]) -> None:
        """Best-effort trusted-metadata write; requires the service-role key."""

        if self._service_role_key is None:
            return
        await self._put(
            f"/admin/users/{user_id}",
            json={"app_metadata": app_metadata},
            headers=self._admin_headers(),
        )

    async def admin_find_user_by_email(self, *, email: str) -> SupabaseUser | None:
        """Used only by the offline demo-user seed script; requires the service-role key."""

        payload = await self._get(
            "/admin/users", params={"page": "1", "per_page": "200"}, headers=self._admin_headers()
        )
        users = payload.get("users") if isinstance(payload.get("users"), list) else []
        for candidate in users:
            if isinstance(candidate, dict) and candidate.get("email") == email:
                return self._parse_user(candidate)
        return None

    async def admin_create_user(self, *, email: str, password: str) -> SupabaseUser:
        """Used only by the offline demo-user seed script; requires the service-role key."""

        payload = await self._post(
            "/admin/users",
            json={"email": email, "password": password, "email_confirm": True},
            headers=self._admin_headers(),
        )
        return self._parse_user(payload)

    async def admin_delete_user(self, *, user_id: str) -> None:
        """Used only by offline tooling (seed/cleanup scripts, E2E test teardown)."""

        await self._delete(f"/admin/users/{user_id}", headers=self._admin_headers())

    async def _delete(self, path: str, *, headers: dict[str, str]) -> dict[str, Any]:
        response = await self._client.delete(f"{self._base}{path}", headers=headers)
        return self._parse_response(response, expect_empty=True)

    async def _get(
        self, path: str, *, headers: dict[str, str], params: dict[str, str] | None = None
    ) -> dict[str, Any]:
        response = await self._client.get(f"{self._base}{path}", headers=headers, params=params)
        return self._parse_response(response)

    def _headers(self, *, bearer: str | None = None) -> dict[str, str]:
        return {"apikey": self._anon_key, "Authorization": f"Bearer {bearer or self._anon_key}"}

    def _admin_headers(self) -> dict[str, str]:
        assert self._service_role_key is not None
        return {
            "apikey": self._service_role_key,
            "Authorization": f"Bearer {self._service_role_key}",
        }

    async def _post(
        self,
        path: str,
        *,
        json: dict[str, Any] | None,
        headers: dict[str, str],
        params: dict[str, str] | None = None,
        expect_empty: bool = False,
    ) -> dict[str, Any]:
        response = await self._client.post(
            f"{self._base}{path}", json=json, headers=headers, params=params
        )
        return self._parse_response(response, expect_empty=expect_empty)

    async def _put(
        self, path: str, *, json: dict[str, Any], headers: dict[str, str]
    ) -> dict[str, Any]:
        response = await self._client.put(f"{self._base}{path}", json=json, headers=headers)
        return self._parse_response(response)

    def _parse_response(
        self, response: httpx.Response, *, expect_empty: bool = False
    ) -> dict[str, Any]:
        if response.status_code >= 400:
            provider_code: str | None = None
            reason = "The authentication provider rejected the request."
            try:
                body = response.json()
            except ValueError:
                body = None
            if isinstance(body, dict):
                provider_code = str(body.get("error_code") or body.get("code") or "") or None
                message = body.get("msg") or body.get("error_description") or body.get("message")
                if isinstance(message, str) and message:
                    reason = message
            raise SupabaseAuthError(
                reason, status_code=response.status_code, provider_code=provider_code
            )
        if expect_empty or not response.content:
            return {}
        try:
            payload = response.json()
        except ValueError as exc:
            raise SupabaseAuthError(
                "The authentication provider returned an unexpected response.", status_code=502
            ) from exc
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _parse_user(payload: dict[str, Any]) -> SupabaseUser:
        return SupabaseUser(
            user_id=str(payload.get("id")),
            email=payload.get("email"),
            app_metadata=payload.get("app_metadata") or {},
            user_metadata=payload.get("user_metadata") or {},
        )

    @staticmethod
    def _parse_session(payload: dict[str, Any]) -> SupabaseSession:
        user = payload.get("user") if isinstance(payload.get("user"), dict) else {}
        return SupabaseSession(
            access_token=str(payload["access_token"]),
            refresh_token=str(payload["refresh_token"]),
            expires_in=int(payload.get("expires_in", 3600)),
            user_id=str(user.get("id")),
            email=user.get("email"),
            app_metadata=user.get("app_metadata") or {},
            user_metadata=user.get("user_metadata") or {},
        )
