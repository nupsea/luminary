"""add ingest_resumes to documents

Revision ID: 7f6bcd0f8881
Revises: 0bd2e2d172eb
Create Date: 2026-11-01 15:32:48.608103

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '7f6bcd0f8881'
down_revision: str | Sequence[str] | None = '0bd2e2d172eb'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    """Upgrade schema."""
    # db_init's legacy bridge builds pre-Alembic databases from the live models.
    if _has_column("documents", "ingest_resumes"):
        return
    op.add_column(
        "documents",
        sa.Column("ingest_resumes", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    # In place, never batch mode: rebuilding documents cascades into its children (I-69).
    op.execute("ALTER TABLE documents DROP COLUMN ingest_resumes")
