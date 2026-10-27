"""Statements on a snapshot's copy of a library database, over a plain `sqlite3` connection."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable


class SnapshotCopyRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def strip_machine_rows(self, setting_keys: Iterable[str]) -> None:
        """Remove what belongs to the machine, not the library: stored keys, paired devices."""
        self.conn.executemany("DELETE FROM settings WHERE key = ?", [(k,) for k in setting_keys])
        self.conn.execute("DELETE FROM devices")
        self.conn.commit()
        self.conn.execute("VACUUM")

    def schema_revision(self) -> str:
        return self.conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
