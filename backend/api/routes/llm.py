"""Provider status and development-only smoke-test endpoints."""

from fastapi import APIRouter, Depends, Request

from backend.api.dependencies import get_llm_provider
from backend.core.config import Settings
from backend.core.exceptions import ApplicationError
from backend.llm.base import GenerationOptions, LLMProvider
from backend.schemas.llm import (
    LLMSmokeTestResponse,
    LLMStatusResponse,
    ProviderSmokeTestOutput,
    TokenUsageResponse,
)

router = APIRouter(prefix="/llm", tags=["llm"])


@router.get("/status", response_model=LLMStatusResponse, summary="Inspect LLM configuration")
async def llm_status(request: Request) -> LLMStatusResponse:
    settings: Settings = request.app.state.settings
    provider: LLMProvider | None = getattr(request.app.state, "llm_provider", None)
    error = getattr(request.app.state, "llm_provider_error", None)
    return LLMStatusResponse(
        provider=settings.llm_provider.value,
        model=provider.model if provider else settings.openai_model,
        embedding_model=(
            provider.embedding_model if provider else settings.openai_embedding_model
        ),
        configured=provider is not None and provider.is_configured,
        smoke_test_enabled=settings.llm_smoke_test_enabled,
        configuration_error=error,
    )


@router.post(
    "/smoke-test",
    response_model=LLMSmokeTestResponse,
    summary="Run a fixed structured-output provider test",
)
async def llm_smoke_test(
    request: Request,
    provider: LLMProvider = Depends(get_llm_provider),
) -> LLMSmokeTestResponse:
    settings: Settings = request.app.state.settings
    if not settings.llm_smoke_test_enabled:
        raise ApplicationError(
            code="LLM_SMOKE_TEST_DISABLED",
            message="The LLM smoke-test endpoint is disabled.",
            status_code=404,
        )

    result = await provider.generate_structured(
        system_prompt=(
            "You are a provider health-check. Return the requested structured output only."
        ),
        user_prompt=(
            "Confirm that the language-model provider can produce a structured response. "
            "Set provider_ready to true and use the message 'Provider is ready.'."
        ),
        response_model=ProviderSmokeTestOutput,
        options=GenerationOptions(max_output_tokens=80),
    )
    return LLMSmokeTestResponse(
        output=result.output,
        provider=result.provider,
        model=result.model,
        latency_ms=result.latency_ms,
        usage=TokenUsageResponse(
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            total_tokens=result.usage.total_tokens,
        ),
        provider_request_id=result.provider_request_id,
    )
