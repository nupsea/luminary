"""drop focus_sessions

Its rows were copied into pomodoro_sessions by the previous revision.

Revision ID: 1822f085552e
Revises: 5b7e0c2d9a41
Create Date: 2026-10-18 18:52:00.045914

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '1822f085552e'
down_revision: str | Sequence[str] | None = '5b7e0c2d9a41'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table() -> bool:
    return sa.inspect(op.get_bind()).has_table("focus_sessions")


def upgrade() -> None:
    """Upgrade schema."""
    if _has_table():
        op.drop_table('focus_sessions')


def downgrade() -> None:
    """Downgrade schema."""
    if _has_table():
        return
    op.create_table('focus_sessions',
    sa.Column('id', sa.VARCHAR(), nullable=False),
    sa.Column('started_at', sa.DATETIME(), nullable=False),
    sa.Column('ended_at', sa.DATETIME(), nullable=True),
    sa.Column('planned_duration_minutes', sa.INTEGER(), nullable=False),
    sa.Column('actual_duration_seconds', sa.INTEGER(), nullable=True),
    sa.Column('session_type', sa.VARCHAR(length=20), nullable=False),
    sa.Column('completed', sa.BOOLEAN(), nullable=False),
    sa.Column('xp_awarded', sa.INTEGER(), nullable=False),
    sa.Column('created_at', sa.DATETIME(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
