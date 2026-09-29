"""add is_favorite to documents and notes

Revision ID: f1a2b3c4d5e6
Revises: 46dcab5902f4
Create Date: 2026-09-29 12:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = '46dcab5902f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("documents", schema=None) as batch_op:
        if not _has_column("documents", "is_favorite"):
            batch_op.add_column(
                sa.Column("is_favorite", sa.Boolean(), nullable=False, server_default="0")
            )

    with op.batch_alter_table("notes", schema=None) as batch_op:
        if not _has_column("notes", "is_favorite"):
            batch_op.add_column(
                sa.Column("is_favorite", sa.Boolean(), nullable=False, server_default="0")
            )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("notes", schema=None) as batch_op:
        if _has_column("notes", "is_favorite"):
            batch_op.drop_column("is_favorite")

    with op.batch_alter_table("documents", schema=None) as batch_op:
        if _has_column("documents", "is_favorite"):
            batch_op.drop_column("is_favorite")
