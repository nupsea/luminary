"""add idempotency keys and note rev

Revision ID: bd9cb257888e
Revises: ac7d219e984f
Create Date: 2026-11-23 18:15:22.846926

A retried write replays its first response (#451), and a note edit made against an older
revision is refused. Plain ALTERs, never batch mode: rebuilding `notes` would drop its
change-feed triggers (I-81) and, with foreign keys on, cascade into its child rows (I-69).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "bd9cb257888e"
down_revision: str | Sequence[str] | None = "ac7d219e984f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table)


def _has_column(table: str, column: str) -> bool:
    return any(c["name"] == column for c in sa.inspect(op.get_bind()).get_columns(table))


def upgrade() -> None:
    # db_init's legacy bridge builds pre-Alembic databases from the live models.
    if not _has_table("idempotency_keys"):
        op.create_table(
            "idempotency_keys",
            sa.Column("principal", sa.String(length=80), nullable=False),
            sa.Column("key", sa.String(length=200), nullable=False),
            sa.Column("request_hash", sa.String(length=64), nullable=False),
            sa.Column("status_code", sa.Integer(), nullable=True),
            sa.Column("body", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("principal", "key"),
        )
    if not _has_column("notes", "rev"):
        op.add_column("notes", sa.Column("rev", sa.Integer(), server_default="0", nullable=False))


def downgrade() -> None:
    if _has_column("notes", "rev"):
        op.execute("ALTER TABLE notes DROP COLUMN rev")
    op.drop_table("idempotency_keys")
