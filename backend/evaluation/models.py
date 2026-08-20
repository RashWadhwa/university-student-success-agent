"""Strict bounded domain models for reproducible Stage 7 evaluation."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator

from backend.rag.types import AuthorityScope, CorpusTier
from backend.schemas.common import StrictModel

BoundedRationale = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]
BoundedCriterion = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]
EvidenceText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1000),
]


class EvaluationWorkflow(StrEnum):
    BASELINE = "baseline"
    AGENTIC = "agentic"
    BOTH = "both"


class EvaluationCitation(StrictModel):
    citation_id: str = Field(min_length=1, max_length=32)
    title: str = Field(min_length=1, max_length=512)
    section: str | None = Field(default=None, max_length=512)
    page: int = Field(ge=1)
    version: str | None = Field(default=None, max_length=100)
    institution: str | None = Field(default=None, max_length=255)
    corpus_tier: CorpusTier = CorpusTier.PRIMARY
    authority_scope: AuthorityScope = AuthorityScope.INSTITUTION_POLICY


class EvaluationInput(StrictModel):
    """Minimum synthetic material needed by an independent semantic judge."""

    question: str = Field(min_length=1, max_length=2000)
    expected_criteria: list[BoundedCriterion] = Field(min_length=1, max_length=10)
    answer: str = Field(min_length=1, max_length=5000)
    evidence: list[EvidenceText] = Field(default_factory=list, max_length=5)
    citations: list[EvaluationCitation] = Field(default_factory=list, max_length=10)
    workflow_mode: Literal["baseline", "agentic"]
    citations_verified: bool
    requires_human_support: bool


class EvaluationOutput(StrictModel):
    """Concise judge scores; reasoning summaries are not chain-of-thought."""

    groundedness: float = Field(ge=0.0, le=1.0)
    policy_correctness: float = Field(ge=0.0, le=1.0)
    completeness: float = Field(ge=0.0, le=1.0)
    helpfulness: float = Field(ge=0.0, le=1.0)
    escalation_correct: bool
    reasoning_summary: BoundedRationale


class EvaluationCase(StrictModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,63}$")
    category: str = Field(min_length=1, max_length=100)
    question: str = Field(min_length=1, max_length=2000)
    expected_criteria: list[BoundedCriterion] = Field(min_length=1, max_length=10)
    relevant_titles: list[str] = Field(default_factory=list, max_length=10)
    expected_escalation: bool
    expected_confidence: Literal["low", "medium", "high"] | None = None
    expected_agents: list[str] = Field(default_factory=list, max_length=5)
    minimum_tool_calls: int = Field(default=0, ge=0, le=10)
    deterministic_only: bool = False

    @field_validator("relevant_titles", "expected_agents")
    @classmethod
    def unique_values(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("evaluation expectations must be unique")
        return values


class DeterministicScores(StrictModel):
    recall_at_k: float = Field(ge=0.0, le=1.0)
    precision_at_k: float = Field(ge=0.0, le=1.0)
    reciprocal_rank: float = Field(ge=0.0, le=1.0)
    hit_rate: float = Field(ge=0.0, le=1.0)
    citation_validity: float = Field(ge=0.0, le=1.0)
    escalation_correctness: float = Field(ge=0.0, le=1.0)
    structured_output_validity: float = Field(ge=0.0, le=1.0)
    confidence_calibration: float = Field(ge=0.0, le=1.0)
    agent_routing: float | None = Field(default=None, ge=0.0, le=1.0)
    tool_selection: float | None = Field(default=None, ge=0.0, le=1.0)


class EvaluationCaseResult(StrictModel):
    case_id: str
    category: str
    workflow_mode: Literal["baseline", "agentic"]
    status: Literal["passed", "partial", "failed"]
    deterministic: DeterministicScores | None = None
    judge: EvaluationOutput | None = None
    latency_ms: float = Field(ge=0.0)
    provider_calls: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    request_id: str | None = None
    trace_id: str | None = None
    error_category: str | None = None


class EvaluationAggregate(StrictModel):
    workflow_mode: Literal["baseline", "agentic"]
    case_count: int = Field(ge=0)
    passed_count: int = Field(ge=0)
    partial_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    deterministic: dict[str, float]
    judge: dict[str, float]
    mean_latency_ms: float = Field(ge=0.0)
    total_provider_calls: int = Field(ge=0)
    total_tool_calls: int = Field(ge=0)


class EvaluationRunResult(StrictModel):
    dataset: str
    workflow: EvaluationWorkflow
    case_count: int = Field(ge=1)
    judge_calls: int = Field(ge=0)
    status: Literal["completed", "partial", "failed"]
    results: list[EvaluationCaseResult]
    summaries: list[EvaluationAggregate]
    winner: Literal["baseline", "agentic", "tie", "not_comparable"]
