"""End-to-end PostgreSQL and pgvector indexing/retrieval integration tests."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from backend.database.manager import DatabaseManager
from backend.database.models import ChunkModel, DocumentModel
from backend.documents.manager import DocumentManager
from backend.documents.models import ChunkRecord, DocumentRecord, PageRecord
from backend.llm.providers.mock_provider import MockLLMProvider
from backend.rag.indexing import IndexingService
from backend.rag.retrieval import RetrievalService
from backend.rag.types import DocumentIndexMetadata, SearchFilters
from backend.repositories.documents import DocumentVectorRepository
from tests.pdf_factory import make_pdf

pytestmark = pytest.mark.integration


@dataclass
class UploadStub:
    content: bytes
    filename: str | None = "mitigating-circumstances.pdf"
    content_type: str | None = "application/pdf"

    async def read(self, size: int = -1) -> bytes:
        return self.content if size < 0 else self.content[:size]


def policy_record() -> DocumentRecord:
    document_id = str(uuid4())
    texts = [
        "Mitigating circumstances require independent evidence before the deadline.",
        "Reassessment rules apply after a failed assessment attempt.",
    ]
    chunks = [
        ChunkRecord(
            id=str(uuid4()),
            index=index,
            text=text,
            char_count=len(text),
            page_start=index + 1,
            page_end=index + 1,
            heading="Evidence" if index == 0 else "Reassessment",
        )
        for index, text in enumerate(texts)
    ]
    return DocumentRecord(
        id=document_id,
        original_filename="assessment-policy.pdf",
        stored_filename="b" * 64 + ".pdf",
        media_type="application/pdf",
        size_bytes=200,
        checksum_sha256="b" * 64,
        page_count=2,
        chunk_count=2,
        created_at=datetime.now(UTC),
        metadata={"/Title": "Assessment Policy"},
        pages=[
            PageRecord(page_number=1, text=texts[0], char_count=len(texts[0])),
            PageRecord(page_number=2, text=texts[1], char_count=len(texts[1])),
        ],
        chunks=chunks,
    )


@pytest.mark.asyncio
async def test_migration_readiness_persistence_and_duplicate_prevention(
    integration_database: DatabaseManager,
) -> None:
    readiness = await integration_database.check_readiness()
    assert readiness.database is True
    assert readiness.pgvector is True

    provider = MockLLMProvider(embedding_dimensions=8)
    service = IndexingService(
        database=integration_database,
        provider=provider,
        embedding_batch_size=1,
        embedding_dimensions=8,
    )
    record = policy_record()
    metadata = DocumentIndexMetadata(
        title="Mitigating Circumstances and Assessment Policy",
        document_type="academic_policy",
        institution="Example University",
        effective_date=date(2026, 9, 1),
        version="3.0",
        source="https://example.edu/assessment-policy",
    )

    first = await service.index_document(record, metadata)
    duplicate = await service.index_document(record, metadata)

    assert first.status == "indexed"
    assert duplicate.status == "already_indexed"
    async with integration_database.session() as session:
        assert await session.scalar(select(func.count()).select_from(DocumentModel)) == 1
        assert await session.scalar(select(func.count()).select_from(ChunkModel)) == 2
        persisted = await session.scalar(select(DocumentModel))
        assert persisted is not None
        assert persisted.institution == "Example University"
        assert persisted.version == "3.0"


@pytest.mark.asyncio
async def test_semantic_keyword_hybrid_filters_and_citations(
    integration_database: DatabaseManager,
) -> None:
    provider = MockLLMProvider(embedding_dimensions=8)
    record = policy_record()
    await IndexingService(
        database=integration_database,
        provider=provider,
        embedding_batch_size=2,
        embedding_dimensions=8,
    ).index_document(
        record,
        DocumentIndexMetadata(
            title="Assessment Policy",
            document_type="academic_policy",
            institution="Example University",
            version="3.0",
        ),
    )
    query_embedding = (await provider.create_embeddings([record.chunks[0].text])).embeddings[0]

    async with integration_database.session() as session:
        repository = DocumentVectorRepository(session)
        semantic = await repository.semantic_search(
            query_embedding,
            limit=2,
            filters=SearchFilters(institution="Example University"),
            minimum_score=0.0,
        )
        keyword = await repository.keyword_search(
            "mitigating circumstances evidence",
            limit=2,
            filters=SearchFilters(document_type="academic_policy"),
        )
        filtered_out = await repository.keyword_search(
            "mitigating circumstances",
            limit=2,
            filters=SearchFilters(institution="Different University"),
        )
        date_filtered_out = await repository.keyword_search(
            "mitigating circumstances",
            limit=2,
            filters=SearchFilters(effective_on_or_after=date(2027, 1, 1)),
        )

    assert semantic[0].chunk_id == record.chunks[0].id
    assert keyword[0].section == "Evidence"
    assert keyword[0].page == 1
    assert filtered_out == []
    assert date_filtered_out == []

    hybrid = await RetrievalService(
        database=integration_database,
        provider=provider,
        embedding_dimensions=8,
    ).search(
        query="mitigating circumstances evidence",
        top_k=2,
        filters=SearchFilters(institution="Example University"),
        minimum_score=0.0,
        prefer_recent=False,
    )

    assert hybrid
    assert hybrid[0].candidate.title == "Assessment Policy"
    assert hybrid[0].candidate.page >= 1
    assert "keyword" in hybrid[0].retrieval_sources


@pytest.mark.asyncio
async def test_pdf_ingestion_to_citation_ready_retrieval(
    integration_database: DatabaseManager,
    tmp_path: Path,
) -> None:
    content = make_pdf(
        "MITIGATING CIRCUMSTANCES\nIndependent evidence must explain the impact and date.",
        title="Mitigating Circumstances Policy",
    )
    record = await DocumentManager(
        storage_path=tmp_path / "documents",
        max_file_size_bytes=1024 * 1024,
        chunk_size=300,
        chunk_overlap=40,
    ).ingest(UploadStub(content))
    provider = MockLLMProvider(embedding_dimensions=8)
    indexed = await IndexingService(
        database=integration_database,
        provider=provider,
        embedding_batch_size=8,
        embedding_dimensions=8,
    ).index_document(
        record,
        DocumentIndexMetadata(
            title="Mitigating Circumstances Policy",
            document_type="academic_policy",
            institution="Example University",
            effective_date=date(2026, 9, 1),
        ),
    )
    results = await RetrievalService(
        database=integration_database,
        provider=provider,
        embedding_dimensions=8,
    ).search(
        query="What independent evidence is needed?",
        top_k=3,
        filters=SearchFilters(document_type="academic_policy"),
        minimum_score=0.0,
        prefer_recent=False,
    )

    assert indexed.status == "indexed"
    assert results[0].candidate.document_id == record.id
    assert results[0].candidate.page == 1
    assert results[0].candidate.section == "MITIGATING CIRCUMSTANCES"
    assert "Independent evidence" in results[0].candidate.content
