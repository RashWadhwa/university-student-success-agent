"""HTTP contract and security tests for the Stage 6 endpoint."""

from typing import Any
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.agents.types import (
    AgenticAskResult,
    AgentName,
    WorkflowMode,
    WorkflowStatus,
)
from backend.ask.types import AskOutcome, AskResult, Confidence
from backend.core.context import get_request_id


def ask_result() -> AskResult:
    return AskResult(
        outcome=AskOutcome.ANSWERED,
        answer="Review the applicable university procedure.",
        recommended_actions=(),
        citations=(),
        confidence=Confidence.MEDIUM,
        limitations=(),
        requires_human_support=False,
        human_support_reason=None,
        request_id=get_request_id(),
        retrieved_count=1,
        evidence_count=1,
        citation_verification_passed=True,
        evaluation={"retrieval_strength": 0.8, "provider_calls": 3},
    )


class FakeAgenticService:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def answer(self, **kwargs: Any) -> AgenticAskResult:
        self.calls.append(kwargs)
        return AgenticAskResult(
            result=ask_result(),
            workflow_mode=WorkflowMode.AGENTIC,
            agents_used=(
                AgentName.COORDINATOR,
                AgentName.RETRIEVAL,
                AgentName.POLICY_ANALYST,
                AgentName.STUDENT_SUPPORT,
                AgentName.VERIFIER,
            ),
            tool_calls=1,
            provider_calls=3,
            duration_ms=12.5,
            verification_passed=True,
            terminal_state=WorkflowStatus.COMPLETED,
        )


class FakeBaselineService:
    async def answer(self, **kwargs: Any) -> AskResult:
        del kwargs
        return ask_result()


def test_baseline_and_agentic_endpoints_coexist(
    app: FastAPI,
    client: TestClient,
) -> None:
    agentic = FakeAgenticService()
    app.state.ask_service = FakeBaselineService()
    app.state.agentic_ask_service = agentic

    baseline_response = client.post(
        "/api/v1/ask",
        json={"question": "How do extensions work?"},
    )
    agentic_response = client.post(
        "/api/v1/ask/agentic",
        headers={"X-Request-ID": "agentic-request-123"},
        json={
            "question": "I missed an assessment and want to appeal.",
            "filters": {"document_type": "academic_policy"},
        },
    )

    assert baseline_response.status_code == 200
    assert "workflow" not in baseline_response.json()
    assert agentic_response.status_code == 200
    body = agentic_response.json()
    assert body["request_id"] == "agentic-request-123"
    assert agentic_response.headers["x-request-id"] == "agentic-request-123"
    assert body["workflow"] == {
        "workflow_mode": "agentic",
        "agents_used": [
            "coordinator",
            "retrieval",
            "policy_analyst",
            "student_support",
            "verifier",
        ],
        "tool_calls": 1,
        "retrieval_count": 1,
        "citation_count": 0,
        "confidence": "medium",
        "requires_human_support": False,
        "duration_ms": 12.5,
        "provider_calls": 3,
        "verification_passed": True,
        "terminal_state": "completed",
    }
    assert agentic.calls[0]["session_id"] is None


def test_agentic_request_is_strictly_validated(app: FastAPI, client: TestClient) -> None:
    app.state.agentic_ask_service = FakeAgenticService()

    response = client.post(
        "/api/v1/ask/agentic",
        json={
            "question": "Appeal question",
            "top_k": 101,
            "sql": "SELECT * FROM documents",
        },
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["request_id"] == response.headers["x-request-id"]


def test_agentic_exception_does_not_leak_provider_or_database_details(
    app: FastAPI,
    client: TestClient,
) -> None:
    secret = "private database connection marker"

    class FailingService:
        async def answer(self, **kwargs: Any) -> Any:
            del kwargs
            raise RuntimeError(secret)

    app.state.agentic_ask_service = FailingService()
    with (
        patch("backend.core.exceptions.logger.error") as handler_log,
        patch("backend.core.middleware.logger.error") as middleware_log,
    ):
        response = client.post(
            "/api/v1/ask/agentic",
            json={"question": "I missed an assessment and want to appeal."},
        )

    assert response.status_code == 500
    assert secret not in response.text
    calls = handler_log.call_args_list + middleware_log.call_args_list
    assert len(calls) == 1
    assert secret not in repr(calls[0])
    assert calls[0].kwargs["extra"]["error_type"] == "RuntimeError"


def test_no_unsafe_agent_debug_endpoint_is_exposed(client: TestClient) -> None:
    response = client.get("/api/v1/ask/agentic/debug")

    assert response.status_code == 404
    assert "prompt" not in response.text.casefold()
    assert "evidence" not in response.text.casefold()
