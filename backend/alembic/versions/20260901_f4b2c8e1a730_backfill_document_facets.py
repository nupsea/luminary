"""backfill document facets from content_type and is_technical

Revision ID: f4b2c8e1a730
Revises: d1a49d907515
Create Date: 2026-09-01 13:12:00.000000

Data only, and separate from the schema revision on purpose. SQLite DDL runs
outside the surrounding transaction while DML does not, so a combined revision
that crashes leaves the column committed and the data rolled back -- and the
usual `if _has_column(...): return` guard then skips the backfill forever.

Guarded on the data instead (`WHERE form IS NULL`), so this is idempotent and
re-running it completes a partial job rather than skipping it.

The mapping is inlined rather than imported from `app.types`: a revision has to
keep producing the same result after the application's own mapping moves on.

`register` is deliberately left null. Nothing classifies it yet, and a guessed
value would be indistinguishable from a measured one.

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f4b2c8e1a730"
down_revision: str | Sequence[str] | None = "d1a49d907515"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Unmapped content types keep a null form: null means "not classified", which
# is honest, where a default would be a guess wearing a measurement's clothes.
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
    # Transient upload choice; classify_node resolves it before persisting, so
    # this only covers a row caught mid-ingest.
    "technical": "article",
}


def upgrade() -> None:
    """Fill facets for rows that predate them."""
    bind = op.get_bind()

    for content_type, form in _FORM_BY_CONTENT_TYPE.items():
        bind.execute(
            sa.text(
                "UPDATE documents SET form = :form "
                "WHERE content_type = :ct AND form IS NULL"
            ),
            {"form": form, "ct": content_type},
        )

    # Exactly what `is_technical_content` resolves: the persisted flag wins when
    # set, and rows predating it fall back to the content type. Reproducing it
    # here rather than improving on it is the point -- NER has to see the same
    # answer after this revision that it saw before.
    bind.execute(
        sa.text(
            "UPDATE documents SET domain = CASE "
            "  WHEN is_technical IS NOT NULL THEN "
            "    CASE WHEN is_technical THEN 'technical' ELSE 'general' END "
            "  WHEN content_type IN ('code', 'tech_book', 'tech_article') THEN 'technical' "
            "  ELSE 'general' "
            "END "
            "WHERE domain IS NULL AND content_type IS NOT NULL"
        )
    )


def downgrade() -> None:
    """No-op.

    The facets exist only because d1a49d907515 added the columns, and that
    revision's downgrade drops them. Nulling the values here would additionally
    discard anything the classifier wrote, which this revision never set.
    """
