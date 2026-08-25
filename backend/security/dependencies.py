"""Rate-limit dependency factories."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request

from backend.auth.dependencies import get_current_principal
from backend.auth.models import Principal
from backend.core.exceptions import ApplicationError
from backend.security.rate_limit import RateLimitService


def rate_limit(bucket: str, setting_name: str) -> Callable[..., None]:
    async def dependency(
        request: Request,
        principal: Annotated[Principal, Depends(get_current_principal)],
    ) -> None:
        service: RateLimitService = request.app.state.rate_limit_service
        limit = int(getattr(request.app.state.settings, setting_name))
        if not await service.allow(identity=str(principal.user_id), bucket=bucket, limit=limit):
            raise ApplicationError(
                code="RATE_LIMITED",
                message="Too many requests. Please try again later.",
                status_code=429,
            )

    return dependency


def rate_limit_by_ip(bucket: str, setting_name: str) -> Callable[..., None]:
    """Rate limit pre-authentication endpoints, keyed by IP since no Principal exists yet."""

    async def dependency(request: Request) -> None:
        service: RateLimitService = request.app.state.rate_limit_service
        limit = int(getattr(request.app.state.settings, setting_name))
        client_host = request.client.host if request.client else "unknown"
        if not await service.allow(identity=client_host, bucket=bucket, limit=limit):
            raise ApplicationError(
                code="RATE_LIMITED",
                message="Too many requests. Please try again later.",
                status_code=429,
            )

    return dependency
