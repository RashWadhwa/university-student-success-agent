"""RLS on alembic_version/documents/chunks/rate_limit_counters (migration 20260829_0004).

Covers what Supabase's Security Advisor flagged: these tables must deny a
role that has broad GRANTs but no RLS bypass and no matching policy (the
shape of Supabase's `anon`/`authenticated` roles), while the application's
own bypass-owning connection remains fully unaffected. `anon`/`authenticated`
themselves only exist on Supabase, so a throwaway role with the same
properties (NOLOGIN, NOBYPASSRLS, broad grants) is used here to keep this
test meaningful against local/CI PostgreSQL too.

Related, already-covered elsewhere and intentionally not duplicated here:
- Staff/admin capability enforcement for document management:
  tests/unit/test_service_endpoints.py::test_student_is_denied_document_management
- Cross-user/tenant semantic_memory and audit_logs isolation:
  tests/integration/test_stage8_rls.py
- Rate limiting behaviour: tests/integration/test_stage8_rate_limit.py
- RAG ingestion/retrieval: tests/integration/test_postgres_rag.py
"""

from uuid import uuid4

import pytest
from sqlalchemy import text

from backend.database.manager import DatabaseManager

pytestmark = pytest.mark.integration

_TABLES = ("alembic_version", "documents", "chunks", "rate_limit_counters")


@pytest.mark.asyncio
async def test_rls_is_enabled_without_force_on_all_four_tables(
    integration_database: DatabaseManager,
) -> None:
    async with integration_database.session() as session:
        flags = (
            await session.execute(
                text(
                    "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relname = ANY(:tables) ORDER BY relname"
                ),
                {"tables": list(_TABLES)},
            )
        ).all()
    assert flags == [
        ("alembic_version", True, False),
        ("chunks", True, False),
        ("documents", True, False),
        ("rate_limit_counters", True, False),
    ]


@pytest.mark.asyncio
async def test_application_role_is_unaffected_by_rls(
    integration_database: DatabaseManager,
) -> None:
    """The app's own connection must keep full access: it owns these tables

    and (on Supabase) has BYPASSRLS; enabling RLS with zero policies must not
    change that.
    """

    async with integration_database.session() as session:
        for table in _TABLES:
            await session.execute(text(f"SELECT 1 FROM {table} LIMIT 1"))


@pytest.mark.asyncio
async def test_a_non_bypass_role_with_broad_grants_is_denied_all_access(
    integration_database: DatabaseManager,
) -> None:
    """Simulates the exact shape of Supabase's anon/authenticated roles:

    NOLOGIN, NOBYPASSRLS, and (as Supabase grants by default) full table
    privileges, but with RLS enabled and no policy naming this role.
    """

    role = f"test_anon_like_{uuid4().hex[:8]}"
    async with integration_database.engine.begin() as connection:
        await connection.execute(text(f"CREATE ROLE {role} NOLOGIN NOSUPERUSER NOBYPASSRLS"))
        for table in _TABLES:
            await connection.execute(
                text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {role}")
            )
    try:
        async with integration_database.session() as session, session.begin():
            await session.execute(text(f"SET LOCAL ROLE {role}"))
            for table in _TABLES:
                rows = (await session.execute(text(f"SELECT 1 FROM {table}"))).all()
                assert rows == [], f"{table} leaked rows to a non-bypass role with no policy"
            with pytest.raises(Exception, match=r"permission denied|row-level security"):
                await session.execute(
                    text(
                        "INSERT INTO rate_limit_counters "
                        "(identity_hash, route_bucket, window_started_at, "
                        "request_count, expires_at) "
                        "VALUES ('x', 'y', now(), 1, now())"
                    )
                )
            await session.rollback()
    finally:
        async with integration_database.engine.begin() as connection:
            for table in _TABLES:
                await connection.execute(text(f"REVOKE ALL ON {table} FROM {role}"))
            await connection.execute(text(f"DROP ROLE {role}"))


@pytest.mark.asyncio
async def test_supabase_client_roles_have_no_grants_where_they_exist(
    integration_database: DatabaseManager,
) -> None:
    """On Supabase, anon/authenticated must end up with zero grants on these

    tables. On local/CI Postgres, where those roles don't exist, this is
    correctly a no-op (nothing to assert).
    """

    async with integration_database.session() as session:
        existing_roles = {
            row[0]
            for row in (
                await session.execute(
                    text("SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated')")
                )
            ).all()
        }
        if not existing_roles:
            pytest.skip("anon/authenticated do not exist outside Supabase-managed Postgres")
        grants = (
            await session.execute(
                text(
                    "SELECT table_name, grantee FROM information_schema.role_table_grants "
                    "WHERE table_schema = 'public' AND table_name = ANY(:tables) "
                    "AND grantee = ANY(:roles)"
                ),
                {"tables": list(_TABLES), "roles": list(existing_roles)},
            )
        ).all()
        assert grants == []
