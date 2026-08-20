"""Safe observability construction with no-op degradation."""

import logging
from collections.abc import Callable
from typing import Any

from backend.core.config import Settings
from backend.observability.base import ObservabilityService
from backend.observability.langfuse import LangfuseObservability
from backend.observability.noop import NoOpObservability

logger = logging.getLogger(__name__)


def create_observability(
    settings: Settings,
    *,
    client_factory: Callable[..., Any] | None = None,
) -> ObservabilityService:
    if not settings.langfuse_enabled:
        return NoOpObservability()
    try:
        if client_factory is None:
            from langfuse import Langfuse

            client_factory = Langfuse
        client = client_factory(
            public_key=settings.langfuse_public_key.get_secret_value(),
            secret_key=settings.langfuse_secret_key.get_secret_value(),
            base_url=settings.langfuse_host,
            tracing_enabled=True,
        )
        return LangfuseObservability(
            client,
            timeout_seconds=settings.langfuse_event_timeout_seconds,
        )
    except Exception as exc:
        logger.warning(
            "Observability initialisation failed",
            extra={"error_type": type(exc).__name__},
        )
        return NoOpObservability()
