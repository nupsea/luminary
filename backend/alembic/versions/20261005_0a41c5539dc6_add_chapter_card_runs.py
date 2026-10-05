"""add chapter_card_runs

Revision ID: 0a41c5539dc6
Revises: 2990dadf372f
Create Date: 2026-10-05 15:34:54.504416

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0a41c5539dc6'
down_revision: Union[str, Sequence[str], None] = '2990dadf372f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    """Upgrade schema."""
    # db_init's legacy bridge builds pre-Alembic databases from the live models, so the table
    # can already exist when this replays.
    if _has_table("chapter_card_runs"):
        return
    op.create_table(
        "chapter_card_runs",
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("chapter_id", sa.String(), nullable=False),
        sa.Column("cards", sa.Integer(), nullable=False),
        sa.Column("written_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("document_id", "chapter_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("chapter_card_runs")
