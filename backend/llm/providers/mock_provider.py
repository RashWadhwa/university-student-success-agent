"""Deterministic provider used by tests and key-free local development."""

from time import perf_counter
from typing import Any

from pydantic import BaseModel, ValidationError

from backend.llm.base import (
    EmbeddingResult,
    GenerationOptions,
    LLMProvider,
    LLMResult,
    StructuredOutputT,
    TextResult,
    TokenUsage,
)
from backend.llm.errors import LLMResponseError


class MockLLMProvider(LLMProvider):
    """A deterministic provider with no network calls or usage cost."""

    def __init__(
        self,
        *,
        text_response: str = "Mock provider response.",
        structured_responses: dict[type[BaseModel], BaseModel | dict[str, Any]] | None = None,
        embedding_dimensions: int = 8,
    ) -> None:
        self._text_response = text_response
        self._structured_responses = structured_responses or {}
        self._embedding_dimensions = embedding_dimensions

    @property
    def name(self) -> str:
        return "mock"

    @property
    def model(self) -> str:
        return "mock-generation-v1"

    @property
    def embedding_model(self) -> str:
        return "mock-embedding-v1"

    @property
    def is_configured(self) -> bool:
        return True

    async def generate_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        options: GenerationOptions | None = None,
    ) -> TextResult:
        del system_prompt, user_prompt, options
        started = perf_counter()
        return TextResult(
            output=self._text_response,
            provider=self.name,
            model=self.model,
            latency_ms=(perf_counter() - started) * 1000,
            usage=TokenUsage(),
            provider_request_id="mock-request",
        )

    async def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[StructuredOutputT],
        options: GenerationOptions | None = None,
    ) -> LLMResult[StructuredOutputT]:
        del system_prompt, user_prompt, options
        started = perf_counter()
        configured = self._structured_responses.get(response_model)

        try:
            if isinstance(configured, response_model):
                output = configured
            elif configured is not None:
                output = response_model.model_validate(configured)
            else:
                output = response_model()
        except ValidationError as exc:
            raise LLMResponseError(
                details={"reason": "No valid mock response is configured for this schema."}
            ) from exc

        return LLMResult(
            output=output,
            provider=self.name,
            model=self.model,
            latency_ms=(perf_counter() - started) * 1000,
            usage=TokenUsage(),
            provider_request_id="mock-request",
        )

    async def create_embeddings(self, texts: list[str]) -> EmbeddingResult:
        if not texts or any(not text.strip() for text in texts):
            raise ValueError("texts must contain at least one non-empty string")

        started = perf_counter()
        embeddings = [
            [
                float((sum(text.encode("utf-8")) + index) % 101) / 100
                for index in range(self._embedding_dimensions)
            ]
            for text in texts
        ]
        return EmbeddingResult(
            embeddings=embeddings,
            provider=self.name,
            model=self.embedding_model,
            latency_ms=(perf_counter() - started) * 1000,
            usage=TokenUsage(),
            provider_request_id="mock-embedding-request",
        )

    async def close(self) -> None:
        return None
