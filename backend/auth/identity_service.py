"""Registration, login, and password-recovery orchestration against Supabase Auth.

This complements ``AuthenticationService`` (token *verification*): this module
handles token *issuance* — the flows Stage 8 never implemented. Role trust
follows the same mechanism Stage 8 already verifies (``app_metadata.app_role``
inside the Supabase-issued JWT) — there is no separate local user table, so a
new account is trusted-student the moment it exists, by construction.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from backend.audit.service import AuditService
from backend.auth.errors import AuthenticationError
from backend.auth.models import Principal, Role
from backend.auth.supabase_provider import SupabaseAuthError, SupabaseAuthProvider, SupabaseSession
from backend.core.context import get_request_id
from backend.core.exceptions import ApplicationError

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AuthenticatedIdentity:
    user_id: UUID
    email: str | None
    display_name: str | None
    role: Role
    tenant_id: str


@dataclass(frozen=True, slots=True)
class IssuedSession:
    identity: AuthenticatedIdentity
    access_token: str
    refresh_token: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class RegistrationOutcome:
    pending_verification: bool
    identity: AuthenticatedIdentity | None
    session: IssuedSession | None


class IdentityService:
    """Owns the Supabase Auth lifecycle: register / login / refresh / logout / recover."""

    def __init__(
        self,
        provider: SupabaseAuthProvider,
        *,
        default_tenant_id: str,
        audit_service: AuditService | None = None,
    ) -> None:
        self._provider = provider
        self._default_tenant_id = default_tenant_id
        self._audit = audit_service

    async def close(self) -> None:
        await self._provider.close()

    def _identity_from_session(self, session: SupabaseSession) -> AuthenticatedIdentity:
        try:
            role = Role(str(session.app_metadata.get("app_role", Role.STUDENT.value)))
        except ValueError:
            role = Role.STUDENT
        tenant_id = str(session.app_metadata.get("tenant_id") or self._default_tenant_id)
        return AuthenticatedIdentity(
            user_id=UUID(session.user_id),
            email=session.email,
            display_name=session.user_metadata.get("display_name"),
            role=role,
            tenant_id=tenant_id,
        )

    def _issued_session(self, session: SupabaseSession) -> IssuedSession:
        return IssuedSession(
            identity=self._identity_from_session(session),
            access_token=session.access_token,
            refresh_token=session.refresh_token,
            expires_at=datetime.now(UTC) + timedelta(seconds=session.expires_in),
        )

    async def _audit_event(self, identity: AuthenticatedIdentity, *, event_type: str) -> None:
        if self._audit is None:
            return
        principal = Principal(
            user_id=identity.user_id, tenant_id=identity.tenant_id, role=identity.role
        )
        try:
            await self._audit.record(
                principal,
                request_id=get_request_id(),
                event_type=event_type,
                decision=None,
                success=True,
            )
        except Exception:
            logger.warning("Failed to record auth audit event", extra={"event_type": event_type})

    async def register(
        self, *, email: str, password: str, display_name: str
    ) -> RegistrationOutcome:
        try:
            user, session = await self._provider.sign_up(
                email=email, password=password, display_name=display_name
            )
        except SupabaseAuthError as exc:
            logger.warning(
                "Registration rejected by provider",
                extra={"status_code": exc.status_code, "provider_code": exc.provider_code},
            )
            raise ApplicationError(
                code="REGISTRATION_FAILED",
                message=(
                    "Registration could not be completed. Please check your details and try again."
                ),
                status_code=400,
            ) from exc

        # Role assignment never reads anything from the request: every new account is
        # trusted-student, set here server-side via the service-role admin API.
        try:
            await self._provider.admin_set_app_metadata(
                user_id=user.user_id,
                app_metadata={
                    "app_role": Role.STUDENT.value,
                    "tenant_id": self._default_tenant_id,
                },
            )
        except SupabaseAuthError:
            logger.warning(
                "Could not set trusted role metadata after registration; "
                "token verification already defaults an unset app_role to student"
            )

        if session is None:
            return RegistrationOutcome(pending_verification=True, identity=None, session=None)

        issued = self._issued_session(session)
        await self._audit_event(issued.identity, event_type="register_success")
        return RegistrationOutcome(
            pending_verification=False, identity=issued.identity, session=issued
        )

    async def login(self, *, email: str, password: str) -> IssuedSession:
        try:
            session = await self._provider.sign_in_with_password(email=email, password=password)
        except SupabaseAuthError as exc:
            if exc.provider_code == "email_not_confirmed":
                raise ApplicationError(
                    code="EMAIL_NOT_VERIFIED",
                    message="Please verify your email address before signing in.",
                    status_code=403,
                ) from exc
            raise AuthenticationError("Invalid email or password.") from exc
        issued = self._issued_session(session)
        await self._audit_event(issued.identity, event_type="login_success")
        return issued

    async def refresh(self, *, refresh_token: str) -> IssuedSession:
        try:
            session = await self._provider.refresh_session(refresh_token=refresh_token)
        except SupabaseAuthError as exc:
            raise AuthenticationError("Your session has expired. Please sign in again.") from exc
        return self._issued_session(session)

    async def logout(self, *, access_token: str, principal: Principal | None) -> None:
        try:
            await self._provider.sign_out(access_token=access_token)
        except SupabaseAuthError:
            logger.info("Provider-side sign-out failed; clearing the local session regardless")
        if principal is not None:
            await self._audit_event(
                AuthenticatedIdentity(
                    user_id=principal.user_id,
                    email=None,
                    display_name=None,
                    role=principal.role,
                    tenant_id=principal.tenant_id,
                ),
                event_type="logout",
            )

    async def request_password_reset(self, *, email: str) -> None:
        """Always succeeds from the caller's perspective; never reveals account existence."""

        try:
            await self._provider.request_password_recovery(email=email)
        except SupabaseAuthError:
            logger.info("Password recovery request could not be forwarded to the provider")

    async def reset_password(self, *, token_hash: str, new_password: str) -> None:
        try:
            session = await self._provider.verify_recovery_token(token_hash=token_hash)
        except SupabaseAuthError as exc:
            raise ApplicationError(
                code="RESET_LINK_INVALID",
                message=(
                    "This password reset link is invalid or has expired. Please request a new one."
                ),
                status_code=400,
            ) from exc
        try:
            await self._provider.update_password(
                access_token=session.access_token, new_password=new_password
            )
        except SupabaseAuthError as exc:
            raise ApplicationError(
                code="PASSWORD_UPDATE_FAILED",
                message="Your password could not be updated. Please try again.",
                status_code=400,
            ) from exc
        await self._audit_event(
            self._identity_from_session(session), event_type="password_reset_completed"
        )
