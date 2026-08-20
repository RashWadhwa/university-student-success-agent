"""Typed API schemas for document ingestion."""

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from backend.schemas.common import StrictModel


class PageResponse(StrictModel):
    """Page text and source metadata returned after ingestion."""

    page_number: int = Field(ge=1)
    text: str
    char_count: int = Field(ge=0)
    metadata: dict[str, Any]


class ChunkResponse(StrictModel):
    """Retrieval-ready chunk with page and heading provenance."""

    id: str
    index: int = Field(ge=0)
    text: str
    char_count: int = Field(ge=1)
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    heading: str | None = None
    metadata: dict[str, Any]


class DocumentResponse(StrictModel):
    """Complete document-ingestion result."""

    id: str
    original_filename: str
    stored_filename: str
    media_type: Literal["application/pdf"]
    size_bytes: int = Field(gt=0)
    checksum_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    page_count: int = Field(gt=0)
    chunk_count: int = Field(gt=0)
    created_at: datetime
    metadata: dict[str, Any]
    pages: list[PageResponse]
    chunks: list[ChunkResponse]


class DocumentUploadResponse(StrictModel):
    """Response envelope for a newly ingested document."""

    status: Literal["ingested"] = "ingested"
    document: DocumentResponse
