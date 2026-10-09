"""add pdf bookmark page to reading positions

Revision ID: a19d3e8f18b5
Revises: e7c41a9b2f08
Create Date: 2026-10-10 00:12:29.679886

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a19d3e8f18b5'
down_revision: Union[str, Sequence[str], None] = 'e7c41a9b2f08'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    """Upgrade schema."""
    # db_init's legacy bridge builds pre-Alembic databases from the live models, so the column
    # can already exist when this replays.
    if _has_column("reading_positions", "pdf_bookmark_page"):
        return
    with op.batch_alter_table("reading_positions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("pdf_bookmark_page", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("reading_positions", schema=None) as batch_op:
        batch_op.drop_column("pdf_bookmark_page")
