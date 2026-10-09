"""drop sections.difficulty_estimate

Written only by the LLM prerequisite extractor, removed with it (#227). That job was
never enqueued, so no database holds a value here.

Revision ID: e7c41a9b2f08
Revises: 473a1ea0dabc
Create Date: 2026-10-09 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e7c41a9b2f08'
down_revision: str | Sequence[str] | None = '473a1ea0dabc'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column() -> bool:
    columns = sa.inspect(op.get_bind()).get_columns("sections")
    return any(c["name"] == "difficulty_estimate" for c in columns)


def upgrade() -> None:
    """Upgrade schema."""
    if _has_column():
        with op.batch_alter_table("sections") as batch_op:
            batch_op.drop_column("difficulty_estimate")


def downgrade() -> None:
    """Downgrade schema."""
    if not _has_column():
        with op.batch_alter_table("sections") as batch_op:
            batch_op.add_column(sa.Column("difficulty_estimate", sa.Integer(), nullable=True))
