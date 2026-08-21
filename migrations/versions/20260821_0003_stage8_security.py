"""Add Stage 8 private data, retention, audit and deny-by-default RLS.

Revision ID: 20260821_0003
Revises: 20260820_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260821_0003"
down_revision: str | None = "20260820_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "DO $$ BEGIN CREATE ROLE student_success_app NOLOGIN NOSUPERUSER NOBYPASSRLS; "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$"
    )
    op.execute("GRANT student_success_app TO CURRENT_USER")
    op.create_table(
        "semantic_memory",
        sa.Column("memory_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(100), nullable=False),
        sa.Column("memory_type", sa.String(40), nullable=False),
        sa.Column("fact", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(50), nullable=False),
        sa.Column("source_reference", sa.String(255)),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("consent_scope", sa.String(50), nullable=False),
        sa.Column("retention_category", sa.String(50), nullable=False),
        sa.Column("case_reference", sa.String(100)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("superseded_by", postgresql.UUID(as_uuid=True)),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.CheckConstraint(
            "memory_type IN ('preference','case_summary','ongoing_action',"
            "'accessibility_preference','institutional_context')",
            name="ck_semantic_memory_type",
        ),
        sa.CheckConstraint("char_length(fact) BETWEEN 1 AND 2000", name="ck_memory_fact_length"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_memory_confidence"),
    )
    op.create_index(
        "ix_memory_owner_active", "semantic_memory", ["tenant_id", "user_id", "is_active"]
    )
    op.create_index("ix_memory_expires_at", "semantic_memory", ["expires_at"])
    op.create_table(
        "audit_logs",
        sa.Column("audit_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(100), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("agent_name", sa.String(50)),
        sa.Column("tool_name", sa.String(100)),
        sa.Column("permission_level", sa.String(30)),
        sa.Column("decision", sa.String(100)),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("failure_category", sa.String(100)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_audit_tenant_created", "audit_logs", ["tenant_id", "created_at"])
    op.create_index("ix_audit_request", "audit_logs", ["request_id"])
    op.create_table(
        "rate_limit_counters",
        sa.Column("identity_hash", sa.String(64), primary_key=True),
        sa.Column("route_bucket", sa.String(50), primary_key=True),
        sa.Column("window_started_at", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_rate_limit_expires_at", "rate_limit_counters", ["expires_at"])
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON documents, chunks TO student_success_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON semantic_memory TO student_success_app")
    op.execute("GRANT SELECT, INSERT, DELETE ON audit_logs TO student_success_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON rate_limit_counters TO student_success_app")
    for table in ("semantic_memory", "audit_logs"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    owner = "user_id = NULLIF(current_setting('app.user_id', true), '')::uuid"
    tenant = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')"
    op.execute(
        "CREATE POLICY memory_owner_isolation ON semantic_memory FOR ALL TO student_success_app "
        f"USING ({owner} AND {tenant}) WITH CHECK ({owner} AND {tenant})"
    )
    op.execute(
        "CREATE POLICY audit_tenant_read ON audit_logs FOR SELECT TO student_success_app "
        f"USING ({tenant} AND current_setting('app.role', true) IN ('staff','admin'))"
    )
    op.execute(
        "CREATE POLICY audit_insert_own ON audit_logs FOR INSERT TO student_success_app "
        f"WITH CHECK ({owner} AND {tenant})"
    )
    op.execute(
        "CREATE POLICY audit_delete_expired ON audit_logs FOR DELETE TO student_success_app "
        f"USING ({tenant} AND expires_at <= now() AND ({owner} OR "
        "current_setting('app.role', true) IN ('staff','admin')))"
    )


def downgrade() -> None:
    op.drop_table("rate_limit_counters")
    op.drop_table("audit_logs")
    op.drop_table("semantic_memory")
    op.execute("REVOKE student_success_app FROM CURRENT_USER")
