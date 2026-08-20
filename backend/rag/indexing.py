"""Atomic document embedding and PostgreSQL indexing service."""

from __future__ import annotations

import logging
from collections.abc import Callable
from time import perf_counter

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.manager import DatabaseManager
from backend.documents.models import DocumentRecord
from backend.llm.base import LLMProvider
from backend.rag.errors import IndexingError
from backend.rag.types import DocumentIndexMetadata, IndexingResult
from backend.repositories.documents import DocumentVectorRepository

logger = logging.getLogger(__name__)
RepositoryFactory = Callable[[AsyncSession], DocumentVectorRepository]


class IndexingService:
    """Generate embeddings in batches and persist one atomic document aggregate."""

    def __init__(
        self,
        *,
        database: DatabaseManager,
        provider: LLMProvider,
        embedding_batch_size: int,
        embedding_dimensions: int,
        repository_factory: RepositoryFactory = DocumentVectorRepository,
    ) -> None:
        self.database = database
        self.provider = provider
        self.embedding_batch_size = embedding_batch_size
        self.embedding_dimensions = embedding_dimensions
        self.repository_factory = repository_factory

    async def index_document(
        self,
        record: DocumentRecord,
        metadata: DocumentIndexMetadata,
    ) -> IndexingResult:
        started = perf_counter()
        if not record.chunks or any(not chunk.text.strip() for chunk in record.chunks):
            raise IndexingError(
                code="DOCUMENT_NOT_INDEXABLE",
                message="The document has no indexable chunks.",
                details={"document_id": record.id},
            )

        logger.info(
            "document_indexing_started",
            extra={"document_id": record.id, "chunk_count": len(record.chunks)},
        )
        async with self.database.session() as session:
            existing = await self.repository_factory(session).find_by_checksum(
                record.checksum_sha256
            )
            if existing is not None:
                return IndexingResult(
                    document_id=str(existing.id),
                    status="already_indexed",
                    chunk_count=record.chunk_count,
                    embedding_model=self.provider.embedding_model,
                    indexed_at=existing.indexed_at,
                )

        embeddings: list[list[float]] = []
        for batch_start in range(0, len(record.chunks), self.embedding_batch_size):
            batch = record.chunks[batch_start : batch_start + self.embedding_batch_size]
            logger.info(
                "embedding_batch_started",
                extra={
                    "document_id": record.id,
                    "batch_size": len(batch),
                    "batch_start": batch_start,
                },
            )
            result = await self.provider.create_embeddings([chunk.text for chunk in batch])
            self._validate_embedding_batch(result.embeddings, expected_count=len(batch))
            embeddings.extend(result.embeddings)
            logger.info(
                "embedding_batch_completed",
                extra={
                    "document_id": record.id,
                    "batch_size": len(batch),
                    "batch_start": batch_start,
                },
            )

        try:
            async with self.database.session() as session, session.begin():
                repository = self.repository_factory(session)
                existing = await repository.find_by_checksum(record.checksum_sha256)
                if existing is not None:
                    return IndexingResult(
                        document_id=str(existing.id),
                        status="already_indexed",
                        chunk_count=record.chunk_count,
                        embedding_model=self.provider.embedding_model,
                        indexed_at=existing.indexed_at,
                    )
                document = await repository.persist_indexed_document(
                    record,
                    metadata=metadata,
                    embeddings=embeddings,
                )
        except IntegrityError as exc:
            raise IndexingError(
                code="DOCUMENT_ALREADY_INDEXED",
                message="The document was indexed concurrently.",
                details={"document_id": record.id},
            ) from exc
        except SQLAlchemyError as exc:
            logger.warning(
                "Document indexing transaction failed",
                extra={"document_id": record.id, "error_type": type(exc).__name__},
            )
            raise IndexingError(
                code="DOCUMENT_INDEXING_FAILED",
                message="The document could not be indexed.",
                details={"document_id": record.id},
            ) from exc

        duration_ms = (perf_counter() - started) * 1000
        logger.info(
            "document_indexing_completed",
            extra={
                "document_id": record.id,
                "chunk_count": len(record.chunks),
                "duration_ms": round(duration_ms, 2),
            },
        )
        return IndexingResult(
            document_id=str(document.id),
            status="indexed",
            chunk_count=len(record.chunks),
            embedding_model=self.provider.embedding_model,
            indexed_at=document.indexed_at,
        )

    def _validate_embedding_batch(
        self,
        embeddings: list[list[float]],
        *,
        expected_count: int,
    ) -> None:
        if len(embeddings) != expected_count:
            raise IndexingError(
                code="EMBEDDING_COUNT_INVALID",
                message="The embedding provider returned an unexpected result count.",
            )
        invalid = [
            index
            for index, vector in enumerate(embeddings)
            if len(vector) != self.embedding_dimensions
        ]
        if invalid:
            raise IndexingError(
                code="EMBEDDING_DIMENSION_INVALID",
                message="The embedding provider returned vectors with invalid dimensions.",
                details={
                    "expected_dimensions": self.embedding_dimensions,
                    "invalid_indexes": invalid,
                },
            )
