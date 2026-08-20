"""Provider independence, mock-only judging, and structured score validation."""

import pytest
from pydantic import ValidationError

from backend.core.config import EvaluationProviderName, Settings
from backend.evaluation.base import EvaluationProvider
from backend.evaluation.factory import create_evaluation_provider
from backend.evaluation.models import EvaluationInput, EvaluationOutput
from backend.evaluation.providers.mock_provider import MockEvaluationProvider
from backend.evaluation.tracing import safe_evaluator_trace_metadata


def evaluation_input() -> EvaluationInput:
    return EvaluationInput(
        question="How does the academic appeal process apply?",
        expected_criteria=["Use current policy evidence."],
        answer="Review the academic appeal policy and contact staff if unclear.",
        evidence=["The policy describes the academic appeal process."],
        citations=[
            {
                "citation_id": "E1",
                "title": "Academic Appeals Policy",
                "page": 2,
            }
        ],
        workflow_mode="baseline",
        citations_verified=True,
        requires_human_support=False,
    )


def test_stage_seven_defaults_to_independent_gemini_judge() -> None:
    settings = Settings(_env_file=None)

    assert settings.eval_provider is EvaluationProviderName.GEMINI
    assert settings.eval_model == "gemini-3.1-flash-lite"


def test_judge_model_can_be_changed_only_through_configuration() -> None:
    settings = Settings(_env_file=None, eval_model="configured-evaluator-model")

    assert settings.eval_model == "configured-evaluator-model"


@pytest.mark.asyncio
async def test_automated_evaluation_uses_replaceable_mock_provider() -> None:
    settings = Settings(_env_file=None, eval_provider=EvaluationProviderName.MOCK)
    provider = create_evaluation_provider(settings)

    assert isinstance(provider, EvaluationProvider)
    assert isinstance(provider, MockEvaluationProvider)
    result = await provider.evaluate(evaluation_input())

    assert result.provider == "mock"
    assert result.model == "mock-evaluator-v1"
    assert result.output.groundedness == 1.0
    assert provider.calls == [evaluation_input()]
    await provider.close()


def test_mock_provider_supports_deterministic_custom_scores() -> None:
    output = EvaluationOutput(
        groundedness=0.9,
        policy_correctness=0.8,
        completeness=0.7,
        helpfulness=0.85,
        escalation_correct=True,
        reasoning_summary="The synthetic answer omits one optional step.",
    )

    provider = MockEvaluationProvider(output=output)

    assert provider.is_configured
    assert provider._output == output


@pytest.mark.parametrize("score", [-0.01, 1.01])
def test_judge_score_range_is_strict(score: float) -> None:
    values = {
        "groundedness": score,
        "policy_correctness": 1.0,
        "completeness": 1.0,
        "helpfulness": 1.0,
        "escalation_correct": True,
        "reasoning_summary": "Bounded rationale.",
    }

    with pytest.raises(ValidationError):
        EvaluationOutput.model_validate(values)


def test_langfuse_metadata_excludes_keys_and_sensitive_payloads() -> None:
    provider = MockEvaluationProvider()
    metadata = safe_evaluator_trace_metadata(provider)

    assert metadata == {
        "provider": "mock",
        "model": "mock-evaluator-v1",
    }
    assert "key" not in " ".join(metadata).casefold()


@pytest.mark.parametrize(
    "values",
    [
        {"question": "x" * 2001},
        {"answer": "x" * 5001},
        {"evidence": ["evidence"] * 6},
        {"expected_criteria": []},
        {"unexpected": "free-form evaluator instruction"},
    ],
)
def test_evaluation_input_is_strictly_bounded(values: dict[str, object]) -> None:
    base = evaluation_input().model_dump()
    base.update(values)

    with pytest.raises(ValidationError):
        EvaluationInput.model_validate(base)
