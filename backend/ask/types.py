"""Provider-neutral value objects for the grounded ask workflow."""

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from backend.rag.types import AuthorityScope, CorpusTier, RetrievalSource, SearchFilters


class AskOutcome(StrEnum):
    ANSWERED = "answered"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    UNSUPPORTED = "unsupported"
    TEMPORARILY_UNAVAILABLE = "temporarily_unavailable"
    VERIFICATION_FAILED = "verification_failed"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True, slots=True)
class AskQuery:
    question: str
    top_k: int
    filters: SearchFilters
    session_id: str | None = None


@dataclass(frozen=True, slots=True)
class ScopeAssessment:
    supported: bool
    reason: str | None = None
    requires_individual_decision: bool = False


@dataclass(frozen=True, slots=True)
class Evidence:
    citation_id: str
    chunk_id: str
    document_id: str
    title: str
    section: str | None
    page: int
    content: str
    score: float
    evidence_score: float
    retrieval_sources: tuple[RetrievalSource, ...]
    version: str | None
    effective_date: date | None
    source: str | None
    institution: str | None = None
    corpus_tier: CorpusTier = CorpusTier.PRIMARY
    authority_scope: AuthorityScope = AuthorityScope.INSTITUTION_POLICY


@dataclass(frozen=True, slots=True)
class EvidenceAssessment:
    evidence: tuple[Evidence, ...]
    sufficient: bool
    conflicting: bool
    max_score: float
    reasons: tuple[str, ...] = ()
    older_versions_omitted: bool = False


@dataclass(frozen=True, slots=True)
class RecommendedAction:
    priority: int
    action: str
    reason: str
    citation_ids: tuple[str, ...] = ()
    kind: str = "practical"


@dataclass(frozen=True, slots=True)
class Citation:
    citation_id: str
    document_id: str
    chunk_id: str
    document_title: str
    section: str | None
    page: int
    source: str | None
    excerpt: str
    version: str | None
    effective_date: date | None
    retrieval_sources: tuple[RetrievalSource, ...]
    institution: str | None = None
    corpus_tier: CorpusTier = CorpusTier.PRIMARY
    authority_scope: AuthorityScope = AuthorityScope.INSTITUTION_POLICY


@dataclass(frozen=True, slots=True)
class AskResult:
    outcome: AskOutcome
    answer: str
    recommended_actions: tuple[RecommendedAction, ...]
    citations: tuple[Citation, ...]
    confidence: Confidence
    limitations: tuple[str, ...]
    requires_human_support: bool
    human_support_reason: str | None
    request_id: str
    retrieved_count: int
    evidence_count: int
    citation_verification_passed: bool
    evaluation: dict[str, float | int | bool | str] = field(default_factory=dict)
