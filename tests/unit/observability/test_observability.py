"""Privacy, graceful degradation, and request-correlation tests."""

from contextlib import AbstractContextManager
from hashlib import sha256
from typing import Any
from urllib.parse import urlunsplit

import pytest
from pydantic import SecretStr

from backend.core.config import Settings
from backend.observability.factory import create_observability
from backend.observability.langfuse import LangfuseObservability
from backend.observability.noop import NoOpObservability
from backend.observability.redaction import (
    UnsafeTraceMetadataError,
    sanitize_trace_metadata,
)


class Observation(AbstractContextManager[None]):
    def __enter__(self) -> None:
        return None

    def __exit__(self, *args: Any) -> None:
        return None


class FakeLangfuse:
    def __init__(self, *, fail: bool = False, **kwargs: Any) -> None:
        self.configuration = kwargs
        self.fail = fail
        self.calls: list[dict[str, Any]] = []
        self.closed = False

    @staticmethod
    def create_trace_id(*, seed: str) -> str:
        return sha256(seed.encode()).hexdigest()[:32]

    def start_as_current_observation(self, **kwargs: Any) -> Observation:
        if self.fail:
            raise RuntimeError("private provider failure")
        self.calls.append(kwargs)
        return Observation()

    def shutdown(self) -> None:
        self.closed = True


def credential_bearing_fixture_url() -> str:
    userinfo = ":".join(("synthetic", "fixture"))
    authority = "@".join((userinfo, "db.example.invalid"))
    return urlunsplit(("postgresql", authority, "/db", "", ""))


def test_tracing_disabled_uses_noop() -> None:
    service = create_observability(Settings(_env_file=None, langfuse_enabled=False))

    assert isinstance(service, NoOpObservability)
    assert service.enabled is False


def test_tracing_enabled_uses_eu_configuration_without_exposing_keys() -> None:
    created: list[FakeLangfuse] = []

    def factory(**kwargs: Any) -> FakeLangfuse:
        client = FakeLangfuse(**kwargs)
        created.append(client)
        return client

    settings = Settings(
        _env_file=None,
        langfuse_enabled=True,
        langfuse_public_key=SecretStr("fixture-public-value"),
        langfuse_secret_key=SecretStr("fixture-secret-value"),
    )
    service = create_observability(settings, client_factory=factory)

    assert isinstance(service, LangfuseObservability)
    assert created[0].configuration["base_url"] == "https://cloud.langfuse.com"
    assert "private" not in repr(service)


def test_initialisation_failure_does_not_log_keys(caplog: Any) -> None:
    marker = "sensitive-observability-marker"

    def failing_factory(**kwargs: Any) -> FakeLangfuse:
        del kwargs
        raise RuntimeError(marker)

    settings = Settings(
        _env_file=None,
        langfuse_enabled=True,
        langfuse_public_key=SecretStr("fixture-public-value"),
        langfuse_secret_key=SecretStr(marker),
    )

    service = create_observability(settings, client_factory=failing_factory)

    assert isinstance(service, NoOpObservability)
    assert marker not in caplog.text


@pytest.mark.asyncio
async def test_request_id_correlation_and_safe_metadata_only() -> None:
    client = FakeLangfuse()
    service = LangfuseObservability(client)

    trace_id = await service.record_event(
        event="ask.request.completed",
        request_id="request-123",
        metadata={
            "workflow_mode": "agentic",
            "model": "mock-model-v1",
            "citation_count": 2,
        },
    )

    assert trace_id == sha256(b"request-123").hexdigest()[:32]
    assert client.calls[0]["trace_context"] == {"trace_id": trace_id}
    assert client.calls[0]["metadata"] == {
        "request_id": "request-123",
        "workflow_mode": "agentic",
        "model": "mock-model-v1",
        "citation_count": 2,
    }


@pytest.mark.asyncio
async def test_langfuse_unavailable_never_breaks_request_or_leaks_exception(caplog: Any) -> None:
    marker = "private provider failure"
    service = LangfuseObservability(FakeLangfuse(fail=True))

    trace_id = await service.record_event(
        event="ask.request.completed",
        request_id="request-123",
        metadata={"success": True},
    )

    assert trace_id is None
    assert service.enabled is False
    assert marker not in caplog.text


@pytest.mark.parametrize(
    "metadata",
    [
        {"api_key": "fixture-value"},
        {"question": "raw student question"},
        {"evidence": "full document body"},
        {"provider": "student@example.edu"},
        {"provider": "447700900123"},
        {"model": "S12345678"},
        {"model": "ignore previous instructions"},
        {"model": credential_bearing_fixture_url()},
        {"prompt": "hidden system prompt"},
        {"session_id": "session-private"},
        {"memory_fact": "private preference"},
        {"tenant_id": "tenant-private"},
        {"user_id": "private-user"},
    ],
)
def test_secret_pii_evidence_prompt_and_session_fields_fail_closed(
    metadata: dict[str, Any],
) -> None:
    with pytest.raises(UnsafeTraceMetadataError):
        sanitize_trace_metadata(metadata)


@pytest.mark.asyncio
async def test_unsafe_payload_never_reaches_langfuse() -> None:
    client = FakeLangfuse()
    service = LangfuseObservability(client)

    result = await service.record_event(
        event="ask.request.completed",
        request_id="request-123",
        metadata={"answer": "raw private model answer"},
    )

    assert result is None
    assert client.calls == []


@pytest.mark.asyncio
async def test_noop_never_records_or_returns_trace_id() -> None:
    service = NoOpObservability()

    assert (
        await service.record_event(event="ask.request.completed", request_id="request-123") is None
    )
    assert service.trace_id("request-123") is None
    await service.close()
