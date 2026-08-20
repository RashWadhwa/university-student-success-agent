"""Language-model provider exceptions safe for API responses."""

from typing import Any

from backend.core.exceptions import ApplicationError


class LLMError(ApplicationError):
    """Base exception for model-provider failures."""


class LLMConfigurationError(LLMError):
    """Raised when provider configuration is missing or invalid."""

    def __init__(self, details: Any | None = None) -> None:
        super().__init__(
            code="LLM_CONFIGURATION_ERROR",
            message="The language-model provider is not configured.",
            status_code=503,
            details=details,
        )


class LLMRequestError(LLMError):
    """Raised when a provider rejects the supplied request."""

    def __init__(self, details: Any | None = None) -> None:
        super().__init__(
            code="LLM_REQUEST_ERROR",
            message="The language-model request was rejected.",
            status_code=400,
            details=details,
        )


class LLMAuthenticationError(LLMError):
    """Raised when provider credentials or permissions are invalid."""

    def __init__(self, details: Any | None = None) -> None:
        super().__init__(
            code="LLM_AUTHENTICATION_ERROR",
            message="The language-model provider rejected the configured credentials.",
            status_code=503,
            details=details,
        )


class LLMRateLimitError(LLMError):
    """Raised when provider capacity or account limits are exceeded."""

    def __init__(self, details: Any | None = None) -> None:
        super().__init__(
            code="LLM_RATE_LIMITED",
            message="The language-model provider is temporarily rate limited.",
            status_code=503,
            details=details,
        )


class LLMTimeoutError(LLMError):
    """Raised when the provider does not complete within the configured timeout."""

    def __init__(self, details: Any | None = None) -> None:
        super().__init__(
            code="LLM_TIMEOUT",
            message="The language-model provider timed out.",
            status_code=504,
            details=details,
        )


class LLMUnavailableError(LLMError):
    """Raised for connection failures and temporary provider outages."""

    def __init__(self, details: Any | None = None) -> None:
        super().__init__(
            code="LLM_UNAVAILABLE",
            message="The language-model provider is temporarily unavailable.",
            status_code=503,
            details=details,
        )


class LLMResponseError(LLMError):
    """Raised when provider output is empty or fails schema validation."""

    def __init__(self, details: Any | None = None) -> None:
        super().__init__(
            code="LLM_RESPONSE_INVALID",
            message="The language-model provider returned an invalid response.",
            status_code=502,
            details=details,
        )
