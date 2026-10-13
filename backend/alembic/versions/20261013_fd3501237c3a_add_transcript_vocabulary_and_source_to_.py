"""add transcript vocabulary, source and corrections to documents

Revision ID: fd3501237c3a
Revises: a19d3e8f18b5
Create Date: 2026-10-13 21:48:13.915271

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import sqlite

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'fd3501237c3a'
down_revision: str | Sequence[str] | None = 'a19d3e8f18b5'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('documents', schema=None) as batch_op:
        if not _has_column('documents', 'transcript_vocabulary'):
            batch_op.add_column(sa.Column('transcript_vocabulary', sqlite.JSON(), nullable=True))
        if not _has_column('documents', 'transcript_source'):
            batch_op.add_column(sa.Column('transcript_source', sa.String(length=20), nullable=True))
        if not _has_column('documents', 'transcript_corrections'):
            batch_op.add_column(sa.Column('transcript_corrections', sqlite.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('documents', schema=None) as batch_op:
        if _has_column('documents', 'transcript_corrections'):
            batch_op.drop_column('transcript_corrections')
        if _has_column('documents', 'transcript_source'):
            batch_op.drop_column('transcript_source')
        if _has_column('documents', 'transcript_vocabulary'):
            batch_op.drop_column('transcript_vocabulary')
