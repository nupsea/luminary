"""add time_on_task for per-activity duration

Revision ID: cae3aba739eb
Revises: e296b18b392a
Create Date: 2026-08-20 09:32:12.881672

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'cae3aba739eb'
down_revision: str | Sequence[str] | None = 'e296b18b392a'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    """Upgrade schema."""
    # db_init's frozen bridge builds pre-Alembic databases from the live models
    # and only then stamps the baseline, so on that path this table already
    # exists by the time the revision replays. An unguarded create_table aborts
    # boot on exactly the databases that have data in them.
    if _has_table("time_on_task"):
        return
    op.create_table('time_on_task',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('activity', sa.String(length=16), nullable=False),
    sa.Column('member_id', sa.String(), nullable=True),
    sa.Column('started_at', sa.DateTime(), nullable=False),
    sa.Column('last_beat_at', sa.DateTime(), nullable=False),
    sa.Column('seconds', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('time_on_task', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_time_on_task_activity'), ['activity'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_time_on_task_started_at'), ['started_at'], unique=False
        )

    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('time_on_task', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_time_on_task_started_at'))
        batch_op.drop_index(batch_op.f('ix_time_on_task_activity'))

    op.drop_table('time_on_task')
    # ### end Alembic commands ###
