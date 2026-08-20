"""Typed hybrid retrieval request and citation-ready response schemas."""

from datetime import date

from pydantic import Field, field_validator, model_validator

from backend.rag.types import AuthorityScope, CorpusTier, FusedRetrievalResult, SearchFilters
from backend.schemas.common import StrictModel


class RetrievalFilters(StrictModel):
    document_type: str | None = Field(default=None, min_length=1, max_length=100)
    institution: str | None = Field(default=None, min_length=1, max_length=255)
    source: str | None = Field(default=None, min_length=1, max_length=2048)
    version: str | None = Field(default=None, min_length=1, max_length=100)
    effective_on_or_before: date | None = None
    effective_on_or_after: date | None = None
    corpus_tier: CorpusTier | None = CorpusTier.PRIMARY
    authority_scope: AuthorityScope | None = AuthorityScope.INSTITUTION_POLICY

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
    def validate_date_range(self) -> "RetrievalFilters":
        if (
            self.effective_on_or_before is not None
            and self.effective_on_or_after is not None
            and self.effective_on_or_after > self.effective_on_or_before
        ):
            raise ValueError("effective date range is invalid")
        allowed_pair = (
            self.corpus_tier is CorpusTier.PRIMARY
            and self.authority_scope is AuthorityScope.INSTITUTION_POLICY
        ) or (
            self.corpus_tier is CorpusTier.SECONDARY
            and self.authority_scope is AuthorityScope.SECTOR_GUIDANCE
        )
        if not allowed_pair and not (self.corpus_tier is None and self.authority_scope is None):
            raise ValueError("corpus tier and authority scope are inconsistent")
        if self.corpus_tier is CorpusTier.SECONDARY and self.institution is None:
            raise ValueError("secondary guidance requires an explicit publisher filter")
        return self

    def to_domain(self, *, default_institution: str | None = None) -> SearchFilters:
        values = self.model_dump()
        values["institution"] = self.institution or default_institution
        return SearchFilters(**values)


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
    corpus_tier: CorpusTier
    authority_scope: AuthorityScope


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
                    corpus_tier=item.candidate.corpus_tier,
                    authority_scope=item.candidate.authority_scope,
                ),
            )
            for item in results
        ]
        return cls(query=query, result_count=len(items), results=items)
