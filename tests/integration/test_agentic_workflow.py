"""PostgreSQL/pgvector integration for the controlled agentic ask path."""

from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.agents.models import PolicyAnalysisOutput, StudentSupportOutput
from backend.core.config import Environment, LLMProviderName, Settings
from backend.llm.providers.mock_provider import MockLLMProvider
from backend.main import create_app
from tests.pdf_factory import make_pdf

pytestmark = pytest.mark.integration


def test_indexed_policy_to_verified_agentic_response(
    migrated_database_url: str,
    tmp_path: Path,
) -> None:
    marker = f"agenticpolicy{uuid4().hex}"
    provider = MockLLMProvider(
        structured_responses={
            PolicyAnalysisOutput: {
                "findings": [
                    {
                        "statement": ("Illness may be addressed through mitigating circumstances."),
                        "citation_ids": ["E1"],
                    }
                ],
                "deadlines": [
                    {
                        "statement": "Academic appeals must be filed within 10 working days.",
                        "deadline": "10 working days",
                        "citation_ids": ["E1"],
                    }
                ],
                "evidence_requirements": [],
                "exceptions": [],
                "conflicts": [],
                "uncertainties": [],
            },
            StudentSupportOutput: {
                "answer": (
                    "Review mitigating circumstances and the 10 working day appeal deadline."
                ),
                "actions": [
                    {
                        "priority": 1,
                        "action": "Review both published university procedures.",
                        "reason": "The indexed policy identifies both routes.",
                        "basis": "policy",
                        "citation_ids": ["E1"],
                    }
                ],
                "citation_ids": ["E1"],
                "limitations": [],
                "requires_human_support": False,
                "human_support_reason": None,
            },
        },
        embedding_dimensions=8,
    )
    settings = Settings(
        _env_file=None,
        environment=Environment.TESTING,
        llm_provider=LLMProviderName.MOCK,
        database_url=migrated_database_url,
        document_storage_path=tmp_path / "agentic-documents",
        embedding_dimensions=8,
        ask_min_retrieval_score=0.0,
        cors_origins=[],
    )
    app = create_app(settings, llm_provider=provider)
    pdf = make_pdf(
        "MITIGATING CIRCUMSTANCES AND APPEALS\n"
        "Students affected by illness may submit mitigating circumstances. "
        "Academic appeals must be filed within 10 working days. "
        f"Reference {marker}.",
        title="Assessment Appeals Policy",
    )

    with TestClient(app) as client:
        upload = client.post(
            "/api/v1/documents",
            files={"file": ("agentic-policy.pdf", pdf, "application/pdf")},
        )
        assert upload.status_code == 201
        document_id = upload.json()["document"]["id"]
        indexed = client.post(
            f"/api/v1/documents/{document_id}/index",
            json={
                "title": "Assessment Appeals Policy",
                "document_type": "academic_policy",
                "institution": marker,
                "effective_date": "2025-09-01",
                "version": "1.0",
                "source": f"https://example.edu/{marker}",
            },
        )
        assert indexed.status_code == 200
        response = client.post(
            "/api/v1/ask/agentic",
            headers={"X-Request-ID": "integration-agentic-request"},
            json={
                "question": (
                    "I missed an assessment due to illness. How do mitigating circumstances "
                    f"and an academic appeal apply? Reference {marker}."
                ),
                "filters": {
                    "document_type": "academic_policy",
                    "institution": marker,
                },
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "answered"
    assert body["request_id"] == "integration-agentic-request"
    assert body["citations"][0]["document_id"] == document_id
    assert body["evaluation"]["citation_verification_passed"] is True
    assert body["workflow"]["workflow_mode"] == "agentic"
    assert body["workflow"]["agents_used"] == [
        "coordinator",
        "retrieval",
        "policy_analyst",
        "student_support",
        "verifier",
    ]
    assert body["workflow"]["tool_calls"] == 1
    assert body["workflow"]["provider_calls"] == 3
