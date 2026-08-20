"""Create Stage 4 document and vector chunk schema.

Revision ID: 20260820_0001
Revises:
"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260820_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("SET search_path TO public, extensions")
    op.create_table(
        "documents",
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("original_filename", sa.String(length=512), nullable=False),
        sa.Column("safe_filename", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("document_type", sa.String(length=100), nullable=True),
        sa.Column("institution", sa.String(length=255), nullable=True),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("review_date", sa.Date(), nullable=True),
        sa.Column("version", sa.String(length=100), nullable=True),
        sa.Column("source", sa.String(length=2048), nullable=True),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("document_id"),
        sa.UniqueConstraint("checksum", name="uq_documents_checksum"),
    )
    op.create_index("ix_documents_document_type", "documents", ["document_type"])
    op.create_index("ix_documents_effective_date", "documents", ["effective_date"])
    op.create_index("ix_documents_institution", "documents", ["institution"])
    op.create_index("ix_documents_source", "documents", ["source"])

    op.create_table(
        "chunks",
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("section", sa.String(length=512), nullable=True),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.document_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("chunk_id"),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_chunks_document_index"),
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])
    op.execute(
        "CREATE INDEX ix_chunks_content_fts ON chunks USING gin (to_tsvector('english', content))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chunks_content_fts")
    op.drop_index("ix_chunks_document_id", table_name="chunks")
    op.drop_table("chunks")
    op.drop_index("ix_documents_source", table_name="documents")
    op.drop_index("ix_documents_institution", table_name="documents")
    op.drop_index("ix_documents_effective_date", table_name="documents")
    op.drop_index("ix_documents_document_type", table_name="documents")
    op.drop_table("documents")
