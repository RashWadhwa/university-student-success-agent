"""PostgreSQL document and vector chunk models."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
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
        CheckConstraint(
            "corpus_tier IN ('primary', 'secondary')",
            name="ck_documents_corpus_tier",
        ),
        CheckConstraint(
            "authority_scope IN ('institution_policy', 'sector_guidance')",
            name="ck_documents_authority_scope",
        ),
        CheckConstraint(
            "(corpus_tier = 'primary' AND authority_scope = 'institution_policy') OR "
            "(corpus_tier = 'secondary' AND authority_scope = 'sector_guidance')",
            name="ck_documents_source_classification",
        ),
        Index("ix_documents_document_type", "document_type"),
        Index("ix_documents_institution", "institution"),
        Index("ix_documents_effective_date", "effective_date"),
        Index("ix_documents_source", "source"),
        Index("ix_documents_corpus_tier", "corpus_tier"),
        Index("ix_documents_authority_scope", "authority_scope"),
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
    corpus_tier: Mapped[str] = mapped_column(String(20), nullable=False, default="primary")
    authority_scope: Mapped[str] = mapped_column(
        String(30), nullable=False, default="institution_policy"
    )
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


class SemanticMemoryModel(Base):
    """Consent-based distilled user memory, separate from RAG and audit data."""

    __tablename__ = "semantic_memory"
    __table_args__ = (
        CheckConstraint(
            "memory_type IN ('preference','case_summary','ongoing_action',"
            "'accessibility_preference','institutional_context')",
            name="ck_semantic_memory_type",
        ),
        CheckConstraint("char_length(fact) BETWEEN 1 AND 2000", name="ck_memory_fact_length"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_memory_confidence"),
        Index("ix_memory_owner_active", "tenant_id", "user_id", "is_active"),
        Index("ix_memory_expires_at", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(
        "memory_id", PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False)
    memory_type: Mapped[str] = mapped_column(String(40), nullable=False)
    fact: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_reference: Mapped[str | None] = mapped_column(String(255))
    confidence: Mapped[float] = mapped_column(nullable=False)
    consent_scope: Mapped[str] = mapped_column(String(50), nullable=False)
    retention_category: Mapped[str] = mapped_column(String(50), nullable=False)
    case_reference: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    superseded_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class AuditLogModel(Base):
    """Minimised persistent security audit metadata."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_tenant_created", "tenant_id", "created_at"),
        Index("ix_audit_request", "request_id"),
    )

    id: Mapped[UUID] = mapped_column(
        "audit_id", PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    agent_name: Mapped[str | None] = mapped_column(String(50))
    tool_name: Mapped[str | None] = mapped_column(String(100))
    permission_level: Mapped[str | None] = mapped_column(String(30))
    decision: Mapped[str | None] = mapped_column(String(100))
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    failure_category: Mapped[str | None] = mapped_column(String(100))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RateLimitModel(Base):
    """Shared fixed-window counters keyed by a pseudonymous identity."""

    __tablename__ = "rate_limit_counters"
    __table_args__ = (Index("ix_rate_limit_expires_at", "expires_at"),)

    identity_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    route_bucket: Mapped[str] = mapped_column(String(50), primary_key=True)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
