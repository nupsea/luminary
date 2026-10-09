"""Graph parity: does the SQLite graph hold what the Kuzu graph held, minus only stale rows?

Copies a library's `luminary.db` and `graph.kuzu` into a scratch directory, migrates the
copy, runs the one-time import on it, then compares the two stores per live document.
The source library is only read. Every row Kuzu has and SQLite lacks must be explained
by one of the importer's skip reasons; anything else, or any row SQLite has that Kuzu
does not, is a parity failure (exit 1).

Run: MEM_CAP_GB=12 scripts/capped_run.sh uv run python tools/graph_parity.py \\
         --source ../.luminary --work /tmp/parity
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


_MARKER = ".graph_parity"


def _copy_library(source: Path, work: Path) -> None:
    if work.exists() and any(work.iterdir()):
        # Replaced only if this tool made it: a mistyped --work must never delete data.
        if not (work / _MARKER).exists():
            sys.exit(f"{work} is not empty and was not made by graph_parity; refusing")
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    (work / _MARKER).touch()
    # The backup API gives a consistent copy of a database a live backend is writing.
    with sqlite3.connect(f"file:{source / 'luminary.db'}?mode=ro", uri=True) as src:
        with sqlite3.connect(work / "luminary.db") as dst:
            src.backup(dst)
    for name in ("graph.kuzu", "graph.kuzu.wal"):
        if (source / name).exists():
            shutil.copy2(source / name, work / name)


def _kuzu_rows(conn, query: str) -> list[tuple]:
    result = conn.execute(query)
    out = []
    while result.has_next():
        out.append(tuple(result.get_next()))
    return out


def _kuzu_sets(conn) -> dict[str, set[tuple]]:
    """Every graph fact Kuzu holds, keyed so the SQLite side can be read the same way."""
    from app.services.graph_import_read import rows  # noqa: PLC0415

    def q(query: str) -> list[tuple]:
        return [tuple(r.values()) for r in rows(conn, query)]

    return {
        "entity": set(
            q("MATCH (e:Entity)-[:MENTIONED_IN]->(d:Document) RETURN e.id, d.id, e.name, e.type")
        ),
        "entity_edge": set(
            q(
                "MATCH (a:Entity)-[r]->(b:Entity) WHERE label(r) <> 'SAME_CONCEPT'"
                " RETURN label(r), a.id, b.id"
            )
        ),
        "entity_link": set(q("MATCH (a:Entity)-[r:SAME_CONCEPT]->(b:Entity) RETURN a.id, b.id")),
        "diagram_node": set(q("MATCH (n:DiagramNode) RETURN n.id, n.document_id")),
        "note_entity": set(
            q(
                "MATCH (n:Note)-[r]->(e:Entity) RETURN n.id, e.id,"
                " CASE WHEN label(r) = 'WRITTEN_ABOUT' THEN 'written_about' ELSE 'tag' END"
            )
        ),
        "concept_edge": set(
            q(
                "MATCH (a:Concept)-[r]->(b:Concept) RETURN"
                " CASE WHEN label(r) = 'CONCEPT_RELATED_TO' THEN 'related' ELSE 'prerequisite' END,"
                " a.id, b.id"
            )
        ),
    }


def _sqlite_sets(db: Path) -> dict[str, set[tuple]]:
    with sqlite3.connect(db) as conn:

        def q(sql: str) -> set[tuple]:
            return set(conn.execute(sql).fetchall())

        return {
            "entity": q("SELECT id, document_id, name, type FROM graph_entities"),
            "entity_edge": q("SELECT kind, source_id, target_id FROM graph_entity_edges"),
            "entity_link": q("SELECT source_id, target_id FROM graph_entity_links"),
            "diagram_node": q("SELECT id, document_id FROM graph_diagram_nodes"),
            "note_entity": q("SELECT note_id, entity_id, kind FROM graph_note_entities"),
            "concept_edge": q("SELECT kind, source_id, target_id FROM graph_concept_edges"),
            "documents": {r[0] for r in q("SELECT id FROM documents")},
            "notes": {r[0] for r in q("SELECT id FROM notes")},
            "concepts": {r[0] for r in q("SELECT id FROM concepts")},
        }


def _why_missing(kind: str, row: tuple, live: dict) -> str | None:
    """The importer's reason for leaving `row` out, or None if it had none."""
    docs, notes, concepts = live["documents"], live["notes"], live["concepts"]
    imported = {r[0] for r in live["entity"]}
    if kind == "entity":
        return "document_deleted" if row[1] not in docs else None
    if kind == "entity_edge":
        _, a, b = row
        if a not in imported or b not in imported:
            return "entity_missing"
        return "self_pair" if a == b and row[0] == "CO_OCCURS" else None
    if kind == "entity_link":
        return "entity_missing" if row[0] not in imported or row[1] not in imported else None
    if kind == "diagram_node":
        return "document_deleted" if row[1] not in docs else None
    if kind == "note_entity":
        if row[0] not in notes:
            return "note_deleted"
        return "entity_missing" if row[1] not in imported else None
    if kind == "concept_edge":
        return "concept_deleted" if row[1] not in concepts or row[2] not in concepts else None
    return None


async def _import(work: Path) -> float:
    os.environ["DATA_DIR"] = str(work)
    from app.config import get_settings  # noqa: PLC0415
    from app.database import get_engine  # noqa: PLC0415
    from app.db_init import init_database  # noqa: PLC0415
    from app.services.graph_import import run_graph_import  # noqa: PLC0415

    get_settings.cache_clear()
    await init_database(get_engine())
    start = time.perf_counter()
    await run_graph_import(str(work))
    return time.perf_counter() - start


async def _facade_timings(document_ids: list[str]) -> dict[str, float]:
    """Slowest single call of each facade read across the library, in ms."""
    from app.services.graph import get_graph_service  # noqa: PLC0415

    svc = get_graph_service()
    reads = {
        "graph_for_document": lambda d: svc.get_graph_for_document(d, include_notes=True),
        "co_occurring_pairs": lambda d: svc.get_co_occurring_pairs_for_document(d, limit=10),
        "entities_by_type": svc.get_entities_by_type_for_document,
    }
    worst: dict[str, float] = {}
    for name, read in reads.items():
        for doc_id in document_ids:
            start = time.perf_counter()
            await read(doc_id)
            worst[name] = max(worst.get(name, 0.0), (time.perf_counter() - start) * 1000)
    return worst


def _compare(work: Path) -> bool:
    """Print per-kind counts and reasons; True when every difference is explained."""
    import kuzu  # noqa: PLC0415

    conn = kuzu.Connection(kuzu.Database(str(work / "graph.kuzu"), read_only=True))
    expected = _kuzu_sets(conn)
    got = _sqlite_sets(work / "luminary.db")
    ok = True
    for kind, kuzu_rows in expected.items():
        sqlite_rows = got[kind]
        if kind == "entity":
            # Kuzu has a row per (entity, mention); compare on (id, document).
            kuzu_rows = {r[:2] for r in kuzu_rows}
            sqlite_rows = {r[:2] for r in sqlite_rows}
        missing = kuzu_rows - sqlite_rows
        extra = sqlite_rows - kuzu_rows
        why = {r: _why_missing(kind, r, got) for r in missing}
        reasons = Counter(why.values())
        unexplained = [r for r, reason in why.items() if reason is None]
        reasons.pop(None, None)
        print(
            f"{kind:14} kuzu={len(kuzu_rows):7} sqlite={len(sqlite_rows):7}"
            f" skipped={dict(reasons)} unexplained={len(unexplained)} extra={len(extra)}"
        )
        for row in sorted(unexplained)[:5]:
            print(f"    unexplained: {row}")
        for row in sorted(extra)[:5]:
            print(f"    extra: {row}")
        ok = ok and not unexplained and not extra
    return ok


async def _run(work: Path) -> int:
    import_s = await _import(work)
    ok = _compare(work)
    with sqlite3.connect(work / "luminary.db") as conn:
        document_ids = [r[0] for r in conn.execute("SELECT id FROM documents")]
    timings = await _facade_timings(document_ids)
    print(f"import: {import_s:.2f}s")
    print("slowest facade read per document (ms):", {k: round(v, 1) for k, v in timings.items()})
    print("PARITY OK" if ok else "PARITY FAILED")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, required=True, help="library DATA_DIR to read")
    parser.add_argument(
        "--work", type=Path, required=True, help="scratch dir; replaced only if this tool made it"
    )
    args = parser.parse_args(argv)
    source, work = args.source.expanduser().resolve(), args.work.expanduser().resolve()
    if work == source or source in work.parents:
        parser.error("--work must not be the library or inside it")
    _copy_library(source, work)
    return asyncio.run(_run(work))


if __name__ == "__main__":
    sys.exit(main())
