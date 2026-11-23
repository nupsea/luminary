"""add scopes to devices

Revision ID: 5c0d3e9a71b2
Revises: 7f6bcd0f8881
Create Date: 2026-11-21 16:00:00.000000

A device paired before 0.19.0 was admitted to every route but two (#532). Its row gets the
default device scopes, so it keeps reading and writing notes and loses the rest.
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5c0d3e9a71b2"
down_revision: str | Sequence[str] | None = "7f6bcd0f8881"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Spelled out, not imported: a revision is a record of what it did then.
_DEFAULTS = json.dumps(["read", "notes:write", "reviews:write"])


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    # db_init's legacy bridge builds pre-Alembic databases from the live models.
    if _has_column("devices", "scopes"):
        return
    op.add_column(
        "devices",
        sa.Column("scopes", sa.JSON(), server_default=_DEFAULTS, nullable=False),
    )


def downgrade() -> None:
    if _has_column("devices", "scopes"):
        op.execute("ALTER TABLE devices DROP COLUMN scopes")
