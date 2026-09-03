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
    LLMIncompleteResponseError,
    LLMRateLimitError,
    LLMRequestError,
    LLMResponseError,
    LLMTimeoutError,
    LLMUnavailableError,
)

logger = logging.getLogger(__name__)

# GPT-5/o-series "reasoning" models spend part of max_output_tokens on hidden
# reasoning before emitting visible output. Without an explicit, low effort
# level, a moderately sized grounded-answer prompt can exhaust the entire
# budget on reasoning alone and return an empty, incomplete response — this
# is the actual generation-path failure mode this constant addresses.
_REASONING_MODEL_PREFIXES = ("gpt-5", "o1", "o3", "o4")
_LOW_REASONING_EFFORT = "low"


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
        except ValidationError as exc:
            # The SDK's own .parse() eagerly parses the (possibly truncated)
            # response text internally, before ever returning an object we
            # can inspect for status="incomplete" — so a truncated response
            # can surface here as a raw JSON-parse failure instead. Only
            # "json_invalid" (malformed/incomplete JSON) means truncation;
            # a structurally valid-but-schema-mismatched response is a
            # genuine structured_output_invalid, not incomplete_response.
            if any(error["type"] == "json_invalid" for error in exc.errors()):
                raise LLMIncompleteResponseError(details={"reason": "truncated_json"}) from exc
            raise LLMResponseError(
                details={"reason": "Structured output validation failed."}
            ) from exc
        except Exception as exc:
            raise self._translate_exception(exc) from exc

        if getattr(response, "status", None) == "incomplete":
            reason = getattr(getattr(response, "incomplete_details", None), "reason", None)
            raise LLMIncompleteResponseError(details={"reason": reason} if reason else None)

        try:
            parsed = getattr(response, "output_parsed", None)
            if isinstance(parsed, response_model):
                output = parsed
            else:
                output = response_model.model_validate(parsed)
        except ValidationError as exc:
            raise LLMResponseError(
                details={"reason": "Structured output validation failed."}
            ) from exc

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
        if self.model.startswith(_REASONING_MODEL_PREFIXES):
            # Grounded extraction from provided evidence does not need deep,
            # multi-step reasoning; without this, reasoning tokens alone can
            # consume the whole max_output_tokens budget (see
            # LLMIncompleteResponseError) before any visible output is written.
            parameters["reasoning"] = {"effort": _LOW_REASONING_EFFORT}

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
        # OpenAI's own machine-readable error code (e.g. "insufficient_quota",
        # "model_not_found") — a small fixed vocabulary from OpenAI's API
        # schema, safe to inspect/log; never the free-text error message.
        provider_code = getattr(exc, "code", None)

        translated: Exception
        if "APITimeoutError" in class_names or "TimeoutError" in class_names:
            translated = LLMTimeoutError(details=details)
        elif {"AuthenticationError", "PermissionDeniedError"} & class_names:
            translated = LLMAuthenticationError(details=details)
        elif "RateLimitError" in class_names:
            translated = LLMRateLimitError(
                details=details, quota_exceeded=provider_code == "insufficient_quota"
            )
        elif provider_code == "model_not_found":
            translated = LLMRequestError(details=details, provider_error_type="model_not_found")
        elif {"BadRequestError", "UnprocessableEntityError", "NotFoundError"} & class_names:
            translated = LLMRequestError(details=details)
        elif {"APIConnectionError", "InternalServerError"} & class_names:
            translated = LLMUnavailableError(details=details)
        else:
            status_code = getattr(exc, "status_code", None)
            if status_code == 429:
                translated = LLMRateLimitError(
                    details=details, quota_exceeded=provider_code == "insufficient_quota"
                )
            elif status_code in {401, 403}:
                translated = LLMAuthenticationError(details=details)
            elif status_code == 404:
                translated = LLMRequestError(details=details, provider_error_type="model_not_found")
            elif status_code in {400, 422}:
                translated = LLMRequestError(details=details)
            else:
                translated = LLMUnavailableError(details=details)

        logger.warning(
            "OpenAI request failed",
            extra={
                "error_type": type(exc).__name__,
                "provider_error_type": translated.provider_error_type,
                "provider_request_id": provider_request_id,
            },
        )
        return translated
