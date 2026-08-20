"""Bounded state-machine orchestration and safe-failure tests."""

import asyncio
import logging
from datetime import date
from typing import Any

import pytest

from backend.agents.coordinator import Coordinator
from backend.agents.errors import AgentLimitError, AgentWorkflowError
from backend.agents.models import (
    CoordinatorInput,
    PolicyAnalysisOutput,
    RetrievalAgentInput,
    RetrievalAgentOutput,
    StudentSupportOutput,
    VerificationOutput,
)
from backend.agents.registry import AgentRegistry
from backend.agents.service import AgenticAskService
from backend.agents.specialists import (
    PolicyAnalyst,
    RetrievalSpecialist,
    StudentSupportSpecialist,
)
from backend.agents.tools import ToolContext, build_tool_executor
from backend.agents.types import AgentName, WorkflowMode, WorkflowState, WorkflowStatus
from backend.agents.verification import WorkflowVerifier
from backend.ask.models import GroundedAnswerOutput
from backend.ask.service import AskService
from backend.ask.types import AskOutcome
from backend.llm.providers.mock_provider import MockLLMProvider
from backend.rag.types import FusedRetrievalResult, RetrievalCandidate, SearchFilters


class FakeRetrieval:
    def __init__(
        self,
        results: list[FusedRetrievalResult],
        error: Exception | None = None,
    ) -> None:
        self.results = results
        self.error = error

    async def search(self, **kwargs: object) -> list[FusedRetrievalResult]:
        del kwargs
        if self.error is not None:
            raise self.error
        return self.results


def retrieved() -> FusedRetrievalResult:
    return FusedRetrievalResult(
        candidate=RetrievalCandidate(
            chunk_id="chunk-1",
            document_id="doc-1",
            content=(
                "A student affected by illness may use mitigating circumstances. "
                "Academic appeals must be submitted within 10 working days."
            ),
            page=3,
            section="Appeals",
            title="Assessment Policy",
            document_type="academic_policy",
            institution="Example University",
            version="3",
            effective_date=date(2025, 1, 1),
            review_date=None,
            source="https://example.edu/policy",
            score=0.9,
        ),
        score=1.0,
        evidence_score=0.9,
        retrieval_sources=["semantic", "keyword"],
        source_scores={"semantic": 0.9, "keyword": 0.9},
    )


def baseline_output() -> dict[str, Any]:
    return {
        "answer": "The policy describes the mitigating circumstances route.",
        "recommended_actions": [],
        "citations": [{"citation_id": "E1"}],
        "limitations": [],
        "confidence": "medium",
        "requires_human_support": False,
        "human_support_reason": None,
    }


def policy_output() -> dict[str, Any]:
    return {
        "findings": [
            {
                "statement": "Illness may be addressed through mitigating circumstances.",
                "citation_ids": ["E1"],
            }
        ],
        "deadlines": [
            {
                "statement": "Academic appeals must be submitted within 10 working days.",
                "deadline": "10 working days",
                "citation_ids": ["E1"],
            }
        ],
        "evidence_requirements": [],
        "exceptions": [],
        "conflicts": [],
        "uncertainties": [],
    }


def support_output(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "answer": (
            "Use the mitigating circumstances route and review the 10 working day appeal rule."
        ),
        "actions": [
            {
                "priority": 1,
                "action": "Review the mitigating circumstances and appeal procedures.",
                "reason": "The policy identifies these routes.",
                "basis": "policy",
                "citation_ids": ["E1"],
            }
        ],
        "citation_ids": ["E1"],
        "limitations": [],
        "requires_human_support": False,
        "human_support_reason": None,
    }
    values.update(overrides)
    return values


def build_service(
    *,
    retrieval: FakeRetrieval | None = None,
    provider: MockLLMProvider | None = None,
    timeout: float = 0.1,
    retries: int = 0,
    service_task_limit: int = 4,
    tool_limit: int = 4,
    retrieval_specialist: RetrievalSpecialist | None = None,
    verifier: WorkflowVerifier | None = None,
    provider_limit: int = 5,
) -> AgenticAskService:
    active_retrieval = retrieval or FakeRetrieval([retrieved()])
    active_provider = provider or MockLLMProvider(
        structured_responses={
            GroundedAnswerOutput: baseline_output(),
            PolicyAnalysisOutput: policy_output(),
            StudentSupportOutput: support_output(),
        },
        embedding_dimensions=8,
    )
    baseline = AskService(
        retrieval=active_retrieval,  # type: ignore[arg-type]
        provider=active_provider,
        default_top_k=5,
        max_top_k=10,
        minimum_evidence_count=1,
        minimum_retrieval_score=0.5,
        maximum_evidence_chunks=5,
        evidence_max_chars_per_chunk=1000,
        maximum_question_chars=2000,
        citation_excerpt_max_chars=120,
    )
    active_registry = AgentRegistry(timeout_seconds=timeout, maximum_retries=retries)
    tools = build_tool_executor(
        registry=active_registry,
        retrieval=active_retrieval,  # type: ignore[arg-type]
        minimum_evidence_count=1,
        minimum_retrieval_score=0.5,
        maximum_evidence_items=5,
        evidence_max_chars_per_chunk=1000,
    )
    return AgenticAskService(
        baseline=baseline,
        coordinator=Coordinator(registry=active_registry, maximum_tasks=4),
        registry=active_registry,
        retrieval_specialist=retrieval_specialist or RetrievalSpecialist(tools=tools),
        policy_analyst=PolicyAnalyst(provider=active_provider),
        support_specialist=StudentSupportSpecialist(provider=active_provider),
        verifier=verifier or WorkflowVerifier(),
        maximum_tasks=service_task_limit,
        maximum_tool_calls=tool_limit,
        maximum_evidence_items=5,
        maximum_provider_calls=provider_limit,
    )


async def ask(service: AgenticAskService, question: str) -> Any:
    return await service.answer(
        question=question,
        top_k=5,
        filters=SearchFilters(document_type="academic_policy"),
    )


@pytest.mark.asyncio
async def test_simple_question_delegates_to_unchanged_baseline() -> None:
    result = await ask(build_service(), "How do mitigating circumstances work?")

    assert result.workflow_mode is WorkflowMode.BASELINE_DELEGATED
    assert result.result.outcome is AskOutcome.ANSWERED
    assert [agent.value for agent in result.agents_used] == ["coordinator"]
    assert result.tool_calls == 0
    assert result.provider_calls == 2
    assert result.terminal_state is WorkflowStatus.COMPLETED


@pytest.mark.asyncio
async def test_complete_agentic_happy_path_is_cited_and_bounded() -> None:
    result = await ask(
        build_service(),
        "I missed an assessment due to illness and need mitigating circumstances and an appeal.",
    )

    assert result.workflow_mode is WorkflowMode.AGENTIC
    assert result.result.outcome is AskOutcome.ANSWERED
    assert result.result.citation_verification_passed is True
    assert [item.citation_id for item in result.result.citations] == ["E1"]
    assert [agent.value for agent in result.agents_used] == [
        "coordinator",
        "retrieval",
        "policy_analyst",
        "student_support",
        "verifier",
    ]
    assert result.tool_calls == 1
    assert result.provider_calls == 3
    assert result.terminal_state is WorkflowStatus.COMPLETED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "service",
    [
        build_service(retrieval=FakeRetrieval([], error=RuntimeError("private database detail"))),
        build_service(provider=MockLLMProvider(embedding_dimensions=8)),
        build_service(service_task_limit=3),
        build_service(tool_limit=0),
    ],
)
async def test_failures_invalid_output_and_limits_escalate_without_internal_details(
    service: AgenticAskService,
) -> None:
    result = await ask(
        service,
        "I missed an assessment and need mitigating circumstances and an appeal.",
    )

    assert result.result.outcome is AskOutcome.TEMPORARILY_UNAVAILABLE
    assert result.result.requires_human_support is True
    assert "private database detail" not in result.result.answer


@pytest.mark.asyncio
async def test_insufficient_evidence_and_verification_failure_are_distinct_fallbacks() -> None:
    insufficient = await ask(
        build_service(retrieval=FakeRetrieval([])),
        "I missed an assessment and want to appeal.",
    )
    bad_provider = MockLLMProvider(
        structured_responses={
            PolicyAnalysisOutput: policy_output(),
            StudentSupportOutput: support_output(answer="Your appeal is approved."),
        },
        embedding_dimensions=8,
    )
    rejected = await ask(
        build_service(provider=bad_provider),
        "I missed an assessment and want to appeal.",
    )

    assert insufficient.result.outcome is AskOutcome.INSUFFICIENT_EVIDENCE
    assert insufficient.terminal_state is WorkflowStatus.ESCALATED
    assert rejected.result.outcome is AskOutcome.VERIFICATION_FAILED
    assert rejected.terminal_state is WorkflowStatus.ESCALATED
    assert rejected.result.citations == ()


class SlowRetrievalSpecialist(RetrievalSpecialist):
    async def execute(self, request: Any, context: ToolContext) -> Any:
        del request, context
        await asyncio.sleep(0.05)
        raise AssertionError("timeout should cancel the specialist")


@pytest.mark.asyncio
async def test_specialist_timeout_is_bounded_and_fails_closed() -> None:
    placeholder = build_tool_executor(
        registry=AgentRegistry(timeout_seconds=0.001, maximum_retries=0),
        retrieval=FakeRetrieval([]),  # type: ignore[arg-type]
        minimum_evidence_count=1,
        minimum_retrieval_score=0.5,
        maximum_evidence_items=1,
        evidence_max_chars_per_chunk=100,
    )
    result = await ask(
        build_service(
            timeout=0.001,
            retrieval_specialist=SlowRetrievalSpecialist(tools=placeholder),
        ),
        "I missed an assessment and want to appeal.",
    )

    assert result.result.outcome is AskOutcome.TEMPORARILY_UNAVAILABLE
    assert result.result.citation_verification_passed is False
    assert result.terminal_state is WorkflowStatus.FAILED


@pytest.mark.asyncio
async def test_logs_contain_only_safe_metadata(caplog: pytest.LogCaptureFixture) -> None:
    marker = "student-private-marker-7281"
    caplog.set_level(logging.INFO)
    result = await ask(
        build_service(),
        f"I missed an assessment and want to appeal {marker}.",
    )

    assert result.result.outcome is AskOutcome.ANSWERED
    assert marker not in caplog.text
    assert "Appeals must be submitted within 10 working days" not in caplog.text


def workflow_state() -> WorkflowState:
    return WorkflowState(
        question="I missed an assessment and want to appeal.",
        top_k=5,
        filters=SearchFilters(),
        request_id="anti-loop-request",
    )


def test_coordinator_can_plan_only_once_per_request() -> None:
    service = build_service()
    state = workflow_state()
    request = CoordinatorInput(question=state.question, top_k=state.top_k)

    service._plan_once(state, request)

    with pytest.raises(AgentLimitError):
        service._plan_once(state, request)
    assert state.coordinator_calls == 1


@pytest.mark.asyncio
async def test_repeated_identical_agent_dispatch_is_rejected() -> None:
    service = build_service()
    state = workflow_state()
    request = RetrievalAgentInput(query="appeal", objective="Retrieve.", top_k=1)
    output = RetrievalAgentOutput(
        evidence=[],
        retrieved_count=0,
        sufficient=False,
        conflicting=False,
        max_score=0.0,
    )

    async def operation() -> RetrievalAgentOutput:
        return output

    await service._run_agent(
        state,
        AgentName.RETRIEVAL,
        operation,
        action_input=request,
        provider_call=False,
    )
    with pytest.raises(AgentLimitError):
        await service._run_agent(
            state,
            AgentName.RETRIEVAL,
            operation,
            action_input=request,
            provider_call=False,
        )


@pytest.mark.asyncio
async def test_agent_cannot_dispatch_itself_or_another_agent_recursively() -> None:
    service = build_service()
    state = workflow_state()
    outer_request = RetrievalAgentInput(query="appeal", objective="Outer.", top_k=1)
    inner_request = RetrievalAgentInput(query="appeal", objective="Inner.", top_k=1)

    async def nested_operation() -> RetrievalAgentOutput:
        return await service._run_agent(
            state,
            AgentName.RETRIEVAL,
            lambda: nested_operation(),
            action_input=inner_request,
            provider_call=False,
        )

    with pytest.raises(AgentWorkflowError):
        await service._run_agent(
            state,
            AgentName.RETRIEVAL,
            nested_operation,
            action_input=outer_request,
            provider_call=False,
        )
    assert state.active_agent is None


class CountingFailingProvider(MockLLMProvider):
    def __init__(self) -> None:
        super().__init__(embedding_dimensions=8)
        self.generation_calls = 0

    async def generate_structured(self, **kwargs: Any) -> Any:
        del kwargs
        self.generation_calls += 1
        raise RuntimeError("provider detail must stay private")


@pytest.mark.asyncio
async def test_retry_and_total_provider_call_limits_terminate_failure() -> None:
    provider = CountingFailingProvider()
    result = await ask(
        build_service(provider=provider, retries=3, provider_limit=2),
        "I missed an assessment and want to appeal.",
    )

    assert provider.generation_calls == 1
    assert result.provider_calls == 2
    assert result.terminal_state is WorkflowStatus.FAILED
    assert result.result.outcome is AskOutcome.TEMPORARILY_UNAVAILABLE


@pytest.mark.asyncio
async def test_retry_limit_allows_only_initial_attempt_plus_bounded_retries() -> None:
    provider = CountingFailingProvider()
    result = await ask(
        build_service(provider=provider, retries=2, provider_limit=5),
        "I missed an assessment and want to appeal.",
    )

    assert provider.generation_calls == 3
    assert result.provider_calls == 4
    assert result.terminal_state is WorkflowStatus.FAILED


class RejectingCountingVerifier(WorkflowVerifier):
    def __init__(self) -> None:
        self.final_calls = 0

    def verify_final(self, **kwargs: Any) -> VerificationOutput:
        del kwargs
        self.final_calls += 1
        return VerificationOutput(valid=False, failure_categories=["rejected"])


@pytest.mark.asyncio
async def test_verifier_rejection_does_not_restart_workflow() -> None:
    verifier = RejectingCountingVerifier()
    result = await ask(
        build_service(verifier=verifier),
        "I missed an assessment and want to appeal.",
    )

    assert verifier.final_calls == 1
    assert result.provider_calls == 3
    assert result.terminal_state is WorkflowStatus.ESCALATED
    assert result.result.outcome is AskOutcome.VERIFICATION_FAILED


def test_terminal_states_are_irreversible() -> None:
    service = build_service()
    state = workflow_state()

    service._transition_terminal(state, WorkflowStatus.COMPLETED)

    with pytest.raises(AgentWorkflowError):
        service._transition_terminal(state, WorkflowStatus.FAILED)
