"""index document_id on the four tables the library list counts

Revision ID: 96079303a732
Revises: f4b2c8e1a730
Create Date: 2026-09-03 08:09:27.358085

`GET /documents` runs a correlated `count(*)` per row over each of these, and
none of them had an index on `document_id`, so every count was a full table
scan -- `chunks` at 75,726 rows, once per document on the page.

`op.create_index` rather than `batch_alter_table`: batch mode can rebuild the
table, and rebuilding `chunks` to add an index is a large copy for no reason.

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "96079303a732"
down_revision: str | Sequence[str] | None = "f4b2c8e1a730"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEXES = (
    ("ix_chunks_document_id", "chunks"),
    ("ix_flashcards_document_id", "flashcards"),
    ("ix_sections_document_id", "sections"),
    ("ix_summaries_document_id", "summaries"),
)


def _existing(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {ix["name"] for ix in inspector.get_indexes(table)}


def upgrade() -> None:
    """Upgrade schema."""
    # Guarded per index: db_init's legacy bridge builds pre-Alembic databases
    # from the live models before stamping the baseline, so a database reaching
    # this revision may already carry them. An unguarded CREATE INDEX on an
    # existing name aborts boot.
    for name, table in _INDEXES:
        if name not in _existing(table):
            op.create_index(name, table, ["document_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    for name, table in reversed(_INDEXES):
        if name in _existing(table):
            op.drop_index(name, table_name=table)
