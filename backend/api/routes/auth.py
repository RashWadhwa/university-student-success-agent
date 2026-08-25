"""Authentication and session-lifecycle endpoints.

``/me`` reflects only the validated token's context (no user id/email/tokens
are ever echoed). The lifecycle routes below (register/login/refresh/logout/
forgot-password/reset-password) proxy Supabase Auth via ``IdentityService`` and
return an application-owned response shape — never Supabase's raw payloads.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.auth.dependencies import get_current_principal
from backend.auth.errors import AuthenticationError
from backend.auth.identity_service import AuthenticatedIdentity, IdentityService, IssuedSession
from backend.auth.models import ROLE_CAPABILITIES, Principal
from backend.auth.service import AuthenticationService
from backend.core.exceptions import ApplicationError
from backend.schemas.auth import (
    AuthenticatedUser,
    AuthResponse,
    AuthSession,
    CurrentUserResponse,
    DemoLoginRequest,
    ForgotPasswordRequest,
    LoginRequest,
    MessageResponse,
    RefreshRequest,
    RegisterRequest,
    RegistrationResponse,
    ResetPasswordRequest,
)
from backend.security.dependencies import rate_limit_by_ip

router = APIRouter(prefix="/auth", tags=["auth"])
_bearer = HTTPBearer(auto_error=False)


def _identity_service(request: Request) -> IdentityService:
    service: IdentityService | None = getattr(request.app.state, "identity_service", None)
    if service is None:
        raise ApplicationError(
            code="AUTH_PROVIDER_UNAVAILABLE",
            message="Account services are temporarily unavailable.",
            status_code=503,
        )
    return service


def _to_authenticated_user(identity: AuthenticatedIdentity) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=str(identity.user_id),
        email=identity.email,
        display_name=identity.display_name,
        role=identity.role,
    )


def _to_session(issued: IssuedSession) -> AuthSession:
    return AuthSession(
        access_token=issued.access_token,
        refresh_token=issued.refresh_token,
        expires_at=issued.expires_at,
    )


@router.get("/me", response_model=CurrentUserResponse)
async def current_user(
    principal: Annotated[Principal, Depends(get_current_principal)],
) -> CurrentUserResponse:
    return CurrentUserResponse(
        role=principal.role,
        tenant_id=principal.tenant_id,
        capabilities=sorted(ROLE_CAPABILITIES[principal.role], key=lambda item: item.value),
    )


@router.post(
    "/register",
    response_model=RegistrationResponse,
    dependencies=[Depends(rate_limit_by_ip("auth_register", "rate_limit_auth_register"))],
)
async def register(payload: RegisterRequest, request: Request) -> RegistrationResponse:
    outcome = await _identity_service(request).register(
        email=payload.email,
        password=payload.password,
        display_name=payload.display_name,
    )
    if outcome.pending_verification:
        return RegistrationResponse(
            status="pending_verification",
            message="Check your email for a verification link before signing in.",
        )
    assert outcome.identity is not None
    assert outcome.session is not None
    return RegistrationResponse(
        status="registered",
        message="Your account has been created.",
        user=_to_authenticated_user(outcome.identity),
        session=_to_session(outcome.session),
    )


@router.post(
    "/login",
    response_model=AuthResponse,
    dependencies=[Depends(rate_limit_by_ip("auth_login", "rate_limit_auth_login"))],
)
async def login(payload: LoginRequest, request: Request) -> AuthResponse:
    issued = await _identity_service(request).login(email=payload.email, password=payload.password)
    return AuthResponse(user=_to_authenticated_user(issued.identity), session=_to_session(issued))


@router.post(
    "/demo-login",
    response_model=AuthResponse,
    dependencies=[Depends(rate_limit_by_ip("auth_login", "rate_limit_auth_login"))],
)
async def demo_login(payload: DemoLoginRequest, request: Request) -> AuthResponse:
    """Signs in a pre-provisioned demo identity through the real login path.

    The demo password never reaches the frontend or this request body — it is
    read from server-side configuration and used only to call the same
    ``IdentityService.login`` real users go through.
    """

    settings = request.app.state.settings
    if not settings.enable_demo_auth:
        raise ApplicationError(
            code="DEMO_AUTH_DISABLED",
            message="Demo sign-in is not enabled.",
            status_code=404,
        )
    credentials_by_role = {
        "student": (settings.demo_student_email, settings.demo_student_password),
        "staff": (settings.demo_staff_email, settings.demo_staff_password),
        "admin": (settings.demo_admin_email, settings.demo_admin_password),
    }
    email, password = credentials_by_role[payload.demo_role]
    if not email or password is None:
        raise ApplicationError(
            code="DEMO_ACCOUNT_NOT_CONFIGURED",
            message="This demo account is not configured.",
            status_code=404,
        )
    issued = await _identity_service(request).login(
        email=email, password=password.get_secret_value()
    )
    return AuthResponse(user=_to_authenticated_user(issued.identity), session=_to_session(issued))


@router.post(
    "/refresh",
    response_model=AuthResponse,
    dependencies=[Depends(rate_limit_by_ip("auth_refresh", "rate_limit_auth_refresh"))],
)
async def refresh(payload: RefreshRequest, request: Request) -> AuthResponse:
    issued = await _identity_service(request).refresh(refresh_token=payload.refresh_token)
    return AuthResponse(user=_to_authenticated_user(issued.identity), session=_to_session(issued))


@router.post("/logout", response_model=MessageResponse)
async def logout(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> MessageResponse:
    token = (
        credentials.credentials
        if credentials and credentials.scheme.casefold() == "bearer"
        else None
    )
    if not token:
        raise AuthenticationError()
    principal: Principal | None = None
    auth_service: AuthenticationService | None = getattr(request.app.state, "auth_service", None)
    if auth_service is not None:
        try:
            principal = await auth_service.authenticate(token)
        except AuthenticationError:
            principal = None
    await _identity_service(request).logout(access_token=token, principal=principal)
    return MessageResponse(message="You have been signed out.")


@router.post(
    "/forgot-password",
    response_model=MessageResponse,
    dependencies=[
        Depends(rate_limit_by_ip("auth_password_reset", "rate_limit_auth_password_reset"))
    ],
)
async def forgot_password(payload: ForgotPasswordRequest, request: Request) -> MessageResponse:
    await _identity_service(request).request_password_reset(email=payload.email)
    return MessageResponse(
        message=(
            "If an account exists for that email address, "
            "password reset instructions have been sent."
        )
    )


@router.post(
    "/reset-password",
    response_model=MessageResponse,
    dependencies=[
        Depends(rate_limit_by_ip("auth_password_reset", "rate_limit_auth_password_reset"))
    ],
)
async def reset_password(payload: ResetPasswordRequest, request: Request) -> MessageResponse:
    await _identity_service(request).reset_password(
        token_hash=payload.token_hash, new_password=payload.new_password
    )
    return MessageResponse(message="Password updated successfully. Please sign in.")
