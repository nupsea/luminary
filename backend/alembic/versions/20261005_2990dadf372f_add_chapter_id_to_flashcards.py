"""add chapter_id to flashcards

Revision ID: 2990dadf372f
Revises: 087906440dcf
Create Date: 2026-10-05 14:16:42.476285

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2990dadf372f'
down_revision: Union[str, Sequence[str], None] = '087906440dcf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    """Upgrade schema."""
    # db_init's legacy bridge builds pre-Alembic databases from the live models, so the column
    # can already exist when this replays.
    if _has_column("flashcards", "chapter_id"):
        return
    with op.batch_alter_table("flashcards", schema=None) as batch_op:
        batch_op.add_column(sa.Column("chapter_id", sa.String(), nullable=True))
        batch_op.create_index(batch_op.f("ix_flashcards_chapter_id"), ["chapter_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("flashcards", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_flashcards_chapter_id"))
        batch_op.drop_column("chapter_id")
