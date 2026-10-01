"""The Kuzu-to-SQLite graph import: copies live rows, skips stale ones, never half-commits."""

import hashlib

import pytest
from sqlalchemy import func, select

from app.models import (
    ConceptModel,
    DocumentModel,
    GraphConceptDocumentModel,
    GraphConceptEdgeModel,
    GraphDiagramDepictionModel,
    GraphDiagramNodeModel,
    GraphEntityEdgeModel,
    GraphEntityLinkModel,
    GraphEntityModel,
    GraphImportStateModel,
    GraphNoteEntityModel,
    NoteModel,
)
from app.repos.graph_import_repo import GraphImportRepo
from app.services import graph_import
from app.services.graph_connection import GraphDatabaseLockedError
from app.services.startup_status import get_startup_status
from tests.kuzu_legacy import legacy_graph

LIVE_CONCEPTS = ("c1", "c2", "c3")


@pytest.fixture
def kuzu(tmp_path):
    """A graph.kuzu holding live rows, plus rows for a deleted concept and document."""
    conn = legacy_graph(tmp_path)
    run = conn.execute
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
    return tmp_path, conn


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


def _fingerprint(path) -> str:
    return hashlib.sha256((path / "graph.kuzu").read_bytes()).hexdigest()


def _contents(conn) -> list[int]:
    """Row counts of every table the import reads. Read through the open connection: a
    byte hash cannot be, because Windows refuses reads of a file Kuzu holds open."""
    nodes = ("Concept", "Document", "Entity", "DiagramNode", "Note")
    rels = ("CONCEPT_RELATED_TO", "EXTRACTED_FROM", "MENTIONED_IN", "CO_OCCURS", "WRITTEN_ABOUT")
    queries = [f"MATCH (n:{t}) RETURN count(n)" for t in nodes]
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


def _seed_entity_graph(conn) -> None:
    """Live rows in d1, plus each kind of stale row the import must skip."""
    run = conn.execute
    for eid, name, aliases in (
        ("e1", "Ulysses", "Odysseus|Ulixes"),
        ("e2", "Minerva", ""),
        ("e3", "Achilles", ""),
        ("e-orphan", "Nobody", ""),
    ):
        run(
            "CREATE (:Entity {id: $id, name: $n, type: 'PERSON', frequency: 3, aliases: $a})",
            {"id": eid, "n": name, "a": aliases},
        )
    for eid, did in (("e1", "d1"), ("e2", "d1"), ("e3", "d-deleted")):
        run(
            "MATCH (e:Entity {id: $e}), (d:Document {id: $d})"
            " CREATE (e)-[:MENTIONED_IN {count: 5}]->(d)",
            {"e": eid, "d": did},
        )

    def edge(rel, a, b, props):
        run(
            f"MATCH (a:Entity {{id: $a}}), (b:Entity {{id: $b}}) CREATE (a)-[:{rel} {props}]->(b)",
            {"a": a, "b": b},
        )

    edge("CO_OCCURS", "e1", "e2", "{weight: 3.0, document_id: 'd1'}")
    edge("CO_OCCURS", "e1", "e1", "{weight: 62.0, document_id: 'd1'}")
    edge("CO_OCCURS", "e1", "e3", "{weight: 1.0, document_id: 'd1'}")
    edge("RELATED_TO", "e1", "e2", "{relation_label: 'guided by', confidence: 0.8}")
    edge(
        "SAME_CONCEPT",
        "e1",
        "e3",
        "{source_doc_id: 'd1', target_doc_id: 'd-deleted', confidence: 0.9, contradiction: 1,"
        " contradiction_note: 'x', prefer_source: 'a'}",
    )
    for nid, did in (("n1", "d1"), ("n2", "d-deleted")):
        run(
            "CREATE (:DiagramNode {id: $id, name: $id, node_type: 'COMPONENT',"
            " source_image_id: 'img', document_id: $d, frequency: 1})",
            {"id": nid, "d": did},
        )
    run(
        "MATCH (a:DiagramNode {id: 'n1'}), (b:DiagramNode {id: 'n2'})"
        " CREATE (a)-[:CONNECTS_TO {document_id: 'd1', label: 'calls'}]->(b)"
    )
    run(
        "MATCH (a:DiagramNode {id: 'n1'}), (e:Entity {id: 'e1'})"
        " CREATE (a)-[:DEPICTS {document_id: 'd1'}]->(e)"
    )
    for note in ("note-live", "note-deleted"):
        run("CREATE (:Note {id: $id, note_id: $id, preview: '', created_at: ''})", {"id": note})
    for note, rel, eid, props in (
        ("note-live", "WRITTEN_ABOUT", "e1", "{confidence: 0.7}"),
        ("note-live", "TAG_IS_CONCEPT", "e2", "{tag: 'minerva'}"),
        ("note-deleted", "WRITTEN_ABOUT", "e1", "{confidence: 0.7}"),
    ):
        run(
            f"MATCH (n:Note {{id: $n}}), (e:Entity {{id: $e}}) CREATE (n)-[:{rel} {props}]->(e)",
            {"n": note, "e": eid},
        )
    run(
        "MATCH (c:Concept {id: 'c1'}), (e:Entity {id: 'e1'})"
        " CREATE (c)-[:PROMOTED_FROM {confidence: 1.0}]->(e)"
    )
    run("MATCH (n:Note {id: 'note-live'}), (d:Document {id: 'd1'}) CREATE (n)-[:DERIVED_FROM]->(d)")
    run(
        "MATCH (a:Note {id: 'note-live'}), (b:Note {id: 'note-deleted'})"
        " CREATE (a)-[:LINKS_TO {link_type: 'see'}]->(b)"
    )


async def _rows(memory_db, model) -> list:
    async with memory_db.factory() as s:
        return list(await s.scalars(select(model)))


async def test_entities_and_notes_import_live_rows_and_count_stale_ones(memory_db, kuzu):
    data_dir, conn = kuzu
    _seed_entity_graph(conn)
    await _seed_sqlite(memory_db)
    async with memory_db.factory() as s:
        s.add(NoteModel(id="note-live", content="On Ulysses", tags=[]))
        await s.commit()

    await graph_import.run_graph_import(str(data_dir), lambda: conn)

    entities = {e.id: e for e in await _rows(memory_db, GraphEntityModel)}
    assert set(entities) == {"e1", "e2"}
    assert entities["e1"].aliases == ["Odysseus", "Ulixes"]
    assert (entities["e1"].document_id, entities["e1"].mention_count) == ("d1", 5)
    edges = {
        (e.kind, e.source_id, e.target_id): e for e in await _rows(memory_db, GraphEntityEdgeModel)
    }
    assert set(edges) == {("CO_OCCURS", "e1", "e2"), ("RELATED_TO", "e1", "e2")}
    # RELATED_TO carried no document in Kuzu; it belongs to its source's.
    assert (edges["RELATED_TO", "e1", "e2"].document_id, edges["RELATED_TO", "e1", "e2"].label) == (
        "d1",
        "guided by",
    )
    assert await _rows(memory_db, GraphEntityLinkModel) == []
    assert [n.id for n in await _rows(memory_db, GraphDiagramNodeModel)] == ["n1"]
    assert len(await _rows(memory_db, GraphDiagramDepictionModel)) == 1
    notes = await _rows(memory_db, GraphNoteEntityModel)
    assert sorted((n.entity_id, n.kind, n.tag) for n in notes) == [
        ("e1", "written_about", None),
        ("e2", "tag", "minerva"),
    ]

    entity_state = await _state(memory_db, "entities")
    assert entity_state.status == "done"
    assert entity_state.skipped_json == {
        "document_deleted": 2,
        "no_document": 1,
        "self_pair": 1,
        "entity_missing": 2,
        "node_missing": 1,
        "unused": 1,
    }
    note_state = await _state(memory_db, "notes")
    assert note_state.skipped_json == {"superseded": 2, "note_deleted": 1}
    assert _phase_state() == "ready"


async def test_a_failed_domain_defers_the_domains_that_point_at_it(memory_db, kuzu, monkeypatch):
    data_dir, conn = kuzu
    _seed_entity_graph(conn)
    await _seed_sqlite(memory_db)

    async def _fail(repo, kuzu_conn):
        raise RuntimeError("entities broke")

    monkeypatch.setitem(
        graph_import.DOMAINS, "entities", (_fail, graph_import.DOMAINS["entities"][1])
    )
    await graph_import.run_graph_import(str(data_dir), lambda: conn)

    assert (await _state(memory_db, "concepts")).status == "done"
    assert (await _state(memory_db, "entities")).status == "failed"
    notes = await _state(memory_db, "notes")
    assert (notes.status, notes.error) == ("deferred", "waits for entities")
    assert await _rows(memory_db, GraphNoteEntityModel) == []
    assert _phase_state() == "failed"


async def test_an_unreadable_graph_fails_every_pending_domain(memory_db, kuzu):
    data_dir, _conn = kuzu

    def _corrupt():
        raise RuntimeError("Load table failed: table 0 doesn't exist in catalog.")

    await graph_import.run_graph_import(str(data_dir), _corrupt)

    for domain in graph_import.DOMAINS:
        assert (await _state(memory_db, domain)).status == "failed"
    assert _phase_state() == "failed"


async def test_the_default_open_is_read_only_and_released(memory_db, kuzu):
    data_dir, conn = kuzu
    await _seed_sqlite(memory_db)
    conn.close()
    conn.database.close()
    before = _fingerprint(data_dir)

    await graph_import.run_graph_import(str(data_dir))

    assert await _counts(memory_db) == (3, 1)
    assert _fingerprint(data_dir) == before
    # Released: a writer can open it straight away.
    writer = legacy_graph(data_dir)
    writer.close()
    writer.database.close()
