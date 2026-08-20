"""Tests for PostgreSQL URL compatibility and durable schema metadata."""

from sqlalchemy.dialects import postgresql

from backend.database.manager import normalise_async_database_url
from backend.database.models import ChunkModel, DocumentModel
from backend.rag.types import AuthorityScope, CorpusTier, SearchFilters
from backend.repositories.documents import DocumentVectorRepository


def test_plain_and_supabase_postgres_urls_normalise_for_asyncpg() -> None:
    local = normalise_async_database_url(
        "postgresql://user:password@localhost:5432/student_success"
    )
    supabase = normalise_async_database_url(
        "postgresql://user:password@db.example.supabase.co:5432/postgres?sslmode=require"
    )

    assert local.startswith("postgresql+asyncpg://user:password@localhost")
    assert "ssl=require" in supabase
    assert "sslmode" not in supabase


def test_models_define_vector_foreign_key_and_duplicate_constraints() -> None:
    assert "embedding" in ChunkModel.__table__.columns
    assert str(ChunkModel.__table__.columns.embedding.type) == "VECTOR"
    foreign_keys = list(ChunkModel.__table__.columns.document_id.foreign_keys)
    assert foreign_keys[0].target_fullname == "documents.document_id"
    assert DocumentModel.__table__.columns.checksum.unique is True


def test_repository_filters_compile_to_bound_parameters() -> None:
    statement = DocumentVectorRepository._apply_filters(
        DocumentModel.__table__.select(),
        SearchFilters(
            institution="Example University",
            source="policy-source",
            corpus_tier=CorpusTier.SECONDARY,
            authority_scope=AuthorityScope.SECTOR_GUIDANCE,
        ),
    )
    compiled = statement.compile(dialect=postgresql.dialect())

    assert "Example University" not in str(compiled)
    assert set(compiled.params.values()) == {
        "Example University",
        "policy-source",
        "secondary",
        "sector_guidance",
    }
