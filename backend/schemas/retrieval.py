"""Typed hybrid retrieval request and citation-ready response schemas."""

from datetime import date

from pydantic import Field, field_validator, model_validator

from backend.rag.types import FusedRetrievalResult, SearchFilters
from backend.schemas.common import StrictModel


class RetrievalFilters(StrictModel):
    document_type: str | None = Field(default=None, min_length=1, max_length=100)
    institution: str | None = Field(default=None, min_length=1, max_length=255)
    source: str | None = Field(default=None, min_length=1, max_length=2048)
    version: str | None = Field(default=None, min_length=1, max_length=100)
    effective_on_or_before: date | None = None
    effective_on_or_after: date | None = None

    @model_validator(mode="after")
    def validate_date_range(self) -> "RetrievalFilters":
        if (
            self.effective_on_or_before is not None
            and self.effective_on_or_after is not None
            and self.effective_on_or_after > self.effective_on_or_before
        ):
            raise ValueError("effective date range is invalid")
        return self

    def to_domain(self) -> SearchFilters:
        return SearchFilters(**self.model_dump())


class RetrievalSearchRequest(StrictModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)
    minimum_score: float = Field(default=0.0, ge=0.0, le=1.0)
    prefer_recent: bool = False
    filters: RetrievalFilters = Field(default_factory=RetrievalFilters)

    @field_validator("query")
    @classmethod
    def query_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("query must not be blank")
        return cleaned


class RetrievalResultMetadata(StrictModel):
    document_type: str | None = None
    institution: str | None = None
    version: str | None = None
    effective_date: date | None = None
    review_date: date | None = None
    source: str | None = None


class RetrievalResult(StrictModel):
    chunk_id: str
    document_id: str
    title: str
    section: str | None = None
    page: int = Field(ge=1)
    content: str
    score: float = Field(ge=0.0, le=1.0)
    evidence_score: float = Field(ge=0.0, le=1.0)
    retrieval_sources: list[str]
    source_scores: dict[str, float]
    metadata: RetrievalResultMetadata


class RetrievalSearchResponse(StrictModel):
    query: str
    result_count: int = Field(ge=0)
    results: list[RetrievalResult]

    @classmethod
    def from_results(
        cls,
        query: str,
        results: list[FusedRetrievalResult],
    ) -> "RetrievalSearchResponse":
        items = [
            RetrievalResult(
                chunk_id=item.candidate.chunk_id,
                document_id=item.candidate.document_id,
                title=item.candidate.title,
                section=item.candidate.section,
                page=item.candidate.page,
                content=item.candidate.content,
                score=item.score,
                evidence_score=item.evidence_score,
                retrieval_sources=item.retrieval_sources,
                source_scores=item.source_scores,
                metadata=RetrievalResultMetadata(
                    document_type=item.candidate.document_type,
                    institution=item.candidate.institution,
                    version=item.candidate.version,
                    effective_date=item.candidate.effective_date,
                    review_date=item.candidate.review_date,
                    source=item.candidate.source,
                ),
            )
            for item in results
        ]
        return cls(query=query, result_count=len(items), results=items)
