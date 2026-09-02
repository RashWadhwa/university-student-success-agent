"""Enable RLS on alembic_version, documents, chunks, rate_limit_counters.

Revision ID: 20260829_0004
Revises: 20260821_0003

Supabase's Security Advisor flags these four tables because Supabase grants
`anon`/`authenticated` broad default privileges on every new `public` table,
and with RLS disabled that means anyone holding the project's anon key can
read/write them directly through Supabase's PostgREST API
(`/rest/v1/documents`, etc.), completely bypassing FastAPI.

This does not touch the application's own access path. The runtime
`DATABASE_URL` role (`postgres` on Supabase) owns every table here and has
the `BYPASSRLS` attribute, which is an unconditional bypass independent of
`ENABLE`/`FORCE ROW LEVEL SECURITY` or policies (see PostgreSQL's row
security docs). `documents`/`chunks` (backend/rag/indexing.py,
backend/rag/retrieval.py) and `rate_limit_counters`
(backend/security/rate_limit.py) all read/write through that same
bypass-owning connection via `DatabaseManager.session()`, never the
constrained `student_success_app` role — so plain `ENABLE ROW LEVEL
SECURITY`, with zero new policies, is sufficient: it fully denies
`anon`/`authenticated` (neither has BYPASSRLS, and no policy matches them)
while leaving the application's own queries completely unaffected.

`FORCE ROW LEVEL SECURITY` is deliberately not used here — unlike
`semantic_memory`/`audit_logs` (Stage 8), where it protects against the
app's own role accidentally bypassing per-user ownership isolation, there is
no equivalent same-role isolation concern for these tables: the app is
trusted to see all of them in full. `FORCE` would also have zero effect on
`postgres` regardless, since `BYPASSRLS` overrides it unconditionally.

`anon`/`authenticated` only exist on Supabase-managed Postgres, not on local
or CI Postgres, so the REVOKE step is guarded by a role-existence check —
it's a real revoke on Supabase and a safe no-op everywhere else.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260829_0004"
down_revision: str | None = "20260821_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("alembic_version", "documents", "chunks", "rate_limit_counters")
_SUPABASE_CLIENT_ROLES = ("anon", "authenticated")


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")

    op.execute(
        "DO $$\n"
        "DECLARE\n"
        "    target_table text;\n"
        "    target_role text;\n"
        "BEGIN\n"
        "    FOREACH target_table IN ARRAY "
        "ARRAY['alembic_version','documents','chunks','rate_limit_counters']\n"
        "    LOOP\n"
        "        FOREACH target_role IN ARRAY ARRAY['anon','authenticated']\n"
        "        LOOP\n"
        "            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = target_role) THEN\n"
        "                EXECUTE format("
        "'REVOKE ALL ON public.%I FROM %I', target_table, target_role);\n"
        "            END IF;\n"
        "        END LOOP;\n"
        "    END LOOP;\n"
        "END $$;"
    )


def downgrade() -> None:
    # Deliberately does not restore anon/authenticated grants: that would
    # reintroduce the exposure this migration exists to close.
    for table in _TABLES:
        op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")
