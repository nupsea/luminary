"""enrichment job attempts counter

Revision ID: d3aec9a2984d
Revises: b3d1a7c4e920
Create Date: 2026-08-06 13:38:06.677902

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd3aec9a2984d'
down_revision: Union[str, Sequence[str], None] = 'b3d1a7c4e920'
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
    if _has_column("enrichment_jobs", "attempts"):
        return
    with op.batch_alter_table("enrichment_jobs", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("attempts", sa.Integer(), server_default="0", nullable=False)
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("enrichment_jobs", schema=None) as batch_op:
        batch_op.drop_column("attempts")
