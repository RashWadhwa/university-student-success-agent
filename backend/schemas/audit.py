"""Safe audit response schemas; payload content is intentionally impossible."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from backend.schemas.common import StrictModel


class AuditEventResponse(StrictModel):
    audit_id: UUID
    request_id: str
    event_type: str
    agent_name: str | None
    tool_name: str | None
    permission_level: str | None
    decision: str | None
    success: bool
    failure_category: str | None
    created_at: datetime


class AuditListResponse(StrictModel):
    items: list[AuditEventResponse]
    count: int = Field(ge=0)
