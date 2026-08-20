"""Tests for provider selection and deterministic mock behaviour."""

import pytest
from pydantic import BaseModel

from backend.core.config import Environment, LLMProviderName, Settings
from backend.llm.errors import LLMConfigurationError
from backend.llm.factory import create_llm_provider
from backend.llm.providers.mock_provider import MockLLMProvider


class StructuredExample(BaseModel):
    value: str


@pytest.mark.asyncio
async def test_mock_provider_uses_configured_structured_payload() -> None:
    provider = MockLLMProvider(structured_responses={StructuredExample: {"value": "deterministic"}})

    result = await provider.generate_structured(
        system_prompt="system",
        user_prompt="user",
        response_model=StructuredExample,
    )

    assert result.output.value == "deterministic"
    assert result.provider == "mock"


@pytest.mark.asyncio
async def test_mock_embeddings_are_deterministic() -> None:
    provider = MockLLMProvider(embedding_dimensions=4)

    first = await provider.create_embeddings(["same text"])
    second = await provider.create_embeddings(["same text"])

    assert first.embeddings == second.embeddings
    assert len(first.embeddings[0]) == 4


def test_factory_creates_mock_provider() -> None:
    settings = Settings(
        _env_file=None,
        environment=Environment.TESTING,
        llm_provider=LLMProviderName.MOCK,
    )

    provider = create_llm_provider(settings)

    assert isinstance(provider, MockLLMProvider)


def test_openai_factory_requires_api_key() -> None:
    settings = Settings(
        _env_file=None,
        environment=Environment.TESTING,
        llm_provider=LLMProviderName.OPENAI,
        openai_api_key=None,
    )

    with pytest.raises(LLMConfigurationError) as exc_info:
        create_llm_provider(settings)

    assert exc_info.value.details == {"missing": ["OPENAI_API_KEY"]}
