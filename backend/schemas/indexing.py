"""Typed document indexing request and response schemas."""

from datetime import date, datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from backend.rag.types import AuthorityScope, CorpusTier, DocumentIndexMetadata, IndexingResult
from backend.schemas.common import StrictModel


class DocumentIndexRequest(StrictModel):
    title: str | None = Field(default=None, min_length=1, max_length=512)
    document_type: str | None = Field(default="policy", min_length=1, max_length=100)
    institution: str | None = Field(default=None, min_length=1, max_length=255)
    effective_date: date | None = None
    review_date: date | None = None
    version: str | None = Field(default=None, min_length=1, max_length=100)
    source: str | None = Field(default=None, min_length=1, max_length=2048)
    corpus_tier: CorpusTier = CorpusTier.PRIMARY
    authority_scope: AuthorityScope = AuthorityScope.INSTITUTION_POLICY

    @field_validator("institution")
    @classmethod
    def normalise_institution(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("institution must not be blank")
        return cleaned

    @model_validator(mode="after")
    def validate_source_classification(self) -> "DocumentIndexRequest":
        expected = (
            AuthorityScope.INSTITUTION_POLICY
            if self.corpus_tier is CorpusTier.PRIMARY
            else AuthorityScope.SECTOR_GUIDANCE
        )
        if self.authority_scope is not expected:
            raise ValueError("corpus tier and authority scope are inconsistent")
        if self.corpus_tier is CorpusTier.SECONDARY and self.institution is None:
            raise ValueError("secondary guidance requires an explicit publisher")
        return self

    def to_domain(self, *, default_institution: str | None = None) -> DocumentIndexMetadata:
        values = self.model_dump()
        values["institution"] = self.institution or default_institution
        return DocumentIndexMetadata(**values)


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
