"""Typed request and response schemas for the grounded ask workflow."""

from datetime import date

from pydantic import Field, field_validator

from backend.ask.types import AskOutcome, AskResult, Confidence
from backend.rag.types import RetrievalSource
from backend.schemas.common import StrictModel
from backend.schemas.retrieval import RetrievalFilters


class AskRequest(StrictModel):
    question: str = Field(min_length=1, max_length=10_000)
    top_k: int | None = Field(default=None, ge=1, le=100)
    filters: RetrievalFilters = Field(default_factory=RetrievalFilters)
    session_id: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("question")
    @classmethod
    def question_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("question must not be blank")
        return cleaned

    @field_validator("session_id")
    @classmethod
    def session_id_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("session_id must not be blank")
        return cleaned


class AskRecommendedAction(StrictModel):
    priority: int = Field(ge=1)
    action: str
    reason: str


class AskCitation(StrictModel):
    citation_id: str
    document_id: str
    chunk_id: str
    document_title: str
    section: str | None = None
    page: int = Field(ge=1)
    source: str | None = None
    excerpt: str
    version: str | None = None
    effective_date: date | None = None
    retrieval_sources: list[RetrievalSource]


class AskEvaluationMetadata(StrictModel):
    retrieved_count: int = Field(ge=0)
    evidence_count: int = Field(ge=0)
    retrieval_strength: float = Field(ge=0.0, le=1.0)
    citation_count: int = Field(ge=0)
    citation_verification_passed: bool


class AskResponse(StrictModel):
    outcome: AskOutcome
    answer: str
    recommended_actions: list[AskRecommendedAction]
    citations: list[AskCitation]
    confidence: Confidence
    limitations: list[str]
    requires_human_support: bool
    human_support_reason: str | None = None
    request_id: str
    evaluation: AskEvaluationMetadata

    @classmethod
    def from_result(cls, result: AskResult) -> "AskResponse":
        return cls(
            outcome=result.outcome.value,
            answer=result.answer,
            recommended_actions=[
                AskRecommendedAction(
                    priority=item.priority,
                    action=item.action,
                    reason=item.reason,
                )
                for item in result.recommended_actions
            ],
            citations=[
                AskCitation(
                    citation_id=item.citation_id,
                    document_id=item.document_id,
                    chunk_id=item.chunk_id,
                    document_title=item.document_title,
                    section=item.section,
                    page=item.page,
                    source=item.source,
                    excerpt=item.excerpt,
                    version=item.version,
                    effective_date=item.effective_date,
                    retrieval_sources=list(item.retrieval_sources),
                )
                for item in result.citations
            ],
            confidence=result.confidence.value,
            limitations=list(result.limitations),
            requires_human_support=result.requires_human_support,
            human_support_reason=result.human_support_reason,
            request_id=result.request_id,
            evaluation=AskEvaluationMetadata(
                retrieved_count=result.retrieved_count,
                evidence_count=result.evidence_count,
                retrieval_strength=float(result.evaluation.get("retrieval_strength", 0.0)),
                citation_count=len(result.citations),
                citation_verification_passed=result.citation_verification_passed,
            ),
        )
