"""One-time import of the Kuzu graph into SQLite, run at startup, one domain at a time.

A domain is imported in one transaction and verified before it commits: the rows added to
each table must equal the rows planned, and imported plus skipped must equal what was read.
A failure rolls back and is retried at the next launch. `graph.kuzu` is only ever read, so
an import can be repeated and an older build still finds its graph. Rows that belonged to
deleted documents or concepts are skipped and counted by reason (#204).
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.database import get_session_factory
from app.models import GraphConceptDocumentModel, GraphConceptEdgeModel
from app.repos.graph_import_repo import GraphImportRepo
from app.services.startup_status import get_startup_status

logger = logging.getLogger(__name__)

_PHASE = "graph_import"


class ImportMismatch(RuntimeError):
    """The rows a domain wrote do not account for the rows it read."""


@dataclass
class DomainPlan:
    """What one domain will write: rows per model, and what it skipped and why."""

    rows: dict[type, list[dict[str, Any]]] = field(default_factory=dict)
    read: int = 0
    skipped: Counter[str] = field(default_factory=Counter)

    def keep(self, model: type, row: dict[str, Any]) -> None:
        self.rows.setdefault(model, []).append(row)


def _rows(conn, query: str) -> list[list]:
    result = conn.execute(query)
    out = []
    while result.has_next():
        out.append(result.get_next())
    return out


def _read_concepts(conn) -> tuple[list, list]:
    related = _rows(
        conn,
        "MATCH (a:Concept)-[r:CONCEPT_RELATED_TO]->(b:Concept)"
        " RETURN a.id, b.id, r.weight, r.status",
    )
    prereq = _rows(
        conn,
        "MATCH (a:Concept)-[r:CONCEPT_PREREQUISITE_OF]->(b:Concept)"
        " RETURN a.id, b.id, r.confidence",
    )
    edges = [("related", a, b, w, None, s) for a, b, w, s in related]
    edges += [("prerequisite", a, b, None, c, None) for a, b, c in prereq]
    links = _rows(conn, "MATCH (c:Concept)-[:EXTRACTED_FROM]->(d:Document) RETURN c.id, d.id")
    return edges, links


async def _plan_concepts(repo: GraphImportRepo, kuzu_conn) -> DomainPlan:
    edges, links = await asyncio.to_thread(_read_concepts, kuzu_conn)
    concepts, documents = await repo.concept_ids(), await repo.document_ids()
    seen_edges, seen_links = await repo.concept_edge_keys(), await repo.concept_document_keys()
    plan = DomainPlan(read=len(edges) + len(links))
    for kind, src, dst, weight, confidence, status in edges:
        if src not in concepts or dst not in concepts:
            plan.skipped["concept_deleted"] += 1
        elif (kind, src, dst) in seen_edges:
            plan.skipped["already_present"] += 1
        else:
            seen_edges.add((kind, src, dst))
            row = {"kind": kind, "source_id": src, "target_id": dst}
            row |= {"weight": weight, "confidence": confidence, "status": status}
            plan.keep(GraphConceptEdgeModel, row)
    for concept_id, document_id in links:
        if concept_id not in concepts:
            plan.skipped["concept_deleted"] += 1
        elif document_id not in documents:
            plan.skipped["document_deleted"] += 1
        elif (concept_id, document_id) in seen_links:
            plan.skipped["already_present"] += 1
        else:
            seen_links.add((concept_id, document_id))
            row = {"concept_id": concept_id, "document_id": document_id}
            plan.keep(GraphConceptDocumentModel, row)
    return plan


# Order is the foreign-key order: a later domain may point at an earlier one's rows. Each
# entry names every table the domain writes, so an empty copy still reports its zeroes.
DOMAINS: dict[str, tuple[Callable, tuple[type, ...]]] = {
    "concepts": (_plan_concepts, (GraphConceptEdgeModel, GraphConceptDocumentModel)),
}


async def _import_domain(name: str, kuzu_conn) -> tuple[dict, dict]:
    plan_fn, tables = DOMAINS[name]
    async with get_session_factory()() as session:
        repo = GraphImportRepo(session)
        plan = await plan_fn(repo, kuzu_conn)
        imported: dict[str, int] = {}
        for model in tables:
            rows = plan.rows.get(model, [])
            before = await repo.count(model)
            await repo.insert_rows(model, rows)
            added = await repo.count(model) - before
            if added != len(rows):
                raise ImportMismatch(f"{model.__tablename__}: wrote {added}, planned {len(rows)}")
            imported[model.__tablename__] = added
        skipped = dict(plan.skipped)
        if sum(imported.values()) + sum(skipped.values()) != plan.read:
            raise ImportMismatch(f"read {plan.read}, imported {imported}, skipped {skipped}")
        await repo.record(name, "done", imported=imported, skipped=skipped)
        await session.commit()
    return imported, skipped


async def _record_alone(domain: str, status: str, error: str | None = None) -> None:
    async with get_session_factory()() as session:
        await GraphImportRepo(session).record(domain, status, error=error)
        await session.commit()


async def _pending_domains() -> list[str]:
    async with get_session_factory()() as session:
        done = await GraphImportRepo(session).done_domains()
    return [name for name in DOMAINS if name not in done]


async def _open(open_kuzu: Callable[[], Any], pending: list[str]):
    """The Kuzu connection, or None after recording why every pending domain must wait."""
    from app.services.graph_connection import GraphDatabaseLockedError  # noqa: PLC0415

    try:
        return open_kuzu()
    except GraphDatabaseLockedError as exc:
        status, error = "deferred", str(exc)
        detail = "Another Luminary process holds the graph; retried next launch"
    except Exception as exc:
        logger.warning("graph import: cannot open graph.kuzu", exc_info=True)
        status, error, detail = "failed", str(exc), "The old knowledge graph could not be read"
    for name in pending:
        await _record_alone(name, status, error)
    get_startup_status().set_state(_PHASE, "failed", detail)
    return None


async def _import_all(pending: list[str], kuzu_conn) -> list[str]:
    failed: list[str] = []
    for name in pending:
        try:
            imported, skipped = await _import_domain(name, kuzu_conn)
            logger.info(
                "graph import: %s done", name, extra={"imported": imported, "skipped": skipped}
            )
        except Exception as exc:
            logger.warning("graph import: %s failed; retried next launch", name, exc_info=True)
            await _record_alone(name, "failed", str(exc))
            failed.append(name)
    return failed


async def run_graph_import(data_dir: str, open_kuzu: Callable[[], Any]) -> None:
    """Import every domain not yet done. Never raises: the app starts either way.

    `open_kuzu` returns a Kuzu connection. While the app still serves unported domains
    from Kuzu it is the app's own connection, because a second open from this process
    would contend with the lock this process already holds.
    """
    status = get_startup_status()
    pending = await _pending_domains()
    if pending and not (Path(data_dir).expanduser() / "graph.kuzu").exists():
        for name in pending:
            await _record_alone(name, "done")
        pending = []
    if not pending:
        status.set_state(_PHASE, "ready")
        return
    status.set_state(_PHASE, "loading", "Moving your knowledge graph")
    kuzu_conn = await _open(open_kuzu, pending)
    if kuzu_conn is None:
        return
    failed = await _import_all(pending, kuzu_conn)
    if failed:
        status.set_state(_PHASE, "failed", f"Not yet moved: {', '.join(failed)}")
    else:
        status.set_state(_PHASE, "ready")
