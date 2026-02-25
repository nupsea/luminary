#!/usr/bin/env python3
"""Seed cleanup utility — remove test/fixture documents from the Luminary database.

Deletes documents whose title (case-insensitive) contains any of:
  test, sample, seed, fixture, untitled

Cascades to all related tables: chunks, sections, summaries, flashcards,
misconceptions, notes, study_sessions, qa_history, FTS5 index, LanceDB
vectors, and Kuzu graph nodes.

Usage:
  python scripts/seed_cleanup.py              # dry-run (lists candidates)
  python scripts/seed_cleanup.py --dry-run    # explicit dry-run
  python scripts/seed_cleanup.py --confirm    # actually delete
  python scripts/seed_cleanup.py --data-dir /custom/path --confirm
"""

import argparse
import sqlite3
import sys
from pathlib import Path

SEED_KEYWORDS = ("test", "sample", "seed", "fixture", "untitled")

# Tables with document_id FK (cleared in cascade order before the document row)
CHILD_TABLES = [
    "misconceptions",
    "flashcards",
    "summaries",
    "notes",
    "qa_history",
    "study_sessions",
    "sections",
    "chunks",
]


def _find_candidates(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """Return list of (id, title) tuples whose titles contain seed keywords."""
    rows = conn.execute("SELECT id, title FROM documents").fetchall()
    candidates = []
    for doc_id, title in rows:
        title_lower = (title or "").lower()
        if any(kw in title_lower for kw in SEED_KEYWORDS):
            candidates.append((doc_id, title))
    return candidates


def _delete_sqlite_cascade(conn: sqlite3.Connection, doc_id: str) -> None:
    """Delete all rows related to doc_id from SQLite (including FTS5 virtual table)."""
    # FTS5 virtual table first (no FK, must delete manually)
    conn.execute("DELETE FROM chunks_fts WHERE document_id = ?", (doc_id,))
    for table in CHILD_TABLES:
        conn.execute(f"DELETE FROM {table} WHERE document_id = ?", (doc_id,))  # noqa: S608
    conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    conn.commit()


def _try_delete_lancedb(vectors_dir: Path, doc_id: str) -> None:
    """Remove vectors for doc_id from LanceDB. Silent no-op if LanceDB unavailable."""
    try:
        import lancedb  # type: ignore[import]
    except ImportError:
        return
    try:
        db = lancedb.connect(str(vectors_dir))
        tables = db.list_tables()
        # lancedb >=0.5 returns an object; handle both list and object
        table_names = tables.tables if hasattr(tables, "tables") else list(tables)
        if "chunk_vectors" in table_names:
            table = db.open_table("chunk_vectors")
            table.delete(f"document_id = '{doc_id}'")
    except Exception as exc:  # noqa: BLE001
        print(f"  [warn] LanceDB cleanup failed for {doc_id}: {exc}", file=sys.stderr)


def _try_delete_kuzu(graph_path: Path, doc_id: str) -> None:
    """Remove graph nodes for doc_id from Kuzu. Silent no-op if Kuzu unavailable."""
    try:
        import kuzu  # type: ignore[import]
    except ImportError:
        return
    try:
        db = kuzu.Database(str(graph_path))
        conn = kuzu.Connection(db)
        conn.execute(
            "MATCH (e:Entity)-[r:MENTIONED_IN]->(d:Document {id: $did}) DELETE r",
            {"did": doc_id},
        )
        conn.execute("MATCH (d:Document {id: $did}) DELETE d", {"did": doc_id})
    except Exception as exc:  # noqa: BLE001
        print(f"  [warn] Kuzu cleanup failed for {doc_id}: {exc}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="Remove seed/test documents from Luminary.")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Actually delete documents (default is dry-run).",
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=True,
        help="List candidates without deleting (default).",
    )
    parser.add_argument(
        "--data-dir",
        default="~/.luminary",
        help="Path to Luminary data directory (default: ~/.luminary).",
    )
    args = parser.parse_args()

    # --confirm overrides --dry-run
    dry_run = not args.confirm

    data_dir = Path(args.data_dir).expanduser()
    db_path = data_dir / "luminary.db"

    if not db_path.exists():
        print(f"Database not found: {db_path}", file=sys.stderr)
        print("Is the data directory correct? Use --data-dir to specify.", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(db_path))
    try:
        candidates = _find_candidates(conn)
    finally:
        if dry_run:
            conn.close()

    if not candidates:
        print("No seed/test documents found.")
        return 0

    print(f"Found {len(candidates)} seed/test document(s):")
    for doc_id, title in candidates:
        print(f"  {doc_id[:8]}...  {title!r}")

    if dry_run:
        print(
            f"\nDry-run: no documents deleted. "
            f"Run with --confirm to delete {len(candidates)} document(s)."
        )
        return 0

    # --confirm: actually delete
    vectors_dir = data_dir / "vectors"
    graph_path = data_dir / "graph.kuzu"

    deleted = 0
    for doc_id, title in candidates:
        print(f"  Deleting {doc_id[:8]}...  {title!r}")
        _delete_sqlite_cascade(conn, doc_id)
        _try_delete_lancedb(vectors_dir, doc_id)
        _try_delete_kuzu(graph_path, doc_id)
        deleted += 1

    conn.close()
    print(f"\nDeleted {deleted} document(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
