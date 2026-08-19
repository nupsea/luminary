"""record the chunks a flashcard was written from

`chunk_id` holds the first chunk of the generation scope, not the passage the card
came from. Trusting it for a retrospective factuality measurement showed the judge
a passage without the card's own quote in it 56 times out of 60, and the resulting
0.3333 measured the harness.

`source_chunk_ids` is the passage, in reading order. NULL means the card predates
this column or came from a path with no chunks (note-sourced); [] means the passage
was text supplied directly and is not reconstructible from the library. Both are
distinct from a recorded passage and neither may be read as one.

Revision ID: eaa07024ed9e
Revises: e424923d6996
Create Date: 2026-08-18 13:07:55.284611

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "eaa07024ed9e"
down_revision: str | Sequence[str] | None = "e424923d6996"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    if _has_column("flashcards", "source_chunk_ids"):
        return
    with op.batch_alter_table("flashcards", schema=None) as batch_op:
        batch_op.add_column(sa.Column("source_chunk_ids", sa.JSON(), nullable=True))


def downgrade() -> None:
    if not _has_column("flashcards", "source_chunk_ids"):
        return
    with op.batch_alter_table("flashcards", schema=None) as batch_op:
        batch_op.drop_column("source_chunk_ids")
