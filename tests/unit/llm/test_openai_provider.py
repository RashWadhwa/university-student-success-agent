"""Unit tests for the OpenAI provider using deterministic fake clients."""

from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from backend.core.config import Environment, LLMProviderName, Settings
from backend.core.context import request_id_context
from backend.llm.base import GenerationOptions
from backend.llm.errors import (
    LLMIncompleteResponseError,
    LLMRateLimitError,
    LLMRequestError,
    LLMTimeoutError,
)
from backend.llm.providers.openai_provider import OpenAIProvider


class SampleOutput(BaseModel):
    answer: str
    confidence: float


class FakeResponses:
    def __init__(self) -> None:
        self.create_kwargs: dict[str, Any] | None = None
        self.parse_kwargs: dict[str, Any] | None = None
        self.create_exception: Exception | None = None
        self.parse_exception: Exception | None = None
        self.parse_result: Any | None = None

    async def create(self, **kwargs: Any) -> Any:
        self.create_kwargs = kwargs
        if self.create_exception is not None:
            raise self.create_exception
        return SimpleNamespace(
            output_text="Provider text response",
            usage=SimpleNamespace(input_tokens=11, output_tokens=4, total_tokens=15),
            _request_id="req_text_123",
        )

    async def parse(self, **kwargs: Any) -> Any:
        self.parse_kwargs = kwargs
        if self.parse_exception is not None:
            raise self.parse_exception
        if self.parse_result is not None:
            return self.parse_result
        return SimpleNamespace(
            status="completed",
            output_parsed=SampleOutput(answer="grounded", confidence=0.9),
            usage=SimpleNamespace(input_tokens=20, output_tokens=8, total_tokens=28),
            _request_id="req_structured_123",
        )


class FakeEmbeddings:
    def __init__(self) -> None:
        self.kwargs: dict[str, Any] | None = None

    async def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        return SimpleNamespace(
            data=[
                SimpleNamespace(index=1, embedding=[0.3, 0.4]),
                SimpleNamespace(index=0, embedding=[0.1, 0.2]),
            ],
            usage=SimpleNamespace(prompt_tokens=0, total_tokens=7),
            _request_id="req_embedding_123",
        )


class FakeClient:
    def __init__(self) -> None:
        self.responses = FakeResponses()
        self.embeddings = FakeEmbeddings()
        self.closed = False

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        environment=Environment.TESTING,
        llm_provider=LLMProviderName.OPENAI,
        openai_api_key="test-key",
        openai_model="gpt-test",
        openai_embedding_model="embedding-test",
        llm_max_output_tokens=500,
        cors_origins=[],
    )


@pytest.mark.asyncio
async def test_generate_text_normalises_output_and_usage(settings: Settings) -> None:
    client = FakeClient()
    provider = OpenAIProvider(settings, client=client)
    token = request_id_context.set("app-request-123")
    try:
        result = await provider.generate_text(
            system_prompt="Follow the policy evidence.",
            user_prompt="What should the student do?",
            options=GenerationOptions(max_output_tokens=120),
        )
    finally:
        request_id_context.reset(token)

    assert result.output == "Provider text response"
    assert result.provider == "openai"
    assert result.model == "gpt-test"
    assert result.usage.total_tokens == 15
    assert result.provider_request_id == "req_text_123"
    assert client.responses.create_kwargs == {
        "model": "gpt-test",
        "instructions": "Follow the policy evidence.",
        "input": "What should the student do?",
        "store": False,
        "max_output_tokens": 120,
        "extra_headers": {"X-Client-Request-Id": "app-request-123"},
    }


@pytest.mark.asyncio
async def test_generate_structured_returns_validated_model(settings: Settings) -> None:
    client = FakeClient()
    provider = OpenAIProvider(settings, client=client)

    result = await provider.generate_structured(
        system_prompt="Return a structured answer.",
        user_prompt="Analyse this case.",
        response_model=SampleOutput,
    )

    assert result.output == SampleOutput(answer="grounded", confidence=0.9)
    assert result.usage.input_tokens == 20
    assert result.provider_request_id == "req_structured_123"
    assert client.responses.parse_kwargs is not None
    assert client.responses.parse_kwargs["text_format"] is SampleOutput
    assert client.responses.parse_kwargs["max_output_tokens"] == 500


@pytest.mark.asyncio
async def test_embeddings_preserve_input_order(settings: Settings) -> None:
    client = FakeClient()
    provider = OpenAIProvider(settings, client=client)

    result = await provider.create_embeddings(["first", "second"])

    assert result.embeddings == [[0.1, 0.2], [0.3, 0.4]]
    assert result.model == "embedding-test"
    assert client.embeddings.kwargs == {
        "model": "embedding-test",
        "input": ["first", "second"],
        "encoding_format": "float",
        "dimensions": 1536,
    }


@pytest.mark.asyncio
async def test_empty_prompt_is_rejected_before_network_call(settings: Settings) -> None:
    provider = OpenAIProvider(settings, client=FakeClient())

    with pytest.raises(LLMRequestError):
        await provider.generate_text(system_prompt="", user_prompt="question")


@pytest.mark.asyncio
async def test_timeout_is_mapped_to_provider_error(settings: Settings) -> None:
    class APITimeoutError(Exception):
        request_id = "req_timeout"

    client = FakeClient()
    client.responses.create_exception = APITimeoutError("timed out")
    provider = OpenAIProvider(settings, client=client)

    with pytest.raises(LLMTimeoutError) as exc_info:
        await provider.generate_text(system_prompt="system", user_prompt="user")

    assert exc_info.value.details == {"provider_request_id": "req_timeout"}


@pytest.mark.asyncio
async def test_close_releases_client(settings: Settings) -> None:
    client = FakeClient()
    provider = OpenAIProvider(settings, client=client)

    await provider.close()

    assert client.closed is True


@pytest.mark.asyncio
async def test_reasoning_capable_model_gets_low_effort_reasoning_param(
    settings: Settings,
) -> None:
    """gpt-5/o-series models must not default to spending the whole output

    budget on hidden reasoning tokens (see LLMIncompleteResponseError).
    """

    reasoning_settings = settings.model_copy(update={"openai_model": "gpt-5-mini"})
    client = FakeClient()
    provider = OpenAIProvider(reasoning_settings, client=client)

    await provider.generate_structured(
        system_prompt="Return a structured answer.",
        user_prompt="Analyse this case.",
        response_model=SampleOutput,
    )

    assert client.responses.parse_kwargs["reasoning"] == {"effort": "low"}


@pytest.mark.asyncio
async def test_non_reasoning_model_does_not_get_reasoning_param(settings: Settings) -> None:
    client = FakeClient()
    provider = OpenAIProvider(settings, client=client)

    await provider.generate_structured(
        system_prompt="Return a structured answer.",
        user_prompt="Analyse this case.",
        response_model=SampleOutput,
    )

    assert "reasoning" not in client.responses.parse_kwargs


@pytest.mark.asyncio
async def test_incomplete_response_raises_distinct_error_not_generic_validation_failure(
    settings: Settings,
) -> None:
    """A reasoning model that exhausts max_output_tokens before answering must

    be classified as incomplete_response, not a confusing schema-validation
    failure — the fix differs (token budget/effort) from a genuine invalid
    structured output.
    """

    client = FakeClient()
    client.responses.parse_result = SimpleNamespace(
        status="incomplete",
        incomplete_details=SimpleNamespace(reason="max_output_tokens"),
        output_parsed=None,
        usage=SimpleNamespace(input_tokens=20, output_tokens=500, total_tokens=520),
        _request_id="req_incomplete_123",
    )
    provider = OpenAIProvider(settings, client=client)

    with pytest.raises(LLMIncompleteResponseError) as exc_info:
        await provider.generate_structured(
            system_prompt="Return a structured answer.",
            user_prompt="Analyse this case.",
            response_model=SampleOutput,
        )

    assert exc_info.value.provider_error_type == "incomplete_response"
    assert exc_info.value.details == {"reason": "max_output_tokens"}


@pytest.mark.asyncio
async def test_rate_limit_without_quota_code_is_classified_as_rate_limit(
    settings: Settings,
) -> None:
    class RateLimitError(Exception):
        code = "rate_limit_exceeded"

    client = FakeClient()
    client.responses.create_exception = RateLimitError("slow down")
    provider = OpenAIProvider(settings, client=client)

    with pytest.raises(LLMRateLimitError) as exc_info:
        await provider.generate_text(system_prompt="system", user_prompt="user")

    assert exc_info.value.provider_error_type == "rate_limit"


@pytest.mark.asyncio
async def test_insufficient_quota_is_classified_distinctly_from_rate_limit(
    settings: Settings,
) -> None:
    class RateLimitError(Exception):
        code = "insufficient_quota"

    client = FakeClient()
    client.responses.create_exception = RateLimitError("no credit")
    provider = OpenAIProvider(settings, client=client)

    with pytest.raises(LLMRateLimitError) as exc_info:
        await provider.generate_text(system_prompt="system", user_prompt="user")

    assert exc_info.value.provider_error_type == "quota"


@pytest.mark.asyncio
async def test_model_not_found_is_classified_as_model_access_issue(settings: Settings) -> None:
    class NotFoundError(Exception):
        code = "model_not_found"
        status_code = 404

    client = FakeClient()
    client.responses.create_exception = NotFoundError("no such model")
    provider = OpenAIProvider(settings, client=client)

    with pytest.raises(LLMRequestError) as exc_info:
        await provider.generate_text(system_prompt="system", user_prompt="user")

    assert exc_info.value.provider_error_type == "model_not_found"
