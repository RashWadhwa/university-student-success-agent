"""No-op observability for local development, tests, and graceful degradation."""

from typing import Any

from backend.observability.base import ObservabilityService


class NoOpObservability(ObservabilityService):
    @property
    def name(self) -> str:
        return "disabled"

    @property
    def enabled(self) -> bool:
        return False

    def trace_id(self, request_id: str) -> None:
        del request_id
        return None

    async def record_event(
        self,
        *,
        event: str,
        request_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        del event, request_id, metadata
        return None

    async def close(self) -> None:
        return None
