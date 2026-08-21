"""Strict public schemas for distilled semantic memory."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field, field_validator

from backend.schemas.common import StrictModel


class MemoryType(StrEnum):
    PREFERENCE = "preference"
    CASE_SUMMARY = "case_summary"
    ONGOING_ACTION = "ongoing_action"
    ACCESSIBILITY_PREFERENCE = "accessibility_preference"
    INSTITUTIONAL_CONTEXT = "institutional_context"


class MemoryCreateRequest(StrictModel):
    memory_type: MemoryType
    fact: str = Field(min_length=1, max_length=2000)
    consent: bool
    durable: bool
    consent_scope: str = Field(default="future_support", min_length=1, max_length=50)
    source_type: str = Field(default="user_provided", pattern=r"^(user_provided|case_update)$")
    source_reference: str | None = Field(default=None, max_length=255)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    case_reference: str | None = Field(default=None, max_length=100)
    supersedes: UUID | None = None

    @field_validator("fact")
    @classmethod
    def reject_transcripts(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        markers = ("user:", "assistant:", "system:", "### conversation", "chat transcript")
        if any(marker in cleaned.casefold() for marker in markers):
            raise ValueError("raw conversation transcripts cannot be stored as memory")
        return cleaned


class MemoryResponse(StrictModel):
    memory_id: UUID
    memory_type: MemoryType
    fact: str
    source_type: str
    source_reference: str | None
    confidence: float
    consent_scope: str
    retention_category: str
    case_reference: str | None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    superseded_by: UUID | None
    is_active: bool


class MemoryListResponse(StrictModel):
    items: list[MemoryResponse]
    count: int = Field(ge=0)


class MemoryDeleteResponse(StrictModel):
    deleted: int = Field(ge=0)
