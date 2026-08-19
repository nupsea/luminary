"""add documents.extraction_report for import fidelity

Revision ID: e296b18b392a
Revises: eaa07024ed9e
Create Date: 2026-08-19 14:45:10.136826

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import sqlite

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e296b18b392a'
down_revision: str | Sequence[str] | None = 'eaa07024ed9e'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    """Upgrade schema."""
    # db_init's legacy bridge builds pre-Alembic databases from the live models
    # and only then stamps the baseline, so on that path this column already
    # exists by the time the revision replays. Additive revisions must tolerate it.
    if _has_column("documents", "extraction_report"):
        return
    # Nullable with no backfill: fidelity is measured while importing, so
    # documents ingested before this column stay null until re-imported. Null
    # therefore means "not measured", never "imported cleanly".
    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.add_column(sa.Column("extraction_report", sqlite.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.drop_column("extraction_report")
