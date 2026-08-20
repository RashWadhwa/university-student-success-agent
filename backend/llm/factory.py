"""Factory for selecting an LLM provider from application settings."""

from backend.core.config import LLMProviderName, Settings
from backend.llm.base import LLMProvider
from backend.llm.errors import LLMConfigurationError
from backend.llm.providers.mock_provider import MockLLMProvider
from backend.llm.providers.openai_provider import OpenAIProvider


def create_llm_provider(settings: Settings) -> LLMProvider:
    """Create the configured provider without exposing provider details to callers."""

    if settings.llm_provider is LLMProviderName.MOCK:
        return MockLLMProvider(embedding_dimensions=settings.embedding_dimensions)
    if settings.llm_provider is LLMProviderName.OPENAI:
        return OpenAIProvider(settings)
    raise LLMConfigurationError(details={"provider": str(settings.llm_provider)})
