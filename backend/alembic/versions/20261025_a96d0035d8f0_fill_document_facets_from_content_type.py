"""fill document facets from content_type before it is dropped

Revision ID: a96d0035d8f0
Revises: bb347838d5f8
Create Date: 2026-10-25 15:30:00.000000

The facets every reader resolves today, written down: `DocumentProfile.of` filled a
null form from content_type and a null domain from is_technical or a technical type.
f4b2c8e1a730 did this once; rows written since (a probe that could not answer) need it
again before 6066079ed434 drops the columns those fallbacks read (#223).

Data only, separate from the drop for the reason f4b2c8e1a730 gives: SQLite DDL runs
outside the transaction. The mapping is inlined so the revision never moves.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a96d0035d8f0"
down_revision: str | Sequence[str] | None = "bb347838d5f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# An unmapped type keeps a null form, which reads as `entries` with or without the column.
_FORM_BY_CONTENT_TYPE = {
    "book": "prose",
    "epub": "prose",
    "paper": "paper",
    "tech_book": "reference",
    "tech_article": "article",
    "conversation": "dialogue",
    "audio": "dialogue",
    "video": "dialogue",
    "notes": "entries",
    "kindle_clippings": "entries",
    "code": "source_code",
    "technical": "article",
}


def _has_column(name: str) -> bool:
    return any(c["name"] == name for c in sa.inspect(op.get_bind()).get_columns("documents"))


def upgrade() -> None:
    """Fill the facets the legacy columns supplied."""
    if not _has_column("content_type"):
        return
    bind = op.get_bind()
    for content_type, form in _FORM_BY_CONTENT_TYPE.items():
        bind.execute(
            sa.text("UPDATE documents SET form = :form WHERE content_type = :ct AND form IS NULL"),
            {"form": form, "ct": content_type},
        )
    bind.execute(
        sa.text(
            "UPDATE documents SET domain = CASE "
            "  WHEN is_technical IS NOT NULL THEN "
            "    CASE WHEN is_technical THEN 'technical' ELSE 'general' END "
            "  ELSE 'technical' "
            "END "
            "WHERE domain IS NULL "
            "  AND (is_technical IS NOT NULL "
            "       OR content_type IN ('code', 'tech_book', 'tech_article'))"
        )
    )


def downgrade() -> None:
    """No-op: the filled values are what every reader already resolved."""
