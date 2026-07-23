"""add documents.is_technical

Revision ID: 41b18d4c6987
Revises: cc1bfee0cb5b
Create Date: 2026-07-23 09:45:46.900592

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '41b18d4c6987'
down_revision: Union[str, Sequence[str], None] = 'cc1bfee0cb5b'
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
    if _has_column("documents", "is_technical"):
        return
    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.add_column(sa.Column("is_technical", sa.Boolean(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.drop_column("is_technical")
