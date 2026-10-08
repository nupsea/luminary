"""flashcards document_id cascades from documents

Revision ID: 473a1ea0dabc
Revises: dc23a62094ab
Create Date: 2026-10-08 23:23:50.634846

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '473a1ea0dabc'
down_revision: str | Sequence[str] | None = 'dc23a62094ab'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FK_NAME = "fk_flashcards_document_id_documents"

_ORPHANS = (
    "SELECT id FROM flashcards WHERE document_id IS NOT NULL"
    " AND document_id NOT IN (SELECT id FROM documents)"
)


def _has_document_fk() -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(
        fk["referred_table"] == "documents" and fk["constrained_columns"] == ["document_id"]
        for fk in inspector.get_foreign_keys("flashcards")
    )


def upgrade() -> None:
    """Upgrade schema."""
    # db_init's legacy bridge builds pre-Alembic databases from the live models, so the key
    # can already exist when this replays.
    if _has_document_fk():
        return
    # Cards of an already-deleted document would fail the key when batch mode copies the table.
    # flashcards_fts has no document_id and is matched through its content table (I-4).
    op.execute(
        "DELETE FROM flashcards_fts WHERE rowid IN"
        f" (SELECT rowid FROM flashcards_fts_content WHERE c2 IN ({_ORPHANS}))"
    )
    op.execute(f"DELETE FROM flashcards WHERE id IN ({_ORPHANS})")
    with op.batch_alter_table("flashcards", schema=None) as batch_op:
        batch_op.create_foreign_key(
            FK_NAME, "documents", ["document_id"], ["id"], ondelete="CASCADE"
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("flashcards", schema=None) as batch_op:
        batch_op.drop_constraint(FK_NAME, type_="foreignkey")
