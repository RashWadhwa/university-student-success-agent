"""Tests for PostgreSQL URL compatibility and durable schema metadata."""

from urllib.parse import urlunsplit

from sqlalchemy.dialects import postgresql

from backend.database.manager import normalise_async_database_url
from backend.database.models import ChunkModel, DocumentModel
from backend.rag.types import AuthorityScope, CorpusTier, SearchFilters
from backend.repositories.documents import DocumentVectorRepository


def test_plain_and_supabase_postgres_urls_normalise_for_asyncpg() -> None:
    userinfo = ":".join(("synthetic", "fixture"))
    local_authority = "@".join((userinfo, "localhost:5432"))
    hosted_authority = "@".join((userinfo, "db.example.supabase.co:5432"))
    local_url = urlunsplit(("postgresql", local_authority, "/student_success", "", ""))
    hosted_url = urlunsplit(("postgresql", hosted_authority, "/postgres", "sslmode=require", ""))
    local = normalise_async_database_url(local_url)
    supabase = normalise_async_database_url(hosted_url)

    expected_authority = "@".join((userinfo, "localhost"))
    assert local.startswith("postgresql+asyncpg://" + expected_authority)
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
