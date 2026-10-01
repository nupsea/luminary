"""add entity_chunks_scanned to documents

Revision ID: 45c26ee949d4
Revises: b4544c54ed42
Create Date: 2026-10-01 20:22:40.141788

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '45c26ee949d4'
down_revision: str | Sequence[str] | None = 'b4544c54ed42'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('documents', schema=None) as batch_op:
        if not _has_column('documents', 'entity_chunks_scanned'):
            batch_op.add_column(sa.Column('entity_chunks_scanned', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('documents', schema=None) as batch_op:
        if _has_column('documents', 'entity_chunks_scanned'):
            batch_op.drop_column('entity_chunks_scanned')
