"""Strict schemas exchanged between coordinator, specialists, tools, and verifier."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from backend.agents.types import (
    AgentName,
    PlanComplexity,
    RequestIntent,
    ToolName,
    ToolPermission,
    WorkflowMode,
    WorkflowStatus,
)
from backend.ask.types import Evidence
from backend.rag.types import AuthorityScope, CorpusTier, RetrievalSource
from backend.schemas.common import StrictModel
from backend.schemas.retrieval import RetrievalFilters

EvidenceId = Annotated[str, StringConstraints(pattern=r"^E[1-9][0-9]*$")]
SafeText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class AgentTask(StrictModel):
    agent: AgentName
    objective: SafeText


class ExecutionPlan(StrictModel):
    intent: str = Field(min_length=1, max_length=200)
    intents: list[RequestIntent] = Field(min_length=1, max_length=5)
    complexity: PlanComplexity
    tasks: list[AgentTask] = Field(default_factory=list, max_length=10)
    use_baseline: bool
    requires_verification: bool = True
    requires_human_support: bool = False

    @model_validator(mode="after")
    def validate_plan_shape(self) -> ExecutionPlan:
        names = [task.agent for task in self.tasks]
        if len(names) != len(set(names)):
            raise ValueError("agent tasks must be unique")
        if self.use_baseline and self.tasks:
            raise ValueError("baseline plans cannot include specialist tasks")
        if not self.use_baseline and not self.tasks:
            raise ValueError("agentic plans require specialist tasks")
        if self.complexity is PlanComplexity.SINGLE_STEP and not self.use_baseline:
            raise ValueError("single-step plans must use the baseline")
        return self


class CoordinatorInput(StrictModel):
    question: str = Field(min_length=1, max_length=10_000)
    top_k: int = Field(ge=1, le=100)
    filters: RetrievalFilters = Field(default_factory=RetrievalFilters)


class CoordinatorDecision(StrictModel):
    scope_supported: bool
    scope_reason: str | None = Field(default=None, max_length=500)
    plan: ExecutionPlan | None = None

    @model_validator(mode="after")
    def plan_matches_scope(self) -> CoordinatorDecision:
        if self.scope_supported != (self.plan is not None):
            raise ValueError("supported coordinator decisions require a plan")
        return self


class AgentEvidence(StrictModel):
    citation_id: EvidenceId
    chunk_id: str = Field(min_length=1, max_length=128)
    document_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=512)
    section: str | None = Field(default=None, max_length=512)
    page: int = Field(ge=1)
    content: str = Field(min_length=1, max_length=10_000)
    score: float = Field(ge=0.0, le=1.0)
    evidence_score: float = Field(ge=0.0, le=1.0)
    retrieval_sources: list[RetrievalSource] = Field(min_length=1, max_length=2)
    version: str | None = Field(default=None, max_length=100)
    effective_date: date | None = None
    source: str | None = Field(default=None, max_length=2048)
    institution: str | None = Field(default=None, max_length=255)
    corpus_tier: CorpusTier = CorpusTier.PRIMARY
    authority_scope: AuthorityScope = AuthorityScope.INSTITUTION_POLICY

    @classmethod
    def from_domain(cls, item: Evidence, *, maximum_content_chars: int) -> AgentEvidence:
        return cls(
            citation_id=item.citation_id,
            chunk_id=item.chunk_id,
            document_id=item.document_id,
            title=item.title,
            section=item.section,
            page=item.page,
            content=item.content[:maximum_content_chars],
            score=item.score,
            evidence_score=item.evidence_score,
            retrieval_sources=list(item.retrieval_sources),
            version=item.version,
            effective_date=item.effective_date,
            source=item.source,
            institution=item.institution,
            corpus_tier=item.corpus_tier,
            authority_scope=item.authority_scope,
        )

    def to_domain(self) -> Evidence:
        return Evidence(
            citation_id=self.citation_id,
            chunk_id=self.chunk_id,
            document_id=self.document_id,
            title=self.title,
            section=self.section,
            page=self.page,
            content=self.content,
            score=self.score,
            evidence_score=self.evidence_score,
            retrieval_sources=tuple(self.retrieval_sources),
            version=self.version,
            effective_date=self.effective_date,
            source=self.source,
            institution=self.institution,
            corpus_tier=self.corpus_tier,
            authority_scope=self.authority_scope,
        )


class RetrievalAgentInput(StrictModel):
    query: str = Field(min_length=1, max_length=10_000)
    objective: SafeText
    top_k: int = Field(ge=1, le=100)
    filters: RetrievalFilters = Field(default_factory=RetrievalFilters)


class RetrievalAgentOutput(StrictModel):
    evidence: list[AgentEvidence] = Field(max_length=20)
    retrieved_count: int = Field(ge=0)
    sufficient: bool
    conflicting: bool
    reasons: list[SafeText] = Field(default_factory=list, max_length=10)
    max_score: float = Field(ge=0.0, le=1.0)
    older_versions_omitted: bool = False


class CitedFinding(StrictModel):
    statement: SafeText
    citation_ids: list[EvidenceId] = Field(min_length=1, max_length=10)

    @field_validator("citation_ids")
    @classmethod
    def citations_must_be_unique(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("citation identifiers must be unique")
        return values


class DeadlineFinding(CitedFinding):
    deadline: str = Field(min_length=1, max_length=200)


class PolicyConflict(StrictModel):
    description: SafeText
    citation_ids: list[EvidenceId] = Field(min_length=2, max_length=10)


class PolicyAnalysisOutput(StrictModel):
    findings: list[CitedFinding] = Field(default_factory=list, max_length=15)
    deadlines: list[DeadlineFinding] = Field(default_factory=list, max_length=10)
    evidence_requirements: list[CitedFinding] = Field(default_factory=list, max_length=10)
    exceptions: list[CitedFinding] = Field(default_factory=list, max_length=10)
    conflicts: list[PolicyConflict] = Field(default_factory=list, max_length=10)
    uncertainties: list[SafeText] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def require_policy_content(self) -> PolicyAnalysisOutput:
        if not (
            self.findings
            or self.deadlines
            or self.evidence_requirements
            or self.exceptions
            or self.conflicts
            or self.uncertainties
        ):
            raise ValueError("policy analysis cannot be empty")
        return self


class PolicyAnalystInput(StrictModel):
    objective: SafeText
    evidence: list[AgentEvidence] = Field(min_length=1, max_length=20)


class SupportAction(StrictModel):
    priority: int = Field(ge=1, le=20)
    action: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=1000)
    basis: Literal["policy", "practical"]
    citation_ids: list[EvidenceId] = Field(default_factory=list, max_length=10)


class StudentSupportOutput(StrictModel):
    answer: str = Field(min_length=1, max_length=5000)
    actions: list[SupportAction] = Field(default_factory=list, max_length=10)
    citation_ids: list[EvidenceId] = Field(min_length=1, max_length=20)
    limitations: list[SafeText] = Field(default_factory=list, max_length=10)
    requires_human_support: bool
    human_support_reason: str | None = Field(default=None, max_length=1000)


class StudentSupportInput(StrictModel):
    intent: str = Field(min_length=1, max_length=200)
    policy_analysis: PolicyAnalysisOutput
    requires_individual_decision: bool = False


class VerificationOutput(StrictModel):
    valid: bool
    citation_ids: list[EvidenceId] = Field(default_factory=list, max_length=20)
    failure_categories: list[str] = Field(default_factory=list, max_length=20)


class AgentAuditEvent(StrictModel):
    request_id: str = Field(min_length=1, max_length=128)
    agent_name: AgentName
    event_type: str = Field(pattern=r"^[a-z][a-z0-9_:-]{0,99}$")
    tool_name: ToolName | None = None
    permission_level: ToolPermission | None = None
    decision: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_:-]{0,99}$")
    duration_ms: float = Field(default=0.0, ge=0.0)
    success: bool
    failure_category: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_:-]{0,99}$")


class ToolInvocationRecord(StrictModel):
    agent_name: AgentName
    tool_name: ToolName
    permission_level: ToolPermission
    authorised: bool
    success: bool


class VerifierInput(StrictModel):
    evidence: list[AgentEvidence] = Field(min_length=1, max_length=20)
    policy_analysis: PolicyAnalysisOutput
    support_output: StudentSupportOutput
    tool_invocations: list[ToolInvocationRecord] = Field(default_factory=list, max_length=20)


class AgenticComparisonMetadata(StrictModel):
    workflow_mode: WorkflowMode
    agents_used: list[AgentName]
    tool_calls: int = Field(ge=0)
    retrieval_count: int = Field(ge=0)
    citation_count: int = Field(ge=0)
    confidence: str
    requires_human_support: bool
    duration_ms: float = Field(ge=0.0)
    provider_calls: int = Field(ge=0)
    verification_passed: bool
    terminal_state: WorkflowStatus
