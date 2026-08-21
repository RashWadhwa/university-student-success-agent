"""Authentication-context endpoint; no token or user identifier is reflected."""

from typing import Annotated

from fastapi import APIRouter, Depends

from backend.auth.dependencies import get_current_principal
from backend.auth.models import ROLE_CAPABILITIES, Principal
from backend.schemas.auth import CurrentUserResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me", response_model=CurrentUserResponse)
async def current_user(
    principal: Annotated[Principal, Depends(get_current_principal)],
) -> CurrentUserResponse:
    return CurrentUserResponse(
        role=principal.role,
        tenant_id=principal.tenant_id,
        capabilities=sorted(ROLE_CAPABILITIES[principal.role], key=lambda item: item.value),
    )
