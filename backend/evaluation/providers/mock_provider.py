"""Deterministic evaluation provider for all automated tests."""

from time import perf_counter

from backend.evaluation.base import EvaluationProvider, EvaluationResult
from backend.evaluation.models import EvaluationInput, EvaluationOutput


class MockEvaluationProvider(EvaluationProvider):
    def __init__(
        self,
        *,
        output: EvaluationOutput | None = None,
        model: str = "mock-evaluator-v1",
    ) -> None:
        self._model = model
        self._output = output or EvaluationOutput(
            groundedness=1.0,
            policy_correctness=1.0,
            completeness=1.0,
            helpfulness=1.0,
            escalation_correct=True,
            reasoning_summary="The synthetic response satisfies the expected criteria.",
        )
        self.calls: list[EvaluationInput] = []

    @property
    def name(self) -> str:
        return "mock"

    @property
    def model(self) -> str:
        return self._model

    @property
    def is_configured(self) -> bool:
        return True

    async def evaluate(self, request: EvaluationInput) -> EvaluationResult:
        started = perf_counter()
        self.calls.append(request)
        return EvaluationResult(
            output=self._output,
            provider=self.name,
            model=self.model,
            latency_ms=(perf_counter() - started) * 1000,
            provider_request_id="mock-evaluation-request",
        )

    async def close(self) -> None:
        return None
