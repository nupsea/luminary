"""One-time import of the Kuzu graph into SQLite, run at startup, one domain at a time.

A domain is imported in one transaction and verified before it commits: the rows added to
each table must equal the rows planned, and imported plus skipped must equal what was read.
A failure rolls back and is retried at the next launch. `graph.kuzu` is only ever read, so
an import can be repeated and an older build still finds its graph. Rows that belonged to
deleted documents, notes or concepts are skipped and counted by reason (#204, #65).

TODO(1.0.0-rc): delete this module, graph_import_read.py, graph_connection.py and the `kuzu`
dependency; the release notes then tell users to delete `graph.kuzu`.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from collections.abc import Callable, Hashable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.database import get_session_factory
from app.models import (
    ConceptModel,
    DocumentModel,
    GraphConceptDocumentModel,
    GraphConceptEdgeModel,
    GraphDiagramDepictionModel,
    GraphDiagramEdgeModel,
    GraphDiagramNodeModel,
    GraphEntityEdgeModel,
    GraphEntityLinkModel,
    GraphEntityModel,
    GraphNoteEntityModel,
    NoteModel,
)
from app.repos.graph_import_repo import GraphImportRepo
from app.services import graph_import_read as read
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

    def keep(self, model: type, seen: set, key: Hashable, row: dict[str, Any]) -> None:
        """Keep `row` unless its unique key is already in SQLite or earlier in this read."""
        if key in seen:
            self.skipped["already_present"] += 1
            return
        seen.add(key)
        self.rows.setdefault(model, []).append(row)


def _pick(row: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {k: row.get(k) for k in keys}


async def _plan_concepts(repo: GraphImportRepo, kuzu_conn) -> DomainPlan:
    edges = await asyncio.to_thread(read.read_concept_edges, kuzu_conn)
    links = await asyncio.to_thread(read.read_concept_documents, kuzu_conn)
    concepts, documents = await repo.keys(ConceptModel.id), await repo.keys(DocumentModel.id)
    E, CD = GraphConceptEdgeModel, GraphConceptDocumentModel
    seen_edges = await repo.keys(E.kind, E.source_id, E.target_id)
    seen_links = await repo.keys(CD.concept_id, CD.document_id)
    plan = DomainPlan(read=len(edges) + len(links))
    for e in edges:
        if e["source_id"] not in concepts or e["target_id"] not in concepts:
            plan.skipped["concept_deleted"] += 1
            continue
        row = _pick(e, "kind", "source_id", "target_id", "weight", "confidence", "status")
        plan.keep(E, seen_edges, (e["kind"], e["source_id"], e["target_id"]), row)
    for link in links:
        if link["concept_id"] not in concepts:
            plan.skipped["concept_deleted"] += 1
        elif link["document_id"] not in documents:
            plan.skipped["document_deleted"] += 1
        else:
            plan.keep(CD, seen_links, (link["concept_id"], link["document_id"]), link)
    return plan


def _entity_rows(raw: list[dict[str, Any]], documents: set[str], plan: DomainPlan) -> dict:
    """One row per live entity, from Kuzu's one row per (entity, mention): id -> row."""
    by_id: dict[str, list[dict[str, Any]]] = {}
    for r in raw:
        by_id.setdefault(r["id"], []).append(r)
    plan.read += len(by_id)
    kept: dict[str, dict[str, Any]] = {}
    for entity_id, mentions in by_id.items():
        live = [m for m in mentions if m["document_id"] in documents]
        if not live:
            # An entity with no mention at all is one the old delete path orphaned (#204).
            plan.skipped["document_deleted" if mentions[0]["document_id"] else "no_document"] += 1
            continue
        first = live[0]
        kept[entity_id] = {
            "id": entity_id,
            "document_id": first["document_id"],
            "name": first["name"] or "",
            "type": first["type"] or "",
            "frequency": first["frequency"] or 1,
            "mention_count": first["mentions"] or 1,
            "aliases": [a for a in (first.get("aliases") or "").split("|") if a],
        }
    return kept


async def _plan_entities(repo: GraphImportRepo, kuzu_conn) -> DomainPlan:
    def read_all(conn) -> tuple[dict[str, list[dict[str, Any]]], int]:
        return {
            "entities": read.read_entities(conn),
            "edges": read.read_entity_edges(conn),
            "links": read.read_entity_links(conn),
            "nodes": read.read_diagram_nodes(conn),
            "diagram_edges": read.read_diagram_edges(conn),
            "depictions": read.read_diagram_depictions(conn),
        }, read.count_unused_entity_edges(conn)

    raw, unused = await asyncio.to_thread(read_all, kuzu_conn)
    documents = await repo.keys(DocumentModel.id)
    plan = DomainPlan(read=sum(len(v) for k, v in raw.items() if k != "entities") + unused)
    if unused:
        plan.skipped["unused"] = unused

    E, EE, EL = GraphEntityModel, GraphEntityEdgeModel, GraphEntityLinkModel
    seen_entities = await repo.keys(E.id)
    entities = _entity_rows(raw["entities"], documents, plan)
    for entity_id, row in entities.items():
        plan.keep(E, seen_entities, entity_id, row)

    seen_edges = await repo.keys(EE.kind, EE.source_id, EE.target_id)
    for e in raw["edges"]:
        src, dst = e["source_id"], e["target_id"]
        # RELATED_TO edges carried no document; an edge belongs to its source's document.
        document_id = e.get("document_id") or entities.get(src, {}).get("document_id")
        if src not in entities or dst not in entities:
            plan.skipped["entity_missing"] += 1
        elif document_id not in documents:
            plan.skipped["document_deleted"] += 1
        elif e["kind"] == "CO_OCCURS" and src == dst:
            plan.skipped["self_pair"] += 1  # I-49
        else:
            row = _pick(e, "kind", "weight", "confidence", "source_section_id", "label")
            row |= {"source_id": src, "target_id": dst, "document_id": document_id}
            plan.keep(EE, seen_edges, (e["kind"], src, dst), row)

    seen_links = await repo.keys(EL.source_id, EL.target_id)
    for link in raw["links"]:
        src, dst = link["source_id"], link["target_id"]
        if src not in entities or dst not in entities:
            plan.skipped["entity_missing"] += 1
            continue
        row = {
            "source_id": src,
            "target_id": dst,
            "source_document_id": link["source_document_id"] or entities[src]["document_id"],
            "target_document_id": link["target_document_id"] or entities[dst]["document_id"],
            "confidence": link["confidence"] or 0.0,
            "contradiction": bool(link["contradiction"]),
            "contradiction_note": link["contradiction_note"] or "",
            "prefer_source": link["prefer_source"] or "",
        }
        plan.keep(EL, seen_links, (src, dst), row)

    _plan_diagrams(plan, raw, documents, set(entities))
    return plan


def _plan_diagrams(plan: DomainPlan, raw: dict, documents: set[str], entities: set[str]) -> None:
    N, DE, DD = GraphDiagramNodeModel, GraphDiagramEdgeModel, GraphDiagramDepictionModel
    nodes: set[str] = set()
    for n in raw["nodes"]:
        if n["document_id"] not in documents:
            plan.skipped["document_deleted"] += 1
            continue
        row = {
            "id": n["id"],
            "document_id": n["document_id"],
            "name": n["name"] or "",
            "node_type": n["node_type"] or "",
            "source_image_id": n["source_image_id"] or "",
            "frequency": n["frequency"] or 1,
        }
        plan.keep(N, nodes, n["id"], row)
    seen_edges: set = set()
    for e in raw["diagram_edges"]:
        if e["source_id"] not in nodes or e["target_id"] not in nodes:
            plan.skipped["node_missing"] += 1
        elif e["document_id"] not in documents:
            plan.skipped["document_deleted"] += 1
        else:
            row = _pick(e, "kind", "source_id", "target_id", "document_id")
            row["label"] = e.get("label") or ""
            plan.keep(DE, seen_edges, (e["kind"], e["source_id"], e["target_id"]), row)
    seen_depictions: set = set()
    for d in raw["depictions"]:
        if d["node_id"] not in nodes:
            plan.skipped["node_missing"] += 1
        elif d["entity_id"] not in entities:
            plan.skipped["entity_missing"] += 1
        elif d["document_id"] not in documents:
            plan.skipped["document_deleted"] += 1
        else:
            plan.keep(DD, seen_depictions, (d["node_id"], d["entity_id"]), d)


async def _plan_notes(repo: GraphImportRepo, kuzu_conn) -> DomainPlan:
    edges = await asyncio.to_thread(read.read_note_entities, kuzu_conn)
    superseded = await asyncio.to_thread(read.count_superseded_note_edges, kuzu_conn)
    notes, entities = await repo.keys(NoteModel.id), await repo.keys(GraphEntityModel.id)
    NE = GraphNoteEntityModel
    seen = await repo.keys(NE.note_id, NE.entity_id, NE.kind)
    plan = DomainPlan(read=len(edges) + superseded)
    if superseded:
        plan.skipped["superseded"] = superseded
    for e in edges:
        if e["note_id"] not in notes:
            plan.skipped["note_deleted"] += 1
        elif e["entity_id"] not in entities:
            plan.skipped["entity_missing"] += 1
        else:
            row = _pick(e, "note_id", "entity_id", "kind", "tag")
            row["confidence"] = e.get("confidence") or 1.0
            plan.keep(NE, seen, (e["note_id"], e["entity_id"], e["kind"]), row)
    return plan


# Order is the foreign-key order: a later domain points at an earlier one's rows, so a
# failure defers the later ones. Each entry names every table the domain writes, so an
# empty copy still reports its zeroes.
DOMAINS: dict[str, tuple[Callable, tuple[type, ...]]] = {
    "concepts": (_plan_concepts, (GraphConceptEdgeModel, GraphConceptDocumentModel)),
    "entities": (
        _plan_entities,
        (
            GraphEntityModel,
            GraphEntityEdgeModel,
            GraphEntityLinkModel,
            GraphDiagramNodeModel,
            GraphDiagramEdgeModel,
            GraphDiagramDepictionModel,
        ),
    ),
    "notes": (_plan_notes, (GraphNoteEntityModel,)),
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
        return await asyncio.to_thread(open_kuzu)
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
    """Import in order; returns the domains not moved: a failed one and every one after it."""
    for i, name in enumerate(pending):
        try:
            imported, skipped = await _import_domain(name, kuzu_conn)
        except Exception as exc:
            logger.warning("graph import: %s failed; retried next launch", name, exc_info=True)
            await _record_alone(name, "failed", str(exc))
            for later in pending[i + 1 :]:
                await _record_alone(later, "deferred", f"waits for {name}")
            return pending[i:]
        logger.info("graph import: %s done", name, extra={"imported": imported, "skipped": skipped})
    return []


async def run_graph_import(data_dir: str, open_kuzu: Callable[[], Any] | None = None) -> None:
    """Import every domain not yet done. Never raises: the app starts either way.

    `open_kuzu` defaults to a read-only open of `<data_dir>/graph.kuzu`, the only place
    `kuzu` is imported.
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
    owned = open_kuzu is None
    if owned:
        from app.services.graph_connection import open_read_only  # noqa: PLC0415

        def open_kuzu():
            return open_read_only(data_dir)

    kuzu_conn = await _open(open_kuzu, pending)
    if kuzu_conn is None:
        return
    try:
        not_moved = await _import_all(pending, kuzu_conn)
    finally:
        if owned:
            kuzu_conn.close()  # releases the read lock an older build would wait on
            kuzu_conn.database.close()
    if not_moved:
        status.set_state(_PHASE, "failed", f"Not yet moved: {', '.join(not_moved)}")
    else:
        status.set_state(_PHASE, "ready")
