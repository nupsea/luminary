"""add documents.structure_type

Revision ID: a108cd659810
Revises: 043bc6e747f6
Create Date: 2026-08-08 08:54:05.530484

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a108cd659810'
down_revision: Union[str, Sequence[str], None] = '043bc6e747f6'
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
    if _has_column("documents", "structure_type"):
        return
    # Nullable with no backfill: the layout is discovered while parsing, so
    # documents ingested before this column stay null until re-ingested.
    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.add_column(sa.Column("structure_type", sa.String(length=20), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.drop_column("structure_type")
