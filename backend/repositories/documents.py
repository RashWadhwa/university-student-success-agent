"""SQLAlchemy repository for atomic indexing and PostgreSQL retrieval."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Select, func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from backend.database.models import ChunkModel, DocumentModel
from backend.documents.models import DocumentRecord
from backend.rag.types import (
    DocumentIndexMetadata,
    RetrievalCandidate,
    SearchFilters,
)


class DocumentVectorRepository:
    """Hide SQLAlchemy and PostgreSQL query details from RAG services."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def find_by_checksum(self, checksum: str) -> DocumentModel | None:
        return await self.session.scalar(
            select(DocumentModel).where(DocumentModel.checksum == checksum)
        )

    async def persist_indexed_document(
        self,
        record: DocumentRecord,
        *,
        metadata: DocumentIndexMetadata,
        embeddings: list[list[float]],
    ) -> DocumentModel:
        """Add a complete indexed aggregate to the current transaction."""

        if len(embeddings) != len(record.chunks):
            raise ValueError("embedding count must match chunk count")
        indexed_at = datetime.now(UTC)
        document = DocumentModel(
            id=UUID(record.id),
            original_filename=record.original_filename,
            safe_filename=record.safe_filename or record.original_filename,
            title=metadata.title or str(record.metadata.get("/Title") or record.original_filename),
            document_type=metadata.document_type,
            institution=metadata.institution,
            effective_date=metadata.effective_date,
            review_date=metadata.review_date,
            version=metadata.version,
            source=metadata.source,
            mime_type=record.media_type,
            file_size_bytes=record.size_bytes,
            checksum=record.checksum_sha256,
            page_count=record.page_count,
            extra_metadata=record.metadata,
            created_at=record.created_at,
            indexed_at=indexed_at,
        )
        document.chunks = [
            ChunkModel(
                id=UUID(chunk.id),
                chunk_index=chunk.index,
                content=chunk.text,
                page=chunk.page_start,
                section=chunk.heading,
                checksum=hashlib.sha256(chunk.text.encode("utf-8")).hexdigest(),
                embedding=embedding,
                extra_metadata=chunk.metadata,
            )
            for chunk, embedding in zip(record.chunks, embeddings, strict=True)
        ]
        self.session.add(document)
        await self.session.flush()
        return document

    async def semantic_search(
        self,
        query_embedding: list[float],
        *,
        limit: int,
        filters: SearchFilters,
        minimum_score: float,
    ) -> list[RetrievalCandidate]:
        distance = ChunkModel.embedding.cosine_distance(query_embedding)
        score = func.greatest(0.0, func.least(1.0, 1.0 - (distance / 2.0)))
        statement = (
            select(ChunkModel, DocumentModel, score.label("score"))
            .join(DocumentModel, ChunkModel.document_id == DocumentModel.id)
            .options(*self._retrieval_load_options())
            .where(score >= minimum_score)
            .order_by(distance.asc(), ChunkModel.id.asc())
            .limit(limit)
        )
        statement = self._apply_filters(statement, filters)
        rows = (await self.session.execute(statement)).all()
        return [
            self._candidate(chunk, document, float(row_score))
            for chunk, document, row_score in rows
        ]

    async def keyword_search(
        self,
        query: str,
        *,
        limit: int,
        filters: SearchFilters,
    ) -> list[RetrievalCandidate]:
        english = literal_column("'english'::regconfig")
        document_vector = func.to_tsvector(english, ChunkModel.content)
        query_vector = func.websearch_to_tsquery(english, query)
        rank = func.ts_rank_cd(document_vector, query_vector)
        score = rank / (rank + 1.0)
        statement = (
            select(ChunkModel, DocumentModel, score.label("score"))
            .join(DocumentModel, ChunkModel.document_id == DocumentModel.id)
            .options(*self._retrieval_load_options())
            .where(document_vector.op("@@")(query_vector))
            .order_by(rank.desc(), ChunkModel.id.asc())
            .limit(limit)
        )
        statement = self._apply_filters(statement, filters)
        rows = (await self.session.execute(statement)).all()
        return [
            self._candidate(chunk, document, float(row_score))
            for chunk, document, row_score in rows
        ]

    @staticmethod
    def _apply_filters(statement: Select, filters: SearchFilters) -> Select:
        if filters.document_type is not None:
            statement = statement.where(DocumentModel.document_type == filters.document_type)
        if filters.institution is not None:
            statement = statement.where(DocumentModel.institution == filters.institution)
        if filters.source is not None:
            statement = statement.where(DocumentModel.source == filters.source)
        if filters.version is not None:
            statement = statement.where(DocumentModel.version == filters.version)
        if filters.effective_on_or_before is not None:
            statement = statement.where(
                DocumentModel.effective_date <= filters.effective_on_or_before
            )
        if filters.effective_on_or_after is not None:
            statement = statement.where(
                DocumentModel.effective_date >= filters.effective_on_or_after
            )
        return statement

    @staticmethod
    def _retrieval_load_options() -> tuple[object, object]:
        """Avoid transferring stored vectors and unrelated metadata in search rows."""

        return (
            load_only(
                ChunkModel.id,
                ChunkModel.document_id,
                ChunkModel.content,
                ChunkModel.page,
                ChunkModel.section,
            ),
            load_only(
                DocumentModel.id,
                DocumentModel.title,
                DocumentModel.document_type,
                DocumentModel.institution,
                DocumentModel.version,
                DocumentModel.effective_date,
                DocumentModel.review_date,
                DocumentModel.source,
            ),
        )

    @staticmethod
    def _candidate(
        chunk: ChunkModel,
        document: DocumentModel,
        score: float,
    ) -> RetrievalCandidate:
        return RetrievalCandidate(
            chunk_id=str(chunk.id),
            document_id=str(document.id),
            content=chunk.content,
            page=chunk.page,
            section=chunk.section,
            title=document.title,
            document_type=document.document_type,
            institution=document.institution,
            version=document.version,
            effective_date=document.effective_date,
            review_date=document.review_date,
            source=document.source,
            score=max(0.0, min(1.0, score)),
        )
