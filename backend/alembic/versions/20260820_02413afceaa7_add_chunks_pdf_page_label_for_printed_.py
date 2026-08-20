"""add chunks.pdf_page_label for printed page numbers

Revision ID: 02413afceaa7
Revises: cae3aba739eb
Create Date: 2026-08-20 14:57:19.314599

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '02413afceaa7'
down_revision: str | Sequence[str] | None = 'cae3aba739eb'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    """Upgrade schema."""
    # db_init's frozen bridge builds pre-Alembic databases from the live models
    # and only then stamps the baseline, so on that path this column already
    # exists by the time the revision replays; an unguarded ADD COLUMN aborts
    # boot on exactly the databases that have data in them.
    if _has_column("chunks", "pdf_page_label"):
        return
    with op.batch_alter_table('chunks', schema=None) as batch_op:
        batch_op.add_column(sa.Column('pdf_page_label', sa.String(), nullable=True))

    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('chunks', schema=None) as batch_op:
        batch_op.drop_column('pdf_page_label')

    # ### end Alembic commands ###
