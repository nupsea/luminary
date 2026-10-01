"""Concept topology lives in SQLite: writes skip missing endpoints, deletes cascade."""

from sqlalchemy import delete, func, select

from app.models import (
    ConceptModel,
    DocumentModel,
    GraphConceptDocumentModel,
    GraphConceptEdgeModel,
)
from app.repos.graph_concept_repo import GraphConceptRepo


async def _seed(session, concepts=("c1", "c2", "c3"), documents=("d1",)):
    for cid in concepts:
        session.add(ConceptModel(id=cid, slug=f"s-{cid}", label=cid))
    for did in documents:
        session.add(
            DocumentModel(id=did, title=did, format="txt", content_type="book", file_path="/x")
        )
    await session.flush()


async def _count(session, model) -> int:
    return await session.scalar(select(func.count()).select_from(model))


async def test_writes_are_idempotent_and_skip_missing_endpoints(memory_db):
    async with memory_db.factory() as s:
        await _seed(s)
        repo = GraphConceptRepo(s)
        assert await repo.add_extracted_from("c1", "d1") is True
        assert await repo.add_extracted_from("c1", "d1") is False
        assert await repo.add_extracted_from("c1", "gone") is False
        assert await repo.add_relation("c1", "c2", weight=0.4) is True
        assert await repo.add_relation("c1", "c2", weight=0.4) is False
        assert await repo.add_relation("c1", "gone") is False
        await s.commit()
        assert await _count(s, GraphConceptDocumentModel) == 1
        assert await _count(s, GraphConceptEdgeModel) == 1


async def test_neighbours_read_both_directions_and_ignore_prerequisites(memory_db):
    async with memory_db.factory() as s:
        await _seed(s)
        repo = GraphConceptRepo(s)
        await repo.add_relation("c1", "c2")
        await repo.add_relation("c3", "c1")
        await repo.add_relation("c1", "c3", kind="prerequisite", confidence=0.9)
        assert sorted(await repo.neighbors("c1")) == ["c2", "c3"]
        assert await repo.neighbors("c2") == ["c1"]


async def test_deleting_a_concept_or_document_drops_its_topology(memory_db):
    async with memory_db.factory() as s:
        await _seed(s, documents=("d1", "d2"))
        repo = GraphConceptRepo(s)
        await repo.add_relation("c1", "c2")
        await repo.add_relation("c2", "c3")
        await repo.add_extracted_from("c1", "d1")
        await repo.add_extracted_from("c2", "d2")
        await s.commit()

        await s.execute(delete(ConceptModel).where(ConceptModel.id == "c1"))
        await s.execute(delete(DocumentModel).where(DocumentModel.id == "d2"))
        await s.commit()

        edges = (await s.execute(select(GraphConceptEdgeModel.source_id))).scalars().all()
        assert edges == ["c2"]
        assert await _count(s, GraphConceptDocumentModel) == 0
