"""add factuality state to flashcards

Whether a card's answer follows from the passage it was written from:
unchecked | supported | unsupported | unverifiable.

Separate from `grounding`, which proves only that the quote is real. A card can
quote a genuine sentence and still assert what the passage does not say.

Existing rows land on 'unchecked'. No checker has seen them, and a row nobody
checked is not a row that passed.

Revision ID: e424923d6996
Revises: 039bbf786620
Create Date: 2026-08-18 11:02:41.118392

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e424923d6996"
down_revision: str | Sequence[str] | None = "039bbf786620"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    if _has_column("flashcards", "factuality"):
        return
    with op.batch_alter_table("flashcards", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "factuality",
                sa.String(),
                server_default=sa.text("'unchecked'"),
                nullable=False,
            )
        )


def downgrade() -> None:
    if not _has_column("flashcards", "factuality"):
        return
    with op.batch_alter_table("flashcards", schema=None) as batch_op:
        batch_op.drop_column("factuality")
