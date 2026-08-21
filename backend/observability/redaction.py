"""Fail-closed trace metadata validation and sanitisation."""

import re
from collections.abc import Mapping
from typing import Any

_SAFE_KEY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_SAFE_TEXT_VALUE = re.compile(r"^[A-Za-z0-9._:/-]{1,200}$")
_STUDENT_ID = re.compile(r"^[sS]\d{6,10}$")
_PHONE_LIKE = re.compile(r"^\d{7,15}$")
_ALLOWED_KEYS = frozenset(
    {
        "workflow_mode",
        "provider",
        "model",
        "latency_ms",
        "input_length",
        "output_length",
        "token_count",
        "retrieval_count",
        "citation_count",
        "agent_names",
        "tool_names",
        "confidence",
        "terminal_state",
        "evaluation_score",
        "case_count",
        "judge_calls",
        "provider_calls",
        "tool_calls",
        "success",
        "outcome",
        "error_category",
    }
)
_FORBIDDEN_FRAGMENTS = (
    "question",
    "answer",
    "content",
    "evidence",
    "prompt",
    "document",
    "session",
    "email",
    "phone",
    "student",
    "secret",
    "password",
    "credential",
    "api_key",
    "database_url",
    "connection",
    "memory",
    "tenant",
    "user_id",
    "audit",
)


class UnsafeTraceMetadataError(ValueError):
    """Raised before a trace provider sees unsafe or unexpected metadata."""


def validate_request_id(request_id: str) -> str:
    if (
        not _SAFE_ID.fullmatch(request_id)
        or _STUDENT_ID.fullmatch(request_id)
        or _PHONE_LIKE.fullmatch(request_id)
    ):
        raise UnsafeTraceMetadataError("request_id is not safe for trace correlation")
    return request_id


def sanitize_trace_metadata(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return a small allowlisted payload or reject the entire event."""

    if metadata is None:
        return {}
    safe: dict[str, Any] = {}
    for key, value in metadata.items():
        normalized = key.casefold()
        if (
            not _SAFE_KEY.fullmatch(key)
            or key not in _ALLOWED_KEYS
            or any(fragment in normalized for fragment in _FORBIDDEN_FRAGMENTS)
        ):
            raise UnsafeTraceMetadataError("trace metadata contained a forbidden field")
        safe[key] = _safe_value(value)
    return safe


def _safe_value(value: Any) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return value
    if isinstance(value, str):
        if (
            not _SAFE_TEXT_VALUE.fullmatch(value)
            or _STUDENT_ID.fullmatch(value)
            or _PHONE_LIKE.fullmatch(value)
        ):
            raise UnsafeTraceMetadataError("trace metadata string was not a safe identifier")
        return value
    if isinstance(value, list | tuple):
        if len(value) > 10:
            raise UnsafeTraceMetadataError("trace metadata list exceeded safe bounds")
        return [_safe_value(item) for item in value]
    raise UnsafeTraceMetadataError("trace metadata value type is not permitted")
