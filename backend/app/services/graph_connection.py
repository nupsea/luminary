"""Read-only access to a `graph.kuzu` left by Luminary up to 0.15.0.

Only the one-time import (`services/graph_import.py`) opens it, and never for writing:
the file stays as it was, so an older build still finds its graph.
"""

from __future__ import annotations

from pathlib import Path

import kuzu


class GraphDatabaseLockedError(RuntimeError):
    """Another live process holds the Kuzu lock."""


def open_read_only(data_dir: str) -> kuzu.Connection:
    """A read-only connection to `<data_dir>/graph.kuzu`.

    Kuzu's lock is an OS file lock the kernel drops when its holder exits, so a held
    lock means a live process (an older Luminary still running): wait for it, never
    clear it (I-24).
    """
    db_path = str(Path(data_dir).expanduser() / "graph.kuzu")
    try:
        return kuzu.Connection(kuzu.Database(db_path, read_only=True))
    except RuntimeError as exc:
        if "lock" in str(exc).lower():
            raise GraphDatabaseLockedError(
                f"The knowledge graph at {db_path} is locked by another running process."
            ) from exc
        raise
