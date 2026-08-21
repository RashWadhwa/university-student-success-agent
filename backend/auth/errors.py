"""Safe authentication and authorization errors."""

from backend.core.exceptions import ApplicationError


class AuthenticationError(ApplicationError):
    def __init__(self, message: str = "Authentication is required.") -> None:
        super().__init__(code="AUTHENTICATION_REQUIRED", message=message, status_code=401)


class AuthorizationError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="INSUFFICIENT_PERMISSION",
            message="You do not have permission to perform this action.",
            status_code=403,
        )
