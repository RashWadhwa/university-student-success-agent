"""Stable enums and request-scoped state for controlled orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from backend.ask.types import AskResult, Evidence, ScopeAssessment
from backend.rag.types import SearchFilters

if TYPE_CHECKING:
    from backend.agents.models import (
        AgentAuditEvent,
        ExecutionPlan,
        PolicyAnalysisOutput,
        StudentSupportOutput,
    )


class AgentName(StrEnum):
    COORDINATOR = "coordinator"
    RETRIEVAL = "retrieval"
    POLICY_ANALYST = "policy_analyst"
    STUDENT_SUPPORT = "student_support"
    VERIFIER = "verifier"


class ToolName(StrEnum):
    SEARCH_KNOWLEDGE_BASE = "search_knowledge_base"
    GET_DOCUMENT_SECTION = "get_document_section"
    FIND_STUDENT_SERVICE = "find_student_service"
    DRAFT_SUPPORT_EMAIL = "draft_support_email"


class ToolPermission(StrEnum):
    READ = "READ"
    PREPARE = "PREPARE"
    EXECUTE = "EXECUTE"


class WorkflowMode(StrEnum):
    BASELINE_DELEGATED = "baseline_delegated"
    AGENTIC = "agentic"


class WorkflowStatus(StrEnum):
    """Explicit lifecycle with irreversible terminal states."""

    RUNNING = "running"
    COMPLETED = "completed"
    ESCALATED = "escalated"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self is not WorkflowStatus.RUNNING


class PlanComplexity(StrEnum):
    SINGLE_STEP = "single_step"
    MULTI_STEP = "multi_step"


class RequestIntent(StrEnum):
    ASSESSMENT_ISSUE = "assessment_issue"
    EXTENSION = "extension"
    MITIGATING_CIRCUMSTANCES = "mitigating_circumstances"
    REASSESSMENT = "reassessment"
    ACADEMIC_APPEAL = "academic_appeal"


@dataclass(frozen=True, slots=True)
class AgenticAskResult:
    result: AskResult
    workflow_mode: WorkflowMode
    agents_used: tuple[AgentName, ...]
    tool_calls: int
    provider_calls: int
    duration_ms: float
    verification_passed: bool
    terminal_state: WorkflowStatus


@dataclass(slots=True)
class WorkflowState:
    """Ephemeral typed state; never persisted or exposed as a whole."""

    question: str
    top_k: int
    filters: SearchFilters
    request_id: str
    scope: ScopeAssessment | None = None
    plan: ExecutionPlan | None = None
    evidence: tuple[Evidence, ...] = ()
    policy_analysis: PolicyAnalysisOutput | None = None
    support_output: StudentSupportOutput | None = None
    final_response: AskResult | None = None
    audit_events: list[AgentAuditEvent] = field(default_factory=list)
    agents_used: list[AgentName] = field(default_factory=list)
    tool_calls: int = 0
    provider_calls: int = 0
    coordinator_calls: int = 0
    final_verifier_calls: int = 0
    active_agent: AgentName | None = None
    agent_action_signatures: set[str] = field(default_factory=set)
    status: WorkflowStatus = WorkflowStatus.RUNNING
