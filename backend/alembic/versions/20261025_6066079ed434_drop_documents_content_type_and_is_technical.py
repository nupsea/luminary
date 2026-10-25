"""drop documents.content_type and documents.is_technical

Revision ID: 6066079ed434
Revises: a96d0035d8f0
Create Date: 2026-10-25 15:31:00.000000

The kind derives from format and the facets, which a96d0035d8f0 filled (#223).

**In place, never batch mode.** Batch mode rebuilds `documents` and drops the old
table, and with foreign keys on, as the app's connection has them, that drop
cascades: every chunk, section, card and note source of every document goes with
it. SQLite has dropped a column in place since 3.35.0; neither column is indexed,
keyed or named by a view or trigger, so nothing blocks it.
"""
import sqlite3
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "6066079ed434"
down_revision: str | Sequence[str] | None = "a96d0035d8f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DROPPED = ("content_type", "is_technical")


def _columns() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("documents")}


def upgrade() -> None:
    if sqlite3.sqlite_version_info < (3, 35, 0):
        raise RuntimeError(
            f"SQLite {sqlite3.sqlite_version} cannot drop a column in place; "
            "3.35.0 or newer is required to upgrade this library"
        )
    present = _columns()
    for column in _DROPPED:
        if column in present:
            op.execute(f"ALTER TABLE documents DROP COLUMN {column}")


def downgrade() -> None:
    """Restore both columns, derived from what replaced them.

    The type is the kind's legacy name: `document_kind` with each technical form
    given the content type that mapped to it.
    """
    present = _columns()
    if "content_type" not in present:
        op.execute("ALTER TABLE documents ADD COLUMN content_type VARCHAR NOT NULL DEFAULT 'book'")
        op.execute(
            "UPDATE documents SET content_type = CASE "
            "  WHEN format IN ('mp3', 'm4a', 'wav', 'flac') THEN 'audio' "
            "  WHEN format = 'mp4' THEN 'video' "
            "  WHEN form = 'dialogue' THEN 'conversation' "
            "  WHEN form = 'paper' THEN 'paper' "
            "  WHEN form = 'source_code' THEN 'code' "
            "  WHEN form = 'entries' THEN 'notes' "
            "  WHEN domain = 'technical' AND form = 'reference' THEN 'tech_book' "
            "  WHEN domain = 'technical' THEN 'tech_article' "
            "  ELSE 'book' END"
        )
    if "is_technical" not in present:
        op.execute("ALTER TABLE documents ADD COLUMN is_technical BOOLEAN")
        op.execute(
            "UPDATE documents SET is_technical = CASE domain "
            "  WHEN 'technical' THEN 1 WHEN 'general' THEN 0 END"
        )
