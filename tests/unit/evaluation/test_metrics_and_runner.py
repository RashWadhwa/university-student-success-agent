"""Deterministic metrics, bounded runner, comparison, and partial failure tests."""

import asyncio
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from backend.agents.types import (
    AgenticAskResult,
    AgentName,
    WorkflowMode,
    WorkflowStatus,
)
from backend.ask.types import AskOutcome, AskResult, Citation, Confidence
from backend.evaluation.dataset import EvaluationDataset
from backend.evaluation.errors import EvaluationBudgetError
from backend.evaluation.metrics import deterministic_scores
from backend.evaluation.models import EvaluationCase, EvaluationWorkflow
from backend.evaluation.providers.mock_provider import MockEvaluationProvider
from backend.evaluation.runner import EvaluationRunner
from backend.observability.noop import NoOpObservability


def case(*, deterministic_only: bool = False) -> EvaluationCase:
    return EvaluationCase(
        id="extension-case",
        category="extension",
        question="How do I request an extension?",
        expected_criteria=["Use the extension policy."],
        relevant_titles=["Assessment Extensions Policy"],
        expected_escalation=False,
        expected_confidence="high",
        expected_agents=["coordinator", "retrieval"],
        minimum_tool_calls=1,
        deterministic_only=deterministic_only,
    )


def answer(*, confidence: Confidence = Confidence.HIGH) -> AskResult:
    return AskResult(
        outcome=AskOutcome.ANSWERED,
        answer="Submit an extension request using the current policy process.",
        recommended_actions=(),
        citations=(
            Citation(
                citation_id="E1",
                document_id="doc-1",
                chunk_id="chunk-1",
                document_title="Assessment Extensions Policy",
                section="Requests",
                page=2,
                source="https://example.edu/extensions",
                excerpt="Students may submit an extension request.",
                version="2",
                effective_date=date(2026, 1, 1),
                retrieval_sources=("semantic", "keyword"),
            ),
        ),
        confidence=confidence,
        limitations=(),
        requires_human_support=False,
        human_support_reason=None,
        request_id="evaluation-request-1",
        retrieved_count=1,
        evidence_count=1,
        citation_verification_passed=True,
        evaluation={"provider_calls": 2},
    )


class FakeBaseline:
    def __init__(self, result: AskResult | None = None) -> None:
        self.result = result or answer()
        self.calls: list[dict[str, Any]] = []

    async def answer(self, **kwargs: Any) -> AskResult:
        self.calls.append(kwargs)
        return self.result


class FakeAgentic:
    def __init__(self, result: AskResult | None = None) -> None:
        self.result = result or answer()
        self.calls: list[dict[str, Any]] = []

    async def answer(self, **kwargs: Any) -> AgenticAskResult:
        self.calls.append(kwargs)
        return AgenticAskResult(
            result=self.result,
            workflow_mode=WorkflowMode.AGENTIC,
            agents_used=(AgentName.COORDINATOR, AgentName.RETRIEVAL),
            tool_calls=1,
            provider_calls=3,
            duration_ms=12.0,
            verification_passed=True,
            terminal_state=WorkflowStatus.COMPLETED,
        )


class SlowWorkflow:
    async def answer(self, **kwargs: Any) -> AskResult:
        del kwargs
        await asyncio.sleep(0.02)
        return answer()


class FailingJudge(MockEvaluationProvider):
    async def evaluate(self, request: Any) -> Any:
        self.calls.append(request)
        raise TimeoutError("private gemini timeout")


def dataset(tmp_path: Path, active_case: EvaluationCase) -> EvaluationDataset:
    path = tmp_path / "cases.jsonl"
    path.write_text(active_case.model_dump_json() + "\n", encoding="utf-8")
    return EvaluationDataset(path)


def runner(
    tmp_path: Path,
    *,
    active_case: EvaluationCase | None = None,
    provider: MockEvaluationProvider | None = None,
    maximum_cases: int = 5,
    maximum_judge_calls: int = 5,
    timeout_seconds: float = 1,
) -> EvaluationRunner:
    return EvaluationRunner(
        dataset=dataset(tmp_path, active_case or case()),
        baseline=FakeBaseline(),
        agentic=FakeAgentic(),
        provider=provider or MockEvaluationProvider(),
        observability=NoOpObservability(),
        maximum_cases=maximum_cases,
        maximum_judge_calls=maximum_judge_calls,
        timeout_seconds=timeout_seconds,
    )


def test_deterministic_metrics_cover_retrieval_citations_escalation_and_routing() -> None:
    scores = deterministic_scores(
        case=case(),
        retrieved_titles=["Assessment Extensions Policy"],
        citations_valid=True,
        requires_human_support=False,
        confidence="high",
        structured_output_valid=True,
        agents_used=["coordinator", "retrieval"],
        tool_calls=1,
        workflow_mode="agentic",
    )

    assert set(scores.model_dump(exclude_none=True).values()) == {1.0}


@pytest.mark.asyncio
async def test_baseline_evaluation_uses_mock_judge(tmp_path: Path) -> None:
    active = runner(tmp_path)

    result = await active.run(workflow=EvaluationWorkflow.BASELINE)

    assert result.status == "completed"
    assert result.judge_calls == 1
    assert result.results[0].judge is not None
    assert result.summaries[0].workflow_mode == "baseline"


@pytest.mark.asyncio
async def test_agentic_evaluation_scores_agent_and_tool_selection(tmp_path: Path) -> None:
    active = runner(tmp_path)

    result = await active.run(workflow=EvaluationWorkflow.AGENTIC)

    scores = result.results[0].deterministic
    assert scores is not None
    assert scores.agent_routing == 1.0
    assert scores.tool_selection == 1.0
    assert result.results[0].tool_calls == 1


@pytest.mark.asyncio
async def test_side_by_side_uses_same_case_and_reports_winner(tmp_path: Path) -> None:
    active = runner(tmp_path)

    result = await active.run(workflow=EvaluationWorkflow.BOTH)

    assert [item.workflow_mode for item in result.results] == ["baseline", "agentic"]
    assert result.winner in {"baseline", "agentic", "tie"}
    assert result.case_count == 1
    assert result.judge_calls == 2


@pytest.mark.asyncio
async def test_partial_judge_failure_preserves_deterministic_results(tmp_path: Path) -> None:
    provider = FailingJudge()
    active = runner(tmp_path, provider=provider)

    result = await active.run(workflow=EvaluationWorkflow.BASELINE)

    assert result.status == "partial"
    assert result.results[0].status == "partial"
    assert result.results[0].error_category == "judge_unavailable"
    assert result.results[0].deterministic is not None
    assert "private" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_case_and_judge_budgets_are_hard_limits(tmp_path: Path) -> None:
    case_limited = runner(tmp_path, maximum_cases=0)
    judge_limited = runner(tmp_path, maximum_judge_calls=0)

    with pytest.raises(EvaluationBudgetError):
        await case_limited.run(workflow=EvaluationWorkflow.BASELINE)
    with pytest.raises(EvaluationBudgetError):
        await judge_limited.run(workflow=EvaluationWorkflow.BASELINE)


@pytest.mark.asyncio
async def test_deterministic_only_case_does_not_call_judge(tmp_path: Path) -> None:
    provider = MockEvaluationProvider()
    active = runner(
        tmp_path,
        active_case=case(deterministic_only=True),
        provider=provider,
        maximum_judge_calls=0,
    )

    result = await active.run(workflow=EvaluationWorkflow.BASELINE)

    assert result.judge_calls == 0
    assert provider.calls == []
    assert result.results[0].judge is None


@pytest.mark.asyncio
async def test_workflow_timeout_fails_case_without_internal_details(tmp_path: Path) -> None:
    active = runner(tmp_path, timeout_seconds=0.001)
    active.baseline = SlowWorkflow()

    result = await active.run(workflow=EvaluationWorkflow.BASELINE)

    assert result.status == "failed"
    assert result.results[0].error_category == "workflow_unavailable"
    assert "timeout" not in result.model_dump_json().casefold()


def test_dataset_is_synthetic_unique_and_covers_required_categories() -> None:
    cases = EvaluationDataset(Path("data/evaluation/stage7-policy-cases.jsonl")).load()
    categories = {item.category for item in cases}

    assert 30 <= len(cases) <= 50
    assert len({item.id for item in cases}) == len(cases)
    assert {
        "direct policy lookup",
        "missed assessment",
        "late submission",
        "extension",
        "mitigating circumstances",
        "reassessment",
        "academic appeal",
        "conflicting evidence",
        "insufficient evidence",
        "out-of-scope",
        "prompt injection",
        "approval claim",
        "invented deadline",
        "human escalation",
        "citation correctness",
    } <= categories
    serialized = "\n".join(json.loads(item.model_dump_json())["question"] for item in cases)
    assert "@" not in serialized
