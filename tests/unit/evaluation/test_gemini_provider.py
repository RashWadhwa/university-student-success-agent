"""Gemini adapter contract tests using an in-memory HTTP transport only."""

import json

import httpx
import pytest
from pydantic import SecretStr

from backend.core.config import Settings
from backend.evaluation.errors import EvaluationError, EvaluationResponseError
from backend.evaluation.models import EvaluationInput
from backend.evaluation.providers.gemini_provider import GeminiEvaluationProvider


def request() -> EvaluationInput:
    return EvaluationInput(
        question="What does the synthetic extension policy require?",
        expected_criteria=["Use the policy evidence."],
        answer="Use the current extension request process.",
        evidence=["Students may submit an extension request."],
        citations=[{"citation_id": "E1", "title": "Extension Policy", "page": 1}],
        workflow_mode="baseline",
        citations_verified=True,
        requires_human_support=False,
    )


def settings() -> Settings:
    return Settings(_env_file=None, gemini_api_key=SecretStr("test-key-never-sent-live"))


def provider_for(handler: httpx.MockTransport) -> GeminiEvaluationProvider:
    return GeminiEvaluationProvider(
        settings(),
        client=httpx.AsyncClient(transport=handler),
    )


def gemini_response(**overrides: object) -> httpx.Response:
    output = {
        "groundedness": 0.95,
        "policy_correctness": 0.9,
        "completeness": 0.85,
        "helpfulness": 0.9,
        "escalation_correct": True,
        "reasoning_summary": "The answer is grounded and concise.",
        **overrides,
    }
    return httpx.Response(
        200,
        headers={"x-request-id": "gemini-request-safe"},
        json={"candidates": [{"content": {"parts": [{"text": json.dumps(output)}]}}]},
    )


@pytest.mark.asyncio
async def test_valid_structured_score_uses_configured_model() -> None:
    provider = provider_for(httpx.MockTransport(lambda request: gemini_response()))

    result = await provider.evaluate(request())

    assert result.output.groundedness == 0.95
    assert result.model == "gemini-3.1-flash-lite"
    assert result.provider_request_id == "gemini-request-safe"


@pytest.mark.asyncio
async def test_invalid_score_range_is_rejected() -> None:
    provider = provider_for(httpx.MockTransport(lambda request: gemini_response(groundedness=1.5)))

    with pytest.raises(EvaluationResponseError):
        await provider.evaluate(request())


@pytest.mark.asyncio
async def test_timeout_is_translated_without_provider_details() -> None:
    def timeout(active_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("private timeout details", request=active_request)

    provider = provider_for(httpx.MockTransport(timeout))

    with pytest.raises(EvaluationError) as captured:
        await provider.evaluate(request())

    assert "private" not in str(captured.value)


@pytest.mark.asyncio
async def test_malformed_response_is_rejected() -> None:
    provider = provider_for(
        httpx.MockTransport(lambda request: httpx.Response(200, json={"candidates": []}))
    )

    with pytest.raises(EvaluationResponseError):
        await provider.evaluate(request())


@pytest.mark.asyncio
async def test_provider_unavailable_is_safe() -> None:
    provider = provider_for(
        httpx.MockTransport(
            lambda request: httpx.Response(503, text="database password and stack trace")
        )
    )

    with pytest.raises(EvaluationError) as captured:
        await provider.evaluate(request())

    assert "password" not in str(captured.value).casefold()
