"""Full HTTP→PostgreSQL/pgvector→grounded-answer path with no live LLM."""

from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.ask.models import GroundedAnswerOutput
from backend.core.config import Environment, LLMProviderName, Settings
from backend.llm.providers.mock_provider import MockLLMProvider
from backend.main import create_app
from tests.pdf_factory import make_pdf

pytestmark = pytest.mark.integration


def test_pdf_to_grounded_ask_api_with_postgres_and_mock_llm(
    migrated_database_url: str,
    tmp_path: Path,
) -> None:
    marker = f"policyref{uuid4().hex}"
    generated = {
        "answer": (
            "The policy indicates that a student who missed an assessment because of illness "
            "may use the mitigating circumstances procedure."
        ),
        "recommended_actions": [
            {
                "priority": 1,
                "action": "Review the published mitigating circumstances procedure.",
                "reason": "The indexed policy identifies this as the relevant route.",
                "basis": "policy",
                "citation_ids": ["E1"],
            }
        ],
        "citations": [{"citation_id": "E1"}],
        "limitations": [],
        "confidence": "high",
        "requires_human_support": False,
        "human_support_reason": None,
    }
    provider = MockLLMProvider(
        structured_responses={GroundedAnswerOutput: generated},
        embedding_dimensions=8,
    )
    settings = Settings(
        _env_file=None,
        environment=Environment.TESTING,
        llm_provider=LLMProviderName.MOCK,
        database_url=migrated_database_url,
        document_storage_path=tmp_path / "ask-documents",
        embedding_dimensions=8,
        ask_min_retrieval_score=0.0,
        cors_origins=[],
    )
    app = create_app(settings, llm_provider=provider)
    pdf = make_pdf(
        "MITIGATING CIRCUMSTANCES\n"
        "Students who miss an assessment because of illness may submit a mitigating "
        f"circumstances claim using the published procedure. Reference {marker}.",
        title="Mitigating Circumstances Policy",
    )

    with TestClient(app) as client:
        upload = client.post(
            "/api/v1/documents",
            files={"file": ("assessment-policy.pdf", pdf, "application/pdf")},
        )
        assert upload.status_code == 201
        document_id = upload.json()["document"]["id"]

        indexed = client.post(
            f"/api/v1/documents/{document_id}/index",
            json={
                "title": "Mitigating Circumstances Policy",
                "document_type": "academic_policy",
                "institution": marker,
                "effective_date": "2025-09-01",
                "version": "3.0",
                "source": f"https://example.edu/{marker}",
            },
        )
        assert indexed.status_code == 200

        response = client.post(
            "/api/v1/ask",
            headers={"X-Request-ID": "integration-ask-request"},
            json={
                "question": "I missed an assessment because I was ill. What should I do?",
                "top_k": 5,
                "filters": {
                    "document_type": "academic_policy",
                    "institution": marker,
                },
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "answered"
    assert body["citations"][0]["document_id"] == document_id
    assert body["citations"][0]["page"] == 1
    assert "mitigating circumstances" in body["citations"][0]["excerpt"].lower()
    assert body["evaluation"]["citation_verification_passed"] is True
    assert body["requires_human_support"] is False
    assert body["request_id"] == "integration-ask-request"
