"""FastAPI dependencies shared across API routes."""

from fastapi import Request

from backend.llm.base import LLMProvider
from backend.llm.errors import LLMConfigurationError


def get_llm_provider(request: Request) -> LLMProvider:
    """Return the initialised provider or a safe configuration error."""

    provider: LLMProvider | None = getattr(request.app.state, "llm_provider", None)
    if provider is None:
        error = getattr(request.app.state, "llm_provider_error", None)
        details = {"reason": error} if error else None
        raise LLMConfigurationError(details=details)
    return provider
