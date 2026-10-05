"""add chapter_prompt_off to documents

Revision ID: 552f50980761
Revises: 0a41c5539dc6
Create Date: 2026-10-05 14:53:01.897777

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '552f50980761'
down_revision: Union[str, Sequence[str], None] = '0a41c5539dc6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    """Upgrade schema."""
    # db_init's legacy bridge builds pre-Alembic databases from the live models, so the column
    # can already exist when this replays.
    if _has_column("documents", "chapter_prompt_off"):
        return
    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("chapter_prompt_off", sa.Boolean(), server_default="0", nullable=False)
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.drop_column("chapter_prompt_off")
