"""OpenAI implementation of the provider-independent LLM contract."""

import logging
from time import perf_counter
from typing import Any

from pydantic import ValidationError

from backend.core.config import Settings
from backend.core.context import get_request_id
from backend.llm.base import (
    EmbeddingResult,
    GenerationOptions,
    LLMProvider,
    LLMResult,
    StructuredOutputT,
    TextResult,
    TokenUsage,
)
from backend.llm.errors import (
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMRateLimitError,
    LLMRequestError,
    LLMResponseError,
    LLMTimeoutError,
    LLMUnavailableError,
)

logger = logging.getLogger(__name__)


class OpenAIProvider(LLMProvider):
    """OpenAI Responses API and embeddings implementation."""

    def __init__(self, settings: Settings, *, client: Any | None = None) -> None:
        self._settings = settings
        self._model = settings.openai_model
        self._embedding_model = settings.openai_embedding_model

        if client is not None:
            self._client = client
            return

        if settings.openai_api_key is None:
            raise LLMConfigurationError(details={"missing": ["OPENAI_API_KEY"]})

        try:
            import httpx
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise LLMConfigurationError(
                details={"reason": "Install the project dependencies to use OpenAI."}
            ) from exc

        timeout = httpx.Timeout(
            settings.llm_timeout_seconds,
            connect=settings.llm_connect_timeout_seconds,
        )
        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            organization=settings.openai_organization,
            project=settings.openai_project,
            base_url=settings.openai_base_url,
            timeout=timeout,
            max_retries=settings.llm_max_retries,
        )

    @property
    def name(self) -> str:
        return "openai"

    @property
    def model(self) -> str:
        return self._model

    @property
    def embedding_model(self) -> str:
        return self._embedding_model

    @property
    def is_configured(self) -> bool:
        return self._client is not None

    async def generate_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        options: GenerationOptions | None = None,
    ) -> TextResult:
        resolved_options = options or GenerationOptions()
        started = perf_counter()

        try:
            response = await self._client.responses.create(
                **self._generation_parameters(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    options=resolved_options,
                )
            )
        except Exception as exc:
            raise self._translate_exception(exc) from exc

        output_text = getattr(response, "output_text", None)
        if not isinstance(output_text, str) or not output_text.strip():
            raise LLMResponseError(
                details={"provider_request_id": getattr(response, "_request_id", None)}
            )

        return TextResult(
            output=output_text.strip(),
            provider=self.name,
            model=self.model,
            latency_ms=(perf_counter() - started) * 1000,
            usage=self._normalise_usage(getattr(response, "usage", None)),
            provider_request_id=getattr(response, "_request_id", None),
        )

    async def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[StructuredOutputT],
        options: GenerationOptions | None = None,
    ) -> LLMResult[StructuredOutputT]:
        resolved_options = options or GenerationOptions()
        started = perf_counter()
        parameters = self._generation_parameters(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            options=resolved_options,
        )
        parameters["text_format"] = response_model

        try:
            response = await self._client.responses.parse(**parameters)
            parsed = getattr(response, "output_parsed", None)
            if isinstance(parsed, response_model):
                output = parsed
            else:
                output = response_model.model_validate(parsed)
        except ValidationError as exc:
            raise LLMResponseError(
                details={"reason": "Structured output validation failed."}
            ) from exc
        except Exception as exc:
            raise self._translate_exception(exc) from exc

        return LLMResult(
            output=output,
            provider=self.name,
            model=self.model,
            latency_ms=(perf_counter() - started) * 1000,
            usage=self._normalise_usage(getattr(response, "usage", None)),
            provider_request_id=getattr(response, "_request_id", None),
        )

    async def create_embeddings(self, texts: list[str]) -> EmbeddingResult:
        if not texts or any(not text.strip() for text in texts):
            raise LLMRequestError(
                details={"field": "texts", "reason": "Non-empty texts are required."}
            )

        started = perf_counter()
        parameters: dict[str, Any] = {
            "model": self.embedding_model,
            "input": texts,
            "encoding_format": "float",
            "dimensions": self._settings.embedding_dimensions,
        }
        extra_headers = self._request_headers()
        if extra_headers:
            parameters["extra_headers"] = extra_headers

        try:
            response = await self._client.embeddings.create(**parameters)
        except Exception as exc:
            raise self._translate_exception(exc) from exc

        ordered = sorted(response.data, key=lambda item: item.index)
        embeddings = [list(item.embedding) for item in ordered]
        if len(embeddings) != len(texts):
            raise LLMResponseError(
                details={
                    "reason": "Embedding count did not match input count.",
                    "provider_request_id": getattr(response, "_request_id", None),
                }
            )

        return EmbeddingResult(
            embeddings=embeddings,
            provider=self.name,
            model=self.embedding_model,
            latency_ms=(perf_counter() - started) * 1000,
            usage=self._normalise_usage(getattr(response, "usage", None)),
            provider_request_id=getattr(response, "_request_id", None),
        )

    async def close(self) -> None:
        close = getattr(self._client, "close", None)
        if close is not None:
            await close()

    def _generation_parameters(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        options: GenerationOptions,
    ) -> dict[str, Any]:
        if not system_prompt.strip() or not user_prompt.strip():
            raise LLMRequestError(details={"reason": "System and user prompts must be non-empty."})

        parameters: dict[str, Any] = {
            "model": self.model,
            "instructions": system_prompt,
            "input": user_prompt,
            "store": False,
            "max_output_tokens": options.max_output_tokens or self._settings.llm_max_output_tokens,
        }
        if options.temperature is not None:
            parameters["temperature"] = options.temperature

        extra_headers = self._request_headers()
        if extra_headers:
            parameters["extra_headers"] = extra_headers
        return parameters

    @staticmethod
    def _normalise_usage(usage: Any | None) -> TokenUsage:
        if usage is None:
            return TokenUsage()
        input_tokens = int(
            getattr(usage, "input_tokens", None) or getattr(usage, "prompt_tokens", 0) or 0
        )
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        total_tokens = int(getattr(usage, "total_tokens", input_tokens + output_tokens) or 0)
        return TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
        )

    @staticmethod
    def _request_headers() -> dict[str, str] | None:
        request_id = get_request_id()
        if request_id == "-":
            return None
        return {"X-Client-Request-Id": request_id}

    @staticmethod
    def _translate_exception(exc: Exception) -> Exception:
        class_names = {base.__name__ for base in type(exc).__mro__}
        provider_request_id = getattr(exc, "request_id", None)
        details = {"provider_request_id": provider_request_id} if provider_request_id else None

        logger.warning(
            "OpenAI request failed",
            extra={
                "error_type": type(exc).__name__,
                "provider_request_id": provider_request_id,
            },
        )

        if "APITimeoutError" in class_names or "TimeoutError" in class_names:
            return LLMTimeoutError(details=details)
        if {"AuthenticationError", "PermissionDeniedError"} & class_names:
            return LLMAuthenticationError(details=details)
        if "RateLimitError" in class_names:
            return LLMRateLimitError(details=details)
        if {"BadRequestError", "UnprocessableEntityError"} & class_names:
            return LLMRequestError(details=details)
        if {"APIConnectionError", "InternalServerError"} & class_names:
            return LLMUnavailableError(details=details)

        status_code = getattr(exc, "status_code", None)
        if status_code == 429:
            return LLMRateLimitError(details=details)
        if status_code in {401, 403}:
            return LLMAuthenticationError(details=details)
        if status_code in {400, 404, 422}:
            return LLMRequestError(details=details)
        if isinstance(status_code, int) and status_code >= 500:
            return LLMUnavailableError(details=details)
        return LLMUnavailableError(details=details)
