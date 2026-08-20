"""Provider-independent safe observability contract."""

from abc import ABC, abstractmethod
from typing import Any


class ObservabilityService(ABC):
    """Record allowlisted operational metadata without request or document content."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def enabled(self) -> bool: ...

    @abstractmethod
    def trace_id(self, request_id: str) -> str | None: ...

    @abstractmethod
    async def record_event(
        self,
        *,
        event: str,
        request_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> str | None: ...

    @abstractmethod
    async def close(self) -> None: ...
