"""Typed internal document, page, and chunk records."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DocumentModel(BaseModel):
    """Base model for persisted document-domain data."""

    model_config = ConfigDict(extra="forbid")


class PageRecord(DocumentModel):
    """Extracted text and source metadata for one PDF page."""

    page_number: int = Field(ge=1)
    text: str
    char_count: int = Field(ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChunkRecord(DocumentModel):
    """A retrieval-ready text chunk with source provenance."""

    id: str
    index: int = Field(ge=0)
    text: str = Field(min_length=1)
    char_count: int = Field(ge=1)
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    heading: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentRecord(DocumentModel):
    """Complete persisted result of one successful ingestion."""

    id: str
    original_filename: str
    safe_filename: str | None = None
    stored_filename: str
    media_type: str
    size_bytes: int = Field(gt=0)
    checksum_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    page_count: int = Field(gt=0)
    chunk_count: int = Field(gt=0)
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
    pages: list[PageRecord]
    chunks: list[ChunkRecord]

    @model_validator(mode="after")
    def default_safe_filename(self) -> "DocumentRecord":
        """Load Stage 3 sidecars written before the explicit safe-name field."""

        if self.safe_filename is None:
            self.safe_filename = self.original_filename
        return self
