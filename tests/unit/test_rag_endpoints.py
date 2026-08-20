"""API tests for document indexing and citation-ready retrieval."""

from datetime import UTC, date, datetime
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.rag.types import FusedRetrievalResult, IndexingResult, RetrievalCandidate
from tests.pdf_factory import make_pdf


class FakeRetrievalService:
    async def search(self, **kwargs: object) -> list[FusedRetrievalResult]:
        del kwargs
        candidate = RetrievalCandidate(
            chunk_id="chunk-123",
            document_id="document-456",
            content="Independent evidence is normally required.",
            page=7,
            section="4.2 Evidence",
            title="Mitigating Circumstances Policy",
            document_type="policy",
            institution="Example University",
            version="3.0",
            effective_date=date(2026, 9, 1),
            review_date=None,
            source="https://example.edu/policy",
            score=0.91,
        )
        return [
            FusedRetrievalResult(
                candidate=candidate,
                score=1.0,
                evidence_score=0.91,
                retrieval_sources=["semantic", "keyword"],
                source_scores={"semantic": 0.91, "keyword": 0.7},
            )
        ]


def test_valid_retrieval_returns_citation_ready_result(
    app: FastAPI,
    client: TestClient,
) -> None:
    app.state.retrieval_service = FakeRetrievalService()

    response = client.post(
        "/api/v1/retrieval/search",
        json={
            "query": "What evidence is required for mitigating circumstances?",
            "top_k": 5,
            "filters": {"document_type": "policy"},
        },
    )

    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["page"] == 7
    assert result["section"] == "4.2 Evidence"
    assert result["retrieval_sources"] == ["semantic", "keyword"]
    assert result["metadata"]["version"] == "3.0"


def test_retrieval_request_validation_uses_structured_errors(client: TestClient) -> None:
    empty = client.post("/api/v1/retrieval/search", json={"query": "   "})
    invalid_top_k = client.post("/api/v1/retrieval/search", json={"query": "appeal", "top_k": 100})
    invalid_filter = client.post(
        "/api/v1/retrieval/search",
        json={"query": "appeal", "filters": {"arbitrary_sql": "DROP TABLE chunks"}},
    )

    assert empty.status_code == 422
    assert invalid_top_k.status_code == 422
    assert invalid_filter.status_code == 422
    assert invalid_filter.json()["error"]["code"] == "VALIDATION_ERROR"


def test_invalid_filter_date_range_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/retrieval/search",
        json={
            "query": "extension",
            "filters": {
                "effective_on_or_after": "2026-09-02",
                "effective_on_or_before": "2026-09-01",
            },
        },
    )

    assert response.status_code == 422


class FakeIndexingService:
    async def index_document(self, record: object, metadata: object) -> IndexingResult:
        del metadata
        return IndexingResult(
            document_id=record.id,  # type: ignore[attr-defined]
            status="indexed",
            chunk_count=len(record.chunks),  # type: ignore[attr-defined]
            embedding_model="mock-embedding-v1",
            indexed_at=datetime.now(UTC),
        )


def test_valid_indexing_request_uses_ingested_record(
    app: FastAPI,
    client: TestClient,
) -> None:
    app.state.indexing_service = FakeIndexingService()
    upload = client.post(
        "/api/v1/documents",
        files={
            "file": (
                "policy.pdf",
                make_pdf("Policy evidence and deadline requirements."),
                "application/pdf",
            )
        },
    )
    document_id = upload.json()["document"]["id"]

    response = client.post(
        f"/api/v1/documents/{document_id}/index",
        json={"title": "Assessment Policy", "document_type": "academic_policy"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "indexed"
    assert response.json()["document_id"] == document_id


def test_indexing_unknown_ingestion_record_returns_404(
    app: FastAPI,
    client: TestClient,
) -> None:
    app.state.indexing_service = FakeIndexingService()
    app.state.document_manager = SimpleNamespace(get_document=lambda document_id: None)

    response = client.post(
        "/api/v1/documents/00000000-0000-0000-0000-000000000001/index",
        json={},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"
