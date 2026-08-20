"""Request-scoped context variables."""

from contextvars import ContextVar

request_id_context: ContextVar[str] = ContextVar("request_id", default="-")


def get_request_id() -> str:
    """Return the current request ID or ``-`` outside a request."""

    return request_id_context.get()
