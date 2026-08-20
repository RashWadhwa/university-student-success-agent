"""API tests for typed grounded answers, validation, and safe fallbacks."""

from datetime import date

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.ask.types import (
    AskOutcome,
    AskResult,
    Citation,
    Confidence,
    RecommendedAction,
)
from backend.core.config import Settings
from backend.core.context import get_request_id


class FakeAskService:
    def __init__(self, *, fallback: bool = False) -> None:
        self.fallback = fallback
        self.calls: list[dict[str, object]] = []

    async def answer(self, **kwargs: object) -> AskResult:
        self.calls.append(kwargs)
        if self.fallback:
            return AskResult(
                outcome=AskOutcome.INSUFFICIENT_EVIDENCE,
                answer="I could not find enough reliable university policy evidence.",
                recommended_actions=(),
                citations=(),
                confidence=Confidence.LOW,
                limitations=("No passage met the configured evidence threshold.",),
                requires_human_support=True,
                human_support_reason="Policy evidence was insufficient.",
                request_id=get_request_id(),
                retrieved_count=0,
                evidence_count=0,
                citation_verification_passed=False,
                evaluation={"retrieval_strength": 0.0},
            )
        return AskResult(
            outcome=AskOutcome.ANSWERED,
            answer="The policy identifies mitigating circumstances as the formal route.",
            recommended_actions=(
                RecommendedAction(
                    priority=1,
                    action="Review the mitigating circumstances procedure.",
                    reason="It describes the university process.",
                ),
            ),
            citations=(
                Citation(
                    citation_id="E1",
                    document_id="doc-1",
                    chunk_id="chunk-1",
                    document_title="Mitigating Circumstances Policy",
                    section="4.2 Evidence",
                    page=7,
                    source="https://example.edu/policy",
                    excerpt="Students affected by illness may submit a claim.",
                    version="3.0",
                    effective_date=date(2025, 9, 1),
                    retrieval_sources=("semantic", "keyword"),
                ),
            ),
            confidence=Confidence.HIGH,
            limitations=(),
            requires_human_support=False,
            human_support_reason=None,
            request_id=get_request_id(),
            retrieved_count=2,
            evidence_count=2,
            citation_verification_passed=True,
            evaluation={"retrieval_strength": 0.92},
        )


def test_valid_ask_returns_typed_grounded_response(
    app: FastAPI,
    client: TestClient,
    test_settings: Settings,
) -> None:
    service = FakeAskService()
    app.state.ask_service = service

    response = client.post(
        "/api/v1/ask",
        headers={"X-Request-ID": "ask-request-1"},
        json={
            "question": "I missed an assessment because I was ill. What should I do?",
            "top_k": 5,
            "filters": {"document_type": "academic_policy"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "answered"
    assert body["citations"][0]["citation_id"] == "E1"
    assert body["citations"][0]["page"] == 7
    assert body["citations"][0]["corpus_tier"] == "primary"
    assert body["citations"][0]["authority_scope"] == "institution_policy"
    assert body["confidence"] == "high"
    assert body["request_id"] == "ask-request-1"
    assert body["evaluation"]["citation_verification_passed"] is True
    assert service.calls[0]["top_k"] == 5
    assert service.calls[0]["filters"].institution == test_settings.primary_institution_name
    assert service.calls[0]["filters"].corpus_tier.value == "primary"


def test_empty_question_uses_existing_validation_envelope(client: TestClient) -> None:
    response = client.post("/api/v1/ask", json={"question": "   "})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_configured_overlong_question_and_invalid_top_k_are_rejected(
    client: TestClient,
) -> None:
    overlong = client.post("/api/v1/ask", json={"question": "x" * 2001})
    invalid_top_k = client.post(
        "/api/v1/ask",
        json={"question": "Can I appeal an assessment decision?", "top_k": 11},
    )

    assert overlong.status_code == 422
    assert overlong.json()["error"]["code"] == "ASK_VALIDATION_ERROR"
    assert invalid_top_k.status_code == 422
    assert invalid_top_k.json()["error"]["code"] == "ASK_VALIDATION_ERROR"


def test_invalid_metadata_filter_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/ask",
        json={
            "question": "Can I request an extension?",
            "filters": {"arbitrary_sql": "DROP TABLE chunks"},
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_structured_insufficient_evidence_fallback(
    app: FastAPI,
    client: TestClient,
) -> None:
    app.state.ask_service = FakeAskService(fallback=True)

    response = client.post(
        "/api/v1/ask",
        json={"question": "What is the assessment extension process?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "insufficient_evidence"
    assert body["confidence"] == "low"
    assert body["requires_human_support"] is True
    assert body["citations"] == []
    serialized = response.text.lower()
    assert "traceback" not in serialized
    assert "asyncpg" not in serialized
    assert "database_url" not in serialized
