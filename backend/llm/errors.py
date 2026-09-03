"""Language-model provider exceptions safe for API responses."""

from typing import Any

from backend.core.exceptions import ApplicationError


class LLMError(ApplicationError):
    """Base exception for model-provider failures.

    ``provider_error_type`` is a small, fixed, non-sensitive vocabulary
    (never raw exception text, prompts, evidence, or answers) suitable for
    structured logging so operators can distinguish failure causes without
    reproducing them manually.
    """

    provider_error_type: str = "provider_error"


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

    def __init__(
        self, details: Any | None = None, *, provider_error_type: str | None = None
    ) -> None:
        super().__init__(
            code="LLM_REQUEST_ERROR",
            message="The language-model request was rejected.",
            status_code=400,
            details=details,
        )
        if provider_error_type is not None:
            self.provider_error_type = provider_error_type


class LLMAuthenticationError(LLMError):
    """Raised when provider credentials or permissions are invalid."""

    provider_error_type = "authentication"

    def __init__(self, details: Any | None = None) -> None:
        super().__init__(
            code="LLM_AUTHENTICATION_ERROR",
            message="The language-model provider rejected the configured credentials.",
            status_code=503,
            details=details,
        )


class LLMRateLimitError(LLMError):
    """Raised when provider capacity or account limits are exceeded."""

    def __init__(self, details: Any | None = None, *, quota_exceeded: bool = False) -> None:
        super().__init__(
            code="LLM_RATE_LIMITED",
            message="The language-model provider is temporarily rate limited.",
            status_code=503,
            details=details,
        )
        self.provider_error_type = "quota" if quota_exceeded else "rate_limit"


class LLMTimeoutError(LLMError):
    """Raised when the provider does not complete within the configured timeout."""

    provider_error_type = "timeout"

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

    provider_error_type = "structured_output_invalid"

    def __init__(self, details: Any | None = None) -> None:
        super().__init__(
            code="LLM_RESPONSE_INVALID",
            message="The language-model provider returned an invalid response.",
            status_code=502,
            details=details,
        )


class LLMIncompleteResponseError(LLMError):
    """Raised when the provider stops before finishing (e.g. hit the output-token cap).

    Distinct from ``LLMResponseError``: the provider request succeeded, but
    the model was cut off before producing any usable output — most often
    because a reasoning-capable model spent its entire output-token budget
    on internal reasoning. The fix is a generation-parameter change (lower
    reasoning effort and/or a higher token budget), not a schema problem.
    """

    provider_error_type = "incomplete_response"

    def __init__(self, details: Any | None = None) -> None:
        super().__init__(
            code="LLM_INCOMPLETE_RESPONSE",
            message="The language-model provider returned an incomplete response.",
            status_code=502,
            details=details,
        )
