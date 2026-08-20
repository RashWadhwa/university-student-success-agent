"""Liveness and readiness endpoints."""

from datetime import UTC, datetime

from fastapi import APIRouter, Request

from backend.core.config import Settings
from backend.core.exceptions import ServiceNotReadyError
from backend.database.manager import DatabaseManager, DatabaseReadiness
from backend.llm.base import LLMProvider
from backend.schemas.common import HealthResponse, ReadinessResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Check process liveness")
async def health(request: Request) -> HealthResponse:
    settings: Settings = request.app.state.settings
    now = datetime.now(UTC)
    started_at: datetime = request.app.state.started_at
    return HealthResponse(
        service=settings.app_name,
        version=settings.app_version,
        timestamp=now,
        uptime_seconds=max(0.0, (now - started_at).total_seconds()),
    )


@router.get("/ready", response_model=ReadinessResponse, summary="Check service readiness")
async def ready(request: Request) -> ReadinessResponse:
    provider: LLMProvider | None = getattr(request.app.state, "llm_provider", None)
    document_manager = getattr(request.app.state, "document_manager", None)
    database_manager: DatabaseManager | None = getattr(request.app.state, "database_manager", None)
    database_readiness = (
        await database_manager.check_readiness()
        if database_manager is not None
        else DatabaseReadiness(database=False, pgvector=False)
    )
    checks = {
        "application": "ok" if request.app.state.ready else "failed",
        "configuration": "ok" if request.app.state.settings is not None else "failed",
        "llm_provider": ("ok" if provider is not None and provider.is_configured else "failed"),
        "document_manager": "ok" if document_manager is not None else "failed",
        "database": "ok" if database_readiness.database else "failed",
        "pgvector": "ok" if database_readiness.pgvector else "failed",
    }
    failed_checks = [name for name, status in checks.items() if status != "ok"]
    if failed_checks:
        raise ServiceNotReadyError(details={"failed_checks": failed_checks})

    return ReadinessResponse(
        checks={name: "ok" for name in checks},
        timestamp=datetime.now(UTC),
    )
