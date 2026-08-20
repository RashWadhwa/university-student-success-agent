"""Provider- and persistence-neutral RAG value objects."""

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

RetrievalSource = Literal["semantic", "keyword"]


class CorpusTier(StrEnum):
    """Provenance tier for indexed public guidance."""

    PRIMARY = "primary"
    SECONDARY = "secondary"


class AuthorityScope(StrEnum):
    """Whether a source is binding institution policy or contextual guidance."""

    INSTITUTION_POLICY = "institution_policy"
    SECTOR_GUIDANCE = "sector_guidance"


@dataclass(frozen=True, slots=True)
class DocumentIndexMetadata:
    title: str | None = None
    document_type: str | None = "policy"
    institution: str | None = None
    effective_date: date | None = None
    review_date: date | None = None
    version: str | None = None
    source: str | None = None
    corpus_tier: CorpusTier = CorpusTier.PRIMARY
    authority_scope: AuthorityScope = AuthorityScope.INSTITUTION_POLICY
    retrieval_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SearchFilters:
    document_type: str | None = None
    institution: str | None = None
    source: str | None = None
    version: str | None = None
    effective_on_or_before: date | None = None
    effective_on_or_after: date | None = None
    corpus_tier: CorpusTier | None = CorpusTier.PRIMARY
    authority_scope: AuthorityScope | None = AuthorityScope.INSTITUTION_POLICY


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
    corpus_tier: CorpusTier = CorpusTier.PRIMARY
    authority_scope: AuthorityScope = AuthorityScope.INSTITUTION_POLICY


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
