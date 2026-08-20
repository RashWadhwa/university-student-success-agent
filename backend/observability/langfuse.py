"""Langfuse Cloud EU adapter with metadata-only observations."""

import asyncio
import logging
import re
from typing import Any, Protocol

from backend.observability.base import ObservabilityService
from backend.observability.redaction import sanitize_trace_metadata, validate_request_id

logger = logging.getLogger(__name__)
_EVENT_NAME = re.compile(r"^[a-z][a-z0-9_.-]{0,79}$")


class LangfuseClient(Protocol):
    @staticmethod
    def create_trace_id(*, seed: str) -> str: ...

    def start_as_current_observation(self, **kwargs: Any) -> Any: ...

    def shutdown(self) -> None: ...


class LangfuseObservability(ObservabilityService):
    """Emit safe spans; SDK/network failures never affect application requests."""

    def __init__(self, client: LangfuseClient, *, timeout_seconds: float = 0.5) -> None:
        self._client = client
        self._timeout_seconds = timeout_seconds
        self._available = True

    @property
    def name(self) -> str:
        return "langfuse"

    @property
    def enabled(self) -> bool:
        return self._available

    def trace_id(self, request_id: str) -> str | None:
        try:
            return self._client.create_trace_id(seed=validate_request_id(request_id))
        except Exception:
            return None

    async def record_event(
        self,
        *,
        event: str,
        request_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> str | None:
        if not self._available:
            return None
        try:
            if not _EVENT_NAME.fullmatch(event):
                raise ValueError("invalid trace event name")
            safe_request_id = validate_request_id(request_id)
            safe_metadata = sanitize_trace_metadata(metadata)
            trace_id = self._client.create_trace_id(seed=safe_request_id)
            async with asyncio.timeout(self._timeout_seconds):
                await asyncio.to_thread(
                    self._record,
                    event,
                    trace_id,
                    safe_request_id,
                    safe_metadata,
                )
            return trace_id
        except Exception as exc:
            self._available = False
            logger.warning(
                "Observability event was not exported",
                extra={"error_type": type(exc).__name__},
            )
            return None

    def _record(
        self,
        event: str,
        trace_id: str,
        request_id: str,
        metadata: dict[str, Any],
    ) -> None:
        with self._client.start_as_current_observation(
            as_type="span",
            name=event,
            trace_context={"trace_id": trace_id},
            metadata={"request_id": request_id, **metadata},
        ):
            pass

    async def close(self) -> None:
        try:
            async with asyncio.timeout(self._timeout_seconds):
                await asyncio.to_thread(self._client.shutdown)
        except Exception as exc:
            logger.warning(
                "Observability shutdown failed",
                extra={"error_type": type(exc).__name__},
            )
