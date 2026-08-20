"""Expected ask-workflow errors safe for API responses."""

from typing import Any

from backend.core.exceptions import ApplicationError


class AskValidationError(ApplicationError):
    def __init__(self, details: Any | None = None) -> None:
        super().__init__(
            code="ASK_VALIDATION_ERROR",
            message="The question could not be validated.",
            status_code=422,
            details=details,
        )
