"""Common API response schemas."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    """Base schema that rejects undocumented fields."""

    model_config = ConfigDict(extra="forbid")


class RootResponse(StrictModel):
    """Service discovery response."""

    name: str
    version: str
    environment: str
    status: Literal["running"] = "running"
    documentation_url: str | None = None


class HealthResponse(StrictModel):
    """Liveness response."""

    status: Literal["ok"] = "ok"
    service: str
    version: str
    timestamp: datetime
    uptime_seconds: float = Field(ge=0)


class ReadinessResponse(StrictModel):
    """Readiness response with individual dependency checks."""

    status: Literal["ready"] = "ready"
    checks: dict[str, Literal["ok"]]
    timestamp: datetime


class ErrorBody(StrictModel):
    """Machine-readable error information."""

    code: str
    message: str
    details: Any | None = None


class ErrorResponse(StrictModel):
    """Consistent error envelope."""

    error: ErrorBody
    request_id: str
