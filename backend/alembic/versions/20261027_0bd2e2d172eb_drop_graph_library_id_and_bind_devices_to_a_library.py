"""drop the graph library_id columns and bind devices to a library

Revision ID: 0bd2e2d172eb
Revises: 6066079ed434
Create Date: 2026-10-27 09:00:00.000000

Libraries are separated by root, not by a column (#388): the nine graph `library_id`
columns were never written, and a device's requests run in its `library`.

The columns go in place, never by batch mode, which would cascade (I-69). None is
indexed, keyed or named by a view or trigger.
"""

import sqlite3
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0bd2e2d172eb"
down_revision: str | Sequence[str] | None = "6066079ed434"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_GRAPH_TABLES = (
    "graph_concept_edges",
    "graph_concept_documents",
    "graph_entities",
    "graph_entity_edges",
    "graph_entity_links",
    "graph_diagram_nodes",
    "graph_diagram_edges",
    "graph_diagram_depictions",
    "graph_note_entities",
)


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if sqlite3.sqlite_version_info < (3, 35, 0):
        raise RuntimeError(
            f"SQLite {sqlite3.sqlite_version} cannot drop a column in place; "
            "3.35.0 or newer is required to upgrade this library"
        )
    for table in _GRAPH_TABLES:
        if "library_id" in _columns(table):
            op.execute(f"ALTER TABLE {table} DROP COLUMN library_id")
    if "library" not in _columns("devices"):
        op.execute("ALTER TABLE devices ADD COLUMN library VARCHAR(63) NOT NULL DEFAULT 'default'")


def downgrade() -> None:
    if "library" in _columns("devices"):
        op.execute("ALTER TABLE devices DROP COLUMN library")
    for table in _GRAPH_TABLES:
        if "library_id" not in _columns(table):
            op.execute(f"ALTER TABLE {table} ADD COLUMN library_id VARCHAR")
