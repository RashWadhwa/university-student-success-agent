"""Credential-free system component status contracts."""

from typing import Literal

from backend.schemas.common import StrictModel

ComponentState = Literal["operational", "unavailable", "disabled", "unconfigured"]


class ComponentStatus(StrictModel):
    status: ComponentState
    provider: str | None = None
    model: str | None = None


class SystemStatusResponse(StrictModel):
    fastapi: ComponentStatus
    database: ComponentStatus
    pgvector: ComponentStatus
    primary_llm: ComponentStatus
    langfuse: ComponentStatus
    evaluation: ComponentStatus
