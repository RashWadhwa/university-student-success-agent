"""Classify public sources by corpus tier and authority.

Revision ID: 20260820_0002
Revises: 20260820_0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260820_0002"
down_revision: str | None = "20260820_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "corpus_tier",
            sa.String(length=20),
            server_default="primary",
            nullable=False,
        ),
    )
    op.add_column(
        "documents",
        sa.Column(
            "authority_scope",
            sa.String(length=30),
            server_default="institution_policy",
            nullable=False,
        ),
    )
    op.create_index("ix_documents_corpus_tier", "documents", ["corpus_tier"])
    op.create_index("ix_documents_authority_scope", "documents", ["authority_scope"])
    op.create_check_constraint(
        "ck_documents_corpus_tier",
        "documents",
        "corpus_tier IN ('primary', 'secondary')",
    )
    op.create_check_constraint(
        "ck_documents_authority_scope",
        "documents",
        "authority_scope IN ('institution_policy', 'sector_guidance')",
    )
    op.create_check_constraint(
        "ck_documents_source_classification",
        "documents",
        "(corpus_tier = 'primary' AND authority_scope = 'institution_policy') OR "
        "(corpus_tier = 'secondary' AND authority_scope = 'sector_guidance')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_documents_source_classification", "documents", type_="check")
    op.drop_constraint("ck_documents_authority_scope", "documents", type_="check")
    op.drop_constraint("ck_documents_corpus_tier", "documents", type_="check")
    op.drop_index("ix_documents_authority_scope", table_name="documents")
    op.drop_index("ix_documents_corpus_tier", table_name="documents")
    op.drop_column("documents", "authority_scope")
    op.drop_column("documents", "corpus_tier")
