"""Provider- and persistence-neutral RAG value objects."""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal

RetrievalSource = Literal["semantic", "keyword"]


@dataclass(frozen=True, slots=True)
class DocumentIndexMetadata:
    title: str | None = None
    document_type: str | None = "policy"
    institution: str | None = None
    effective_date: date | None = None
    review_date: date | None = None
    version: str | None = None
    source: str | None = None


@dataclass(frozen=True, slots=True)
class SearchFilters:
    document_type: str | None = None
    institution: str | None = None
    source: str | None = None
    version: str | None = None
    effective_on_or_before: date | None = None
    effective_on_or_after: date | None = None


@dataclass(frozen=True, slots=True)
class RetrievalCandidate:
    chunk_id: str
    document_id: str
    content: str
    page: int
    section: str | None
    title: str
    document_type: str | None
    institution: str | None
    version: str | None
    effective_date: date | None
    review_date: date | None
    source: str | None
    score: float


@dataclass(slots=True)
class FusedRetrievalResult:
    candidate: RetrievalCandidate
    score: float
    evidence_score: float
    retrieval_sources: list[RetrievalSource] = field(default_factory=list)
    source_scores: dict[RetrievalSource, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class IndexingResult:
    document_id: str
    status: Literal["indexed", "already_indexed"]
    chunk_count: int
    embedding_model: str
    indexed_at: datetime | None
    metadata: dict[str, Any] = field(default_factory=dict)
