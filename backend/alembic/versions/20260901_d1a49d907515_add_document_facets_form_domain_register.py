"""add document facets form domain register

Revision ID: d1a49d907515
Revises: 02413afceaa7
Create Date: 2026-09-01 13:01:08.901538

Schema only. The backfill is revision f4b2c8e1a730, deliberately separate:
SQLite DDL runs outside the surrounding transaction, so a crash in a revision
that both adds a column and fills it commits the column and rolls the data
back. The column guard below would then skip the backfill on the replay, and
every row would stay null with nothing reporting it.

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d1a49d907515"
down_revision: str | Sequence[str] | None = "02413afceaa7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = ("form", "domain", "register")


def _existing() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {col["name"] for col in inspector.get_columns("documents")}


def upgrade() -> None:
    """Upgrade schema."""
    # Guarded per column, not per revision: db_init's legacy bridge builds
    # pre-Alembic databases from the live models before stamping the baseline,
    # so some of these may already exist while others do not.
    present = _existing()
    missing = [c for c in _COLUMNS if c not in present]
    if not missing:
        return
    with op.batch_alter_table("documents", schema=None) as batch_op:
        for name in missing:
            batch_op.add_column(sa.Column(name, sa.String(length=20), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    present = _existing()
    with op.batch_alter_table("documents", schema=None) as batch_op:
        for name in reversed(_COLUMNS):
            if name in present:
                batch_op.drop_column(name)
