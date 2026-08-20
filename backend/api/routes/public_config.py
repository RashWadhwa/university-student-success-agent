"""Safe public configuration for institution-neutral clients."""

from typing import Annotated

from fastapi import APIRouter, Depends

from backend.api.dependencies import get_primary_institution_name
from backend.schemas.public_config import PublicConfigResponse

router = APIRouter(prefix="/config", tags=["configuration"])


@router.get("/public", response_model=PublicConfigResponse)
async def public_config(
    primary_institution: Annotated[str, Depends(get_primary_institution_name)],
) -> PublicConfigResponse:
    return PublicConfigResponse(primary_institution_name=primary_institution)
