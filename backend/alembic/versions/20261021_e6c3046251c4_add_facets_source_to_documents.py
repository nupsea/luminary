"""add facets_source to documents

"reader" marks facets a reader chose from a card's type menu, so ingestion keeps them
instead of re-measuring them (#223). Null is every existing row: measured.

Revision ID: e6c3046251c4
Revises: 1822f085552e
Create Date: 2026-10-21 11:37:53.003632

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e6c3046251c4'
down_revision: str | Sequence[str] | None = '1822f085552e'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    """Upgrade schema."""
    if not _has_column('documents', 'facets_source'):
        with op.batch_alter_table('documents', schema=None) as batch_op:
            batch_op.add_column(sa.Column('facets_source', sa.String(length=10), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    if _has_column('documents', 'facets_source'):
        with op.batch_alter_table('documents', schema=None) as batch_op:
            batch_op.drop_column('facets_source')
