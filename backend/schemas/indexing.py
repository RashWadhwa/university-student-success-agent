"""Typed document indexing request and response schemas."""

from datetime import date, datetime
from typing import Literal

from pydantic import Field

from backend.rag.types import DocumentIndexMetadata, IndexingResult
from backend.schemas.common import StrictModel


class DocumentIndexRequest(StrictModel):
    title: str | None = Field(default=None, min_length=1, max_length=512)
    document_type: str | None = Field(default="policy", min_length=1, max_length=100)
    institution: str | None = Field(default=None, min_length=1, max_length=255)
    effective_date: date | None = None
    review_date: date | None = None
    version: str | None = Field(default=None, min_length=1, max_length=100)
    source: str | None = Field(default=None, min_length=1, max_length=2048)

    def to_domain(self) -> DocumentIndexMetadata:
        return DocumentIndexMetadata(**self.model_dump())


class DocumentIndexResponse(StrictModel):
    document_id: str
    status: Literal["indexed", "already_indexed"]
    chunk_count: int = Field(ge=0)
    embedding_model: str
    indexed_at: datetime | None = None

    @classmethod
    def from_result(cls, result: IndexingResult) -> "DocumentIndexResponse":
        return cls(
            document_id=result.document_id,
            status=result.status,
            chunk_count=result.chunk_count,
            embedding_model=result.embedding_model,
            indexed_at=result.indexed_at,
        )
