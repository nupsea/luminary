"""add grounding state to flashcards

Whether a card's source_excerpt was found in the text the card came from:
unchecked | verified | unsupported | unverifiable.

Every existing row lands on 'unchecked' rather than on a verdict. A card nobody
has audited is not a card that passed, and defaulting to 'verified' would have
certified the 26% of a real library that quote text their document does not
contain. POST /flashcards/grounding/audit computes the real verdicts.

Revision ID: 039bbf786620
Revises: a108cd659810
Create Date: 2026-08-18 10:06:16.402859

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "039bbf786620"
down_revision: str | Sequence[str] | None = "a108cd659810"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    # Databases that came through the frozen db_init.py bridge may already carry
    # this column; an unguarded ADD COLUMN aborts boot on exactly those.
    if _has_column("flashcards", "grounding"):
        return
    with op.batch_alter_table("flashcards", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "grounding",
                sa.String(),
                server_default=sa.text("'unchecked'"),
                nullable=False,
            )
        )


def downgrade() -> None:
    if not _has_column("flashcards", "grounding"):
        return
    with op.batch_alter_table("flashcards", schema=None) as batch_op:
        batch_op.drop_column("grounding")
