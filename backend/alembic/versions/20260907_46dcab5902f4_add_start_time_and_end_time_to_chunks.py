"""add start_time and end_time to chunks

Revision ID: 46dcab5902f4
Revises: 96079303a732
Create Date: 2026-09-07 08:16:56.658091

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '46dcab5902f4'
down_revision: Union[str, Sequence[str], None] = '96079303a732'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    """Upgrade schema."""
    # db_init's legacy bridge builds pre-Alembic databases from the live models
    # and only then stamps the baseline, so on that path these columns already
    # exist by the time the revision replays. Additive revisions must tolerate it.
    with op.batch_alter_table("chunks", schema=None) as batch_op:
        if not _has_column("chunks", "start_time"):
            batch_op.add_column(sa.Column("start_time", sa.Float(), nullable=True))
        if not _has_column("chunks", "end_time"):
            batch_op.add_column(sa.Column("end_time", sa.Float(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("chunks", schema=None) as batch_op:
        batch_op.drop_column("end_time")
        batch_op.drop_column("start_time")
