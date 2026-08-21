"""Structured JSON logging built on Python's standard logging package."""

import json
import logging
from datetime import UTC, datetime
from typing import Any

from backend.core.context import get_request_id

_STANDARD_LOG_RECORD_FIELDS = set(logging.makeLogRecord({}).__dict__)
_FORBIDDEN_EXTRA_FRAGMENTS = (
    "question",
    "prompt",
    "content",
    "evidence",
    "answer",
    "memory",
    "fact",
    "token",
    "secret",
    "password",
    "credential",
    "database_url",
    "connection_string",
)


class JsonFormatter(logging.Formatter):
    """Format log records as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", get_request_id()),
        }

        for key, value in record.__dict__.items():
            if (
                key not in _STANDARD_LOG_RECORD_FIELDS
                and key not in payload
                and not any(fragment in key.casefold() for fragment in _FORBIDDEN_EXTRA_FRAGMENTS)
            ):
                payload[key] = value

        if record.exc_info:
            payload["error_type"] = record.exc_info[0].__name__

        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(log_level: str = "INFO") -> None:
    """Configure the root logger with a consistent structured handler."""

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(log_level)

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root_logger.addHandler(handler)

    # Keep server access logging from duplicating our request-completion log.
    logging.getLogger("uvicorn.access").disabled = True
    # Third-party debug logs can contain request or connection context. Application
    # events provide the safe observability surface even when our own level is DEBUG.
    for logger_name in (
        "openai",
        "httpx",
        "httpcore",
        "asyncpg",
        "sqlalchemy.engine",
        "langfuse",
        "pypdf",
    ):
        logging.getLogger(logger_name).disabled = True
