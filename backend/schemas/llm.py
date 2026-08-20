"""Schemas for Stage 2 provider diagnostics."""

from typing import Literal

from pydantic import Field

from backend.schemas.common import StrictModel


class LLMStatusResponse(StrictModel):
    """Safe provider configuration summary."""

    provider: str
    model: str | None = None
    embedding_model: str | None = None
    configured: bool
    smoke_test_enabled: bool
    configuration_error: str | None = None


class ProviderSmokeTestOutput(StrictModel):
    """Structured output required from the model smoke test."""

    message: str = Field(default="Provider is ready.", min_length=1, max_length=120)
    provider_ready: Literal[True] = True


class TokenUsageResponse(StrictModel):
    """API representation of normalised token usage."""

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


class LLMSmokeTestResponse(StrictModel):
    """Result from the fixed, low-risk model-provider smoke test."""

    output: ProviderSmokeTestOutput
    provider: str
    model: str
    latency_ms: float = Field(ge=0)
    usage: TokenUsageResponse
    provider_request_id: str | None = None
