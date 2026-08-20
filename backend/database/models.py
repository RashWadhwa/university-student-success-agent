"""PostgreSQL document and vector chunk models."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database.base import Base


class DocumentModel(Base):
    """Durable university policy document metadata."""

    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_document_type", "document_type"),
        Index("ix_documents_institution", "institution"),
        Index("ix_documents_effective_date", "effective_date"),
        Index("ix_documents_source", "source"),
    )

    id: Mapped[UUID] = mapped_column(
        "document_id", PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    safe_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    document_type: Mapped[str | None] = mapped_column(String(100))
    institution: Mapped[str | None] = mapped_column(String(255))
    effective_date: Mapped[date | None] = mapped_column(Date)
    review_date: Mapped[date | None] = mapped_column(Date)
    version: Mapped[str | None] = mapped_column(String(100))
    source: Mapped[str | None] = mapped_column(String(2048))
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    chunks: Mapped[list[ChunkModel]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ChunkModel(Base):
    """Page-aware policy chunk and its embedding vector."""

    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_chunks_document_index"),
        Index("ix_chunks_document_id", "document_id"),
    )

    id: Mapped[UUID] = mapped_column(
        "chunk_id", PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("documents.document_id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    page: Mapped[int] = mapped_column(Integer, nullable=False)
    section: Mapped[str | None] = mapped_column(String(512))
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(), nullable=False)
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    document: Mapped[DocumentModel] = relationship(back_populates="chunks")
