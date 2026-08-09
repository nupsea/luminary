"""add sections.body for lossless reader text

Revision ID: 043bc6e747f6
Revises: d3aec9a2984d
Create Date: 2026-08-07 23:53:34.253084

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '043bc6e747f6'
down_revision: Union[str, Sequence[str], None] = 'd3aec9a2984d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    """Upgrade schema."""
    # db_init's legacy bridge builds pre-Alembic databases from the live models
    # and only then stamps the baseline, so on that path this column already
    # exists by the time the revision replays. Additive revisions must tolerate it.
    if _has_column("sections", "body"):
        return
    # server_default fills existing rows: the column is NOT NULL and batch mode
    # recreates the table, so rows ingested before this revision need a value.
    # They stay empty on purpose -- their original text was never stored and
    # cannot be recovered, so the reader falls back a tier (I-29) until the
    # document is re-ingested.
    with op.batch_alter_table("sections", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("body", sa.Text(), nullable=False, server_default="")
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("sections", schema=None) as batch_op:
        batch_op.drop_column("body")
