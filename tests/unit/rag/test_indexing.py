"""Unit tests for batching, idempotency, and indexing transactions."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError

from backend.documents.models import ChunkRecord, DocumentRecord, PageRecord
from backend.llm.providers.mock_provider import MockLLMProvider
from backend.rag.errors import IndexingError
from backend.rag.indexing import IndexingService
from backend.rag.types import DocumentIndexMetadata


def document_record() -> DocumentRecord:
    document_id = str(uuid4())
    chunks = [
        ChunkRecord(
            id=str(uuid4()),
            index=index,
            text=f"Policy evidence chunk {index}",
            char_count=23,
            page_start=1,
            page_end=1,
        )
        for index in range(5)
    ]
    return DocumentRecord(
        id=document_id,
        original_filename="policy.pdf",
        stored_filename="a" * 64 + ".pdf",
        media_type="application/pdf",
        size_bytes=100,
        checksum_sha256="a" * 64,
        page_count=1,
        chunk_count=len(chunks),
        created_at=datetime.now(UTC),
        pages=[PageRecord(page_number=1, text="Policy", char_count=6)],
        chunks=chunks,
    )


class Transaction:
    def __init__(self, database: "FakeDatabase") -> None:
        self.database = database

    async def __aenter__(self) -> None:
        self.database.transactions += 1

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if exc_type is not None:
            self.database.rollbacks += 1


class FakeSession:
    def __init__(self, database: "FakeDatabase") -> None:
        self.database = database

    def begin(self) -> Transaction:
        return Transaction(self.database)


class FakeDatabase:
    def __init__(self) -> None:
        self.transactions = 0
        self.rollbacks = 0

    @asynccontextmanager
    async def session(self) -> Any:
        yield FakeSession(self)


class FakeRepository:
    existing: Any = None
    persisted_embeddings: list[list[float]] | None = None
    failure: Exception | None = None

    def __init__(self, session: FakeSession) -> None:
        del session

    async def find_by_checksum(self, checksum: str) -> Any:
        del checksum
        return self.existing

    async def persist_indexed_document(
        self,
        record: DocumentRecord,
        *,
        metadata: DocumentIndexMetadata,
        embeddings: list[list[float]],
    ) -> Any:
        del metadata
        if self.failure:
            raise self.failure
        self.__class__.persisted_embeddings = embeddings
        return SimpleNamespace(id=record.id, indexed_at=datetime.now(UTC))


@pytest.fixture(autouse=True)
def reset_repository() -> None:
    FakeRepository.existing = None
    FakeRepository.persisted_embeddings = None
    FakeRepository.failure = None


@pytest.mark.asyncio
async def test_successful_indexing_batches_and_commits_once() -> None:
    class BatchProvider(MockLLMProvider):
        def __init__(self, *, embedding_dimensions: int) -> None:
            super().__init__(embedding_dimensions=embedding_dimensions)
            self.batch_sizes: list[int] = []

        async def create_embeddings(self, texts: list[str]) -> Any:
            self.batch_sizes.append(len(texts))
            return await super().create_embeddings(texts)

    database = FakeDatabase()
    provider = BatchProvider(embedding_dimensions=4)
    service = IndexingService(
        database=database,  # type: ignore[arg-type]
        provider=provider,
        embedding_batch_size=2,
        embedding_dimensions=4,
        repository_factory=FakeRepository,  # type: ignore[arg-type]
    )

    result = await service.index_document(document_record(), DocumentIndexMetadata())

    assert result.status == "indexed"
    assert result.chunk_count == 5
    assert len(FakeRepository.persisted_embeddings or []) == 5
    assert database.transactions == 1
    assert provider.batch_sizes == [2, 2, 1]


@pytest.mark.asyncio
async def test_duplicate_prevents_embedding_generation() -> None:
    class CountingProvider(MockLLMProvider):
        calls = 0

        async def create_embeddings(self, texts: list[str]) -> Any:
            self.calls += 1
            return await super().create_embeddings(texts)

    FakeRepository.existing = SimpleNamespace(id=uuid4(), indexed_at=datetime.now(UTC), chunks=[])
    provider = CountingProvider(embedding_dimensions=4)
    service = IndexingService(
        database=FakeDatabase(),  # type: ignore[arg-type]
        provider=provider,
        embedding_batch_size=2,
        embedding_dimensions=4,
        repository_factory=FakeRepository,  # type: ignore[arg-type]
    )

    result = await service.index_document(document_record(), DocumentIndexMetadata())

    assert result.status == "already_indexed"
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_database_failure_rolls_back_transaction() -> None:
    database = FakeDatabase()
    FakeRepository.failure = SQLAlchemyError("database failed")
    service = IndexingService(
        database=database,  # type: ignore[arg-type]
        provider=MockLLMProvider(embedding_dimensions=4),
        embedding_batch_size=10,
        embedding_dimensions=4,
        repository_factory=FakeRepository,  # type: ignore[arg-type]
    )

    with pytest.raises(IndexingError) as exc_info:
        await service.index_document(document_record(), DocumentIndexMetadata())

    assert exc_info.value.code == "DOCUMENT_INDEXING_FAILED"
    assert database.rollbacks == 1


@pytest.mark.asyncio
async def test_invalid_embedding_dimensions_never_open_transaction() -> None:
    database = FakeDatabase()
    service = IndexingService(
        database=database,  # type: ignore[arg-type]
        provider=MockLLMProvider(embedding_dimensions=3),
        embedding_batch_size=10,
        embedding_dimensions=4,
        repository_factory=FakeRepository,  # type: ignore[arg-type]
    )

    with pytest.raises(IndexingError) as exc_info:
        await service.index_document(document_record(), DocumentIndexMetadata())

    assert exc_info.value.code == "EMBEDDING_DIMENSION_INVALID"
    assert database.transactions == 0
