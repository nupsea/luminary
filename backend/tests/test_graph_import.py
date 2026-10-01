"""The Kuzu-to-SQLite graph import: copies live rows, skips stale ones, never half-commits."""

import pytest
from sqlalchemy import func, select

from app.models import (
    ConceptModel,
    DocumentModel,
    GraphConceptDocumentModel,
    GraphConceptEdgeModel,
    GraphImportStateModel,
)
from app.repos.graph_import_repo import GraphImportRepo
from app.services import graph_import
from app.services.graph_connection import GraphDatabaseLockedError, KuzuConnection
from app.services.startup_status import get_startup_status

LIVE_CONCEPTS = ("c1", "c2", "c3")


@pytest.fixture
def kuzu(tmp_path):
    """A graph.kuzu holding live rows, plus rows for a deleted concept and document."""
    graph = KuzuConnection(str(tmp_path))
    run = graph.conn.execute
    for did in ("d1", "d-deleted"):
        run("CREATE (:Document {id: $id, title: $id, content_type: 'book'})", {"id": did})
    for cid in (*LIVE_CONCEPTS, "c-deleted"):
        run(
            "CREATE (:Concept {id: $id, slug: $id, label: $id, kind: 'concept', status: 'x'})",
            {"id": cid},
        )

    def edge(rel, a, b, props=""):
        match = "MATCH (a:Concept {id: $a}), (b:Concept {id: $b})"
        run(f"{match} CREATE (a)-[:{rel} {props}]->(b)", {"a": a, "b": b})

    edge("CONCEPT_RELATED_TO", "c1", "c2", "{weight: 0.7, status: 'proposed'}")
    edge("CONCEPT_RELATED_TO", "c2", "c3", "{weight: 0.5, status: 'confirmed'}")
    edge("CONCEPT_RELATED_TO", "c1", "c-deleted", "{weight: 0.1, status: 'proposed'}")
    edge("CONCEPT_PREREQUISITE_OF", "c3", "c1", "{confidence: 0.9}")
    for cid, did in (("c1", "d1"), ("c2", "d-deleted"), ("c-deleted", "d1")):
        run(
            "MATCH (c:Concept {id: $c}), (d:Document {id: $d}) CREATE (c)-[:EXTRACTED_FROM]->(d)",
            {"c": cid, "d": did},
        )
    return tmp_path, graph.conn


async def _seed_sqlite(memory_db):
    async with memory_db.factory() as s:
        for cid in LIVE_CONCEPTS:
            s.add(ConceptModel(id=cid, slug=f"s-{cid}", label=cid))
        s.add(DocumentModel(id="d1", title="d1", format="txt", content_type="book", file_path="/x"))
        await s.commit()


async def _counts(memory_db) -> tuple[int, int]:
    async with memory_db.factory() as s:
        edges = await s.scalar(select(func.count()).select_from(GraphConceptEdgeModel))
        links = await s.scalar(select(func.count()).select_from(GraphConceptDocumentModel))
    return edges, links


async def _state(memory_db, domain="concepts") -> GraphImportStateModel | None:
    async with memory_db.factory() as s:
        return await s.get(GraphImportStateModel, domain)


def _contents(conn) -> list[int]:
    """Row counts of every table the import reads. Read through the open connection: a
    byte hash cannot be, because Windows refuses reads of a file Kuzu holds open."""
    tables = ("Concept", "Document")
    rels = ("CONCEPT_RELATED_TO", "CONCEPT_PREREQUISITE_OF", "EXTRACTED_FROM")
    queries = [f"MATCH (n:{t}) RETURN count(n)" for t in tables]
    queries += [f"MATCH ()-[r:{r}]->() RETURN count(r)" for r in rels]
    return [conn.execute(q).get_next()[0] for q in queries]


def _phase_state() -> str:
    phases = get_startup_status().snapshot()["phases"]
    return next(p["state"] for p in phases if p["key"] == "graph_import")


def _must_not_open():
    raise AssertionError("the import opened Kuzu with nothing to import")


async def test_live_rows_are_copied_and_stale_rows_counted_by_reason(memory_db, kuzu):
    data_dir, conn = kuzu
    await _seed_sqlite(memory_db)

    await graph_import.run_graph_import(str(data_dir), lambda: conn)

    assert await _counts(memory_db) == (3, 1)
    state = await _state(memory_db)
    assert state.status == "done"
    assert state.imported_json == {"graph_concept_edges": 3, "graph_concept_documents": 1}
    assert state.skipped_json == {"concept_deleted": 2, "document_deleted": 1}
    async with memory_db.factory() as s:
        prereq = await s.scalar(
            select(GraphConceptEdgeModel).where(GraphConceptEdgeModel.kind == "prerequisite")
        )
    assert (prereq.source_id, prereq.target_id) == ("c3", "c1")
    # Kuzu's FLOAT is 32-bit; the copy keeps the stored value, not the one written.
    assert prereq.confidence == pytest.approx(0.9, rel=1e-6)
    assert _phase_state() == "ready"


async def test_a_second_launch_does_not_reimport(memory_db, kuzu):
    data_dir, conn = kuzu
    await _seed_sqlite(memory_db)
    await graph_import.run_graph_import(str(data_dir), lambda: conn)

    await graph_import.run_graph_import(str(data_dir), _must_not_open)

    assert await _counts(memory_db) == (3, 1)


async def test_rows_written_since_a_failed_attempt_are_not_duplicated(memory_db, kuzu):
    data_dir, conn = kuzu
    await _seed_sqlite(memory_db)
    async with memory_db.factory() as s:
        s.add(GraphConceptEdgeModel(kind="related", source_id="c1", target_id="c2", weight=0.7))
        await s.commit()

    await graph_import.run_graph_import(str(data_dir), lambda: conn)

    assert await _counts(memory_db) == (3, 1)
    assert (await _state(memory_db)).skipped_json["already_present"] == 1


async def test_a_failure_mid_domain_commits_nothing_and_leaves_kuzu_untouched(
    memory_db, kuzu, monkeypatch
):
    data_dir, conn = kuzu
    await _seed_sqlite(memory_db)
    before = _contents(conn)
    real_count = GraphImportRepo.count
    calls = {"n": 0}

    async def _count_then_fail(self, model):
        calls["n"] += 1
        if model is GraphConceptDocumentModel:
            raise RuntimeError("disk full")
        return await real_count(self, model)

    monkeypatch.setattr(GraphImportRepo, "count", _count_then_fail)
    await graph_import.run_graph_import(str(data_dir), lambda: conn)

    assert calls["n"] >= 2, "the edges table was written before the failure"
    assert await _counts(memory_db) == (0, 0)
    state = await _state(memory_db)
    assert state.status == "failed" and "disk full" in state.error
    assert _contents(conn) == before

    monkeypatch.setattr(GraphImportRepo, "count", real_count)
    await graph_import.run_graph_import(str(data_dir), lambda: conn)
    assert await _counts(memory_db) == (3, 1)


async def test_a_graph_locked_by_another_process_is_deferred(memory_db, kuzu):
    data_dir, _conn = kuzu

    def _locked():
        raise GraphDatabaseLockedError("held by another process")

    await graph_import.run_graph_import(str(data_dir), _locked)

    assert (await _state(memory_db)).status == "deferred"
    assert _phase_state() == "failed"


async def test_a_new_install_has_nothing_to_import(memory_db, tmp_path):
    await graph_import.run_graph_import(str(tmp_path / "fresh"), _must_not_open)

    assert (await _state(memory_db)).status == "done"
    assert await _counts(memory_db) == (0, 0)
