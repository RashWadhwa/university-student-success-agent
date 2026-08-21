"""FastAPI authentication and capability dependencies."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.auth.errors import AuthenticationError, AuthorizationError
from backend.auth.models import Capability, Principal
from backend.auth.service import AuthenticationService

_bearer = HTTPBearer(auto_error=False)


async def get_current_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    service: AuthenticationService | None = getattr(request.app.state, "auth_service", None)
    if service is None:
        raise AuthenticationError()
    token = (
        credentials.credentials
        if credentials and credentials.scheme.casefold() == "bearer"
        else None
    )
    principal = await service.authenticate(token)
    request.state.principal = principal
    return principal


def require_capability(capability: Capability) -> Callable[..., Principal]:
    async def dependency(
        principal: Annotated[Principal, Depends(get_current_principal)],
    ) -> Principal:
        if not principal.can(capability):
            raise AuthorizationError()
        return principal

    return dependency
