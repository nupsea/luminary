"""copy focus_sessions into pomodoro_sessions

The header timer writes pomodoro_sessions; focus_sessions was a second record of the same
thing that no UI wrote. Any rows it holds move across before the next revision drops it.
A row that never ended becomes 'abandoned': an 'active' one would block the timer.

Revision ID: 5b7e0c2d9a41
Revises: fd3501237c3a
Create Date: 2026-10-18 19:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '5b7e0c2d9a41'
down_revision: str | Sequence[str] | None = 'fd3501237c3a'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    if not sa.inspect(op.get_bind()).has_table("focus_sessions"):
        return
    op.execute(
        """
        INSERT OR IGNORE INTO pomodoro_sessions (
            id, started_at, completed_at, focus_minutes, break_minutes, status, surface,
            pause_accumulated_seconds, created_at
        )
        SELECT
            id, started_at, CASE WHEN completed THEN ended_at END, planned_duration_minutes, 5,
            CASE WHEN completed THEN 'completed' ELSE 'abandoned' END, 'none', 0, created_at
        FROM focus_sessions
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    # The copied rows are indistinguishable from pomodoros recorded by the timer.
