"""Seed the SQLite graph for tests, through the same write path ingestion uses."""

from __future__ import annotations

from sqlalchemy import select

from app.models import DocumentModel, GraphEntityEdgeModel, GraphNoteEntityModel, NoteModel
from app.services.graph import DocumentGraph, get_graph_service


async def add_documents(memory_db, *doc_ids: str) -> None:
    async with memory_db.factory() as s:
        for doc_id in doc_ids:
            s.add(
                DocumentModel(
                    id=doc_id, title=doc_id, format="txt", content_type="book", file_path="/x"
                )
            )
        await s.commit()


async def add_graph(
    memory_db,
    doc_id: str,
    entities: dict[str, tuple[str, str]],
    *,
    co_occurs: tuple[tuple[str, str], ...] = (),
    edges: tuple[tuple[str, str, str, dict], ...] = (),
) -> None:
    """Write one document's graph. `entities` is {id: (name, type)}; the document is
    created if it does not exist. Each edge is (kind, source, target, properties)."""
    async with memory_db.factory() as s:
        exists = await s.get(DocumentModel, doc_id)
    if exists is None:
        await add_documents(memory_db, doc_id)
    graph = DocumentGraph()
    for entity_id, (name, entity_type) in entities.items():
        graph.add_entity(entity_id, name, entity_type)
    for a, b in co_occurs:
        graph.add_co_occurrence(a, b)
    for kind, a, b, props in edges:
        graph.add_edge(kind, a, b, **props)
    assert await get_graph_service().write_document_graph(doc_id, graph)


async def add_raw_edge(memory_db, kind: str, a: str, b: str, doc_id: str, **props) -> None:
    """An edge written past the write path's guards, as older builds stored it."""
    async with memory_db.factory() as s:
        s.add(
            GraphEntityEdgeModel(kind=kind, source_id=a, target_id=b, document_id=doc_id, **props)
        )
        await s.commit()


async def add_note(
    memory_db, note_id: str, content: str, entity_id: str | None = None, kind="written_about"
) -> None:
    async with memory_db.factory() as s:
        if await s.get(NoteModel, note_id) is None:
            s.add(NoteModel(id=note_id, content=content, tags=[]))
            await s.flush()  # no ORM relationship orders the two inserts
        if entity_id:
            s.add(
                GraphNoteEntityModel(
                    note_id=note_id, entity_id=entity_id, kind=kind, confidence=0.9
                )
            )
        await s.commit()


async def edges(memory_db, kind: str) -> list[GraphEntityEdgeModel]:
    async with memory_db.factory() as s:
        result = await s.scalars(
            select(GraphEntityEdgeModel).where(GraphEntityEdgeModel.kind == kind)
        )
        return list(result)
