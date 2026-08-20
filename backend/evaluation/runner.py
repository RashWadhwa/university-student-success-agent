"""Bounded, reproducible baseline-versus-agentic evaluation orchestration."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from time import perf_counter
from typing import Any, Literal

from backend.agents.types import AgenticAskResult
from backend.ask.types import AskResult
from backend.evaluation.base import EvaluationProvider
from backend.evaluation.dataset import EvaluationDataset
from backend.evaluation.errors import EvaluationBudgetError
from backend.evaluation.metrics import deterministic_scores
from backend.evaluation.models import (
    EvaluationAggregate,
    EvaluationCase,
    EvaluationCaseResult,
    EvaluationCitation,
    EvaluationInput,
    EvaluationRunResult,
    EvaluationWorkflow,
)
from backend.observability.base import ObservabilityService
from backend.rag.types import SearchFilters

WorkflowMode = Literal["baseline", "agentic"]


class EvaluationRunner:
    """Run each workflow once per case with hard, non-recursive budgets."""

    def __init__(
        self,
        *,
        dataset: EvaluationDataset,
        baseline: Any,
        agentic: Any,
        provider: EvaluationProvider,
        observability: ObservabilityService,
        maximum_cases: int,
        maximum_judge_calls: int,
        timeout_seconds: float,
    ) -> None:
        self.dataset = dataset
        self.baseline = baseline
        self.agentic = agentic
        self.provider = provider
        self.observability = observability
        self.maximum_cases = maximum_cases
        self.maximum_judge_calls = maximum_judge_calls
        self.timeout_seconds = timeout_seconds

    async def run(
        self,
        *,
        workflow: EvaluationWorkflow,
        case_ids: list[str] | None = None,
    ) -> EvaluationRunResult:
        cases = self.dataset.select(case_ids)
        if len(cases) > self.maximum_cases:
            raise EvaluationBudgetError(details={"limit": "cases"})
        modes = self._modes(workflow)
        required_judges = sum(not case.deterministic_only for case in cases) * len(modes)
        if required_judges > self.maximum_judge_calls:
            raise EvaluationBudgetError(details={"limit": "judge_calls"})

        results: list[EvaluationCaseResult] = []
        judge_calls = 0
        for case in cases:
            for mode in modes:
                result, called = await self._run_case(case, mode)
                results.append(result)
                judge_calls += int(called)
        summaries = [self._aggregate(mode, results) for mode in modes]
        return EvaluationRunResult(
            dataset=self.dataset.name,
            workflow=workflow,
            case_count=len(cases),
            judge_calls=judge_calls,
            status=self._run_status(results),
            results=results,
            summaries=summaries,
            winner=self._winner(summaries),
        )

    async def _run_case(
        self,
        case: EvaluationCase,
        mode: WorkflowMode,
    ) -> tuple[EvaluationCaseResult, bool]:
        started = perf_counter()
        try:
            async with asyncio.timeout(self.timeout_seconds):
                raw = await self._answer(case, mode)
            answer, agents, tool_calls, provider_calls = self._normalise(raw)
        except Exception:
            return (
                EvaluationCaseResult(
                    case_id=case.id,
                    category=case.category,
                    workflow_mode=mode,
                    status="failed",
                    latency_ms=(perf_counter() - started) * 1000,
                    provider_calls=0,
                    tool_calls=0,
                    error_category="workflow_unavailable",
                ),
                False,
            )

        deterministic = deterministic_scores(
            case=case,
            retrieved_titles=[item.document_title for item in answer.citations],
            citations_valid=answer.citation_verification_passed,
            requires_human_support=answer.requires_human_support,
            confidence=answer.confidence.value,
            structured_output_valid=True,
            agents_used=agents,
            tool_calls=tool_calls,
            workflow_mode=mode,
        )
        judge = None
        called = False
        error_category = None
        if not case.deterministic_only:
            called = True
            try:
                async with asyncio.timeout(self.timeout_seconds):
                    judged = await self.provider.evaluate(
                        EvaluationInput(
                            question=case.question,
                            expected_criteria=case.expected_criteria,
                            answer=answer.answer,
                            evidence=[item.excerpt[:1000] for item in answer.citations[:5]],
                            citations=[
                                EvaluationCitation(
                                    citation_id=item.citation_id,
                                    title=item.document_title,
                                    section=item.section,
                                    page=item.page,
                                    version=item.version,
                                    institution=item.institution,
                                    corpus_tier=item.corpus_tier,
                                    authority_scope=item.authority_scope,
                                )
                                for item in answer.citations[:10]
                            ],
                            workflow_mode=mode,
                            citations_verified=answer.citation_verification_passed,
                            requires_human_support=answer.requires_human_support,
                        )
                    )
                judge = judged.output
            except Exception:
                error_category = "judge_unavailable"

        status = "partial" if error_category else "passed"
        elapsed_ms = (perf_counter() - started) * 1000
        trace_id = await self.observability.record_event(
            event="evaluation.case.completed",
            request_id=answer.request_id,
            metadata={
                "workflow_mode": mode,
                "provider": self.provider.name,
                "model": self.provider.model,
                "latency_ms": round(elapsed_ms, 2),
                "citation_count": len(answer.citations),
                "judge_calls": int(called),
                "success": status == "passed",
                "error_category": error_category,
            },
        )
        return (
            EvaluationCaseResult(
                case_id=case.id,
                category=case.category,
                workflow_mode=mode,
                status=status,
                deterministic=deterministic,
                judge=judge,
                latency_ms=elapsed_ms,
                provider_calls=provider_calls,
                tool_calls=tool_calls,
                request_id=answer.request_id,
                trace_id=trace_id,
                error_category=error_category,
            ),
            called,
        )

    async def _answer(
        self,
        case: EvaluationCase,
        mode: WorkflowMode,
    ) -> AskResult | AgenticAskResult:
        service = self.baseline if mode == "baseline" else self.agentic
        return await service.answer(
            question=case.question,
            top_k=None,
            filters=SearchFilters(),
            session_id=None,
        )

    @staticmethod
    def _normalise(
        raw: AskResult | AgenticAskResult,
    ) -> tuple[AskResult, tuple[str, ...], int, int]:
        if isinstance(raw, AgenticAskResult):
            return (
                raw.result,
                tuple(agent.value for agent in raw.agents_used),
                raw.tool_calls,
                raw.provider_calls,
            )
        return raw, (), 0, int(raw.evaluation.get("provider_calls", 0))

    @staticmethod
    def _modes(workflow: EvaluationWorkflow) -> tuple[WorkflowMode, ...]:
        if workflow is EvaluationWorkflow.BOTH:
            return ("baseline", "agentic")
        return (workflow.value,)

    @staticmethod
    def _run_status(results: list[EvaluationCaseResult]) -> str:
        if all(result.status == "failed" for result in results):
            return "failed"
        if any(result.status != "passed" for result in results):
            return "partial"
        return "completed"

    @staticmethod
    def _aggregate(mode: WorkflowMode, results: list[EvaluationCaseResult]) -> EvaluationAggregate:
        selected = [result for result in results if result.workflow_mode == mode]
        deterministic_values: dict[str, list[float]] = defaultdict(list)
        judge_values: dict[str, list[float]] = defaultdict(list)
        for result in selected:
            if result.deterministic is not None:
                for key, value in result.deterministic.model_dump().items():
                    if value is not None:
                        deterministic_values[key].append(float(value))
            if result.judge is not None:
                for key in ("groundedness", "policy_correctness", "completeness", "helpfulness"):
                    judge_values[key].append(float(getattr(result.judge, key)))
                judge_values["escalation_correct"].append(float(result.judge.escalation_correct))

        def average(values: list[float]) -> float:
            return round(sum(values) / len(values), 4) if values else 0.0

        return EvaluationAggregate(
            workflow_mode=mode,
            case_count=len(selected),
            passed_count=sum(result.status == "passed" for result in selected),
            partial_count=sum(result.status == "partial" for result in selected),
            failed_count=sum(result.status == "failed" for result in selected),
            deterministic={key: average(values) for key, values in deterministic_values.items()},
            judge={key: average(values) for key, values in judge_values.items()},
            mean_latency_ms=average([result.latency_ms for result in selected]),
            total_provider_calls=sum(result.provider_calls for result in selected),
            total_tool_calls=sum(result.tool_calls for result in selected),
        )

    @staticmethod
    def _winner(summaries: list[EvaluationAggregate]) -> str:
        if len(summaries) != 2:
            return "not_comparable"

        def score(summary: EvaluationAggregate) -> float:
            values = list(summary.deterministic.values()) + list(summary.judge.values())
            return sum(values) / len(values) if values else 0.0

        baseline, agentic = summaries
        difference = score(agentic) - score(baseline)
        if abs(difference) < 0.0001:
            return "tie"
        return "agentic" if difference > 0 else "baseline"
