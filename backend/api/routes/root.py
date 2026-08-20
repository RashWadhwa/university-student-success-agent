"""Root service-discovery route."""

from fastapi import APIRouter, Request

from backend.core.config import Settings
from backend.schemas.common import RootResponse

router = APIRouter(tags=["service"])


@router.get("/", response_model=RootResponse, summary="Describe the service")
async def root(request: Request) -> RootResponse:
    settings: Settings = request.app.state.settings
    documentation_url = str(request.url_for("swagger_ui_html")) if settings.docs_enabled else None
    return RootResponse(
        name=settings.app_name,
        version=settings.app_version,
        environment=settings.environment.value,
        documentation_url=documentation_url,
    )
