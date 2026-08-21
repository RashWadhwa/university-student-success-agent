"""Logging remains useful without serialising sensitive payload fields or traces."""

import json
import logging

from backend.core.logging import JsonFormatter


def test_formatter_drops_sensitive_extras_and_exception_text() -> None:
    try:
        raise RuntimeError("private-memory-value")
    except RuntimeError:
        record = logging.getLogger("test").makeRecord(
            "test",
            logging.ERROR,
            __file__,
            1,
            "safe failure",
            (),
            __import__("sys").exc_info(),
            extra={
                "memory_fact": "private-memory-value",
                "prompt": "private-prompt",
                "route": "/api/v1/memory",
            },
        )

    payload = json.loads(JsonFormatter().format(record))
    assert payload["error_type"] == "RuntimeError"
    assert payload["route"] == "/api/v1/memory"
    assert "memory_fact" not in payload
    assert "prompt" not in payload
    assert "private-memory-value" not in json.dumps(payload)
