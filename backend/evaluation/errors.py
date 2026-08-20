"""Safe Stage 7 evaluator errors that never expose provider internals."""

from typing import Any

from backend.core.exceptions import ApplicationError


class EvaluationError(ApplicationError):
    def __init__(
        self,
        *,
        code: str = "EVALUATION_FAILED",
        message: str = "The independent evaluation could not be completed.",
        status_code: int = 503,
        details: Any | None = None,
    ) -> None:
        super().__init__(code=code, message=message, status_code=status_code, details=details)


class EvaluationConfigurationError(EvaluationError):
    def __init__(self, details: Any | None = None) -> None:
        super().__init__(
            code="EVALUATION_CONFIGURATION_ERROR",
            message="The evaluation provider is not configured.",
            details=details,
        )


class EvaluationResponseError(EvaluationError):
    def __init__(self) -> None:
        super().__init__(
            code="EVALUATION_RESPONSE_INVALID",
            message="The evaluation provider returned an invalid response.",
            status_code=502,
        )


class EvaluationBudgetError(EvaluationError):
    def __init__(self, details: Any | None = None) -> None:
        super().__init__(
            code="EVALUATION_BUDGET_EXCEEDED",
            message="The requested evaluation exceeds a configured safety budget.",
            status_code=422,
            details=details,
        )


class EvaluationDatasetError(EvaluationError):
    def __init__(self) -> None:
        super().__init__(
            code="EVALUATION_DATASET_INVALID",
            message="The configured evaluation dataset is unavailable or invalid.",
            status_code=503,
        )
