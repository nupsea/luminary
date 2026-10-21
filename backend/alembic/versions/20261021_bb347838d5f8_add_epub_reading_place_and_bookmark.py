"""add epub reading place and bookmark

Revision ID: bb347838d5f8
Revises: 1822f085552e
Create Date: 2026-10-21 15:22:45.258119

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'bb347838d5f8'
down_revision: str | Sequence[str] | None = '1822f085552e'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = ("last_epub_block_index", "epub_bookmark_chapter_index", "epub_bookmark_block_index")


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    """Upgrade schema."""
    # db_init's legacy bridge builds pre-Alembic databases from the live models, so the columns
    # can already exist when this replays.
    missing = [c for c in _COLUMNS if not _has_column("reading_positions", c)]
    if not missing:
        return
    with op.batch_alter_table("reading_positions", schema=None) as batch_op:
        for column in missing:
            batch_op.add_column(sa.Column(column, sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("reading_positions", schema=None) as batch_op:
        for column in reversed(_COLUMNS):
            batch_op.drop_column(column)
