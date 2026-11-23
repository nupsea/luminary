"""add change feed

Revision ID: ac7d219e984f
Revises: b81e4c2f9d07
Create Date: 2026-11-23 17:48:00.408527

Triggers record every write to notes and documents in `change_log`, one row per entity (#450).
Every existing note and document gets a row, so a cursor of 0 lists the whole library.
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ac7d219e984f"
down_revision: str | Sequence[str] | None = "b81e4c2f9d07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Spelled out, not imported: a revision is a record of what it did then.
_TABLES = {
    "documents": (
        "document",
        "title, format, stage, tags, word_count, page_count, chapter_count, error_message, "
        "form, domain, register, is_favorite",
    ),
    "notes": (
        "note",
        "document_id, chunk_id, section_id, content, tags, group_name, title, description, "
        "archived, is_favorite",
    ),
}


def _record(entity: str, row: str, op_name: str) -> str:
    return (
        f"DELETE FROM change_log WHERE entity = '{entity}' AND entity_id = {row}.id; "
        f"INSERT INTO change_log (entity, entity_id, op, at) "
        f"VALUES ('{entity}', {row}.id, '{op_name}', CURRENT_TIMESTAMP);"
    )


def _triggers(table: str) -> list[str]:
    entity, columns = _TABLES[table]
    return [
        f"CREATE TRIGGER IF NOT EXISTS change_feed_{table}_insert AFTER INSERT ON {table} "
        f"BEGIN {_record(entity, 'NEW', 'upsert')} END",
        f"CREATE TRIGGER IF NOT EXISTS change_feed_{table}_update "
        f"AFTER UPDATE OF {columns} ON {table} BEGIN {_record(entity, 'NEW', 'upsert')} END",
        f"CREATE TRIGGER IF NOT EXISTS change_feed_{table}_delete AFTER DELETE ON {table} "
        f"BEGIN {_record(entity, 'OLD', 'delete')} END",
    ]


def _has_table(table: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table)


def upgrade() -> None:
    # db_init's legacy bridge builds pre-Alembic databases from the live models.
    if not _has_table("change_feed_state"):
        op.create_table(
            "change_feed_state",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("epoch", sa.String(length=36), nullable=False),
            sa.Column("horizon_seq", sa.Integer(), server_default="0", nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
    if not _has_table("change_log"):
        op.create_table(
            "change_log",
            sa.Column("seq", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("entity", sa.String(length=16), nullable=False),
            sa.Column("entity_id", sa.String(), nullable=False),
            sa.Column("op", sa.String(length=8), nullable=False),
            sa.Column(
                "at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False
            ),
            sa.PrimaryKeyConstraint("seq"),
            sa.UniqueConstraint("entity", "entity_id", name="uq_change_log_entity"),
            sqlite_autoincrement=True,
        )
    op.execute(
        sa.text(
            "INSERT OR IGNORE INTO change_feed_state (id, epoch, horizon_seq) VALUES (1, :e, 0)"
        ).bindparams(e=str(uuid.uuid4()))
    )
    for table, (entity, _) in _TABLES.items():
        op.execute(
            f"INSERT OR IGNORE INTO change_log (entity, entity_id, op, at) "
            f"SELECT '{entity}', id, 'upsert', CURRENT_TIMESTAMP FROM {table} ORDER BY created_at"
        )
        for ddl in _triggers(table):
            op.execute(ddl)


def downgrade() -> None:
    for table in _TABLES:
        for kind in ("insert", "update", "delete"):
            op.execute(f"DROP TRIGGER IF EXISTS change_feed_{table}_{kind}")
    op.drop_table("change_log")
    op.drop_table("change_feed_state")
